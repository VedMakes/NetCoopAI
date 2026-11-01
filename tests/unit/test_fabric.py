"""Unit tests for NetCoop AI Integration Fabric: EventBus, QueryRouter, TaskDispatcher,
and multi-tower collaboration on a unified incident context.
"""

from datetime import datetime, timezone
from typing import Any

import pytest

from netcoop.communication.events import EventBus, EventEnvelope
from netcoop.communication.fabric import IntegrationFabric
from netcoop.communication.queries import PeerQuery, QueryRouter
from netcoop.communication.registry import CapabilityRegistry
from netcoop.communication.tasks import (
    InvalidTaskTransitionError,
    InvestigationTask,
    TaskDispatcher,
    TaskResult,
)
from netcoop.models.enums import (
    QueryStatus,
    TaskStatus,
    TowerId,
)
from netcoop.models.observations import (
    CanonicalObservation,
    MetricObservation,
    TopologyObservation,
)
from netcoop.storage.sqlite import SQLiteRepository


@pytest.fixture
def memory_repo() -> SQLiteRepository:
    return SQLiteRepository(":memory:")


@pytest.fixture
def sample_utc() -> datetime:
    return datetime.now(timezone.utc)


def test_event_bus_publish_subscribe_and_deterministic_ordering(memory_repo: SQLiteRepository, sample_utc: datetime):
    bus = EventBus(repository=memory_repo)
    call_order: list[str] = []

    # Subscribe out-of-alphabetical order to test deterministic ordering (sorted by consumer_id)
    bus.subscribe("network.alert", "consumer_z", lambda evt: call_order.append("consumer_z"))
    bus.subscribe("network.alert", "consumer_a", lambda evt: call_order.append("consumer_a"))
    bus.subscribe("network.alert", "consumer_m", lambda evt: call_order.append("consumer_m"))

    evt = EventEnvelope(
        id="EVT-001",
        source="netcoop/performance",
        type="network.alert",
        time=sample_utc,
        dataschema="netcoop://schemas/events/alert/1.0",
        correlationid="INC-001",
        data={"detail": "High utilization detected"},
    )

    summary = bus.publish(evt)

    # Deterministic alphabetical ordering
    assert call_order == ["consumer_a", "consumer_m", "consumer_z"]
    assert summary.delivered_to == ["consumer_a", "consumer_m", "consumer_z"]
    assert summary.failed_deliveries == {}
    assert summary.skipped_duplicate == []

    # Event persisted in SQLite repository
    events_in_db = memory_repo.get_events("INC-001")
    assert len(events_in_db) == 1
    assert events_in_db[0].id == "EVT-001"

    # Deliveries recorded in SQLite repository
    deliveries = memory_repo.get_event_deliveries("EVT-001")
    assert len(deliveries) == 3
    assert {d["consumer_id"] for d in deliveries} == {"consumer_a", "consumer_m", "consumer_z"}
    assert all(d["status"] == "completed" for d in deliveries)


def test_event_bus_idempotency_prevents_duplicate_delivery(memory_repo: SQLiteRepository, sample_utc: datetime):
    bus = EventBus(repository=memory_repo)
    invocations: list[str] = []

    bus.subscribe("network.alert", "consumer_1", lambda evt: invocations.append(evt.id))

    evt = EventEnvelope(
        id="EVT-IDEMP-01",
        source="netcoop/test",
        type="network.alert",
        time=sample_utc,
        dataschema="netcoop://schemas/events/alert/1.0",
        correlationid="INC-002",
        data={},
    )

    # First delivery succeeds
    summary1 = bus.publish(evt)
    assert summary1.delivered_to == ["consumer_1"]
    assert len(invocations) == 1

    # Second delivery with the same event ID is skipped via idempotency check
    summary2 = bus.publish(evt)
    assert summary2.delivered_to == []
    assert summary2.skipped_duplicate == ["consumer_1"]
    assert len(invocations) == 1  # Handler was NOT invoked again


def test_event_bus_failure_isolation_does_not_abort_unrelated_consumers(
    memory_repo: SQLiteRepository, sample_utc: datetime
):
    bus = EventBus(repository=memory_repo)
    delivered: list[str] = []

    def failing_handler(evt: EventEnvelope):
        raise RuntimeError("Transient crash in consumer_bad")

    bus.subscribe("device.reboot", "consumer_bad", failing_handler)
    bus.subscribe("device.reboot", "consumer_good", lambda evt: delivered.append("consumer_good"))

    evt = EventEnvelope(
        id="EVT-FAIL-01",
        source="netcoop/infrastructure",
        type="device.reboot",
        time=sample_utc,
        dataschema="netcoop://schemas/events/reboot/1.0",
        correlationid="INC-003",
        data={"device": "SW_CORE"},
    )

    summary = bus.publish(evt)

    # consumer_good received the event despite consumer_bad failing
    assert "consumer_good" in summary.delivered_to
    assert "consumer_bad" in summary.failed_deliveries
    assert "Transient crash in consumer_bad" in summary.failed_deliveries["consumer_bad"]
    assert delivered == ["consumer_good"]

    # Delivery status stored in SQLite
    deliveries = memory_repo.get_event_deliveries("EVT-FAIL-01")
    deliv_map = {d["consumer_id"]: d for d in deliveries}
    assert deliv_map["consumer_good"]["status"] == "completed"
    assert deliv_map["consumer_bad"]["status"] == "failed"


def test_query_router_one_hop_restriction_and_unauthorized_rejections(
    memory_repo: SQLiteRepository, sample_utc: datetime
):
    registry = CapabilityRegistry.load()
    router = QueryRouter(registry=registry, repository=memory_repo)

    # Attempt nested recursive query from inside a handler
    def recursive_handler(q: PeerQuery) -> Any:
        nested_query = PeerQuery(
            query_id="Q-NESTED",
            incident_id="INC-004",
            requester="connectivity",
            recipient="connectivity",
            capability="connectivity.trace_path",
            scope=["SW_1", "SW_2"],
            expected_schema="netcoop://schemas/test/1.0",
            created_at=datetime.now(timezone.utc),
        )
        return router.request(nested_query)

    router.register(TowerId.CONNECTIVITY, "connectivity.trace_path", recursive_handler)

    outer_query = PeerQuery(
        query_id="Q-OUTER",
        incident_id="INC-004",
        requester="performance",
        recipient="connectivity",
        capability="connectivity.trace_path",
        scope=["SW_1", "SW_2"],
        expected_schema="netcoop://schemas/test/1.0",
        created_at=sample_utc,
    )

    nested_result = router.request(outer_query)
    # The outer handler invoked the nested query, which should have been rejected as UNAUTHORIZED
    assert nested_result.status == QueryStatus.UNAUTHORIZED
    assert any("one-hop" in w.lower() for w in nested_result.warnings)


def test_query_router_mismatched_recipient_rejection(memory_repo: SQLiteRepository, sample_utc: datetime):
    registry = CapabilityRegistry.load()
    router = QueryRouter(registry=registry, repository=memory_repo)

    # Query connectivity capability but address recipient as performance
    bad_query = PeerQuery(
        query_id="Q-BAD-RECIPIENT",
        incident_id="INC-005",
        requester="services",
        recipient="performance",
        capability="connectivity.trace_path",  # Belongs to connectivity!
        scope=["AP_1", "GW_1"],
        expected_schema="netcoop://schemas/test/1.0",
        created_at=sample_utc,
    )

    result = router.request(bad_query)
    assert result.status == QueryStatus.UNAUTHORIZED
    assert any("belongs to tower" in w for w in result.warnings)


def test_task_dispatcher_supervisor_only_authorization(memory_repo: SQLiteRepository):
    dispatcher = TaskDispatcher(repository=memory_repo)

    # Non-supervisor requester MUST be rejected with PermissionError
    with pytest.raises(PermissionError) as exc_info:
        dispatcher.create_task(
            requester="performance",  # Not supervisor!
            assignee=TowerId.CONNECTIVITY,
            capability="INVESTIGATE_TOPOLOGY",
            objective={"target": "SW_CORE"},
        )
    assert "Only 'supervisor' may create persistent investigation tasks" in str(exc_info.value)


def test_task_dispatcher_lifecycle_and_single_counter_proposal(memory_repo: SQLiteRepository):
    dispatcher = TaskDispatcher(repository=memory_repo)

    # 1. Supervisor creates task
    task = dispatcher.create_task(
        requester="supervisor",
        assignee=TowerId.INFRASTRUCTURE,
        capability="INVESTIGATE_DEVICE",
        objective={"device": "SW_CORE_01"},
        constraints={"timeout_sec": 30},
    )
    assert task.status == TaskStatus.CREATED
    assert task.counter_proposal_count == 0

    # 2. Counter-propose (allowed once)
    cp_task = dispatcher.counter_propose(
        task.task_id,
        revised_constraints={"timeout_sec": 60},
        reason="Device polling takes 45s",
    )
    assert cp_task.status == TaskStatus.COUNTER_PROPOSED
    assert cp_task.counter_proposal_count == 1
    assert cp_task.constraints["timeout_sec"] == 60

    # 3. Second counter-proposal must be strictly rejected
    with pytest.raises(InvalidTaskTransitionError) as exc:
        dispatcher.counter_propose(
            task.task_id,
            revised_constraints={"timeout_sec": 90},
            reason="Second counter-proposal attempt",
        )
    assert "Maximum allowed is 1" in str(exc.value)

    # 4. Supervisor accepts revised task
    acc_task = dispatcher.accept(task.task_id)
    assert acc_task.status == TaskStatus.ACCEPTED

    # 5. Register handler and execute
    def dummy_handler(t: InvestigationTask) -> TaskResult:
        return TaskResult(
            result_id="RES-001",
            task_id=t.task_id,
            assignee=t.assignee,
            status=TaskStatus.COMPLETED,
            result_schema="netcoop://schemas/test/1.0",
            result={"status": "healthy"},
            completed_at=datetime.now(timezone.utc),
        )

    dispatcher.register_handler(TowerId.INFRASTRUCTURE, "INVESTIGATE_DEVICE", dummy_handler)
    res = dispatcher.execute(task.task_id)

    assert res.status == TaskStatus.COMPLETED
    assert res.result == {"status": "healthy"}

    # Verified persisted state in SQLite
    final_task = dispatcher.get(task.task_id)
    assert final_task.status == TaskStatus.COMPLETED
    assert final_task.result_id == "RES-001"


def test_task_dispatcher_declined_and_failed_tasks_do_not_crash(memory_repo: SQLiteRepository):
    dispatcher = TaskDispatcher(repository=memory_repo)

    # 1. Decline task
    task1 = dispatcher.create_task(
        requester="supervisor",
        assignee=TowerId.SERVICES,
        capability="INVESTIGATE_DNS",
        objective={"query": "test"},
    )
    declined_task = dispatcher.decline(task1.task_id, reason="DNS service unconfigured")
    assert declined_task.status == TaskStatus.DECLINED
    assert declined_task.error_detail == "DNS service unconfigured"

    # 2. Failing handler
    task2 = dispatcher.create_task(
        requester="supervisor",
        assignee=TowerId.SERVICES,
        capability="INVESTIGATE_DHCP",
        objective={"query": "test"},
    )

    def failing_handler(t: InvestigationTask) -> TaskResult:
        raise ConnectionResetError("Device connection dropped unexpectedly")

    dispatcher.register_handler(TowerId.SERVICES, "INVESTIGATE_DHCP", failing_handler)
    failed_res = dispatcher.execute(task2.task_id)

    assert failed_res.status == TaskStatus.FAILED
    assert any("Device connection dropped" in w for w in failed_res.warnings)

    task2_record = dispatcher.get(task2.task_id)
    assert task2_record.status == TaskStatus.FAILED
    assert task2_record.error_code == "EXECUTION_ERROR"
    assert "Device connection dropped" in (task2_record.error_detail or "")


def test_fabric_end_to_end_peer_queries(memory_repo: SQLiteRepository, sample_utc: datetime):
    fabric = IntegrationFabric(repository=memory_repo)

    # Preload connectivity topology observations
    topo_obs1 = TopologyObservation(
        observation_id="TOPO-01",
        incident_id="INC-FABRIC-01",
        source="topology_db",
        entity_id="SW_CORE",
        source_entity="SW_CORE",
        target_entity="SW_DIST",
        relationship_type="connected_to",
        link_speed_mbps=10000.0,
        interface_name="eth0",
        timestamp=sample_utc,
    )
    topo_obs2 = TopologyObservation(
        observation_id="TOPO-02",
        incident_id="INC-FABRIC-01",
        source="topology_db",
        entity_id="SW_DIST",
        source_entity="SW_DIST",
        target_entity="AP_HOSTEL_01",
        relationship_type="connected_to",
        link_speed_mbps=1000.0,
        interface_name="eth1",
        timestamp=sample_utc,
    )
    fabric.get_tower(TowerId.CONNECTIVITY).analyze_incident("INC-FABRIC-01", [topo_obs1, topo_obs2])

    # 1. Performance Tower queries Connectivity Tower for topological path
    q1 = PeerQuery(
        query_id="PQ-PERF-TO-CONN-01",
        incident_id="INC-FABRIC-01",
        requester="performance",
        recipient="connectivity",
        capability="connectivity.trace_path",
        scope=["AP_HOSTEL_01", "SW_CORE"],
        expected_schema="netcoop://schemas/capabilities/connectivity-trace-path-output/1.0",
        created_at=sample_utc,
    )
    res1 = fabric.query_peer(q1)
    assert res1.status == QueryStatus.COMPLETED
    assert res1.result is not None
    assert res1.result["reachable"] is True
    assert res1.result["path"] == ["AP_HOSTEL_01", "SW_DIST", "SW_CORE"]
    assert res1.result["hops"] == 2
    assert "TOPO-01" in res1.evidence_refs
    assert "TOPO-02" in res1.evidence_refs

    # 2. Services Tower queries Infrastructure Tower for device health
    q2 = PeerQuery(
        query_id="PQ-SERV-TO-INFRA-01",
        incident_id="INC-FABRIC-01",
        requester="services",
        recipient="infrastructure",
        capability="infrastructure.check_device_health",
        scope=["SW_CORE"],
        expected_schema="netcoop://schemas/capabilities/infrastructure-device-health-output/1.0",
        created_at=sample_utc,
    )
    res2 = fabric.query_peer(q2)
    assert res2.status == QueryStatus.COMPLETED
    assert res2.result is not None
    # Topology alone does not prove operational health.
    assert res2.result["status"] == "unknown"
    assert any("No matching metric evidence" in warning for warning in res2.warnings)


def test_fabric_four_towers_run_on_shared_incident(memory_repo: SQLiteRepository, sample_utc: datetime):
    fabric = IntegrationFabric(repository=memory_repo)
    incident_id = "INC-MULTI-TOWER-01"

    # Multi-domain observations: 1 congestion metric, 1 CPU overload metric, 1 topology link, 1 DNS latency metric
    observations: list[CanonicalObservation] = [
        # Performance: high link utilization + queue drops
        MetricObservation(
            observation_id="OBS-M1",
            incident_id=incident_id,
            source="snmp",
            entity_id="LINK_CORE_DIST",
            metric_name="link_utilization_pct",
            value=96.0,
            unit="percent",
            timestamp=sample_utc,
        ),
        MetricObservation(
            observation_id="OBS-M2",
            incident_id=incident_id,
            source="snmp",
            entity_id="LINK_CORE_DIST",
            metric_name="queue_drops",
            value=150.0,
            unit="count",
            timestamp=sample_utc,
        ),
        # Infrastructure: high CPU utilization
        MetricObservation(
            observation_id="OBS-M3",
            incident_id=incident_id,
            source="snmp",
            entity_id="SW_CORE_01",
            metric_name="cpu_utilization_pct",
            value=92.0,
            unit="percent",
            timestamp=sample_utc,
        ),
        # Connectivity: topology link
        TopologyObservation(
            observation_id="OBS-T1",
            incident_id=incident_id,
            source="topology_db",
            entity_id="SW_CORE_01",
            source_entity="SW_CORE_01",
            target_entity="SW_DIST_01",
            relationship_type="connected_to",
            link_speed_mbps=10000.0,
            timestamp=sample_utc,
        ),
        # Services: severe DNS latency
        MetricObservation(
            observation_id="OBS-M4",
            incident_id=incident_id,
            source="synthetic_probe",
            entity_id="SRV_DNS_01",
            metric_name="latency_ms",
            value=650.0,
            unit="milliseconds",
            timestamp=sample_utc,
        ),
    ]

    # Run all four towers through the fabric
    reports = fabric.run_all_towers(incident_id, observations=observations)

    # All 4 towers executed
    assert len(reports) == 4
    assert TowerId.PERFORMANCE in reports
    assert TowerId.INFRASTRUCTURE in reports
    assert TowerId.CONNECTIVITY in reports
    assert TowerId.SERVICES in reports

    # Performance Tower derived findings & hypotheses
    perf_report = reports[TowerId.PERFORMANCE]
    assert len(perf_report.findings) >= 1
    assert any(h.fault_code == "LINK_CONGESTION" for h in perf_report.hypotheses)

    # Infrastructure Tower derived findings & hypotheses
    infra_report = reports[TowerId.INFRASTRUCTURE]
    assert len(infra_report.findings) >= 1
    assert any(h.fault_code == "DEVICE_OVERLOAD" for h in infra_report.hypotheses)

    # Services Tower derived DNS resolution failure
    serv_report = reports[TowerId.SERVICES]
    assert len(serv_report.findings) >= 1
    assert any(h.fault_code == "DNS_FAILURE" for h in serv_report.hypotheses)

    # Reports and findings stored transactionally in SQLite
    stored_reports = memory_repo.get_tower_reports(incident_id)
    assert len(stored_reports) == 4

    stored_findings = memory_repo.get_findings(incident_id)
    assert len(stored_findings) >= 3

    # EventBus received published findings notifications
    events = memory_repo.get_events(incident_id)
    event_types = {e.type for e in events}
    assert "performance.findings_published" in event_types
    assert "infrastructure.findings_published" in event_types
    assert "services.findings_published" in event_types
