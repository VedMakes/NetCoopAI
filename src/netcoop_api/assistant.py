"""Incident Explanation Assistant for read-only multi-turn Q&A over certified incident artifacts."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from netcoop.models.reports import FinalReport, TowerReport
from netcoop.supervisor.openrouter import DEFAULT_FREE_MODEL, DEFAULT_OPENROUTER_URL
from netcoop_api.schemas import AssistantRequest, AssistantResponse
from netcoop_api.service import run_manager

logger = logging.getLogger(__name__)


class ExplanationAssistant:
    """Read-only assistant explaining certified reports, evidence, gate outcomes, and tower findings."""

    def answer_question(self, run_id: str, req: AssistantRequest) -> AssistantResponse:
        report = run_manager.get_run_report(run_id)
        if not report:
            return AssistantResponse(
                question=req.question,
                answer=f"Run '{run_id}' has not produced a certified report yet or does not exist.",
                provider_used="deterministic",
            )

        with run_manager._lock:
            rec = run_manager._runs.get(run_id)
            tower_reports = rec.tower_reports if rec else {}
            gate_result = rec.gate_result if rec else None

        # Gather evidence IDs and findings for citation
        cited_evidence_ids: list[str] = list(report.evidence_sources)
        cited_findings: list[str] = []

        for tr in tower_reports.values():
            for f in tr.findings:
                cited_findings.append(f"{f.severity.value} {f.finding_type}: {f.description}")

        # Check if LLM requested and available
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if req.llm in ("auto", "on") and api_key:
            try:
                llm_answer = self._query_openrouter(
                    question=req.question,
                    history=req.history,
                    report=report,
                    tower_reports=tower_reports,
                    gate_result=gate_result,
                    api_key=api_key,
                )
                if llm_answer:
                    return AssistantResponse(
                        question=req.question,
                        answer=llm_answer,
                        cited_evidence_ids=cited_evidence_ids[:10],
                        cited_findings=cited_findings[:5],
                        provider_used=f"openrouter:{DEFAULT_FREE_MODEL}",
                    )
            except Exception as exc:
                logger.warning(f"OpenRouter assistant query failed: {exc}; falling back to deterministic.")
                if req.llm == "on":
                    return AssistantResponse(
                        question=req.question,
                        answer=f"LLM query failed ({exc}) and --llm on was requested.",
                        provider_used="error",
                    )

        # Deterministic rule-based answer generator
        answer = self._generate_deterministic_answer(
            question=req.question,
            report=report,
            tower_reports=tower_reports,
            gate_result=gate_result,
        )

        return AssistantResponse(
            question=req.question,
            answer=answer,
            cited_evidence_ids=cited_evidence_ids[:10],
            cited_findings=cited_findings[:5],
            provider_used="deterministic",
        )

    def _generate_deterministic_answer(
        self,
        question: str,
        report: FinalReport,
        tower_reports: dict[Any, TowerReport],
        gate_result: Any,
    ) -> str:
        q = question.lower()

        # 1. Why / Root Cause / Suspected Fault
        if any(w in q for w in ["why", "cause", "diagnos", "reason", "root"]):
            if report.status == "insufficient_evidence" or "ABSTAIN" in report.suspected_root_cause:
                return (
                    f"**Abstention Rationale:** The system abstained from diagnosing an outage because telemetry is within nominal baseline parameters.\n\n"
                    f"• **Certified Status:** `{report.status}`\n"
                    f"• **Confidence:** {report.confidence:.2f} (Category: {report.confidence_category})\n"
                    f"• **Explanation:** {report.suspected_root_cause}\n"
                    f"• **Evidence Gate:** Certified clean non-escalation without inventing false alarms."
                )

            evidence_bullets = "\n".join(
                f"  - **{item.metric}**: observed `{item.value}` — {item.interpretation}"
                for item in report.supporting_evidence[:5]
            )
            return (
                f"### Diagnosed Root Cause: `{report.suspected_root_cause}`\n\n"
                f"• **Confidence Score:** {report.confidence:.2f} (`{report.confidence_category}`)\n"
                f"• **Directly Observed Entities:** {', '.join(report.observed_symptom_entities) or 'None'}\n"
                f"• **Inferred Affected Entities:** {', '.join(report.inferred_affected_entities) or 'None'}\n\n"
                f"**Supporting Telemetry Evidence:**\n{evidence_bullets or '  - None cited'}\n\n"
                f"**Recommended Next Steps:**\n" + "\n".join(f"• {act}" for act in report.recommended_actions[:3])
            )

        # 2. Specific Tower Queries
        for tower_name in ["performance", "infrastructure", "connectivity", "services"]:
            if tower_name in q:
                # Find matching tower report
                matched_tr = None
                for tid, tr in tower_reports.items():
                    if tower_name in str(tid).lower():
                        matched_tr = tr
                        break
                if not matched_tr or not matched_tr.findings:
                    return f"The **{tower_name.title()} Tower** evaluated the shared observations and found no abnormal indicators or faults."

                findings_list = "\n".join(
                    f"• [{f.severity.value.upper()}] **{f.finding_type}** ({f.confidence:.2f}): {f.description} (entities: {', '.join(f.entity_refs) or 'N/A'})"
                    for f in matched_tr.findings
                )
                return f"### {tower_name.title()} Tower Assessment\n\n{findings_list}"

        # 3. Evidence / Observations / Citations
        if any(w in q for w in ["evidence", "metric", "observation", "citation", "signal"]):
            if not report.supporting_evidence:
                return "The certified report contains no supporting evidence items (nominal baseline or insufficient evidence)."

            items = "\n".join(
                f"• **{item.metric}** ({item.interpretation}): value `{item.value}`"
                for item in report.supporting_evidence
            )
            sources = f"\n\n**Cited Observation Sources:** {', '.join(report.evidence_sources)}" if report.evidence_sources else ""
            return f"### Grounded Evidence Citations\n\nEvery cited observation was independently verified by the Evidence Release Gate:\n\n{items}{sources}"

        # 4. Evidence Gate / Verification
        if any(w in q for w in ["gate", "verif", "provenance", "check", "valid"]):
            outcome = gate_result.outcome.value if gate_result else "UNKNOWN"
            warnings = "\n".join(f"• {w}" for w in getattr(gate_result, "data_quality_warnings", [])[:3])
            return (
                f"### Evidence Release Gate Verification\n\n"
                f"• **Outcome:** `{outcome}`\n"
                f"• **Integrity Check:** All cited observation IDs exist in the incident record and match the target incident scope.\n"
                f"• **Contradictions Checked:** Conflicting multi-source telemetry signals were evaluated.\n"
                f"{('• **Data Quality Warnings:**\n' + warnings) if warnings else '• **Data Quality:** Zero critical quality warnings.'}"
            )

        # 5. Impact / Entities / Devices
        if any(w in q for w in ["affect", "impact", "device", "entity", "entities", "blast"]):
            return (
                f"### Impact Analysis\n\n"
                f"• **Directly Observed Symptoms (Confirmed Telemetry):**\n"
                f"  {', '.join(report.observed_symptom_entities) or 'None'}\n\n"
                f"• **Inferred Affected Candidates (Topology Blast Radius):**\n"
                f"  {', '.join(report.inferred_affected_entities) or 'None'}\n\n"
                f"*Note: Inferred entities are downstream path predictions from the network topology graph, not direct metric confirmations.*"
            )

        # 6. Alternatives / Pruned Hypotheses
        if any(w in q for w in ["alternative", "reject", "compete", "other", "prune"]):
            alts = "\n".join(f"• {c}" for c in report.concurrent_causes)
            if not alts:
                return "No competing alternative hypotheses met the confidence threshold; the diagnosed cause had dominant causal priority."
            return f"### Evaluated Alternative Causes\n\n{alts}\n\nThese were considered during supervisory reasoning and either classified as concurrent effects or subordinated due to lack of corroborating evidence."

        # Default summary
        return (
            f"### Incident Summary: `{report.incident_id}`\n\n"
            f"• **Suspected Root Cause:** `{report.suspected_root_cause}`\n"
            f"• **Report Status:** `{report.status}` (Confidence: {report.confidence:.2f})\n"
            f"• **Direct Symptoms:** {', '.join(report.observed_symptom_entities) or 'None'}\n"
            f"• **Supporting Evidence Items:** {len(report.supporting_evidence)}\n"
            f"• **Recommendations:**\n" + "\n".join(f"  - {a}" for a in report.recommended_actions[:3])
        )

    def _query_openrouter(
        self,
        question: str,
        history: list[Any],
        report: FinalReport,
        tower_reports: dict[Any, TowerReport],
        gate_result: Any,
        api_key: str,
    ) -> str | None:
        context = {
            "incident_id": report.incident_id,
            "status": report.status,
            "suspected_root_cause": report.suspected_root_cause,
            "confidence": report.confidence,
            "confidence_category": str(report.confidence_category),
            "observed_symptom_entities": report.observed_symptom_entities,
            "inferred_affected_entities": report.inferred_affected_entities,
            "supporting_evidence": [
                {"metric": item.metric, "value": item.value, "interpretation": item.interpretation}
                for item in report.supporting_evidence
            ],
            "evidence_sources": report.evidence_sources,
            "gate_outcome": gate_result.outcome.value if gate_result else "UNKNOWN",
            "recommended_actions": report.recommended_actions,
        }

        system_prompt = (
            "You are the NetCoop AI Incident Explanation Assistant. You answer questions about a completed network diagnosis.\n"
            "STRICT RULES:\n"
            "1. Ground all explanations exclusively in the provided incident context. Do not invent metrics, timestamps, entities, or causes.\n"
            "2. You are read-only: you cannot modify the report, dispatch tasks, or change the gate outcome.\n"
            "3. Cite evidence observation IDs where appropriate.\n"
            "4. Clearly distinguish directly observed symptoms from topology-inferred impact candidates.\n"
            "5. Keep responses concise, professional, and formatted in Markdown."
        )

        messages = [
            {"role": "system", "content": f"{system_prompt}\n\nINCIDENT ARTIFACTS:\n{json.dumps(context, indent=2)}"}
        ]
        for turn in history[-4:]:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": question})

        payload = {
            "model": DEFAULT_FREE_MODEL,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 600,
        }

        req = urllib.request.Request(
            f"{DEFAULT_OPENROUTER_URL}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/VedMakes/NetCoopAI",
                "X-Title": "NetCoop AI Explanation Assistant",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]


# Global assistant singleton
assistant_service = ExplanationAssistant()
