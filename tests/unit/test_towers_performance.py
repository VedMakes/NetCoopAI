"""Unit tests for the Performance Diagnostic Tower and Engine."""

from datetime import datetime, timedelta

from netcoop.communication.queries import PeerQuery
from netcoop.communication.tasks import DiagnosticTaskArtifact, InvestigationTask
from netcoop.models.enums import (
    ConfidenceCategory,
    QueryStatus,
    Severity,
    TaskStatus,
    TowerId,
)
from netcoop.models.observations import MetricObservation
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.towers.performance import PerformanceEngine, PerformanceTower


def make_metric(
    obs_id: str,
    entity_id: str,
    metric_name: str,
    value: float,
    unit: str,
    timestamp: datetime,
    incident_id: str = "INC-PERF-TEST",
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


def test_hypothesis_review_returns_provenance_and_explicitly_marks_no_new_measurement(sample_utc_time):
    repo = SQLiteRepository(":memory:")
    incident_id = "INC-REVIEW-ARTIFACT"
    observations = [
        make_metric("REV-UTIL-1", "SW_CORE:Gi0/2", "link_utilization_pct", 94.0, "percent", sample_utc_time, incident_id),
        make_metric("REV-UTIL-2", "SW_CORE:Gi0/2", "link_utilization_pct", 42.0, "percent", sample_utc_time, incident_id).model_copy(update={"source": "collector-b"}),
        make_metric("REV-DROP-1", "SW_CORE:Gi0/2", "queue_drops", 120.0, "count", sample_utc_time, incident_id),
    ]
    for observation in observations:
        repo.insert_observation(observation)
    tower = PerformanceTower(repository=repo)
    task = InvestigationTask(
        task_id="TASK-REVIEW-ARTIFACT",
        incident_id=incident_id,
        requester="supervisor",
        assignee=TowerId.PERFORMANCE,
        capability="performance.challenge_congestion_hypothesis",
        objective={"hypothesis_code": "LINK_CONGESTION", "target_entities": ["SW_CORE:Gi0/2"]},
        expected_result_schema="netcoop://schemas/tasks/diagnostic-artifact/1.1",
        created_at=sample_utc_time,
        updated_at=sample_utc_time,
    )

    result = tower.execute_task(task)
    artifact = DiagnosticTaskArtifact.model_validate(result.result)
    review = artifact.hypothesis_reviews[0]
    context_by_id = {item.observation_id: item for item in artifact.evidence_context}

    assert review.fault_code == "LINK_CONGESTION"
    assert set(review.supporting_evidence_refs) <= set(result.evidence_refs)
    assert set(review.inspected_evidence_refs) <= set(context_by_id)
    assert context_by_id["REV-UTIL-1"].source == "test"
    assert context_by_id["REV-UTIL-1"].observed_at == sample_utc_time
    assert review.new_evidence_refs == []
    utilization_summary = next(item for item in review.temporal_summaries if item.signal == "link_utilization_pct")
    assert utilization_summary.time_point_count == 1
    assert utilization_summary.source_count == 2
    assert utilization_summary.conflicting_time_points == 1
    assert "did not collect a live measurement" in (context_by_id["REV-UTIL-1"].limitation or "")


def test_normal_telemetry_produces_no_severe_faults(sample_utc_time):
    observations = [
        make_metric("M1", "SW_CORE:Gi0/1", "link_utilization_pct", 35.0, "percent", sample_utc_time),
        make_metric("M2", "SW_CORE:Gi0/1", "queue_drops", 0.0, "count", sample_utc_time),
        make_metric("M3", "SW_CORE:Gi0/1", "latency_ms", 8.5, "milliseconds", sample_utc_time),
        make_metric("M4", "SW_CORE:Gi0/1", "packet_loss_pct", 0.0, "percent", sample_utc_time),
    ]

    engine = PerformanceEngine()
    findings, hypotheses = engine.analyze("INC-NORMAL", observations)

    # Normal telemetry should not trigger any high or critical findings or hypotheses
    high_findings = [f for f in findings if f.severity in (Severity.HIGH, Severity.CRITICAL)]
    assert len(high_findings) == 0
    assert len(hypotheses) == 0


def test_link_congestion_detected(sample_utc_time):
    observations = [
        make_metric("M1", "SW_CORE:Gi0/2", "link_utilization_pct", 96.5, "percent", sample_utc_time),
        make_metric("M2", "SW_CORE:Gi0/2", "queue_drops", 280.0, "count", sample_utc_time),
        make_metric("M3", "SW_CORE:Gi0/2", "latency_ms", 290.0, "milliseconds", sample_utc_time),
        make_metric("M4", "SW_CORE:Gi0/2", "packet_loss_pct", 2.2, "percent", sample_utc_time),
    ]

    engine = PerformanceEngine()
    findings, hypotheses = engine.analyze("INC-CONG", observations)

    assert len(findings) >= 1
    cong_finding = findings[0]
    assert cong_finding.finding_type == "congestion_candidate"
    assert cong_finding.severity in (Severity.HIGH, Severity.CRITICAL)
    assert cong_finding.entity_refs == ["SW_CORE:Gi0/2"]

    # Invariant: Evidence references must match input observation IDs
    assert "M1" in cong_finding.evidence_refs
    assert "M2" in cong_finding.evidence_refs

    assert len(hypotheses) == 1
    assert hypotheses[0].fault_code == "LINK_CONGESTION"
    # A single complete snapshot is actionable, but cannot establish persistence.
    assert hypotheses[0].confidence_category == ConfidenceCategory.LOW
    assert "SW_CORE:Gi0/2" in hypotheses[0].suspected_entities


def test_single_congestion_spike_in_a_series_is_not_diagnosed(sample_utc_time):
    observations = []
    for step in range(5):
        ts = sample_utc_time + timedelta(seconds=30 * step)
        spike = step == 4
        observations.extend([
            make_metric(f"U{step}", "SW_CORE:Gi0/2", "link_utilization_pct", 96.0 if spike else 35.0, "percent", ts),
            make_metric(f"Q{step}", "SW_CORE:Gi0/2", "queue_drops", 250.0 if spike else 0.0, "count", ts),
            make_metric(f"L{step}", "SW_CORE:Gi0/2", "latency_ms", 250.0 if spike else 8.0, "milliseconds", ts),
            make_metric(f"P{step}", "SW_CORE:Gi0/2", "packet_loss_pct", 2.0 if spike else 0.0, "percent", ts),
        ])

    findings, hypotheses = PerformanceEngine().analyze("INC-SPIKE", observations)
    assert not hypotheses
    assert len(findings) == 1
    assert findings[0].severity == Severity.LOW


def test_high_utilization_alone_does_not_trigger_congestion_hypothesis(sample_utc_time):
    # High utilization without queue drops or latency degradation
    observations = [
        make_metric("M1", "SW_CORE:Gi0/2", "link_utilization_pct", 91.0, "percent", sample_utc_time),
        make_metric("M2", "SW_CORE:Gi0/2", "queue_drops", 0.0, "count", sample_utc_time),
        make_metric("M3", "SW_CORE:Gi0/2", "latency_ms", 12.0, "milliseconds", sample_utc_time),
        make_metric("M4", "SW_CORE:Gi0/2", "packet_loss_pct", 0.0, "percent", sample_utc_time),
    ]

    engine = PerformanceEngine()
    findings, hypotheses = engine.analyze("INC-HIGH-LOAD", observations)

    # Should emit only a low-severity warning, NOT a congestion hypothesis
    assert len(hypotheses) == 0
    assert len(findings) == 1
    assert findings[0].severity == Severity.LOW


def test_weak_wifi_detected(sample_utc_time):
    observations = [
        make_metric("W1", "AP_HOSTEL_A", "rssi_dbm", -84.0, "dbm", sample_utc_time),
        make_metric("W2", "AP_HOSTEL_A", "snr_db", 10.5, "db", sample_utc_time),
        make_metric("W3", "AP_HOSTEL_A", "throughput_mbps", 8.0, "mbps", sample_utc_time),
        make_metric("W4", "AP_HOSTEL_A", "packet_loss_pct", 6.5, "percent", sample_utc_time),
    ]

    engine = PerformanceEngine()
    findings, hypotheses = engine.analyze("INC-WIFI", observations)

    assert len(findings) == 1
    assert findings[0].finding_type == "weak_wifi_signal"
    assert findings[0].severity == Severity.HIGH
    assert "W1" in findings[0].evidence_refs
    assert "W2" in findings[0].evidence_refs

    assert len(hypotheses) == 1
    assert hypotheses[0].fault_code == "WEAK_WIFI"
    assert "AP_HOSTEL_A" in hypotheses[0].suspected_entities


def test_performance_tower_controller_and_sqlite(memory_repo: SQLiteRepository, sample_utc_time):
    observations = [
        make_metric("M1", "SW_CORE:Gi0/2", "link_utilization_pct", 95.0, "percent", sample_utc_time, incident_id="INC-TOWER-1"),
        make_metric("M2", "SW_CORE:Gi0/2", "queue_drops", 150.0, "count", sample_utc_time, incident_id="INC-TOWER-1"),
    ]
    for obs in observations:
        memory_repo.insert_observation(obs)

    tower = PerformanceTower(repository=memory_repo)
    assert tower.tower_id == TowerId.PERFORMANCE
    assert len(tower.capabilities) > 0

    report = tower.analyze_incident("INC-TOWER-1")
    assert report.tower_id == TowerId.PERFORMANCE
    assert report.status == "completed"
    assert len(report.findings) >= 1

    # Verify persisted in SQLite
    stored_findings = memory_repo.get_findings("INC-TOWER-1", tower_id=TowerId.PERFORMANCE)
    assert len(stored_findings) == len(report.findings)

    stored_reports = memory_repo.get_tower_reports("INC-TOWER-1")
    assert len(stored_reports) == 1


def test_performance_tower_peer_query_and_task(sample_utc_time):
    tower = PerformanceTower()
    query = PeerQuery(
        query_id="QRY-PERF-01",
        incident_id="INC-1",
        requester="infrastructure",
        recipient="performance",
        capability="performance.query_metric_window",
        scope=["SW_CORE:Gi0/2"],
        expected_schema="netcoop://schemas/capabilities/performance-query-metric-output/1.0",
        created_at=sample_utc_time,
    )
    result = tower.handle_query(query)
    assert result.status == QueryStatus.COMPLETED

    task = InvestigationTask(
        task_id="TASK-PERF-01",
        incident_id="INC-1",
        assignee=TowerId.PERFORMANCE,
        capability="performance.detect_congestion",
        objective={"entity": "SW_CORE:Gi0/2"},
        expected_result_schema="netcoop://schemas/tasks/congestion-output/1.0",
        status=TaskStatus.RUNNING,
        created_at=sample_utc_time,
        updated_at=sample_utc_time,
    )
    task_res = tower.execute_task(task)
    assert task_res.status == TaskStatus.COMPLETED
