"""Unit tests for the Infrastructure Health Tower and Engine."""

from datetime import datetime

from netcoop.communication.queries import PeerQuery
from netcoop.communication.tasks import InvestigationTask
from netcoop.models.enums import (
    ConfidenceCategory,
    QueryStatus,
    Severity,
    TaskStatus,
    TowerId,
)
from netcoop.models.observations import LogObservation, MetricObservation
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.towers.infrastructure import InfrastructureEngine, InfrastructureTower


def make_metric(
    obs_id: str,
    entity_id: str,
    metric_name: str,
    value: float,
    unit: str,
    timestamp: datetime,
    incident_id: str = "INC-INFRA-TEST",
) -> MetricObservation:
    return MetricObservation(
        observation_id=obs_id,
        incident_id=incident_id,
        source="test",
        entity_id=entity_id,
        metric_name=metric_name,
        value=value,
        unit=unit,
        timestamp=timestamp,
    )


def test_device_overload_detected(sample_utc_time):
    observations = [
        make_metric("C1", "SW_CORE_01", "cpu_utilization_pct", 98.5, "percent", sample_utc_time),
        make_metric("M1", "SW_CORE_01", "memory_utilization_pct", 92.0, "percent", sample_utc_time),
    ]

    engine = InfrastructureEngine()
    findings, hypotheses = engine.analyze("INC-OVERLOAD", observations)

    assert len(findings) == 1
    assert findings[0].finding_type == "hardware_overload"
    assert findings[0].severity == Severity.CRITICAL
    assert findings[0].entity_refs == ["SW_CORE_01"]
    assert "C1" in findings[0].evidence_refs
    assert "M1" in findings[0].evidence_refs

    assert len(hypotheses) == 1
    assert hypotheses[0].fault_code == "DEVICE_OVERLOAD"
    assert hypotheses[0].confidence_category == ConfidenceCategory.HIGH
    assert "SW_CORE_01" in hypotheses[0].suspected_entities


def test_interface_fault_detected(sample_utc_time):
    observations = [
        make_metric("E1", "SW_DIST_DEPT:Gi0/1", "interface_errors", 120.0, "count", sample_utc_time),
        make_metric("F1", "SW_DIST_DEPT:Gi0/1", "link_flaps", 2.0, "count", sample_utc_time),
    ]

    engine = InfrastructureEngine()
    findings, hypotheses = engine.analyze("INC-IFACE", observations)

    assert len(findings) == 1
    assert findings[0].finding_type == "interface_degradation"
    assert findings[0].severity == Severity.HIGH
    assert "E1" in findings[0].evidence_refs
    assert "F1" in findings[0].evidence_refs

    assert len(hypotheses) == 1
    assert hypotheses[0].fault_code == "INTERFACE_FAULT"
    assert "SW_DIST_DEPT:Gi0/1" in hypotheses[0].suspected_entities


def test_log_error_detection_and_deduplication(sample_utc_time):
    log1 = LogObservation(
        observation_id="L1",
        incident_id="INC-LOGS",
        source="syslog",
        entity_id="SW_CORE_01",
        log_level="CRITICAL",
        message="LINK-3-UPDOWN: Interface GigabitEthernet0/2, changed state to down",
        facility="LINK",
        timestamp=sample_utc_time,
    )
    # Duplicate message with different timestamp should be deduplicated
    log2 = LogObservation(
        observation_id="L2",
        incident_id="INC-LOGS",
        source="syslog",
        entity_id="SW_CORE_01",
        log_level="CRITICAL",
        message="LINK-3-UPDOWN: Interface GigabitEthernet0/2, changed state to down",
        facility="LINK",
        timestamp=sample_utc_time,
    )

    engine = InfrastructureEngine()
    findings, _ = engine.analyze("INC-LOGS", [log1, log2])

    assert len(findings) == 1
    assert findings[0].finding_type == "interface_degradation"
    assert findings[0].severity == Severity.HIGH
    assert "L1" in findings[0].evidence_refs


def test_normal_telemetry_causes_no_faults(sample_utc_time):
    observations = [
        make_metric("C1", "SW_CORE_01", "cpu_utilization_pct", 25.0, "percent", sample_utc_time),
        make_metric("M1", "SW_CORE_01", "memory_utilization_pct", 40.0, "percent", sample_utc_time),
        make_metric("E1", "SW_CORE_01:Gi0/1", "interface_errors", 0.0, "count", sample_utc_time),
        make_metric("F1", "SW_CORE_01:Gi0/1", "link_flaps", 0.0, "count", sample_utc_time),
    ]

    engine = InfrastructureEngine()
    findings, hypotheses = engine.analyze("INC-NORM", observations)

    assert len(findings) == 0
    assert len(hypotheses) == 0


def test_infrastructure_tower_controller_and_sqlite(memory_repo: SQLiteRepository, sample_utc_time):
    observations = [
        make_metric("C1", "SW_CORE_01", "cpu_utilization_pct", 96.0, "percent", sample_utc_time, incident_id="INC-TOWER-INFRA"),
    ]
    for obs in observations:
        memory_repo.insert_observation(obs)

    tower = InfrastructureTower(repository=memory_repo)
    assert tower.tower_id == TowerId.INFRASTRUCTURE
    assert len(tower.capabilities) > 0

    report = tower.analyze_incident("INC-TOWER-INFRA")
    assert report.tower_id == TowerId.INFRASTRUCTURE
    assert report.status == "completed"
    assert len(report.findings) == 1

    stored_findings = memory_repo.get_findings("INC-TOWER-INFRA", tower_id=TowerId.INFRASTRUCTURE)
    assert len(stored_findings) == 1


def test_infrastructure_peer_query_and_task(sample_utc_time):
    tower = InfrastructureTower()
    query = PeerQuery(
        query_id="QRY-INFRA-01",
        incident_id="INC-1",
        requester="performance",
        recipient="infrastructure",
        capability="infrastructure.query_interface_health",
        scope=["SW_CORE:Gi0/1"],
        expected_schema="netcoop://schemas/capabilities/infrastructure-interface-health-output/1.0",
        created_at=sample_utc_time,
    )
    result = tower.handle_query(query)
    assert result.status == QueryStatus.COMPLETED

    task = InvestigationTask(
        task_id="TASK-INFRA-01",
        incident_id="INC-1",
        assignee=TowerId.INFRASTRUCTURE,
        capability="infrastructure.check_device_health",
        objective={"entity": "SW_CORE_01"},
        expected_result_schema="netcoop://schemas/tasks/infra-health-output/1.0",
        status=TaskStatus.RUNNING,
        created_at=sample_utc_time,
        updated_at=sample_utc_time,
    )
    task_res = tower.execute_task(task)
    assert task_res.status == TaskStatus.COMPLETED
