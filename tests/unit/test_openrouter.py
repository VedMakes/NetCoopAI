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
    assert "NEVER invent or fabricate" in sys_prompt

    user_prompt = payload["messages"][1]["content"]
    assert "INC-OR-01" in user_prompt
    assert "SW_CORE_01:Gi0/1" in user_prompt


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
