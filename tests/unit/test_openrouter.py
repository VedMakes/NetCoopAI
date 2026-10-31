"""Unit tests for OpenRouter provider integration, environment loading, and fallback mechanics."""

from __future__ import annotations

import json
import os
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import pytest

from netcoop.models.enums import (
    ConfidenceCategory,
    FindingStatus,
    ProposalDecision,
    Severity,
    TowerId,
)
from netcoop.models.findings import Finding
from netcoop.models.hypotheses import Hypothesis
from netcoop.supervisor.agent import DeterministicRCAProvider, get_rca_provider
from netcoop.supervisor.models import IncidentDossier
from netcoop.supervisor.openrouter import OpenRouterProvider
from netcoop.utils.env import load_dotenv


@pytest.fixture
def sample_dossier() -> IncidentDossier:
    f1 = Finding(
        finding_id="F-PERF-01",
        incident_id="INC-OR-01",
        source_tower=TowerId.PERFORMANCE,
        producer="performance.engine",
        finding_type="congestion_candidate",
        severity=Severity.HIGH,
        status=FindingStatus.ACTIVE,
        entity_refs=["SW_CORE_01:Gi0/1"],
        evidence_refs=["OBS-M-01"],
        confidence=0.88,
        independence_group="metrics",
        observed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        description="Sustained link congestion",
    )
    h1 = Hypothesis(
        hypothesis_id="HYP-PERF-01",
        incident_id="INC-OR-01",
        fault_code="LINK_CONGESTION",
        suspected_entities=["SW_CORE_01:Gi0/1"],
        supporting_finding_refs=["F-PERF-01"],
        contradicting_finding_refs=[],
        confidence_score=0.88,
        confidence_category=ConfidenceCategory.HIGH,
        rationale="Link congestion verified",
        status="active",
        created_at=datetime.now(timezone.utc),
    )
    return IncidentDossier(
        incident_id="INC-OR-01",
        symptom="Core switch link congestion",
        affected_entities=["SW_CORE_01:Gi0/1"],
        tower_reports={},
        findings=[f1],
        hypotheses=[h1],
        topology_summary={},
        conflicts=[],
        investigation_round=1,
        task_history=[],
        available_capabilities=["performance.inspect_upstream_capacity"],
        data_quality_warnings=[],
    )


def test_env_loading_from_file(tmp_path: Path):
    """Verifies load_dotenv parses key-value pairs into os.environ."""
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_KEY_NETCOOP=openrouter_secret_val\n# comment\nOTHER_KEY='hello'\n")

    assert "TEST_KEY_NETCOOP" not in os.environ
    load_dotenv(env_file)
    assert os.environ.get("TEST_KEY_NETCOOP") == "openrouter_secret_val"
    assert os.environ.get("OTHER_KEY") == "hello"


def test_openrouter_provider_fallback_without_api_key(sample_dossier: IncidentDossier):
    """Verifies provider transparently falls back to DeterministicRCAProvider when API key is missing."""
    provider = OpenRouterProvider(api_key="")
    proposal, manifest = provider.diagnose(sample_dossier)

    assert proposal.decision == ProposalDecision.PROPOSE_DIAGNOSIS
    assert "LINK_CONGESTION" in proposal.suspected_root_cause
    assert "F-PERF-01" in proposal.supporting_finding_refs
    assert manifest.finding_ids == ["F-PERF-01"]


def test_openrouter_build_prompt_payload(sample_dossier: IncidentDossier):
    """Verifies prompt generation enforces token minimization and strict citation invariants."""
    provider = OpenRouterProvider(api_key="test-key", model="meta-llama/llama-3.3-70b-instruct:free")
    payload = provider._build_prompt_payload(sample_dossier)

    assert payload["model"] == "meta-llama/llama-3.3-70b-instruct:free"
    assert len(payload["messages"]) == 2

    sys_prompt = payload["messages"][0]["content"]
    assert "F-PERF-01" in sys_prompt
    assert "OBS-M-01" in sys_prompt
    assert "deterministic controller is authoritative" in sys_prompt
    assert "read-only follow-up" in sys_prompt.lower()

    user_prompt = payload["messages"][1]["content"]
    assert "INC-OR-01" in user_prompt
    assert "SW_CORE_01:Gi0/1" in user_prompt
    assert "controller_decision" in user_prompt


def test_openrouter_skips_model_when_controller_requests_evidence(sample_dossier: IncidentDossier, monkeypatch):
    competing = Hypothesis(
        hypothesis_id="HYP-INFRA-02",
        incident_id=sample_dossier.incident_id,
        fault_code="DEVICE_OVERLOAD",
        suspected_entities=["SW_CORE_01"],
        supporting_finding_refs=[],
        contradicting_finding_refs=[],
        confidence_score=0.7,
        confidence_category=ConfidenceCategory.MODERATE,
        rationale="Device resource pressure",
        status="active",
        created_at=datetime.now(timezone.utc),
    )
    sample_dossier.hypotheses.append(competing)
    provider = OpenRouterProvider(api_key="test-key")
    monkeypatch.setattr(provider, "_call_openrouter", lambda payload: pytest.fail("unexpected model call"))

    proposal, _ = provider.diagnose(sample_dossier)

    assert proposal.decision == ProposalDecision.REQUEST_EVIDENCE
    assert proposal.requested_tasks


def test_openrouter_cannot_reverse_abstention_after_inconclusive_reviews(
    sample_dossier: IncidentDossier, monkeypatch
):
    competing = Hypothesis(
        hypothesis_id="HYP-INFRA-02",
        incident_id=sample_dossier.incident_id,
        fault_code="DEVICE_OVERLOAD",
        suspected_entities=["SW_CORE_01"],
        supporting_finding_refs=[],
        contradicting_finding_refs=[],
        confidence_score=0.7,
        confidence_category=ConfidenceCategory.MODERATE,
        rationale="Device resource pressure",
        status="active",
        created_at=datetime.now(timezone.utc),
    )
    sample_dossier.hypotheses.append(competing)
    sample_dossier.investigation_round = 2
    sample_dossier.task_history = [{
        "hypothesis_reviews": [
            {"fault_code": "LINK_CONGESTION", "status": "inconclusive"},
            {"fault_code": "DEVICE_OVERLOAD", "status": "inconclusive"},
        ]
    }]
    provider = OpenRouterProvider(api_key="test-key")
    monkeypatch.setattr(provider, "_call_openrouter", lambda payload: pytest.fail("unexpected model call"))

    proposal, _ = provider.diagnose(sample_dossier)

    assert proposal.decision == ProposalDecision.ABSTAIN
    assert proposal.confidence_category == ConfidenceCategory.INSUFFICIENT


def test_openrouter_preserves_controller_diagnosis_and_evidence(sample_dossier: IncidentDossier, monkeypatch):
    controller, controller_manifest = DeterministicRCAProvider().diagnose(sample_dossier)
    response = {
        "decision": "propose_diagnosis",
        "suspected_root_cause": "LINK_CONGESTION: changed model explanation",
        "affected_entities": ["UNOBSERVED_DEVICE"],
        "supporting_finding_refs": ["F-PERF-01"],
        "confidence_category": "high",
        "alternative_causes": ["DEVICE_OVERLOAD"],
        "concurrent_causes": ["DNS_FAILURE"],
        "recommended_actions": ["Inspect SW_CORE_01:Gi0/1 queue counters"],
        "abstain_reason": None,
        "requested_tasks": [],
        "claim": "Model supplied claim",
        "observation_ids": ["OBS-M-01"],
        "contradiction_ids": [],
        "contradiction_disclosures": [],
    }
    provider = OpenRouterProvider(api_key="test-key")
    monkeypatch.setattr(provider, "_call_openrouter", lambda payload: json.dumps(response))

    proposal, manifest = provider.diagnose(sample_dossier)

    assert proposal.decision == controller.decision
    assert proposal.suspected_root_cause == controller.suspected_root_cause
    assert proposal.affected_entities == controller.affected_entities
    assert proposal.supporting_finding_refs == controller.supporting_finding_refs
    assert proposal.confidence_category == controller.confidence_category
    assert proposal.alternative_causes == controller.alternative_causes
    assert proposal.concurrent_causes == controller.concurrent_causes
    assert manifest == controller_manifest
    assert proposal.recommended_actions == response["recommended_actions"]


def test_openrouter_serializes_timestamps_in_task_history(sample_dossier: IncidentDossier):
    sample_dossier.task_history = [{"task_id": "TASK-1", "completed_at": datetime.now(timezone.utc)}]
    payload = OpenRouterProvider(api_key="test-key")._build_prompt_payload(sample_dossier)
    user_data = json.loads(payload["messages"][1]["content"])
    assert user_data["task_history"][0]["completed_at"].endswith("+00:00")


def test_openrouter_falls_back_for_finding_id_used_as_fault_code(sample_dossier: IncidentDossier, monkeypatch):
    response = {
        "decision": "propose_diagnosis",
        "suspected_root_cause": "F-PERF-01: Link congestion",
        "affected_entities": ["SW_CORE_01:Gi0/1"],
        "supporting_finding_refs": ["F-PERF-01"],
        "confidence_category": "high",
        "alternative_causes": [],
        "concurrent_causes": [],
        "recommended_actions": ["Inspect SW_CORE_01:Gi0/1 queue counters"],
        "abstain_reason": None,
        "requested_tasks": [],
        "claim": "claim",
        "observation_ids": ["OBS-M-01"],
        "contradiction_ids": [],
        "contradiction_disclosures": [],
    }
    provider = OpenRouterProvider(api_key="test-key")
    monkeypatch.setattr(provider, "_call_openrouter", lambda payload: json.dumps(response))

    proposal, _ = provider.diagnose(sample_dossier)

    assert proposal.suspected_root_cause.startswith("LINK_CONGESTION:")


def test_openrouter_discards_mutating_or_unknown_entity_recommendations(sample_dossier: IncidentDossier, monkeypatch):
    controller, _ = DeterministicRCAProvider().diagnose(sample_dossier)
    response = {
        "decision": "propose_diagnosis",
        "suspected_root_cause": controller.suspected_root_cause,
        "affected_entities": controller.affected_entities,
        "supporting_finding_refs": controller.supporting_finding_refs,
        "confidence_category": controller.confidence_category.value,
        "alternative_causes": controller.alternative_causes,
        "concurrent_causes": controller.concurrent_causes,
        "recommended_actions": ["Restart UNOBSERVED_DEVICE to clear the fault"],
        "abstain_reason": None,
        "requested_tasks": [],
        "claim": "claim",
        "observation_ids": ["OBS-M-01"],
        "contradiction_ids": [],
        "contradiction_disclosures": [],
    }
    provider = OpenRouterProvider(api_key="test-key")
    monkeypatch.setattr(provider, "_call_openrouter", lambda payload: json.dumps(response))

    proposal, _ = provider.diagnose(sample_dossier)

    assert proposal.recommended_actions == controller.recommended_actions


def test_openrouter_cannot_change_controller_decision_to_abstain(sample_dossier: IncidentDossier, monkeypatch):
    controller, _ = DeterministicRCAProvider().diagnose(sample_dossier)
    response = {
        "decision": "abstain",
        "suspected_root_cause": None,
        "affected_entities": [],
        "supporting_finding_refs": [],
        "confidence_category": "insufficient",
        "alternative_causes": [],
        "concurrent_causes": [],
        "recommended_actions": ["Inspect SW_CORE_01:Gi0/1 queue counters"],
        "abstain_reason": "Model opinion",
        "requested_tasks": [],
        "claim": "claim",
        "observation_ids": [],
        "contradiction_ids": [],
        "contradiction_disclosures": [],
    }
    provider = OpenRouterProvider(api_key="test-key")
    monkeypatch.setattr(provider, "_call_openrouter", lambda payload: json.dumps(response))

    proposal, _ = provider.diagnose(sample_dossier)

    assert proposal.decision == controller.decision
    assert proposal.suspected_root_cause == controller.suspected_root_cause


def test_openrouter_response_parsing_valid(sample_dossier: IncidentDossier, monkeypatch):
    """Verifies valid LLM JSON response is parsed into Proposal and Manifest models."""
    mock_llm_json = json.dumps({
        "decision": "propose_diagnosis",
        "suspected_root_cause": "LINK_CONGESTION: Saturated core uplink Gi0/1",
        "affected_entities": ["SW_CORE_01:Gi0/1"],
        "supporting_finding_refs": ["F-PERF-01"],
        "confidence_category": "high",
        "alternative_causes": [],
        "recommended_actions": ["Reroute non-essential traffic"],
        "abstain_reason": None,
        "requested_tasks": [],
        "claim": "Core switch Gi0/1 egress link saturation confirmed",
        "observation_ids": ["OBS-M-01"],
        "contradiction_ids": [],
        "contradiction_disclosures": [],
    })

    provider = OpenRouterProvider(api_key="mock-key")
    monkeypatch.setattr(provider, "_call_openrouter", lambda payload: mock_llm_json)

    proposal, manifest = provider.diagnose(sample_dossier)
    assert proposal.decision == ProposalDecision.PROPOSE_DIAGNOSIS
    assert "LINK_CONGESTION" in proposal.suspected_root_cause
    assert proposal.confidence_category == ConfidenceCategory.HIGH
    assert proposal.supporting_finding_refs == ["F-PERF-01"]
    assert manifest.finding_ids == ["F-PERF-01"]
    assert manifest.observation_ids == ["OBS-M-01"]


def test_openrouter_strips_hallucinated_ids(sample_dossier: IncidentDossier, monkeypatch):
    """Verifies unknown/hallucinated finding and observation IDs are sanitized."""
    mock_llm_json = json.dumps({
        "decision": "propose_diagnosis",
        "suspected_root_cause": "LINK_CONGESTION: Core uplink",
        "affected_entities": ["SW_CORE_01:Gi0/1"],
        "supporting_finding_refs": ["F-PERF-01", "F-HALLUCINATED-999"],
        "confidence_category": "high",
        "alternative_causes": [],
        "recommended_actions": ["Inspect link"],
        "abstain_reason": None,
        "requested_tasks": [],
        "claim": "Diagnosed link congestion",
        "observation_ids": ["OBS-M-01", "OBS-FABRICATED-777"],
        "contradiction_ids": [],
        "contradiction_disclosures": [],
    })

    provider = OpenRouterProvider(api_key="mock-key")
    monkeypatch.setattr(provider, "_call_openrouter", lambda payload: mock_llm_json)

    proposal, manifest = provider.diagnose(sample_dossier)
    # The hallucinated finding and observation IDs must be filtered out
    assert "F-HALLUCINATED-999" not in proposal.supporting_finding_refs
    assert proposal.supporting_finding_refs == ["F-PERF-01"]
    assert "OBS-FABRICATED-777" not in manifest.observation_ids
    assert manifest.observation_ids == ["OBS-M-01"]


def test_openrouter_network_error_fallback(sample_dossier: IncidentDossier, monkeypatch):
    """Verifies network connection error triggers automatic deterministic fallback without crashing."""
    provider = OpenRouterProvider(api_key="mock-key")

    def failing_call(payload):
        raise urllib.error.URLError("Simulated connection timeout")

    monkeypatch.setattr(provider, "_call_openrouter", failing_call)

    proposal, manifest = provider.diagnose(sample_dossier)
    # Fallback produces valid diagnosis
    assert proposal.decision == ProposalDecision.PROPOSE_DIAGNOSIS
    assert "LINK_CONGESTION" in proposal.suspected_root_cause


def test_get_rca_provider_factory():
    """Verifies get_rca_provider respects llm_mode settings."""
    # 1. off mode
    p_off = get_rca_provider(llm_mode="off")
    assert isinstance(p_off, DeterministicRCAProvider)

    # 2. auto mode without key
    p_auto = get_rca_provider(llm_mode="auto", api_key="")
    assert isinstance(p_auto, DeterministicRCAProvider)

    # 3. on mode without key raises error
    with pytest.raises(ValueError) as exc:
        get_rca_provider(llm_mode="on", api_key="")
    assert "OPENROUTER_API_KEY was not found" in str(exc.value)

    # 4. on mode with key returns OpenRouterProvider
    p_on = get_rca_provider(llm_mode="on", api_key="sk-or-test12345")
    assert isinstance(p_on, OpenRouterProvider)
    assert p_on.api_key == "sk-or-test12345"
