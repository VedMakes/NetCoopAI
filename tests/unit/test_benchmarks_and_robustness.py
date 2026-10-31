"""Phase 8: Comprehensive benchmark evaluation, robustness, and ground-truth isolation tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from netcoop.cli.main import _load_observations_from_target
from netcoop.communication.fabric import IntegrationFabric
from netcoop.configuration.profile import NetworkProfile
from netcoop.models.observations import MetricObservation
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.supervisor.runtime import SupervisorRuntime
from netcoop.towers.rules import load_rules
from reference.sample_generator import SCENARIO_PRESETS, generate_scenario

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


def test_cli_ingestion_quarantine_is_preserved_in_final_report(tmp_path: Path):
    source = SCENARIOS_DIR / "link_congestion"
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        (source / "telemetry.jsonl").read_text(encoding="utf-8") + "{broken json line\n",
        encoding="utf-8",
    )
    shutil.copyfile(source / "topology.json", tmp_path / "topology.json")

    quality_warnings: list[str] = []
    incident_id, observations = _load_observations_from_target(
        tmp_path, data_quality_warnings=quality_warnings
    )
    report = SupervisorRuntime().run_incident(
        incident_id, observations, data_quality_warnings=quality_warnings
    )

    assert report.status == "diagnosed"
    assert len(report.data_quality_warnings) == 1
    assert "quarantined record" in report.data_quality_warnings[0]


@pytest.mark.parametrize("scenario_name", list(SCENARIO_PRESETS))
@pytest.mark.parametrize("seed", [7, 42, 2026])
def test_owned_generator_multi_seed_diagnostic_matrix(tmp_path: Path, scenario_name: str, seed: int):
    """Score generated cases across seeds; ground truth is read only by this test."""
    scenario = tmp_path / f"{scenario_name}-{seed}"
    generate_scenario(scenario_name, scenario, seed=seed, num_steps=15)
    incident_id, observations = _load_observations_from_target(scenario)
    report = SupervisorRuntime().run_incident(incident_id, observations)
    truth = json.loads((scenario / "evaluation" / "ground_truth.json").read_text(encoding="utf-8"))

    expected = truth["injected_fault_class"].upper()
    if expected == "HEALTHY":
        assert report.status == "insufficient_evidence", (scenario_name, seed, report)
    else:
        assert report.status == "diagnosed", (scenario_name, seed, report)
        assert expected.upper() in report.suspected_root_cause.upper(), (scenario_name, seed, report)
        assert truth["target_entity"] in report.affected_devices, (scenario_name, seed, report.affected_devices)


@pytest.mark.parametrize(
    "scenario_name,expected_scope",
    [
        ("dns_failure", ["HOSTEL_ZONE_A", "SRV_DNS_01"]),
        ("dhcp_failure", ["HOSTEL_ZONE_A", "SRV_DHCP_01"]),
    ],
)
def test_service_diagnoses_record_real_services_to_connectivity_peer_query(scenario_name, expected_scope):
    incident_id, observations = _load_observations_from_target(SCENARIOS_DIR / scenario_name)
    report = SupervisorRuntime().run_incident(incident_id, observations)

    assert report.status == "diagnosed"
    service_interactions = [
        item for item in report.peer_interactions
        if item["requester"] == "services" and not item.get("supplementary")
    ]
    supplemental_interactions = [
        item for item in report.peer_interactions if item.get("supplementary")
    ]
    assert len(service_interactions) == 1
    assert len(supplemental_interactions) == 1
    interaction = service_interactions[0]
    assert interaction["requester"] == "services"
    assert interaction["recipient"] == "connectivity"
    assert interaction["capability"] == "connectivity.trace_path"
    assert interaction["scope"] == expected_scope
    assert interaction["status"] == "completed"
    assert interaction["result"]["reachable"] is True
    assert supplemental_interactions[0]["requester"] == "supervisor"
    assert supplemental_interactions[0]["result"]["reachable"] is True


def test_report_separates_entities_with_cited_symptoms_from_predicted_impact():
    incident_id, observations = _load_observations_from_target(SCENARIOS_DIR / "dns_failure")
    report = SupervisorRuntime().run_incident(incident_id, observations)

    assert "SRV_DNS_01" in report.observed_symptom_entities
    assert "HOSTEL_ZONE_A" in report.inferred_affected_entities
    assert set(report.observed_symptom_entities) <= set(report.affected_devices)
    assert set(report.inferred_affected_entities) <= set(report.affected_devices)


def test_compound_dns_and_dhcp_incident_queries_each_declared_service_dependency():
    observations = []
    for scenario_name in ("dns_failure", "dhcp_failure"):
        _, case_observations = _load_observations_from_target(SCENARIOS_DIR / scenario_name)
        observations.extend(
            obs.model_copy(update={
                "incident_id": "INC-DNS-DHCP-COMPOUND",
                "observation_id": f"{scenario_name}:{obs.observation_id}",
            })
            for obs in case_observations
        )

    report = SupervisorRuntime().run_incident("INC-DNS-DHCP-COMPOUND", observations)

    assert report.status == "diagnosed"
    assert {tuple(item["scope"]) for item in report.peer_interactions} == {
        ("HOSTEL_ZONE_A", "SRV_DNS_01"),
        ("HOSTEL_ZONE_A", "SRV_DHCP_01"),
    }
    assert all(item["result"]["reachable"] is True for item in report.peer_interactions)


def test_service_peer_query_reports_unknown_for_missing_path_in_unknown_topology(tmp_path: Path):
    source = SCENARIOS_DIR / "dhcp_failure"
    (tmp_path / "telemetry.jsonl").write_text(
        (source / "telemetry.jsonl").read_text(encoding="utf-8"), encoding="utf-8"
    )
    topology = json.loads((source / "topology.json").read_text(encoding="utf-8"))
    topology["links"] = []
    (tmp_path / "topology.json").write_text(json.dumps(topology), encoding="utf-8")
    profile = NetworkProfile.model_validate({
        "profile_id": "unknown-topology", "display_name": "Unknown completeness",
        "topology_completeness": "unknown",
    })
    incident_id, observations = _load_observations_from_target(tmp_path, profile=profile)
    report = SupervisorRuntime(
        fabric=IntegrationFabric(rules=profile.apply_to_rules(load_rules())),
        network_profile={"profile_id": profile.profile_id, "version": profile.version},
    ).run_incident(incident_id, observations)

    assert report.status == "diagnosed"
    path_interactions = [
        item for item in report.peer_interactions
        if item["capability"] == "connectivity.trace_path"
    ]
    assert len(path_interactions) == 2
    assert all(item["result"]["reachable"] is None for item in path_interactions)
    assert all("unknown" in item["result"]["warning"] for item in path_interactions)


def test_generated_compound_dns_and_congestion_preserves_both_causes(tmp_path: Path):
    fault_cases = []
    for name in ("dns_failure", "link_congestion"):
        folder = tmp_path / name
        generate_scenario(name, folder, seed=31, num_steps=15)
        _, observations = _load_observations_from_target(folder)
        fault_cases.extend(
            obs.model_copy(update={
                "incident_id": "INC-COMPOUND",
                "observation_id": f"{name}:{obs.observation_id}",
            })
            for obs in observations
        )

    report = SupervisorRuntime().run_incident("INC-COMPOUND", fault_cases)

    assert report.status == "diagnosed"
    causes = [report.suspected_root_cause, *report.concurrent_causes]
    assert any("DNS_FAILURE" in cause for cause in causes)
    assert any("LINK_CONGESTION" in cause for cause in causes)


def test_invalid_topology_is_reported_and_diagnosis_continues(tmp_path: Path):
    source = SCENARIOS_DIR / "link_congestion"
    (tmp_path / "telemetry.jsonl").write_text(
        (source / "telemetry.jsonl").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "topology.json").write_text('{"links": [broken', encoding="utf-8")
    warnings: list[str] = []
    incident_id, observations = _load_observations_from_target(tmp_path, data_quality_warnings=warnings)
    report = SupervisorRuntime().run_incident(incident_id, observations, data_quality_warnings=warnings)

    assert report.status == "diagnosed"
    assert any("topology file ignored" in warning for warning in report.data_quality_warnings)
