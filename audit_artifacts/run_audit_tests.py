#!/usr/bin/env python3
"""NetCoop AI — Independent Hardcoding and Metamorphic Verification Test Runner.

Executes black-box, metamorphic, and adversarial tests against the live runtime.
Automatically verifies expected properties with rigorous assertions.
Produces structured JSON outputs and exits with non-zero exit code on failure.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from netcoop.cli.main import _load_observations_from_target
from netcoop.models.observations import (
    CanonicalObservation,
    LogObservation,
    MetricObservation,
    TopologyObservation,
)
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.supervisor.runtime import SupervisorRuntime

BASE_DIR = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = BASE_DIR / "fixtures" / "scenarios"
OUTPUT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def run_pipeline(
    observations: list[CanonicalObservation],
    incident_id: str | None = None,
    symptom: str = "",
) -> dict[str, Any]:
    inc_id = incident_id or f"INC-AUDIT-{uuid.uuid4().hex[:8]}"

    scoped_obs = []
    for o in observations:
        o_copy = copy.deepcopy(o)
        o_copy.incident_id = inc_id
        scoped_obs.append(o_copy)

    repo = SQLiteRepository(":memory:")
    runtime = SupervisorRuntime(repository=repo)
    report = runtime.run_incident(incident_id=inc_id, observations=scoped_obs, symptom=symptom)
    gate_result = repo.get_gate_result(inc_id)
    tower_reports = repo.get_tower_reports(inc_id)

    return {
        "incident_id": inc_id,
        "report_status": str(report.status),
        "diagnostic_status": getattr(report, "diagnostic_status", "DIAGNOSIS"),
        "suspected_root_cause": report.suspected_root_cause,
        "confidence": report.confidence,
        "confidence_category": report.confidence_category.value if hasattr(report.confidence_category, "value") else str(report.confidence_category),
        "affected_devices": report.affected_devices,
        "directly_affected_entities": report.directly_affected_entities,
        "observed_symptom_entities": report.observed_symptom_entities,
        "inferred_affected_entities": report.inferred_affected_entities,
        "supporting_evidence_count": len(report.supporting_evidence),
        "supporting_evidence": [
            {"metric": e.metric, "value": e.value, "interpretation": e.interpretation, "entity_id": e.entity_id}
            for e in report.supporting_evidence
        ],
        "alternative_causes": report.alternative_causes,
        "concurrent_causes": report.concurrent_causes,
        "limitations": report.limitations,
        "gate_outcome": gate_result.outcome.value if gate_result else "NONE",
        "gate_passed": gate_result.passed if gate_result else False,
        "gate_checks": [
            {"name": c.check_name, "passed": c.passed, "message": c.message}
            for c in getattr(gate_result, "checks", [])
        ],
        "gate_errors": getattr(gate_result, "errors", []),
        "gate_warnings": getattr(gate_result, "warnings", []),
        "gate_limitations": getattr(gate_result, "limitations", []),
        "towers": [
            {
                "tower_id": tr.tower_id.value,
                "findings_count": len(tr.findings),
                "hypotheses_count": len(tr.hypotheses),
                "hypotheses": [
                    {"code": h.fault_code, "confidence": h.confidence_score, "rationale": h.rationale}
                    for h in tr.hypotheses
                ],
            }
            for tr in tower_reports
        ],
    }


def test_a_baseline_scenarios() -> tuple[dict[str, Any], bool]:
    print(">>> Running Test A: 7 Baseline Scenarios...")
    expected_matrix = {
        "healthy": {"is_fault": False, "fault_code": "ABSTAIN", "diagnostic_status": "NORMAL"},
        "link_congestion": {"is_fault": True, "fault_code": "LINK_CONGESTION", "diagnostic_status": "DIAGNOSIS"},
        "weak_wifi": {"is_fault": True, "fault_code": "WEAK_WIFI", "diagnostic_status": "DIAGNOSIS"},
        "interface_fault": {"is_fault": True, "fault_code": "INTERFACE_FAULT", "diagnostic_status": "DIAGNOSIS"},
        "device_overload": {"is_fault": True, "fault_code": "DEVICE_OVERLOAD", "diagnostic_status": "DIAGNOSIS"},
        "dns_failure": {"is_fault": True, "fault_code": "DNS_FAILURE", "diagnostic_status": "DIAGNOSIS"},
        "dhcp_failure": {"is_fault": True, "fault_code": "DHCP_FAILURE", "diagnostic_status": "DIAGNOSIS"},
    }

    results = {}
    all_passed = True

    for name, expected in expected_matrix.items():
        path = SCENARIOS_DIR / name
        inc_id, obs = _load_observations_from_target(path)
        res = run_pipeline(obs, incident_id=f"INC-TEST-A-{name}")

        status = "PASS"
        failure_reasons = []

        if not expected["is_fault"]:
            if res["gate_outcome"] != "ABSTAIN":
                status = "FAIL"
                failure_reasons.append(f"Expected gate outcome ABSTAIN, got {res['gate_outcome']}")
            if res["diagnostic_status"] != expected["diagnostic_status"]:
                status = "FAIL"
                failure_reasons.append(f"Expected diagnostic status {expected['diagnostic_status']}, got {res['diagnostic_status']}")
        else:
            if not res["gate_passed"]:
                status = "FAIL"
                failure_reasons.append("Expected gate certification to pass")
            if expected["fault_code"] not in res["suspected_root_cause"]:
                status = "FAIL"
                failure_reasons.append(f"Expected {expected['fault_code']} in root cause, got {res['suspected_root_cause']}")

        if status == "FAIL":
            all_passed = False

        res["test_assertion"] = {
            "status": status,
            "expected_fault": expected["fault_code"],
            "failure_reasons": failure_reasons,
        }
        results[name] = res
        print(f"  [{name}] -> Status: {status} | Cause: {res['suspected_root_cause'][:55]} | Gate: {res['gate_outcome']}")

    return results, all_passed


def test_b_identity_independence() -> tuple[dict[str, Any], bool]:
    print("\n>>> Running Test B: Scenario Identity Independence (Genuine Anonymous Dir Execution)...")
    cases = [
        ("link_congestion", "INC-ANONYMOUS-TEST-9921", "LINK_CONGESTION"),
        ("dns_failure", "INC-ANONYMOUS-DNS-4412", "DNS_FAILURE"),
        ("weak_wifi", "INC-ANONYMOUS-WIFI-3321", "WEAK_WIFI"),
    ]
    results = {}
    all_passed = True

    for scenario_name, blind_id, expected_code in cases:
        src_dir = SCENARIOS_DIR / scenario_name
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Genuine anonymous directory creation on filesystem
            anon_dir = Path(tmp_dir) / f"isolated_benchmark_{uuid.uuid4().hex[:8]}"
            anon_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_dir / "telemetry.jsonl", anon_dir / "telemetry.jsonl")
            shutil.copy2(src_dir / "topology.json", anon_dir / "topology.json")

            # Load strictly from anonymous target
            _, raw_obs = _load_observations_from_target(anon_dir)
            res = run_pipeline(raw_obs, incident_id=blind_id)

            status = "PASS"
            failure_reasons = []
            if expected_code not in res["suspected_root_cause"]:
                status = "FAIL"
                failure_reasons.append(f"Blinded run failed to diagnose {expected_code}; got {res['suspected_root_cause']}")
                all_passed = False

            res["test_assertion"] = {
                "status": status,
                "anonymous_path": str(anon_dir),
                "expected_fault": expected_code,
                "failure_reasons": failure_reasons,
            }
            results[f"blinded_{scenario_name}"] = res
            print(f"  [blinded_{scenario_name}] -> Status: {status} | Cause: {res['suspected_root_cause'][:55]}")

    return results, all_passed


def test_c_evidence_perturbation() -> tuple[dict[str, Any], bool]:
    print("\n>>> Running Test C: Evidence Perturbation...")
    results = {}
    all_passed = True

    # Perturbation 1: Lower utilization on link_congestion to 25%, zero out drops
    _, obs = _load_observations_from_target(SCENARIOS_DIR / "link_congestion")
    perturbed_obs = []
    for o in obs:
        o_copy = copy.deepcopy(o)
        if isinstance(o_copy, MetricObservation):
            if o_copy.metric_name == "link_utilization_pct":
                o_copy.value = 25.0
            elif o_copy.metric_name in ("queue_drops", "packet_loss_pct"):
                o_copy.value = 0.0
            elif o_copy.metric_name == "latency_ms":
                o_copy.value = 10.0
        perturbed_obs.append(o_copy)

    res_cong_low = run_pipeline(perturbed_obs, incident_id="INC-PERTURB-CONGESTION-LOW")
    p1_passed = res_cong_low["gate_outcome"] == "ABSTAIN" and res_cong_low["diagnostic_status"] in ("NORMAL", "INSUFFICIENT_EVIDENCE")
    if not p1_passed:
        all_passed = False
    res_cong_low["test_assertion"] = {"status": "PASS" if p1_passed else "FAIL", "expected": "ABSTAIN/NORMAL"}
    results["link_congestion_lowered_to_normal"] = res_cong_low
    print(f"  [link_congestion_lowered] -> Status: {'PASS' if p1_passed else 'FAIL'} | Cause: {res_cong_low['suspected_root_cause'][:55]}")

    # Perturbation 2: Improve weak_wifi RSSI to strong -40dBm and SNR to 35dB
    _, wifi_obs = _load_observations_from_target(SCENARIOS_DIR / "weak_wifi")
    perturbed_wifi = []
    for o in wifi_obs:
        o_copy = copy.deepcopy(o)
        if isinstance(o_copy, MetricObservation):
            if o_copy.metric_name == "rssi_dbm":
                o_copy.value = -40.0
            elif o_copy.metric_name == "snr_db":
                o_copy.value = 35.0
            elif o_copy.metric_name == "packet_loss_pct":
                o_copy.value = 0.0
        perturbed_wifi.append(o_copy)

    res_wifi_norm = run_pipeline(perturbed_wifi, incident_id="INC-PERTURB-WIFI-STRONG")
    p2_passed = res_wifi_norm["gate_outcome"] == "ABSTAIN"
    if not p2_passed:
        all_passed = False
    res_wifi_norm["test_assertion"] = {"status": "PASS" if p2_passed else "FAIL", "expected": "ABSTAIN"}
    results["weak_wifi_improved_to_strong"] = res_wifi_norm
    print(f"  [weak_wifi_improved] -> Status: {'PASS' if p2_passed else 'FAIL'} | Cause: {res_wifi_norm['suspected_root_cause'][:55]}")

    # Perturbation 3: Lower CPU on device_overload to 15%
    _, dev_obs = _load_observations_from_target(SCENARIOS_DIR / "device_overload")
    perturbed_dev = []
    for o in dev_obs:
        o_copy = copy.deepcopy(o)
        if isinstance(o_copy, MetricObservation) and o_copy.metric_name in ("cpu_utilization_pct", "memory_utilization_pct"):
            o_copy.value = 15.0
        perturbed_dev.append(o_copy)

    res_dev_low = run_pipeline(perturbed_dev, incident_id="INC-PERTURB-CPU-LOW")
    p3_passed = res_dev_low["gate_outcome"] == "ABSTAIN"
    if not p3_passed:
        all_passed = False
    res_dev_low["test_assertion"] = {"status": "PASS" if p3_passed else "FAIL", "expected": "ABSTAIN"}
    results["device_overload_lowered_to_idle"] = res_dev_low
    print(f"  [device_overload_lowered] -> Status: {'PASS' if p3_passed else 'FAIL'} | Cause: {res_dev_low['suspected_root_cause'][:55]}")

    # Perturbation 4: Clean DNS latency to 15ms and remove SERVFAIL logs
    _, dns_obs = _load_observations_from_target(SCENARIOS_DIR / "dns_failure")
    perturbed_dns = []
    for o in dns_obs:
        o_copy = copy.deepcopy(o)
        if isinstance(o_copy, MetricObservation) and o_copy.metric_name == "latency_ms":
            o_copy.value = 15.0
            perturbed_dns.append(o_copy)
        elif isinstance(o_copy, LogObservation):
            if "SERVFAIL" in o_copy.message.upper() or "TIMEOUT" in o_copy.message.upper():
                o_copy.message = "Query processed successfully in 15ms NOERROR"
                o_copy.log_level = "INFO"
            perturbed_dns.append(o_copy)
        else:
            perturbed_dns.append(o_copy)

    res_dns_clean = run_pipeline(perturbed_dns, incident_id="INC-PERTURB-DNS-FAST")
    p4_passed = res_dns_clean["gate_outcome"] == "ABSTAIN"
    if not p4_passed:
        all_passed = False
    res_dns_clean["test_assertion"] = {"status": "PASS" if p4_passed else "FAIL", "expected": "ABSTAIN"}
    results["dns_failure_fixed_to_fast"] = res_dns_clean
    print(f"  [dns_failure_fixed] -> Status: {'PASS' if p4_passed else 'FAIL'} | Cause: {res_dns_clean['suspected_root_cause'][:55]}")

    return results, all_passed


def test_d_evidence_removal() -> tuple[dict[str, Any], bool]:
    print("\n>>> Running Test D: Evidence Removal (Corroboration Enforcement)...")
    results = {}
    all_passed = True

    # Removal 1: Remove all queue drops and packet loss from link_congestion (leaving 97% utilization only)
    _, obs = _load_observations_from_target(SCENARIOS_DIR / "link_congestion")
    stripped_obs = [
        o for o in obs
        if not (isinstance(o, MetricObservation) and o.metric_name in ("queue_drops", "packet_loss_pct"))
    ]
    res_no_drops = run_pipeline(stripped_obs, incident_id="INC-REMOVAL-NO-DROPS")

    # MUST identify INSUFFICIENT_EVIDENCE and must NOT claim Normal telemetry!
    r1_passed = (
        res_no_drops["diagnostic_status"] == "INSUFFICIENT_EVIDENCE"
        and "Normal telemetry" not in res_no_drops["suspected_root_cause"]
        and "Insufficient evidence" in res_no_drops["suspected_root_cause"]
    )
    if not r1_passed:
        all_passed = False
    res_no_drops["test_assertion"] = {"status": "PASS" if r1_passed else "FAIL", "expected": "INSUFFICIENT_EVIDENCE"}
    results["link_congestion_without_drops_or_loss"] = res_no_drops
    print(f"  [congestion_without_drops] -> Status: {'PASS' if r1_passed else 'FAIL'} | Cause: {res_no_drops['suspected_root_cause'][:55]}")

    # Removal 2: Remove all Wi-Fi signal observations from weak_wifi
    _, wifi_obs = _load_observations_from_target(SCENARIOS_DIR / "weak_wifi")
    stripped_wifi = [
        o for o in wifi_obs
        if not (isinstance(o, MetricObservation) and o.metric_name in ("rssi_dbm", "snr_db"))
    ]
    res_no_rssi = run_pipeline(stripped_wifi, incident_id="INC-REMOVAL-NO-RSSI")
    r2_passed = res_no_rssi["gate_outcome"] == "ABSTAIN"
    if not r2_passed:
        all_passed = False
    res_no_rssi["test_assertion"] = {"status": "PASS" if r2_passed else "FAIL", "expected": "ABSTAIN"}
    results["weak_wifi_without_rssi_snr"] = res_no_rssi
    print(f"  [weak_wifi_without_rssi] -> Status: {'PASS' if r2_passed else 'FAIL'} | Cause: {res_no_rssi['suspected_root_cause'][:55]}")

    return results, all_passed


def test_e_contradictory_evidence() -> tuple[dict[str, Any], bool]:
    print("\n>>> Running Test E: Contradictory Evidence & Conflict Arbitration...")
    results = {}
    all_passed = True

    # Contradiction 1: 99% link utilization on SW_CORE_01:Gi0/2, BUT explicit 0 queue drops, 0% packet loss, 5ms latency
    _, obs = _load_observations_from_target(SCENARIOS_DIR / "link_congestion")
    conflicting_obs = []
    for o in obs:
        o_copy = copy.deepcopy(o)
        if isinstance(o_copy, MetricObservation):
            if o_copy.metric_name == "link_utilization_pct":
                o_copy.value = 99.0
            elif o_copy.metric_name in ("queue_drops", "packet_loss_pct"):
                o_copy.value = 0.0
            elif o_copy.metric_name == "latency_ms":
                o_copy.value = 5.0
        conflicting_obs.append(o_copy)

    res_conflict_1 = run_pipeline(conflicting_obs, incident_id="INC-CONFLICT-HIGH-UTIL-NO-DROPS")
    c1_passed = res_conflict_1["gate_outcome"] == "ABSTAIN"
    if not c1_passed:
        all_passed = False
    res_conflict_1["test_assertion"] = {"status": "PASS" if c1_passed else "FAIL", "expected": "ABSTAIN"}
    results["high_util_without_pressure"] = res_conflict_1
    print(f"  [high_util_no_pressure] -> Status: {'PASS' if c1_passed else 'FAIL'} | Cause: {res_conflict_1['suspected_root_cause'][:55]}")

    # Contradiction 2: Simultaneous Link Congestion on SW_CORE_01:Gi0/2 AND CPU Overload (96%) on SW_CORE_01
    _, dev_obs = _load_observations_from_target(SCENARIOS_DIR / "device_overload")
    merged_obs = copy.deepcopy(obs)
    for o in dev_obs:
        if isinstance(o, MetricObservation) and o.metric_name in ("cpu_utilization_pct", "memory_utilization_pct"):
            merged_obs.append(copy.deepcopy(o))

    res_multi_conflict = run_pipeline(merged_obs, incident_id="INC-CONFLICT-CONGESTION-AND-CPU")
    c2_passed = (
        ("DEVICE_OVERLOAD" in res_multi_conflict["suspected_root_cause"] and any("LINK_CONGESTION" in a for a in res_multi_conflict["alternative_causes"]))
        or ("LINK_CONGESTION" in res_multi_conflict["suspected_root_cause"] and any("DEVICE_OVERLOAD" in a for a in res_multi_conflict["alternative_causes"]))
    )
    if not c2_passed:
        all_passed = False
    res_multi_conflict["test_assertion"] = {"status": "PASS" if c2_passed else "FAIL", "expected": "DEVICE_OVERLOAD or LINK_CONGESTION arbitrated with other as alternative"}
    results["congestion_plus_cpu_overload"] = res_multi_conflict
    print(f"  [congestion_plus_cpu_overload] -> Status: {'PASS' if c2_passed else 'FAIL'} | Cause: {res_multi_conflict['suspected_root_cause'][:55]}")

    return results, all_passed


def test_f_unseen_and_mixed_conditions() -> tuple[dict[str, Any], bool]:
    print("\n>>> Running Test F: Unseen Conditions & Arbitrary Topologies...")
    results = {}
    all_passed = True
    now = datetime.now(timezone.utc)

    # Case 1: Arbitrary topology with completely unseen names: ALPHA_CORE, BETA_EDGE, GAMMA_HOST
    novel_obs: list[CanonicalObservation] = [
        TopologyObservation(
            observation_id="TOPO-NOV-01",
            incident_id="INC-NOVEL-01",
            source="config/netflow",
            timestamp=now,
            entity_id="ALPHA_CORE",
            source_entity="ALPHA_CORE",
            target_entity="BETA_EDGE",
            relationship_type="connected_to",
        ),
        TopologyObservation(
            observation_id="TOPO-NOV-02",
            incident_id="INC-NOVEL-01",
            source="config/netflow",
            timestamp=now,
            entity_id="BETA_EDGE",
            source_entity="BETA_EDGE",
            target_entity="GAMMA_HOST",
            relationship_type="connected_to",
        ),
    ]
    for i in range(5):
        novel_obs.append(
            MetricObservation(
                observation_id=f"MET-NOV-{i*2}",
                incident_id="INC-NOVEL-01",
                source="telemetry/snmp",
                timestamp=now,
                entity_id="ALPHA_CORE:eth0",
                metric_name="interface_errors",
                value=250.0 + i * 50,
                unit="count",
            )
        )
        novel_obs.append(
            MetricObservation(
                observation_id=f"MET-NOV-{i*2+1}",
                incident_id="INC-NOVEL-01",
                source="telemetry/snmp",
                timestamp=now,
                entity_id="ALPHA_CORE:eth0",
                metric_name="link_flaps",
                value=4.0 + i,
                unit="count",
            )
        )

    res_novel = run_pipeline(novel_obs, incident_id="INC-NOVEL-TOPOLOGY-01")
    f1_passed = "INTERFACE_FAULT" in res_novel["suspected_root_cause"] and "ALPHA_CORE:eth0" in res_novel["affected_devices"][0]
    if not f1_passed:
        all_passed = False
    res_novel["test_assertion"] = {"status": "PASS" if f1_passed else "FAIL", "expected": "INTERFACE_FAULT on ALPHA_CORE:eth0"}
    results["arbitrary_novel_topology"] = res_novel
    print(f"  [arbitrary_novel_topology] -> Status: {'PASS' if f1_passed else 'FAIL'} | Cause: {res_novel['suspected_root_cause'][:55]}")

    # Case 2: Multi-fault: Weak Wi-Fi on AP_HOSTEL_01 + DNS Failure on SRV_DNS_01
    _, wifi_obs = _load_observations_from_target(SCENARIOS_DIR / "weak_wifi")
    _, dns_obs = _load_observations_from_target(SCENARIOS_DIR / "dns_failure")
    combined_obs = copy.deepcopy(wifi_obs)
    for o in dns_obs:
        if "DNS" in o.entity_id or (isinstance(o, LogObservation) and "DNS" in o.message):
            combined_obs.append(copy.deepcopy(o))

    res_multi_fault = run_pipeline(combined_obs, incident_id="INC-MULTI-FAULT-WIFI-DNS")
    f2_passed = (
        ("DNS_FAILURE" in res_multi_fault["suspected_root_cause"] and any("WEAK_WIFI" in c for c in res_multi_fault["concurrent_causes"]))
        or ("WEAK_WIFI" in res_multi_fault["suspected_root_cause"] and any("DNS_FAILURE" in c for c in res_multi_fault["concurrent_causes"]))
    )
    if not f2_passed:
        all_passed = False
    res_multi_fault["test_assertion"] = {"status": "PASS" if f2_passed else "FAIL", "expected": "Multi-fault preserved primary + concurrent"}
    results["simultaneous_wifi_and_dns_fault"] = res_multi_fault
    print(f"  [simultaneous_wifi_and_dns] -> Status: {'PASS' if f2_passed else 'FAIL'} | Cause: {res_multi_fault['suspected_root_cause'][:55]}")

    # Case 3: Transient single-sample spike (should tag single-snapshot limitation)
    transient_obs: list[CanonicalObservation] = [
        MetricObservation(
            observation_id="OBS-TRANSIENT-01",
            incident_id="INC-TRANSIENT-01",
            source="telemetry",
            timestamp=now,
            entity_id="CORE_SWITCH:Gi0/1",
            metric_name="link_utilization_pct",
            value=98.0,
            unit="percent",
        ),
        MetricObservation(
            observation_id="OBS-TRANSIENT-02",
            incident_id="INC-TRANSIENT-01",
            source="telemetry",
            timestamp=now,
            entity_id="CORE_SWITCH:Gi0/1",
            metric_name="queue_drops",
            value=20.0,
            unit="count",
        ),
    ]
    res_transient = run_pipeline(transient_obs, incident_id="INC-TRANSIENT-01")
    f3_passed = any("single-snapshot" in lim.lower() for lim in res_transient["limitations"])
    if not f3_passed:
        all_passed = False
    res_transient["test_assertion"] = {"status": "PASS" if f3_passed else "FAIL", "expected": "single_snapshot_limitation"}
    results["transient_single_sample"] = res_transient
    print(f"  [transient_single_sample] -> Status: {'PASS' if f3_passed else 'FAIL'} | Limitations: {res_transient['limitations'][:1]}")

    return results, all_passed


def main():
    print("================================================================")
    print("NetCoop AI — Independent Hardcoding & Metamorphic Test Suite")
    print("================================================================\n")

    res_a, pass_a = test_a_baseline_scenarios()
    res_b, pass_b = test_b_identity_independence()
    res_c, pass_c = test_c_evidence_perturbation()
    res_d, pass_d = test_d_evidence_removal()
    res_e, pass_e = test_e_contradictory_evidence()
    res_f, pass_f = test_f_unseen_and_mixed_conditions()

    suite_passed = pass_a and pass_b and pass_c and pass_d and pass_e and pass_f

    all_artifacts = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": "PASS" if suite_passed else "FAIL",
        "test_a_baseline": res_a,
        "test_b_independence": res_b,
        "test_c_perturbation": res_c,
        "test_d_removal": res_d,
        "test_e_contradictory": res_e,
        "test_f_unseen_and_mixed": res_f,
    }

    artifact_file = OUTPUT_DIR / "audit_test_results.json"
    artifact_file.write_text(json.dumps(all_artifacts, indent=2), encoding="utf-8")
    print(f"\n✓ All audit tests completed. Artifacts saved to: {artifact_file}")

    if not suite_passed:
        print("❌ AUDIT TEST RUN FAILED: One or more automated assertions failed.")
        sys.exit(1)
    else:
        print("✅ AUDIT TEST RUN PASSED: 100% of metamorphic and adversarial assertions verified.")
        sys.exit(0)


if __name__ == "__main__":
    main()
