"""Phase 8: Comprehensive benchmark evaluation, robustness, and ground-truth isolation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from netcoop.cli.main import _load_observations_from_target
from netcoop.models.observations import MetricObservation
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.supervisor.runtime import SupervisorRuntime

SCENARIOS_DIR = Path("fixtures/scenarios")


@pytest.mark.parametrize(
    "scenario_name,expected_fault_code,is_abstain",
    [
        ("healthy", "ABSTAIN", True),
        ("link_congestion", "LINK_CONGESTION", False),
        ("weak_wifi", "WEAK_WIFI", False),
        ("device_overload", "DEVICE_OVERLOAD", False),
        ("dns_failure", "DNS_FAILURE", False),
        ("interface_fault", "INTERFACE_FAULT", False),
        ("dhcp_failure", "DHCP_FAILURE", False),
    ],
)
def test_all_seven_benchmark_scenarios_accuracy(
    scenario_name: str, expected_fault_code: str, is_abstain: bool
):
    """Evaluates diagnosis across all 7 benchmark scenarios against official ground truth."""
    scenario_path = SCENARIOS_DIR / scenario_name
    inc_id, observations = _load_observations_from_target(scenario_path)

    repo = SQLiteRepository(":memory:")
    runtime = SupervisorRuntime(repository=repo)
    report = runtime.run_incident(incident_id=inc_id, observations=observations)

    if is_abstain:
        assert report.status == "insufficient_evidence"
        assert "ABSTAIN" in report.suspected_root_cause
        assert report.confidence == 0.0
    else:
        assert report.status == "diagnosed"
        assert expected_fault_code in report.suspected_root_cause
        assert report.confidence >= 0.60
        assert len(report.supporting_evidence) > 0
        assert len(report.affected_devices) > 0

    # Verify ground truth alignment
    gt_file = scenario_path / "evaluation" / "ground_truth.json"
    if gt_file.exists():
        gt = json.loads(gt_file.read_text(encoding="utf-8"))
        if is_abstain:
            assert gt.get("injected_fault_class") == "healthy"
        else:
            injected = gt.get("injected_fault_class", "").upper()
            assert expected_fault_code in injected
            target = gt.get("target_entity")
            if target and target != "none":
                assert any(target in d for d in report.affected_devices)


def test_red_herring_high_utilization_alone_does_not_diagnose_congestion():
    """Confirms that high link utilization alone does not result in link congestion diagnosis."""
    repo = SQLiteRepository(":memory:")
    runtime = SupervisorRuntime(repository=repo)

    # Telemetry with 92% link utilization but 0 packet loss and 0 queue drops
    obs = [
        MetricObservation(
            observation_id="OBS-RH-01",
            incident_id="INC-REDHERRING",
            source="collector/synthetic",
            entity_id="SW_CAMPUS_1:Gi0/1",
            metric_name="link_utilization_pct",
            value=92.5,
            unit="percent",
            timestamp="2026-10-31T12:00:00Z",
        ),
        MetricObservation(
            observation_id="OBS-RH-02",
            incident_id="INC-REDHERRING",
            source="collector/synthetic",
            entity_id="SW_CAMPUS_1:Gi0/1",
            metric_name="packet_loss_pct",
            value=0.0,
            unit="percent",
            timestamp="2026-10-31T12:00:00Z",
        ),
        MetricObservation(
            observation_id="OBS-RH-03",
            incident_id="INC-REDHERRING",
            source="collector/synthetic",
            entity_id="SW_CAMPUS_1:Gi0/1",
            metric_name="queue_drops",
            value=0.0,
            unit="count",
            timestamp="2026-10-31T12:00:00Z",
        ),
    ]

    report = runtime.run_incident(incident_id="INC-REDHERRING", observations=obs)
    # Must abstain because high utilization without queue pressure or loss is normal workload
    assert report.status == "insufficient_evidence"
    assert "ABSTAIN" in report.suspected_root_cause


def test_deterministic_replay_and_reproducibility():
    """Verifies that running the same telemetry repeatedly produces identical output."""
    scenario_path = SCENARIOS_DIR / "link_congestion"
    inc_id, observations = _load_observations_from_target(scenario_path)

    # Run 1
    repo1 = SQLiteRepository(":memory:")
    runtime1 = SupervisorRuntime(repository=repo1)
    report1 = runtime1.run_incident(incident_id=inc_id, observations=observations)

    # Run 2
    repo2 = SQLiteRepository(":memory:")
    runtime2 = SupervisorRuntime(repository=repo2)
    report2 = runtime2.run_incident(incident_id=inc_id, observations=observations)

    assert report1.suspected_root_cause == report2.suspected_root_cause
    assert report1.confidence == report2.confidence
    assert report1.affected_devices == report2.affected_devices
    assert report1.status == report2.status
    assert len(report1.supporting_evidence) == len(report2.supporting_evidence)


def test_zero_leakage_of_ground_truth_into_runtime():
    """Verifies runtime modules do not import or leak evaluation ground_truth."""
    runtime_src = Path("src/netcoop")
    for py_file in runtime_src.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "ground_truth.json" not in content, f"Leaked ground truth reference in {py_file}"
        assert "evaluation/ground_truth" not in content, f"Leaked ground truth reference in {py_file}"
