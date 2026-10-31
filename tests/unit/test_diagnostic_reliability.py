"""Comprehensive diagnostic reliability, abstention semantics, gate verification, and arbitration tests."""

from __future__ import annotations

import copy
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from netcoop.cli.main import _load_observations_from_target
from netcoop.models.enums import (
    ConfidenceCategory,
    FindingStatus,
    ProposalDecision,
    Severity,
    TowerId,
)
from netcoop.models.findings import Finding
from netcoop.models.hypotheses import Hypothesis
from netcoop.models.observations import MetricObservation
from netcoop.models.reports import ClaimEvidenceManifest, SupervisorProposal
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.supervisor.agent import SupervisoryRCAAgent
from netcoop.supervisor.gate import EvidenceReleaseGate
from netcoop.supervisor.models import GateOutcome, IncidentDossier
from netcoop.supervisor.runtime import SupervisorRuntime


@pytest.fixture
def memory_repo() -> SQLiteRepository:
    return SQLiteRepository(":memory:")


def test_abstention_semantics_normal(memory_repo: SQLiteRepository):
    """Verifies NORMAL telemetry is distinguished when all metrics are nominal."""
    runtime = SupervisorRuntime(repository=memory_repo)
    now = datetime.now(timezone.utc)
    normal_obs = [
        MetricObservation(
            observation_id="OBS-NORM-1",
            incident_id="INC-HEALTHY-01",
            source="collector/telemetry",
            timestamp=now,
            entity_id="SW_CORE_01",
            metric_name="cpu_utilization_pct",
            value=22.0,
            unit="percent",
        ),
        MetricObservation(
            observation_id="OBS-NORM-2",
            incident_id="INC-HEALTHY-01",
            source="collector/telemetry",
            timestamp=now,
            entity_id="SW_CORE_01:Gi0/1",
            metric_name="link_utilization_pct",
            value=25.0,
            unit="percent",
        ),
        MetricObservation(
            observation_id="OBS-NORM-3",
            incident_id="INC-HEALTHY-01",
            source="collector/telemetry",
            timestamp=now,
            entity_id="SW_CORE_01:Gi0/1",
            metric_name="queue_drops",
            value=0.0,
            unit="count",
        ),
    ]

    report = runtime.run_incident("INC-HEALTHY-01", normal_obs)

    assert report.diagnostic_status == "NORMAL"
    assert report.status in ("insufficient_evidence", "normal")
    assert "Normal telemetry" in report.suspected_root_cause
    assert report.confidence == 0.0
    assert report.confidence_category == ConfidenceCategory.INSUFFICIENT


def test_abstention_semantics_insufficient_evidence(memory_repo: SQLiteRepository):
    """Verifies INSUFFICIENT_EVIDENCE when 97% utilization is observed without buffer pressure metrics."""
    runtime = SupervisorRuntime(repository=memory_repo)
    now = datetime.now(timezone.utc)
    # 97% utilization on core link, but NO queue drops and NO packet loss observations provided
    high_util_obs = [
        MetricObservation(
            observation_id="OBS-UTIL-97",
            incident_id="INC-UNCONFIRMED-CONG",
            source="collector/telemetry",
            timestamp=now,
            entity_id="SW_CORE_01:Gi0/2",
            metric_name="link_utilization_pct",
            value=97.0,
            unit="percent",
        ),
    ]

    report = runtime.run_incident("INC-UNCONFIRMED-CONG", high_util_obs)

    # Must NOT report normal telemetry! Must report insufficient evidence!
    assert report.diagnostic_status == "INSUFFICIENT_EVIDENCE"
    assert report.status == "insufficient_evidence"
    assert "Insufficient evidence" in report.suspected_root_cause
    assert "buffer pressure" in report.suspected_root_cause.lower() or "missing" in report.suspected_root_cause.lower()
    assert "Normal telemetry" not in report.suspected_root_cause


def test_abstention_semantics_contradictory_evidence(memory_repo: SQLiteRepository):
    """Verifies contradictory high utilization (99%) with explicit 0 drops and 5ms latency."""
    runtime = SupervisorRuntime(repository=memory_repo)
    now = datetime.now(timezone.utc)
    contradictory_obs = [
        MetricObservation(
            observation_id="OBS-UTIL-99",
            incident_id="INC-CONTRADICTION",
            source="collector/telemetry",
            timestamp=now,
            entity_id="SW_CORE_01:Gi0/2",
            metric_name="link_utilization_pct",
            value=99.0,
            unit="percent",
        ),
        MetricObservation(
            observation_id="OBS-QUEUE-0",
            incident_id="INC-CONTRADICTION",
            source="collector/telemetry",
            timestamp=now,
            entity_id="SW_CORE_01:Gi0/2",
            metric_name="queue_drops",
            value=0.0,
            unit="count",
        ),
        MetricObservation(
            observation_id="OBS-LAT-5",
            incident_id="INC-CONTRADICTION",
            source="collector/telemetry",
            timestamp=now,
            entity_id="SW_CORE_01:Gi0/2",
            metric_name="latency_ms",
            value=5.0,
            unit="milliseconds",
        ),
    ]

    report = runtime.run_incident("INC-CONTRADICTION", contradictory_obs)
    assert report.diagnostic_status in ("INSUFFICIENT_EVIDENCE", "ABSTAIN_UNRESOLVED")
    assert "LINK_CONGESTION" not in report.suspected_root_cause


def test_arbitration_strong_vs_weak():
    """Verifies a lower-priority fault (WEAK_WIFI, prio 50) with strong evidence beats a higher-priority fault (DEVICE_OVERLOAD, prio 85) with weak evidence."""
    now = datetime.now(timezone.utc)
    inc_id = "INC-COMPETE-01"

    # Strong Wi-Fi finding: critical severity, 3 qualifying samples, high confidence
    wifi_finding = Finding(
        finding_id="F-WIFI-STRONG",
        incident_id=inc_id,
        source_tower=TowerId.PERFORMANCE,
        producer="performance.detect_weak_wifi",
        finding_type="weak_wifi_signal",
        severity=Severity.CRITICAL,
        status=FindingStatus.ACTIVE,
        entity_refs=["AP_HOSTEL_01"],
        evidence_refs=["OBS-RSSI-1", "OBS-RSSI-2", "OBS-RSSI-3"],
        confidence=0.92,
        independence_group="telemetry:wifi:AP_HOSTEL_01",
        observed_at=now,
        created_at=now,
        description="Severe RF attenuation on AP_HOSTEL_01 (RSSI -88 dBm, SNR 10 dB)",
        metadata={"qualifying_samples": 3, "observed_samples": 3},
    )

    # Weak Device Overload finding: low severity, 1 sample, low confidence
    cpu_finding = Finding(
        finding_id="F-CPU-WEAK",
        incident_id=inc_id,
        source_tower=TowerId.INFRASTRUCTURE,
        producer="infrastructure.detect_device_overload",
        finding_type="hardware_overload",
        severity=Severity.LOW,
        status=FindingStatus.ACTIVE,
        entity_refs=["SW_CORE_01"],
        evidence_refs=["OBS-CPU-1"],
        confidence=0.25,
        independence_group="telemetry:cpu:SW_CORE_01",
        observed_at=now,
        created_at=now,
        description="Brief minor CPU spike on SW_CORE_01 (76%)",
        metadata={"qualifying_samples": 1, "observed_samples": 1},
    )

    hyp_wifi = Hypothesis(
        hypothesis_id="H-WIFI",
        incident_id=inc_id,
        fault_code="WEAK_WIFI",
        suspected_entities=["AP_HOSTEL_01"],
        supporting_finding_refs=["F-WIFI-STRONG"],
        confidence_score=0.92,
        confidence_category=ConfidenceCategory.HIGH,
        rationale="Severe chronic RF attenuation verified across multiple polling intervals.",
        created_at=now,
    )

    hyp_cpu = Hypothesis(
        hypothesis_id="H-CPU",
        incident_id=inc_id,
        fault_code="DEVICE_OVERLOAD",
        suspected_entities=["SW_CORE_01"],
        supporting_finding_refs=["F-CPU-WEAK"],
        confidence_score=0.25,
        confidence_category=ConfidenceCategory.LOW,
        rationale="Transient CPU reading without persistence.",
        created_at=now,
    )

    dossier = IncidentDossier(
        incident_id=inc_id,
        symptom="Network degradation",
        affected_entities=["AP_HOSTEL_01", "SW_CORE_01"],
        tower_reports={},
        findings=[wifi_finding, cpu_finding],
        hypotheses=[hyp_wifi, hyp_cpu],
        investigation_round=2,
    )

    agent = SupervisoryRCAAgent()
    proposal, manifest = agent.diagnose(dossier)

    # WEAK_WIFI must win as primary root cause despite DEVICE_OVERLOAD having higher base priority!
    assert proposal.decision == ProposalDecision.PROPOSE_DIAGNOSIS
    assert "WEAK_WIFI" in (proposal.suspected_root_cause or "")
    assert "DEVICE_OVERLOAD" not in (proposal.suspected_root_cause or "")


def test_arbitration_neither_has_enough_evidence():
    """Verifies that if neither competing hypothesis has enough evidence, the supervisor abstains."""
    now = datetime.now(timezone.utc)
    inc_id = "INC-WEAK-COMPETE"

    hyp1 = Hypothesis(
        hypothesis_id="H-WIFI-WEAK",
        incident_id=inc_id,
        fault_code="WEAK_WIFI",
        suspected_entities=["AP_HOSTEL_01"],
        supporting_finding_refs=[],
        confidence_score=0.15,
        confidence_category=ConfidenceCategory.INSUFFICIENT,
        rationale="Unconfirmed Wi-Fi flicker.",
        created_at=now,
    )
    hyp2 = Hypothesis(
        hypothesis_id="H-CONG-WEAK",
        incident_id=inc_id,
        fault_code="LINK_CONGESTION",
        suspected_entities=["SW_CORE_01:Gi0/1"],
        supporting_finding_refs=[],
        confidence_score=0.18,
        confidence_category=ConfidenceCategory.INSUFFICIENT,
        rationale="Unconfirmed link blip.",
        created_at=now,
    )

    dossier = IncidentDossier(
        incident_id=inc_id,
        symptom="General slowdown",
        affected_entities=["AP_HOSTEL_01", "SW_CORE_01:Gi0/1"],
        tower_reports={},
        findings=[],
        hypotheses=[hyp1, hyp2],
        investigation_round=2,
    )

    agent = SupervisoryRCAAgent()
    proposal, _ = agent.diagnose(dossier)

    assert proposal.decision == ProposalDecision.ABSTAIN
    assert proposal.abstain_type == "ABSTAIN_UNRESOLVED"
    assert "Neither competing hypothesis" in (proposal.abstain_reason or "")


def test_arbitration_concurrent_faults_preserved():
    """Verifies that two independent faults with strong evidence on disjoint entities are preserved concurrently."""
    now = datetime.now(timezone.utc)
    inc_id = "INC-DUAL-FAULT"

    wifi_finding = Finding(
        finding_id="F-WIFI",
        incident_id=inc_id,
        source_tower=TowerId.PERFORMANCE,
        producer="performance.detect_weak_wifi",
        finding_type="weak_wifi_signal",
        severity=Severity.HIGH,
        status=FindingStatus.ACTIVE,
        entity_refs=["AP_HOSTEL_01"],
        evidence_refs=["OBS-RF-1"],
        confidence=0.85,
        independence_group="telemetry:wifi:AP_HOSTEL_01",
        observed_at=now,
        created_at=now,
        description="RF attenuation on AP_HOSTEL_01",
        metadata={"qualifying_samples": 3},
    )

    dns_finding = Finding(
        finding_id="F-DNS",
        incident_id=inc_id,
        source_tower=TowerId.SERVICES,
        producer="services.detect_dns_failure",
        finding_type="dns_resolution_failure",
        severity=Severity.HIGH,
        status=FindingStatus.ACTIVE,
        entity_refs=["SRV_DNS_01"],
        evidence_refs=["OBS-DNS-1"],
        confidence=0.88,
        independence_group="telemetry:dns:SRV_DNS_01",
        observed_at=now,
        created_at=now,
        description="DNS timeouts on SRV_DNS_01",
        metadata={"qualifying_samples": 3},
    )

    hyp_wifi = Hypothesis(
        hypothesis_id="H-WIFI",
        incident_id=inc_id,
        fault_code="WEAK_WIFI",
        suspected_entities=["AP_HOSTEL_01"],
        supporting_finding_refs=["F-WIFI"],
        confidence_score=0.85,
        confidence_category=ConfidenceCategory.HIGH,
        rationale="Weak Wi-Fi on AP_HOSTEL_01",
        created_at=now,
    )

    hyp_dns = Hypothesis(
        hypothesis_id="H-DNS",
        incident_id=inc_id,
        fault_code="DNS_FAILURE",
        suspected_entities=["SRV_DNS_01"],
        supporting_finding_refs=["F-DNS"],
        confidence_score=0.88,
        confidence_category=ConfidenceCategory.HIGH,
        rationale="DNS failure on SRV_DNS_01",
        created_at=now,
    )

    dossier = IncidentDossier(
        incident_id=inc_id,
        symptom="Multiple complaints",
        affected_entities=["AP_HOSTEL_01", "SRV_DNS_01"],
        tower_reports={},
        findings=[wifi_finding, dns_finding],
        hypotheses=[hyp_dns, hyp_wifi],
        investigation_round=2,
    )

    agent = SupervisoryRCAAgent()
    proposal, _ = agent.diagnose(dossier)

    assert proposal.decision == ProposalDecision.PROPOSE_DIAGNOSIS
    # Primary is DNS_FAILURE
    assert "DNS_FAILURE" in (proposal.suspected_root_cause or "")
    # Concurrent causes MUST preserve WEAK_WIFI
    assert any("WEAK_WIFI" in c for c in proposal.concurrent_causes)


def test_evidence_gate_semantic_validation_rejects_unrelated_evidence():
    """Adversarial test: Gate must REJECT when proposal claims LINK_CONGESTION on core switch but cites only DNS latency observations."""
    gate = EvidenceReleaseGate()
    now = datetime.now(timezone.utc)
    inc_id = "INC-ADVERSARIAL-01"

    # Observation exists in SQLite, matches incident ID, but is for SRV_DNS_01 latency, NOT core switch utilization
    unrelated_obs = [
        MetricObservation(
            observation_id="OBS-DNS-LAT-1",
            incident_id=inc_id,
            source="collector/synthetic",
            timestamp=now,
            entity_id="SRV_DNS_01",
            metric_name="latency_ms",
            value=850.0,
            unit="milliseconds",
        )
    ]

    finding = Finding(
        finding_id="F-FAKE-CONG",
        incident_id=inc_id,
        source_tower=TowerId.PERFORMANCE,
        producer="performance.detect_congestion",
        finding_type="congestion_candidate",
        severity=Severity.HIGH,
        status=FindingStatus.ACTIVE,
        entity_refs=["SW_CORE_01:Gi0/2"],
        evidence_refs=["OBS-DNS-LAT-1"],
        confidence=0.85,
        independence_group="telemetry:fake",
        observed_at=now,
        created_at=now,
        description="Fake finding linking DNS observation to congestion claim",
    )

    proposal = SupervisorProposal(
        proposal_id="PROP-ADV-01",
        incident_id=inc_id,
        decision=ProposalDecision.PROPOSE_DIAGNOSIS,
        suspected_root_cause="LINK_CONGESTION: High utilization on SW_CORE_01:Gi0/2",
        affected_entities=["SW_CORE_01:Gi0/2"],
        supporting_finding_refs=["F-FAKE-CONG"],
        confidence_category=ConfidenceCategory.HIGH,
        alternative_causes=[],
        recommended_actions=[],
        created_at=now,
    )

    manifest = ClaimEvidenceManifest(
        incident_id=inc_id,
        claim="Claimed congestion on core switch",
        claimed_entities=["SW_CORE_01:Gi0/2"],
        finding_ids=["F-FAKE-CONG"],
        observation_ids=["OBS-DNS-LAT-1"],
        independence_groups=["telemetry"],
        contradiction_ids=[],
        contradiction_disclosures=[],
    )

    result = gate.evaluate(
        proposal=proposal,
        manifest=manifest,
        known_observations=unrelated_obs,
        known_findings=[finding],
    )

    # Gate MUST reject because observations on SRV_DNS_01 do not corroborate SW_CORE_01 congestion!
    assert result.outcome == GateOutcome.REJECT
    assert not result.passed
    semantic_check = next((c for c in result.checks if c.check_name == "claim_evidence_semantic_consistency"), None)
    assert semantic_check is not None
    assert not semantic_check.passed
    assert "Semantic validation failed" in semantic_check.message or "lacks supporting" in semantic_check.message


def test_single_snapshot_confidence_limitation():
    """Verifies that evidence from a single polling snapshot receives conservative confidence and explicit limitation disclosure."""
    gate = EvidenceReleaseGate()
    now = datetime.now(timezone.utc)
    inc_id = "INC-SNAPSHOT-TEST"

    # Only one single observation timestamp
    single_obs = [
        MetricObservation(
            observation_id="OBS-SNGL-1",
            incident_id=inc_id,
            source="collector/telemetry",
            timestamp=now,
            entity_id="SW_CORE_01:Gi0/2",
            metric_name="link_utilization_pct",
            value=95.0,
            unit="percent",
        ),
        MetricObservation(
            observation_id="OBS-SNGL-2",
            incident_id=inc_id,
            source="collector/telemetry",
            timestamp=now,
            entity_id="SW_CORE_01:Gi0/2",
            metric_name="queue_drops",
            value=50.0,
            unit="count",
        ),
    ]

    finding = Finding(
        finding_id="F-SNGL",
        incident_id=inc_id,
        source_tower=TowerId.PERFORMANCE,
        producer="performance.detect_congestion",
        finding_type="congestion_candidate",
        severity=Severity.HIGH,
        status=FindingStatus.ACTIVE,
        entity_refs=["SW_CORE_01:Gi0/2"],
        evidence_refs=["OBS-SNGL-1", "OBS-SNGL-2"],
        confidence=0.88,
        independence_group="telemetry:link_utilization:SW_CORE_01:Gi0/2",
        observed_at=now,
        created_at=now,
        description="Single snapshot congestion candidate",
        metadata={"qualifying_samples": 1, "observed_samples": 1},
    )

    # Propose HIGH confidence
    proposal = SupervisorProposal(
        proposal_id="PROP-SNGL",
        incident_id=inc_id,
        decision=ProposalDecision.PROPOSE_DIAGNOSIS,
        suspected_root_cause="LINK_CONGESTION: Utilization on SW_CORE_01:Gi0/2",
        affected_entities=["SW_CORE_01:Gi0/2"],
        supporting_finding_refs=["F-SNGL"],
        confidence_category=ConfidenceCategory.HIGH,
        alternative_causes=[],
        recommended_actions=[],
        created_at=now,
    )

    manifest = ClaimEvidenceManifest(
        incident_id=inc_id,
        claim="Congestion on core switch",
        claimed_entities=["SW_CORE_01:Gi0/2"],
        finding_ids=["F-SNGL"],
        observation_ids=["OBS-SNGL-1", "OBS-SNGL-2"],
        independence_groups=["telemetry"],
        contradiction_ids=[],
        contradiction_disclosures=[],
    )

    result = gate.evaluate(
        proposal=proposal,
        manifest=manifest,
        known_observations=single_obs,
        known_findings=[finding],
    )

    # Gate must disclose single snapshot in limitations and downgrade confidence
    assert result.passed
    assert any("single-snapshot" in lim.lower() for lim in result.limitations)
    assert result.certified_final_report.confidence_category != ConfidenceCategory.HIGH


def test_anonymous_scenario_paths_and_ground_truth_isolation():
    """Verifies that copying scenario data to an anonymous directory with a random path and ID executes identically, with ground truth strictly quarantined."""
    base_scenario = Path("fixtures/scenarios/link_congestion")
    with tempfile.TemporaryDirectory() as tmp_dir:
        anon_dir = Path(tmp_dir) / f"blinded_run_{uuid.uuid4().hex[:8]}"
        anon_dir.mkdir(parents=True, exist_ok=True)

        # Copy ONLY telemetry.jsonl and topology.json (do NOT copy evaluation/ground_truth.json)
        shutil.copy2(base_scenario / "telemetry.jsonl", anon_dir / "telemetry.jsonl")
        shutil.copy2(base_scenario / "topology.json", anon_dir / "topology.json")

        assert not (anon_dir / "evaluation").exists()
        assert not (anon_dir / "ground_truth.json").exists()

        # Load from anonymous directory
        inc_id, observations = _load_observations_from_target(anon_dir)
        blind_id = f"INC-ANONYMOUS-{uuid.uuid4().hex[:6]}"

        scoped_obs = []
        for o in observations:
            o_copy = copy.deepcopy(o)
            o_copy.incident_id = blind_id
            scoped_obs.append(o_copy)

        repo = SQLiteRepository(":memory:")
        runtime = SupervisorRuntime(repository=repo)
        report = runtime.run_incident(incident_id=blind_id, observations=scoped_obs)

        # Diagnosis must be LINK_CONGESTION on core switch
        assert report.status == "diagnosed"
        assert report.diagnostic_status == "DIAGNOSIS"
        assert "LINK_CONGESTION" in report.suspected_root_cause
        assert "SW_CORE_01" in report.affected_devices[0]
