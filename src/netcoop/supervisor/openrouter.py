"""OpenRouter API adapter for Supervisory RCA Agent.

Supports free reasoning models on OpenRouter (e.g. meta-llama/llama-3.3-70b-instruct:free,
google/gemini-2.0-flash-exp:free, deepseek/deepseek-r1:free) with strict schema validation
and automatic fallback to DeterministicRCAProvider.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from netcoop.models.enums import ConfidenceCategory, ProposalDecision
from netcoop.models.reports import ClaimEvidenceManifest, SupervisorProposal
from netcoop.supervisor.agent import DeterministicRCAProvider
from netcoop.supervisor.models import IncidentDossier
from netcoop.utils.env import load_dotenv
from netcoop.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

DEFAULT_FREE_MODEL = "nvidia/nemotron-3.5-lightning:free"
DEFAULT_OPENROUTER_URL = "https://openrouter.ai/api/v1"


def call_openrouter_chat(
    payload: dict[str, Any],
    *,
    api_key: str,
    base_url: str = DEFAULT_OPENROUTER_URL,
    timeout_seconds: float = 30.0,
) -> str:
    """Shared transport for isolated supervisory add-on providers."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/NetCoopAI/netcoop",
        "X-Title": "NetCoop AI",
    }
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
        resp_json = json.loads(response.read().decode("utf-8"))
    choices = resp_json.get("choices", [])
    if not choices:
        raise ValueError("OpenRouter API returned empty choices array.")
    return choices[0].get("message", {}).get("content", "")


class OpenRouterProvider:
    """OpenRouter API adapter for case-level LLM diagnostic reasoning."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        load_dotenv()
        self.api_key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
        self.model = model if model is not None else os.environ.get("OPENROUTER_MODEL", DEFAULT_FREE_MODEL)
        self.base_url = (base_url if base_url is not None else os.environ.get("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_URL)).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.fallback = DeterministicRCAProvider()

    def diagnose(self, dossier: IncidentDossier) -> tuple[SupervisorProposal, ClaimEvidenceManifest]:
        """Queries OpenRouter LLM for diagnostic proposal with automatic deterministic fallback."""
        if not self.api_key:
            logger.info("OpenRouter API key missing; utilizing deterministic arbitration fallback.")
            return self.fallback.diagnose(dossier)

        try:
            prompt_payload = self._build_prompt_payload(dossier)
            raw_response = self._call_openrouter(prompt_payload)
            proposal, manifest = self._parse_and_validate_response(raw_response, dossier)
            return proposal, manifest
        except Exception as e:
            logger.warning(
                f"OpenRouter diagnostic reasoning encountered issue ({e}); safely falling back to deterministic arbitration."
            )
            return self.fallback.diagnose(dossier)

    def _build_prompt_payload(self, dossier: IncidentDossier) -> dict[str, Any]:
        """Constructs compact structured prompt minimizing tokens and hallucination risk."""
        # Compile structured summary of tower reports
        towers_summary = {}
        for t_id, report in dossier.tower_reports.items():
            towers_summary[t_id.value] = {
                "status": report.status,
                "summary": report.summary,
                "findings": [
                    {
                        "finding_id": f.finding_id,
                        "type": f.finding_type,
                        "severity": f.severity.value,
                        "entities": f.entity_refs,
                        "evidence_refs": f.evidence_refs,
                        "description": f.description,
                    }
                    for f in report.findings
                ],
                "hypotheses": [
                    {
                        "hypothesis_id": h.hypothesis_id,
                        "fault_code": h.fault_code,
                        "confidence_score": h.confidence_score,
                        "confidence_category": h.confidence_category.value,
                        "suspected_entities": h.suspected_entities,
                        "rationale": h.rationale,
                    }
                    for h in report.hypotheses
                ],
            }

        valid_finding_ids = [f.finding_id for f in dossier.findings]
        all_obs_ids = []
        for f in dossier.findings:
            all_obs_ids.extend(f.evidence_refs)
        valid_obs_ids = sorted(list(set(all_obs_ids)))

        system_instruction = (
            "You are the Supervisory RCA Agent for NetCoop AI, an evidence-backed network fault diagnostic system.\n"
            "Your task is to analyze the compact multi-tower incident dossier and formulate a case-level diagnosis.\n"
            "MANDATORY INVARIANTS:\n"
            "1. Output ONLY a valid JSON object matching the requested schema.\n"
            f"2. You may ONLY cite finding IDs from this valid list: {valid_finding_ids}\n"
            f"3. You may ONLY cite observation IDs from this valid list: {valid_obs_ids}\n"
            "4. NEVER invent or fabricate non-existent finding or observation IDs. Any unknown ID will cause the release gate to reject your diagnosis.\n"
            "5. If normal telemetry is observed without anomalies, set decision to 'abstain' with abstain_reason.\n"
            "6. Classify any competing hypotheses between towers and disclose them in alternative_causes.\n"
            "7. Distinguish independent simultaneous faults from competing explanations; list supported independent faults in concurrent_causes.\n"
            "8. Treat data-quality warnings and sparse observations as limitations; lower confidence or abstain when coverage cannot support a diagnosis.\n"
            "9. When gate_feedback is present, address each issue using only the dossier. Request one targeted read-only task only when it can gather discriminating evidence; otherwise correct the proposal or abstain.\n"
            "10. Challenge tasks must report supporting and contradicting evidence references, missing measurements, and a discriminating test. Repeating the same evidence is not independent confirmation.\n"
            "7. Output JSON format:\n"
            "{\n"
            '  "decision": "propose_diagnosis" | "request_evidence" | "abstain",\n'
            '  "suspected_root_cause": "FAULT_CODE: concise reason" (or null if abstain),\n'
            '  "affected_entities": ["DEVICE_OR_INTERFACE"],\n'
            '  "supporting_finding_refs": ["VALID_FINDING_ID"],\n'
            '  "confidence_category": "high" | "moderate" | "low" | "insufficient",\n'
            '  "alternative_causes": ["ALTERNATIVE_FAULT_CODE"],\n'
            '  "concurrent_causes": ["INDEPENDENT_FAULT_CODE"],\n'
            '  "recommended_actions": ["Safe read-only check recommendation"],\n'
            '  "abstain_reason": null or "Reason for abstention",\n'
            '  "requested_tasks": [],\n'
            '  "claim": "Factual diagnostic claim statement",\n'
            '  "observation_ids": ["VALID_OBS_ID"],\n'
            '  "contradiction_ids": [],\n'
            '  "contradiction_disclosures": []\n'
            "}"
        )

        user_content = json.dumps(
            {
                "incident_id": dossier.incident_id,
                "symptom": dossier.symptom,
                "affected_entities": dossier.affected_entities,
                "investigation_round": dossier.investigation_round,
                "task_history": dossier.task_history,
                "gate_feedback": dossier.gate_feedback,
                "data_quality_warnings": dossier.data_quality_warnings,
                "topology_summary": dossier.topology_summary,
                "available_capabilities": dossier.available_capabilities[:8],
                "towers": towers_summary,
            },
            indent=2,
        )

        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

    def _call_openrouter(self, payload: dict[str, Any]) -> str:
        """Executes HTTP request to OpenRouter chat completions endpoint."""
        return call_openrouter_chat(
            payload,
            api_key=self.api_key,
            base_url=self.base_url,
            timeout_seconds=self.timeout_seconds,
        )

    def _parse_and_validate_response(
        self, raw_content: str, dossier: IncidentDossier
    ) -> tuple[SupervisorProposal, ClaimEvidenceManifest]:
        """Parses LLM JSON output, validates cited IDs against dossier, and constructs models."""
        cleaned = raw_content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        data = json.loads(cleaned)

        raw_decision = data.get("decision", "propose_diagnosis").lower()
        if raw_decision == "abstain":
            decision = ProposalDecision.ABSTAIN
        elif raw_decision == "request_evidence":
            decision = ProposalDecision.REQUEST_EVIDENCE
        else:
            decision = ProposalDecision.PROPOSE_DIAGNOSIS

        # Sanitize and validate cited Finding IDs
        valid_f_ids = {f.finding_id for f in dossier.findings}
        cited_findings = [f_id for f_id in data.get("supporting_finding_refs", []) if f_id in valid_f_ids]

        # Sanitize and validate cited Observation IDs
        known_obs_ids = set()
        for f in dossier.findings:
            known_obs_ids.update(f.evidence_refs)
        cited_obs_ids = [obs_id for obs_id in data.get("observation_ids", []) if obs_id in known_obs_ids]

        # If LLM failed to cite valid findings when proposing diagnosis, fallback
        if decision == ProposalDecision.PROPOSE_DIAGNOSIS and not cited_findings:
            logger.info("LLM proposal cited no valid existing findings; falling back to deterministic provider.")
            return self.fallback.diagnose(dossier)

        # Parse confidence category
        raw_conf = data.get("confidence_category", "moderate").lower()
        try:
            confidence_cat = ConfidenceCategory(raw_conf)
        except ValueError:
            confidence_cat = ConfidenceCategory.MODERATE

        # Calculate independence groups
        cited_finding_objs = [f for f in dossier.findings if f.finding_id in cited_findings]
        independence_groups = sorted(
            list({f.independence_group or f.source_tower.value for f in cited_finding_objs})
        )

        proposal = SupervisorProposal(
            proposal_id=generate_id("PROP-LLM"),
            incident_id=dossier.incident_id,
            decision=decision,
            suspected_root_cause=data.get("suspected_root_cause") if decision != ProposalDecision.ABSTAIN else None,
            affected_entities=data.get("affected_entities", dossier.affected_entities),
            supporting_finding_refs=cited_findings,
            confidence_category=confidence_cat,
            alternative_causes=data.get("alternative_causes", []),
            concurrent_causes=data.get("concurrent_causes", []),
            recommended_actions=data.get("recommended_actions", ["Perform detailed interface telemetry review."]),
            abstain_reason=data.get("abstain_reason") if decision == ProposalDecision.ABSTAIN else None,
            requested_tasks=data.get("requested_tasks", []),
            created_at=datetime.now(timezone.utc),
        )

        manifest = ClaimEvidenceManifest(
            incident_id=dossier.incident_id,
            claim=data.get("claim", f"Diagnosis: {proposal.suspected_root_cause}"),
            claimed_entities=proposal.affected_entities,
            finding_ids=cited_findings,
            observation_ids=cited_obs_ids,
            independence_groups=independence_groups,
            contradiction_ids=data.get("contradiction_ids", []),
            contradiction_disclosures=data.get("contradiction_disclosures", []),
        )

        return proposal, manifest
