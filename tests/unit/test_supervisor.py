"""Unit tests for NetCoop AI Supervisor subsystem.

Verifies SupervisorRuntime, SupervisoryRCAAgent, conflict arbitration,
investigation budgets, and independent EvidenceReleaseGate validation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from netcoop.models.observations import (
    ConfigObservation,
    LogObservation,
    MetricObservation,
    TopologyObservation,
)
from netcoop.models.reports import ClaimEvidenceManifest, SupervisorProposal
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.supervisor.agent import (
    DeterministicRCAProvider,
    FakeLLMProvider,
    SupervisoryRCAAgent,
)
from netcoop.supervisor.gate import EvidenceReleaseGate, _infer_impact_records
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


@pytest.mark.parametrize(
    "alternative_causes, expected_pass",
    [(["DEVICE_OVERLOAD"], True), ([], False)],
)
def test_gate_checks_competing_hypothesis_disclosure_by_fault_code(
    alternative_causes: list[str], expected_pass: bool
):
    proposal = SupervisorProposal(
        proposal_id="PROP-CONFLICT-CODE",
        incident_id="INC-CONFLICT-CODE",
        decision=ProposalDecision.PROPOSE_DIAGNOSIS,
        suspected_root_cause="LINK_CONGESTION: link pressure",
        affected_entities=["SW-1:eth0"],
        supporting_finding_refs=[],
        confidence_category=ConfidenceCategory.LOW,
        alternative_causes=alternative_causes,
        recommended_actions=[],
        created_at=datetime.now(timezone.utc),
    )
    result = EvidenceReleaseGate().evaluate(
        proposal,
        incident_id=proposal.incident_id,
        known_observations=[],
        known_findings=[],
        competing_hypotheses=["LINK_CONGESTION: ['SW-1:eth0']", "DEVICE_OVERLOAD: ['SW-1']"],
    )
    check = next(
        item for item in result.checks
        if item.check_name == "contradiction_disclosure" and "DEVICE_OVERLOAD" in item.message
    )
    assert check.passed is expected_pass
    if not expected_pass:
        assert check.severity == "error"
        assert any(issue.code == "unresolved_hypothesis" for issue in result.issues)


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

    dossier.task_history = [
        {"status": "COMPLETED", "hypothesis_reviews": [
            {"fault_code": "LINK_CONGESTION", "status": "inconclusive", "new_evidence_refs": [],
                "disposition": "operator_input_needed", "discriminating_measurement": "repeated link counters",
                "missing_measurements": ["same-time readings conflict"]},
        ]},
        {"status": "COMPLETED", "hypothesis_reviews": [
            {"fault_code": "DEVICE_OVERLOAD", "status": "inconclusive", "new_evidence_refs": [],
                "disposition": "operator_input_needed", "discriminating_measurement": "repeated CPU samples",
                "missing_measurements": ["same-time readings conflict"]},
        ]},
    ]
    classified_conflicts = provider._classify_conflicts(dossier)
    assert any({"LINK_CONGESTION", "DEVICE_OVERLOAD"} <= set(item.competing_hypotheses) for item in classified_conflicts)
    proposal3, _ = provider.diagnose(dossier)
    assert proposal3.decision == ProposalDecision.ABSTAIN
    assert set(proposal3.alternative_causes) == {"LINK_CONGESTION", "DEVICE_OVERLOAD"}
    assert len(proposal3.operator_questions) == 1
    assert "authoritative" in proposal3.operator_questions[0]


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


def test_unavailable_signal_becomes_specific_operator_question():
    dossier = IncidentDossier(
        incident_id="INC-OPERATOR-QUESTION",
        task_history=[{
            "status": "SIGNAL_UNAVAILABLE",
            "objective": {
                "target_entities": ["SW-EDGE-2"],
                "required_signals": ["cpu_utilization_pct", "memory_utilization_pct"],
            },
        }],
    )

    questions = DeterministicRCAProvider._operator_questions(dossier)
    assert len(questions) == 1
    assert "SW-EDGE-2" in questions[0]
    assert "timestamps and collector/source names" in questions[0]


def test_task_selection_ranks_information_value_against_cost():
    high_value = {
        "objective": {"expected_information_gain": 0.8, "decision_impact": 1.0, "estimated_cost": 1.0}
    }
    low_value = {
        "objective": {"expected_information_gain": 0.3, "decision_impact": 0.5, "estimated_cost": 2.0}
    }
    assert SupervisorRuntime._task_value(high_value) > SupervisorRuntime._task_value(low_value)


def test_task_value_uses_signal_coverage_time_and_source_diversity(sample_utc_time):
    candidate = {
        "objective": {
            "required_signals": ["cpu_utilization_pct", "memory_utilization_pct"],
            "target_entities": ["SW-EDGE-2"], "estimated_cost": 1.0,
        }
    }
    sparse = [MetricObservation(
        observation_id="OBS-ONE", incident_id="INC-VALUE", source="collector-a",
        entity_id="SW-EDGE-2", metric_name="cpu_utilization_pct", value=90.0,
        unit="percent", timestamp=sample_utc_time,
    )]
    corroborated = [
        MetricObservation(
            observation_id=f"OBS-{metric}-{index}", incident_id="INC-VALUE",
            source=f"collector-{index % 2}", entity_id="SW-EDGE-2",
            metric_name=metric, value=90.0, unit="percent",
            timestamp=sample_utc_time + timedelta(seconds=index),
        )
        for metric in ("cpu_utilization_pct", "memory_utilization_pct")
        for index in range(3)
    ]

    assert SupervisorRuntime._task_value(candidate, corroborated) > SupervisorRuntime._task_value(candidate, sparse)


def test_signal_detection_does_not_confuse_unrelated_logs_or_topology(sample_utc_time):
    dns_log = LogObservation(
        observation_id="LOG-DNS", incident_id="INC-SIGNAL", source="syslog",
        entity_id="resolver-1", log_level="ERROR", message="SERVFAIL for example.org",
        timestamp=sample_utc_time,
    )
    topology = TopologyObservation(
        observation_id="TOPO-PATH", incident_id="INC-SIGNAL", source="map",
        entity_id="SW-CORE", source_entity="SW-CORE", target_entity="SW-DIST",
        relationship_type="connected_to", timestamp=sample_utc_time,
    )
    config = ConfigObservation(
        observation_id="CFG-CURRENT", incident_id="INC-SIGNAL", source="backup",
        entity_id="SW-CORE", config_key="mtu", config_value="1500", timestamp=sample_utc_time,
    )

    assert SupervisorRuntime._has_required_signal(["dns_response_code"], [dns_log])
    assert not SupervisorRuntime._has_required_signal(["dhcp_lease_events"], [dns_log])
    assert not SupervisorRuntime._has_required_signal(["path_reachability"], [topology])
    assert SupervisorRuntime._has_required_signal(["config_current_value"], [config])
    assert not SupervisorRuntime._has_required_signal(["config_baseline"], [config])


def test_topology_impact_traverses_dependencies_without_spreading_through_physical_links(sample_utc_time):
    observations = [
        TopologyObservation(
            observation_id="DEP-DNS-ZONE", incident_id="INC-IMPACT", source="map",
            entity_id="ZONE-A", source_entity="ZONE-A", target_entity="DNS-1",
            relationship_type="dns", timestamp=sample_utc_time,
        ),
        TopologyObservation(
            observation_id="DEP-ZONE-SEGMENT", incident_id="INC-IMPACT", source="map",
            entity_id="SEGMENT-B", source_entity="SEGMENT-B", target_entity="ZONE-A",
            relationship_type="uplink", timestamp=sample_utc_time,
        ),
        TopologyObservation(
            observation_id="PHYS-DNS-SW", incident_id="INC-IMPACT", source="map",
            entity_id="DNS-1", source_entity="DNS-1", target_entity="SW-CORE",
            relationship_type="connected_to", timestamp=sample_utc_time,
        ),
        TopologyObservation(
            observation_id="PHYS-OTHER", incident_id="INC-IMPACT", source="map",
            entity_id="SW-CORE", source_entity="SW-CORE", target_entity="SW-OTHER",
            relationship_type="connected_to", timestamp=sample_utc_time,
        ),
    ]

    impacts = _infer_impact_records(["DNS-1"], observations)
    by_entity = {impact.entity_id: impact for impact in impacts}
    assert set(by_entity) == {"ZONE-A", "SEGMENT-B"}
    assert by_entity["ZONE-A"].hops == 1
    assert by_entity["ZONE-A"].topology_evidence_refs == ["DEP-DNS-ZONE"]
    assert by_entity["SEGMENT-B"].hops == 2
    assert by_entity["SEGMENT-B"].path == ["DNS-1", "ZONE-A", "SEGMENT-B"]


def test_interface_level_topology_impact_excludes_parent_device(sample_utc_time):
    observations = [
        TopologyObservation(
            observation_id="LINK-CORE-DIST", incident_id="INC-PORT-IMPACT", source="map",
            entity_id="SW-CORE", source_entity="SW-CORE", target_entity="SW-DIST",
            relationship_type="connected_to", interface_name="SW-CORE:eth2", timestamp=sample_utc_time,
        ),
        TopologyObservation(
            observation_id="LINK-DIST-AP", incident_id="INC-PORT-IMPACT", source="map",
            entity_id="SW-DIST", source_entity="SW-DIST", target_entity="AP-2",
            relationship_type="connected_to", interface_name="SW-DIST:eth1", timestamp=sample_utc_time,
        ),
    ]

    impacts = _infer_impact_records(["SW-CORE:eth2"], observations)
    by_entity = {impact.entity_id: impact for impact in impacts}
    assert set(by_entity) == {"SW-DIST", "AP-2"}
    assert "SW-CORE" not in by_entity
    assert by_entity["SW-DIST"].path == ["SW-CORE:eth2", "SW-DIST"]
    assert by_entity["AP-2"].topology_evidence_refs == ["LINK-CORE-DIST", "LINK-DIST-AP"]


def test_task_result_rejects_mismatched_observation_provenance():
    now = datetime.now(timezone.utc)
    observation = MetricObservation(
        observation_id="OBS-PROVENANCE",
        incident_id="INC-PROVENANCE",
        source="collector-a",
        entity_id="SW-EDGE-2",
        metric_name="cpu_utilization_pct",
        value=91.0,
        unit="percent",
        timestamp=now,
    )
    history_entry = {"warnings": [], "limitations": []}
    artifact = {
        "incident_id": "INC-PROVENANCE",
        "capability": "infrastructure.challenge_device_overload_hypothesis",
        "target_entities": ["SW-EDGE-2"],
        "findings": [], "hypotheses": [], "finding_refs": [],
        "evidence_refs": ["OBS-PROVENANCE"], "summary": "reviewed",
        "evidence_context": [{
            "observation_id": "OBS-PROVENANCE", "observed_at": now,
            "source": "invented-source", "entity_id": "SW-EDGE-2",
            "signal": "cpu_utilization_pct", "value": 91.0, "unit": "percent",
        }],
    }

    SupervisorRuntime._merge_task_artifact(
        IncidentDossier(incident_id="INC-PROVENANCE"), artifact, history_entry,
        [], ["OBS-PROVENANCE"], {"OBS-PROVENANCE": observation},
    )
    assert any("provenance does not match" in warning for warning in history_entry["warnings"])


def test_stored_only_task_skips_when_required_signal_is_unavailable():
    runtime = SupervisorRuntime()
    dossier = IncidentDossier(incident_id="INC-SIGNAL-MISSING")
    proposal = SupervisorProposal(
        proposal_id="PROP-SIGNAL-MISSING", incident_id="INC-SIGNAL-MISSING",
        decision=ProposalDecision.REQUEST_EVIDENCE, confidence_category=ConfidenceCategory.LOW,
        requested_tasks=[{
            "assignee": TowerId.INFRASTRUCTURE.value,
            "capability": "infrastructure.challenge_device_overload_hypothesis",
            "objective": {
                "hypothesis_code": "DEVICE_OVERLOAD", "target_entities": ["SW-EDGE-2"],
                "required_signals": ["cpu_utilization_pct", "memory_utilization_pct"],
                "evidence_mode": "stored_observations_only",
            },
        }],
        created_at=datetime.now(timezone.utc),
    )

    dispatched = runtime._dispatch_task_requests(proposal, dossier, "INC-SIGNAL-MISSING", [])
    assert dispatched == 0
    assert runtime.tasks_dispatched == 0
    assert dossier.task_history[0]["status"] == "SIGNAL_UNAVAILABLE"
    assert DeterministicRCAProvider._operator_questions(dossier)


def test_same_task_repeats_only_after_observation_set_changes(memory_repo: SQLiteRepository, sample_utc_time):
    incident_id = "INC-TASK-NOVELTY"
    first = MetricObservation(
        observation_id="OBS-CPU-A", incident_id=incident_id, source="collector-a",
        entity_id="SW-EDGE-2", metric_name="cpu_utilization_pct", value=91.0,
        unit="percent", timestamp=sample_utc_time,
    )
    memory_repo.insert_observation(first)
    runtime = SupervisorRuntime(repository=memory_repo)
    dossier = IncidentDossier(incident_id=incident_id)
    proposal = SupervisorProposal(
        proposal_id="PROP-TASK-NOVELTY", incident_id=incident_id,
        decision=ProposalDecision.REQUEST_EVIDENCE, confidence_category=ConfidenceCategory.LOW,
        requested_tasks=[{
            "assignee": TowerId.INFRASTRUCTURE.value, "capability": "INVESTIGATE_DEVICE",
            "objective": {"target_entities": ["SW-EDGE-2"]},
        }],
        created_at=datetime.now(timezone.utc),
    )

    runtime._dispatch_task_requests(proposal, dossier, incident_id, [first])
    runtime._dispatch_task_requests(proposal, dossier, incident_id, [first])
    assert runtime.tasks_dispatched == 1
    assert dossier.task_history[-1]["status"] == "SKIPPED_DUPLICATE"

    second = MetricObservation(
        observation_id="OBS-CPU-B", incident_id=incident_id, source="collector-a",
        entity_id="SW-EDGE-2", metric_name="cpu_utilization_pct", value=89.0,
        unit="percent", timestamp=sample_utc_time + timedelta(seconds=30),
    )
    memory_repo.insert_observation(second)
    runtime._dispatch_task_requests(proposal, dossier, incident_id, [first, second])
    assert runtime.tasks_dispatched == 2
    assert dossier.task_history[-1]["status"] == "COMPLETED"
    assert dossier.task_history[-1]["new_evidence_refs"] == []
    assert set(dossier.task_history[-1]["evidence_refs"]) == {"OBS-CPU-A", "OBS-CPU-B"}


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
