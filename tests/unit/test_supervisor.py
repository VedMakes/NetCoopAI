"""Unit tests for NetCoop AI Supervisor subsystem.

Verifies SupervisorRuntime, SupervisoryRCAAgent, conflict arbitration,
investigation budgets, and independent EvidenceReleaseGate validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from netcoop.ingestion.loaders import TelemetryLoader
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
from netcoop.supervisor.agent import (
    DeterministicRCAProvider,
    FakeLLMProvider,
    SupervisoryRCAAgent,
)
from netcoop.supervisor.gate import EvidenceReleaseGate
from netcoop.supervisor.models import (
    GateOutcome,
    IncidentDossier,
    IncidentLifecycleState,
    InvestigationBudget,
)
from netcoop.supervisor.runtime import SupervisorRuntime


@pytest.fixture
def memory_repo() -> SQLiteRepository:
    return SQLiteRepository(":memory:")


@pytest.fixture
def sample_incident_observations() -> list:
    loader = TelemetryLoader()
    batch = loader.load_file(Path("fixtures/sample_incident.json"))
    return batch.observations


def test_supervisor_runtime_end_to_end_on_incident(
    memory_repo: SQLiteRepository, sample_incident_observations: list
):
    """Verifies complete deterministic run of SupervisorRuntime from intake to publication."""
    runtime = SupervisorRuntime(repository=memory_repo)

    final_report = runtime.run_incident(
        incident_id="INC-2026-001",
        observations=sample_incident_observations,
        symptom="Core switch congestion",
    )

    assert final_report.incident_id == "INC-2026-001"
    assert final_report.status == "diagnosed"
    assert "LINK_CONGESTION" in final_report.suspected_root_cause
    # This fixture is a single snapshot; keep the diagnosis explicitly low confidence.
    assert final_report.confidence <= 0.5
    assert final_report.confidence_category == ConfidenceCategory.LOW
    assert len(final_report.affected_devices) > 0
    assert len(final_report.supporting_evidence) > 0
    assert len(final_report.recommended_actions) > 0
    assert runtime.state == IncidentLifecycleState.PUBLISHED

    # Verify SQLite persistence
    persisted_report = memory_repo.get_final_report("INC-2026-001")
    assert persisted_report is not None
    assert persisted_report.suspected_root_cause == final_report.suspected_root_cause

    proposals = memory_repo.get_supervisor_proposals("INC-2026-001")
    assert len(proposals) >= 1
    assert proposals[0].decision == ProposalDecision.PROPOSE_DIAGNOSIS

    gate_result = memory_repo.get_gate_result("INC-2026-001")
    assert gate_result is not None
    assert gate_result.passed is True
    assert gate_result.outcome in {GateOutcome.PASS, GateOutcome.PASS_WITH_LIMITATIONS}


def test_evidence_gate_rejects_invented_observation_ids(memory_repo: SQLiteRepository):
    """Verifies the gate strictly rejects proposals citing non-existent or fabricated evidence."""
    gate = EvidenceReleaseGate(repository=memory_repo)
    inc_id = "INC-TEST-001"

    valid_finding = Finding(
        finding_id="F-001",
        incident_id=inc_id,
        source_tower=TowerId.PERFORMANCE,
        producer="performance.engine",
        finding_type="congestion_candidate",
        severity=Severity.HIGH,
        status=FindingStatus.ACTIVE,
        entity_refs=["SW_CAMPUS_5:Gi0/1"],
        evidence_refs=["OBS-001"],
        confidence=0.9,
        independence_group="metrics",
        observed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        description="Queue pressure detected",
    )
    memory_repo.insert_finding(valid_finding)

    # Valid observation exists
    memory_repo.insert_observation(
        MetricObservation(
            observation_id="OBS-001",
            incident_id=inc_id,
            source="test",
            entity_id="SW_CAMPUS_5:Gi0/1",
            metric_name="queue_drops",
            value=100.0,
            unit="count",
            timestamp=datetime.now(timezone.utc),
        )
    )

    proposal = SupervisorProposal(
        proposal_id="PROP-001",
        incident_id=inc_id,
        decision=ProposalDecision.PROPOSE_DIAGNOSIS,
        suspected_root_cause="LINK_CONGESTION: SW_CAMPUS_5:Gi0/1",
        affected_entities=["SW_CAMPUS_5:Gi0/1"],
        supporting_finding_refs=["F-001"],
        confidence_category=ConfidenceCategory.HIGH,
        alternative_causes=[],
        recommended_actions=["Check queue"],
        created_at=datetime.now(timezone.utc),
    )

    # Manifest contains invented observation ID
    manifest = ClaimEvidenceManifest(
        incident_id=inc_id,
        claim="Link congestion on SW_CAMPUS_5:Gi0/1",
        claimed_entities=["SW_CAMPUS_5:Gi0/1"],
        finding_ids=["F-001"],
        observation_ids=["OBS-INVENTED-9999"],
        independence_groups=["performance"],
        contradiction_ids=[],
        contradiction_disclosures=[],
    )

    result = gate.evaluate(proposal, manifest, incident_id=inc_id)
    assert result.passed is False
    assert result.outcome == GateOutcome.REJECT
    assert any("OBS-INVENTED-9999" in err for err in result.errors)
    assert result.certified_final_report is None


def test_evidence_gate_rejects_superseded_or_retracted_findings(memory_repo: SQLiteRepository):
    """Verifies the gate rejects proposals relying on superseded or retracted findings."""
    gate = EvidenceReleaseGate(repository=memory_repo)
    inc_id = "INC-TEST-002"

    superseded_finding = Finding(
        finding_id="F-SUPERSEDED",
        incident_id=inc_id,
        source_tower=TowerId.PERFORMANCE,
        producer="performance.engine",
        finding_type="congestion_candidate",
        severity=Severity.HIGH,
        status=FindingStatus.SUPERSEDED,
        entity_refs=["SW_CAMPUS_5:Gi0/1"],
        evidence_refs=["OBS-002"],
        confidence=0.85,
        independence_group="metrics",
        observed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        description="Superseded finding",
    )
    memory_repo.insert_finding(superseded_finding)

    proposal = SupervisorProposal(
        proposal_id="PROP-002",
        incident_id=inc_id,
        decision=ProposalDecision.PROPOSE_DIAGNOSIS,
        suspected_root_cause="LINK_CONGESTION",
        affected_entities=["SW_CAMPUS_5:Gi0/1"],
        supporting_finding_refs=["F-SUPERSEDED"],
        confidence_category=ConfidenceCategory.MODERATE,
        created_at=datetime.now(timezone.utc),
    )

    result = gate.evaluate(proposal, incident_id=inc_id)
    assert result.passed is False
    assert result.outcome == GateOutcome.REJECT
    assert any("SUPERSEDED" in err for err in result.errors)


def test_evidence_gate_rejects_wrong_incident_evidence(memory_repo: SQLiteRepository):
    """Verifies that evidence belonging to a different incident cannot be cited."""
    gate = EvidenceReleaseGate(repository=memory_repo)
    current_inc = "INC-CURRENT"
    other_inc = "INC-FOREIGN"

    foreign_finding = Finding(
        finding_id="F-FOREIGN",
        incident_id=other_inc,
        source_tower=TowerId.INFRASTRUCTURE,
        producer="infrastructure.engine",
        finding_type="hardware_overload",
        severity=Severity.HIGH,
        status=FindingStatus.ACTIVE,
        entity_refs=["ROUTER_FOREIGN"],
        evidence_refs=["OBS-FOREIGN"],
        confidence=0.9,
        independence_group="device",
        observed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        description="Foreign finding",
    )
    memory_repo.insert_finding(foreign_finding)

    proposal = SupervisorProposal(
        proposal_id="PROP-003",
        incident_id=current_inc,
        decision=ProposalDecision.PROPOSE_DIAGNOSIS,
        suspected_root_cause="DEVICE_OVERLOAD",
        affected_entities=["ROUTER_FOREIGN"],
        supporting_finding_refs=["F-FOREIGN"],
        confidence_category=ConfidenceCategory.MODERATE,
        created_at=datetime.now(timezone.utc),
    )

    result = gate.evaluate(proposal, incident_id=current_inc)
    assert result.passed is False
    assert result.outcome == GateOutcome.REJECT
    assert any("different incident" in err for err in result.errors)


def test_supervisor_abstention_on_normal_telemetry(memory_repo: SQLiteRepository):
    """Verifies supervisor safely abstains when telemetry has no severe faults or anomalies."""
    runtime = SupervisorRuntime(repository=memory_repo)
    normal_obs = [
        MetricObservation(
            observation_id="OBS-NORM-1",
            incident_id="INC-HEALTHY",
            source="collector/synthetic",
            entity_id="SW-CORE-1",
            metric_name="cpu_utilization_pct",
            value=25.0,
            unit="percent",
            timestamp=datetime.now(timezone.utc),
        ),
        MetricObservation(
            observation_id="OBS-NORM-2",
            incident_id="INC-HEALTHY",
            source="collector/synthetic",
            entity_id="SW-CORE-1:Gi0/1",
            metric_name="link_utilization_pct",
            value=35.0,
            unit="percent",
            timestamp=datetime.now(timezone.utc),
        ),
    ]

    report = runtime.run_incident(
        incident_id="INC-HEALTHY",
        observations=normal_obs,
        symptom="Routine sanity check",
    )

    assert report.status == "insufficient_evidence"
    assert "ABSTAIN" in report.suspected_root_cause
    assert report.confidence == 0.0
    assert report.confidence_category == ConfidenceCategory.INSUFFICIENT
    assert runtime.state == IncidentLifecycleState.ABSTAINED


def test_supervisor_conflict_classification_and_task_dispatch():
    """Verifies conflict classification triggers an investigation task in round 1."""

    # Performance congestion and Infrastructure overload hypotheses
    dossier = IncidentDossier(
        incident_id="INC-CONFLICT",
        symptom="Slow network",
        affected_entities=["SW_DIST_1"],
        tower_reports={},
        findings=[
            Finding(
                finding_id="F-C1",
                incident_id="INC-CONFLICT",
                source_tower=TowerId.PERFORMANCE,
                producer="performance.engine",
                finding_type="congestion_candidate",
                severity=Severity.HIGH,
                status=FindingStatus.ACTIVE,
                entity_refs=["SW_DIST_1:Gi0/1"],
                evidence_refs=["OBS-C1"],
                confidence=0.85,
                independence_group="metrics",
                observed_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                description="Queue pressure high",
            ),
            Finding(
                finding_id="F-C2",
                incident_id="INC-CONFLICT",
                source_tower=TowerId.INFRASTRUCTURE,
                producer="infrastructure.engine",
                finding_type="hardware_overload",
                severity=Severity.HIGH,
                status=FindingStatus.ACTIVE,
                entity_refs=["SW_DIST_1"],
                evidence_refs=["OBS-C2"],
                confidence=0.90,
                independence_group="device",
                observed_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                description="CPU utilization extreme",
            ),
        ],
        hypotheses=[
            Hypothesis(
                hypothesis_id="H-1",
                incident_id="INC-CONFLICT",
                fault_code="LINK_CONGESTION",
                suspected_entities=["SW_DIST_1:Gi0/1"],
                supporting_finding_refs=["F-C1"],
                contradicting_finding_refs=[],
                confidence_score=0.85,
                confidence_category=ConfidenceCategory.HIGH,
                rationale="Link congestion suspected",
                status="candidate",
                created_at=datetime.now(timezone.utc),
            ),
            Hypothesis(
                hypothesis_id="H-2",
                incident_id="INC-CONFLICT",
                fault_code="DEVICE_OVERLOAD",
                suspected_entities=["SW_DIST_1"],
                supporting_finding_refs=["F-C2"],
                contradicting_finding_refs=[],
                confidence_score=0.90,
                confidence_category=ConfidenceCategory.HIGH,
                rationale="Device CPU overload suspected",
                status="candidate",
                created_at=datetime.now(timezone.utc),
            ),
        ],
        investigation_round=1,
    )

    provider = DeterministicRCAProvider()
    proposal, manifest = provider.diagnose(dossier)

    # In round 1 with competing hypotheses, provider requests discriminating evidence
    assert proposal.decision == ProposalDecision.REQUEST_EVIDENCE
    assert len(proposal.requested_tasks) > 0
    assert {task["capability"] for task in proposal.requested_tasks} == {
        "performance.challenge_congestion_hypothesis",
        "infrastructure.challenge_device_overload_hypothesis",
    }
    assert {task["assignee"] for task in proposal.requested_tasks} == {
        TowerId.PERFORMANCE.value,
        TowerId.INFRASTRUCTURE.value,
    }
    assert {task["objective"]["hypothesis_code"] for task in proposal.requested_tasks} == {
        "LINK_CONGESTION", "DEVICE_OVERLOAD"
    }
    assert manifest.contradiction_ids == ["LINK_CONGESTION", "DEVICE_OVERLOAD"]

    # In round 2 with task history, provider arbitrates
    dossier.investigation_round = 2
    dossier.task_history.extend([
        {"status": "COMPLETED", "result": {"hypothesis_review": {
            "hypothesis_code": "LINK_CONGESTION", "status": "supported",
            "supporting_evidence_refs": ["OBS-C1"], "contradicting_evidence_refs": [],
            "missing_measurements": [], "discriminating_measurement": "queue drops over time",
            "summary": "Queue pressure supported by observations.",
        }}},
        {"status": "COMPLETED", "result": {"hypothesis_review": {
            "hypothesis_code": "DEVICE_OVERLOAD", "status": "weakened",
            "supporting_evidence_refs": [], "contradicting_evidence_refs": ["OBS-C2"],
            "missing_measurements": ["repeated CPU samples"],
            "discriminating_measurement": "CPU samples across the incident window",
            "summary": "The lone CPU observation does not establish sustained overload.",
        }}},
    ])
    proposal2, manifest2 = provider.diagnose(dossier)

    assert proposal2.decision == ProposalDecision.PROPOSE_DIAGNOSIS
    # Hardware/overload has higher causal priority than downstream congestion
    assert "DEVICE_OVERLOAD" in proposal2.suspected_root_cause


def test_disjoint_supported_hypotheses_are_reported_as_concurrent_causes():
    now = datetime.now(timezone.utc)
    findings = [
        Finding(
            finding_id="F-DNS", incident_id="INC-MULTI", source_tower=TowerId.SERVICES,
            producer="services.engine", finding_type="dns_resolution_failure", severity=Severity.HIGH,
            entity_refs=["SRV_DNS_01"], evidence_refs=["OBS-DNS"], confidence=0.9,
            independence_group="dns", observed_at=now, created_at=now, description="DNS query failures",
        ),
        Finding(
            finding_id="F-LINK", incident_id="INC-MULTI", source_tower=TowerId.PERFORMANCE,
            producer="performance.engine", finding_type="congestion_candidate", severity=Severity.HIGH,
            entity_refs=["SW_CORE_01:Gi0/2"], evidence_refs=["OBS-LINK"], confidence=0.88,
            independence_group="link", observed_at=now, created_at=now, description="Sustained queue pressure",
        ),
    ]
    hypotheses = [
        Hypothesis(
            hypothesis_id="H-DNS", incident_id="INC-MULTI", fault_code="DNS_FAILURE",
            suspected_entities=["SRV_DNS_01"], supporting_finding_refs=["F-DNS"],
            confidence_score=0.9, confidence_category=ConfidenceCategory.HIGH,
            rationale="Resolver errors", created_at=now,
        ),
        Hypothesis(
            hypothesis_id="H-LINK", incident_id="INC-MULTI", fault_code="LINK_CONGESTION",
            suspected_entities=["SW_CORE_01:Gi0/2"], supporting_finding_refs=["F-LINK"],
            confidence_score=0.88, confidence_category=ConfidenceCategory.HIGH,
            rationale="Queue drops under high utilization", created_at=now,
        ),
    ]
    dossier = IncidentDossier(
        incident_id="INC-MULTI", findings=findings, hypotheses=hypotheses,
        tower_reports={},
    )

    proposal, _ = DeterministicRCAProvider().diagnose(dossier)
    assert proposal.decision == ProposalDecision.PROPOSE_DIAGNOSIS
    assert proposal.concurrent_causes == ["LINK_CONGESTION: ['SW_CORE_01:Gi0/2']"]
    assert set(proposal.supporting_finding_refs) == {"F-DNS", "F-LINK"}


def test_connectivity_peer_result_changes_dns_vs_routing_arbitration():
    now = datetime.now(timezone.utc)
    findings = [
        Finding(
            finding_id="F-ROUTE", incident_id="INC-DNS-ROUTE", source_tower=TowerId.CONNECTIVITY,
            producer="connectivity.engine", finding_type="path_interruption", severity=Severity.HIGH,
            entity_refs=["HOSTEL_ZONE_A"], evidence_refs=["OBS-PATH"], confidence=0.85,
            independence_group="path", observed_at=now, created_at=now, description="Path symptoms",
        ),
        Finding(
            finding_id="F-DNS-ROUTE", incident_id="INC-DNS-ROUTE", source_tower=TowerId.SERVICES,
            producer="services.engine", finding_type="dns_resolution_failure", severity=Severity.HIGH,
            entity_refs=["SRV_DNS_01"], evidence_refs=["OBS-DNS"], confidence=0.85,
            independence_group="dns", observed_at=now, created_at=now, description="DNS failures",
        ),
    ]
    hypotheses = [
        Hypothesis(
            hypothesis_id="H-ROUTE", incident_id="INC-DNS-ROUTE", fault_code="ROUTING_FAILURE",
            suspected_entities=["SW_CORE_01"], supporting_finding_refs=["F-ROUTE"],
            confidence_score=0.85, confidence_category=ConfidenceCategory.HIGH,
            rationale="Possible path failure", created_at=now,
        ),
        Hypothesis(
            hypothesis_id="H-DNS-ROUTE", incident_id="INC-DNS-ROUTE", fault_code="DNS_FAILURE",
            suspected_entities=["SRV_DNS_01"], supporting_finding_refs=["F-DNS-ROUTE"],
            confidence_score=0.85, confidence_category=ConfidenceCategory.HIGH,
            rationale="Possible resolver failure", created_at=now,
        ),
    ]
    dossier = IncidentDossier(
        incident_id="INC-DNS-ROUTE", findings=findings, hypotheses=hypotheses,
        investigation_round=2,
        peer_query_history=[{
            "status": "completed", "capability": "connectivity.trace_path",
            "result": {"reachable": True, "path": ["HOSTEL_ZONE_A", "SRV_DNS_01"]},
        }],
    )

    proposal, _ = DeterministicRCAProvider().diagnose(dossier)

    assert "DNS_FAILURE" in (proposal.suspected_root_cause or "")


def test_supervisor_budget_exhaustion_limits_task_dispatch(memory_repo: SQLiteRepository):
    """Verifies investigation budget strictly caps task dispatching."""
    budget = InvestigationBudget(max_tasks=1, max_investigation_rounds=1)
    runtime = SupervisorRuntime(repository=memory_repo, budget=budget)

    obs = [
        MetricObservation(
            observation_id="OBS-B1",
            incident_id="INC-BUDGET",
            source="test",
            entity_id="SW_1",
            metric_name="cpu_utilization_pct",
            value=95.0,
            unit="percent",
            timestamp=datetime.now(timezone.utc),
        ),
        MetricObservation(
            observation_id="OBS-B2",
            incident_id="INC-BUDGET",
            source="test",
            entity_id="SW_1:Gi0/1",
            metric_name="link_utilization_pct",
            value=95.0,
            unit="percent",
            timestamp=datetime.now(timezone.utc),
        ),
        MetricObservation(
            observation_id="OBS-B3",
            incident_id="INC-BUDGET",
            source="test",
            entity_id="SW_1:Gi0/1",
            metric_name="queue_drops",
            value=300.0,
            unit="count",
            timestamp=datetime.now(timezone.utc),
        ),
    ]

    report = runtime.run_incident("INC-BUDGET", observations=obs)
    assert report.incident_id == "INC-BUDGET"
    assert runtime.tasks_dispatched <= budget.max_tasks
    assert runtime.investigation_rounds <= budget.max_investigation_rounds


def test_fake_llm_provider_and_fallback_mechanics(sample_incident_observations: list):
    """Verifies FakeLLMProvider integration and graceful fallback on provider failure."""
    failing_provider = FakeLLMProvider(should_fail=True)
    agent = SupervisoryRCAAgent(provider=failing_provider, llm_mode="auto")

    # When provider fails, agent automatically falls back to DeterministicRCAProvider
    runtime = SupervisorRuntime(rca_agent=agent)
    report = runtime.run_incident(
        incident_id="INC-2026-001",
        observations=sample_incident_observations,
    )

    assert report.status == "diagnosed"
    assert "LINK_CONGESTION" in report.suspected_root_cause


def test_gate_rejection_exposes_actionable_retry_issue(memory_repo: SQLiteRepository):
    """Gate failures carry machine-readable feedback for the bounded retry path."""
    runtime = SupervisorRuntime(repository=memory_repo)
    invalid_proposal = SupervisorProposal(
        proposal_id="PROP-INVALID",
        incident_id="INC-INVALID",
        decision=ProposalDecision.PROPOSE_DIAGNOSIS,
        suspected_root_cause="LINK_CONGESTION",
        affected_entities=[],
        supporting_finding_refs=[],
        confidence_category=ConfidenceCategory.MODERATE,
        created_at=datetime.now(timezone.utc),
    )

    result = runtime.gate.evaluate(invalid_proposal, incident_id="INC-INVALID")
    assert result.passed is False
    assert {issue.code for issue in result.issues} >= {"missing_support"}
    assert all(issue.check_name for issue in result.issues)


def test_runtime_retries_gate_once_after_invalid_citation(sample_incident_observations: list):
    """A retry can repair a citation once; the first rejected proposal is never published."""

    class RetryCitationProvider:
        calls = 0

        def diagnose(self, dossier):
            self.calls += 1
            proposal, manifest = DeterministicRCAProvider().diagnose(dossier)
            if self.calls == 1 and proposal.decision == ProposalDecision.PROPOSE_DIAGNOSIS:
                manifest = manifest.model_copy(update={"observation_ids": ["OBS-NOT-IN-INCIDENT"]})
            return proposal, manifest

    provider = RetryCitationProvider()
    runtime = SupervisorRuntime(rca_agent=provider)
    report = runtime.run_incident(
        "INC-2026-001", sample_incident_observations, symptom="Intermittent connectivity"
    )

    assert provider.calls == 2
    assert runtime.supervisor_calls == 2
    assert report.status == "diagnosed"
    assert runtime.state == IncidentLifecycleState.PUBLISHED


def test_runtime_abstains_when_gate_retry_does_not_resolve_issue(sample_incident_observations: list):
    """A repeated invalid citation is bounded to one retry and safely abstains."""

    class PersistentlyInvalidProvider:
        calls = 0

        def diagnose(self, dossier):
            self.calls += 1
            proposal, manifest = DeterministicRCAProvider().diagnose(dossier)
            if proposal.decision == ProposalDecision.PROPOSE_DIAGNOSIS:
                manifest = manifest.model_copy(update={"observation_ids": ["OBS-STILL-MISSING"]})
            return proposal, manifest

    provider = PersistentlyInvalidProvider()
    runtime = SupervisorRuntime(rca_agent=provider)
    report = runtime.run_incident("INC-2026-001", sample_incident_observations)

    assert provider.calls == 2
    assert runtime.supervisor_calls == 2
    assert report.status == "insufficient_evidence"
    assert "ABSTAIN" in report.suspected_root_cause
    assert runtime.state == IncidentLifecycleState.ABSTAINED
