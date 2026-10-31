"""Unit tests for SQLiteRepository transactional operations and round-trip persistence."""


from netcoop.communication.events import EventEnvelope
from netcoop.communication.queries import PeerQuery, PeerQueryResult
from netcoop.communication.tasks import InvestigationTask, TaskResult
from netcoop.models.enums import (
    ConfidenceCategory,
    QueryStatus,
    Severity,
    TaskStatus,
    TowerId,
)
from netcoop.models.findings import Finding
from netcoop.models.observations import (
    ConfigObservation,
    LogObservation,
    MetricObservation,
    TopologyObservation,
)
from netcoop.models.reports import FinalReport, SupportingEvidenceItem
from netcoop.storage.sqlite import SCHEMA_VERSION, SQLiteRepository


def test_sqlite_schema_version(memory_repo: SQLiteRepository):
    assert memory_repo.get_schema_version() == SCHEMA_VERSION


def test_sqlite_incident_record(memory_repo: SQLiteRepository):
    memory_repo.record_incident("INC-100", status="active", description="Test Incident")
    # Record again to verify idempotent upsert
    memory_repo.record_incident("INC-100", status="investigating", description="Updated")


def test_sqlite_observations_roundtrip(memory_repo: SQLiteRepository, sample_utc_time):
    m_obs = MetricObservation(
        observation_id="OBS-M1",
        incident_id="INC-100",
        source="snmp",
        entity_id="SW_1",
        metric_name="cpu_utilization_pct",
        value=50.0,
        unit="percent",
        timestamp=sample_utc_time,
    )
    l_obs = LogObservation(
        observation_id="OBS-L1",
        incident_id="INC-100",
        source="syslog",
        entity_id="SW_1",
        log_level="CRITICAL",
        message="Power supply degraded",
        timestamp=sample_utc_time,
    )
    t_obs = TopologyObservation(
        observation_id="OBS-T1",
        incident_id="INC-100",
        source="lldp",
        entity_id="SW_1",
        source_entity="SW_1",
        target_entity="SW_2",
        relationship_type="connected_to",
        timestamp=sample_utc_time,
    )
    c_obs = ConfigObservation(
        observation_id="OBS-C1",
        incident_id="INC-100",
        source="git",
        entity_id="SW_1",
        config_key="vlan.10.name",
        config_value="HOSTEL_WIFI",
        timestamp=sample_utc_time,
    )

    memory_repo.insert_observation(m_obs)
    memory_repo.insert_observation(l_obs)
    memory_repo.insert_observation(t_obs)
    memory_repo.insert_observation(c_obs)

    stored = memory_repo.get_observations("INC-100")
    assert len(stored) == 4
    types = {obs.observation_type for obs in stored}
    assert types == {"metric", "log", "topology", "config"}


def test_sqlite_findings_roundtrip(memory_repo: SQLiteRepository, sample_finding: Finding):
    memory_repo.insert_finding(sample_finding)

    findings = memory_repo.get_findings("INC-100")
    assert len(findings) == 1
    assert findings[0].finding_id == sample_finding.finding_id
    assert findings[0].severity == Severity.HIGH

    # Query by specific tower
    tower_findings = memory_repo.get_findings("INC-100", tower_id=TowerId.PERFORMANCE)
    assert len(tower_findings) == 1

    other_tower_findings = memory_repo.get_findings("INC-100", tower_id=TowerId.INFRASTRUCTURE)
    assert len(other_tower_findings) == 0

    # Query by ID
    by_id = memory_repo.get_finding_by_id(sample_finding.finding_id)
    assert by_id is not None
    assert by_id.description == sample_finding.description


def test_sqlite_event_outbox(memory_repo: SQLiteRepository, sample_utc_time):
    event = EventEnvelope(
        specversion="1.0",
        id="EVT-000001",
        source="netcoop/performance",
        type="performance.congestion_candidate",
        subject="SW_1:Gi0/1",
        time=sample_utc_time,
        datacontenttype="application/json",
        dataschema="netcoop://schemas/events/congestion-candidate/1.0",
        correlationid="INC-100",
        data={"finding_refs": ["F-001"]},
    )
    # Insert as pending
    memory_repo.insert_event(event, dispatched=False)

    pending = memory_repo.get_pending_outbox_events(limit=10)
    assert len(pending) == 1
    assert pending[0].id == "EVT-000001"

    # Mark as dispatched
    memory_repo.mark_event_dispatched("EVT-000001")
    pending_after = memory_repo.get_pending_outbox_events(limit=10)
    assert len(pending_after) == 0

    # Still accessible via correlation query
    corr_events = memory_repo.get_events("INC-100")
    assert len(corr_events) == 1


def test_sqlite_peer_query_lifecycle(memory_repo: SQLiteRepository, sample_utc_time):
    query = PeerQuery(
        query_id="QRY-001",
        incident_id="INC-100",
        requester="performance",
        recipient="connectivity",
        capability="connectivity.trace_path",
        scope=["SW_1", "SW_2"],
        expected_schema="netcoop://schemas/tasks/trace-output/1.0",
        created_at=sample_utc_time,
    )
    memory_repo.insert_peer_query(query)

    result = PeerQueryResult(
        query_id="QRY-001",
        status=QueryStatus.COMPLETED,
        result={"hops": ["SW_1", "RTR_1", "SW_2"]},
        completed_at=sample_utc_time,
    )
    memory_repo.update_peer_query_result(result)

    with memory_repo.transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT status, result_json FROM peer_queries WHERE query_id = ?", ("QRY-001",))
        row = cur.fetchone()
        assert row["status"] == "completed"
        assert "RTR_1" in row["result_json"]


def test_sqlite_task_and_result(memory_repo: SQLiteRepository, sample_utc_time):
    task = InvestigationTask(
        task_id="TASK-001",
        incident_id="INC-100",
        assignee=TowerId.PERFORMANCE,
        capability="performance.analyze_metrics",
        objective={"entity": "SW_1"},
        expected_result_schema="netcoop://schemas/tasks/perf-output/1.0",
        status=TaskStatus.CREATED,
        created_at=sample_utc_time,
        updated_at=sample_utc_time,
    )
    memory_repo.insert_task(task)

    # Transition to ACCEPTED
    updated = memory_repo.update_task_status("TASK-001", TaskStatus.ACCEPTED)
    assert updated.status == TaskStatus.ACCEPTED

    # Transition to RUNNING
    updated = memory_repo.update_task_status("TASK-001", TaskStatus.RUNNING)
    assert updated.status == TaskStatus.RUNNING

    # Transition to COMPLETED
    updated = memory_repo.update_task_status("TASK-001", TaskStatus.COMPLETED)
    assert updated.status == TaskStatus.COMPLETED

    # Insert task result
    task_res = TaskResult(
        result_id="RES-001",
        task_id="TASK-001",
        assignee=TowerId.PERFORMANCE,
        status=TaskStatus.COMPLETED,
        result_schema="netcoop://schemas/tasks/perf-output/1.0",
        result={"anomaly_detected": True},
        completed_at=sample_utc_time,
    )
    memory_repo.insert_task_result(task_res)

    saved_res = memory_repo.get_task_result("TASK-001")
    assert saved_res is not None
    assert saved_res.result["anomaly_detected"] is True


def test_sqlite_final_report_roundtrip(memory_repo: SQLiteRepository, sample_utc_time):
    report = FinalReport(
        incident_id="INC-100",
        status="diagnosed",
        suspected_root_cause="Link congestion at SW_CAMPUS_5",
        confidence=0.88,
        confidence_category=ConfidenceCategory.HIGH,
        affected_devices=["SW_CAMPUS_5"],
        supporting_evidence=[
            SupportingEvidenceItem(
                metric="link_utilization_pct",
                value=94.2,
                interpretation="Near capacity",
            )
        ],
        alternative_causes=[],
        recommended_actions=["Review uplink traffic"],
        evidence_sources=["performance"],
        limitations=[],
        generated_at=sample_utc_time,
    )
    memory_repo.insert_final_report(report)

    stored = memory_repo.get_final_report("INC-100")
    assert stored is not None
    assert stored.suspected_root_cause == "Link congestion at SW_CAMPUS_5"
    assert stored.confidence == 0.88
