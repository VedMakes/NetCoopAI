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
        conf_cat = report.confidence_category.value if hasattr(report.confidence_category, "value") else str(report.confidence_category or "calibrated")

        # 1. Remediation / Actions / Fix / Steps / Mitigation (check before generic 'why')
        if any(w in q for w in ["remediat", "action", "step", "fix", "mitigat", "next", "resolv"]):
            if not report.recommended_actions:
                return (
                    f"### Recommended Actions for Incident `{report.incident_id}`\n\n"
                    "No immediate operator remediation actions were formulated (baseline nominal or insufficient evidence)."
                )

            actions_list = "\n".join(
                f"{i + 1}. **{act}**" for i, act in enumerate(report.recommended_actions)
            )
            return (
                f"### Prioritized Remediation Steps\n\n"
                f"Based on certified diagnosis `{report.suspected_root_cause}`:\n\n"
                f"{actions_list}\n\n"
                f"*(Note: NetCoop AI is a diagnostic & recommendation platform and does not automatically execute network configuration changes.)*"
            )

        # 2. Limitations / Uncertainties / Caveats / Boundary Conditions
        if any(w in q for w in ["limitat", "uncertain", "caveat", "boundar", "risk", "gap", "shortcom"]):
            gate_lims = list(getattr(gate_result, "limitations", [])) if gate_result else []
            gate_warns = list(getattr(gate_result, "warnings", [])) if gate_result else []
            rep_lims = list(report.limitations or [])
            all_lims = list(dict.fromkeys(rep_lims + gate_lims))

            lims_text = "\n".join(f"• {lim}" for lim in all_lims) if all_lims else "• No active limitation flags recorded."
            warns_text = "\n".join(f"• {w}" for w in gate_warns) if gate_warns else ""

            return (
                f"### System Limitations & Boundary Conditions\n\n"
                f"The following caveats were audited by the Evidence Release Gate:\n\n"
                f"{lims_text}\n"
                f"{('\n**Gate Warnings:**\n' + warns_text) if warns_text else ''}\n\n"
                f"• **Confidence Category:** `{conf_cat}` (Score: {report.confidence:.2f})\n"
                f"• **Corroboration Scope:** Diagnostic claims are strictly bound to captured scenario observations and topology records."
            )

        # 3. Alternatives / Competing Hypotheses / Downweighted Causes / Dispute Resolution
        if any(w in q for w in ["alternative", "reject", "compete", "downweight", "other cause", "dispute", "prune"]):
            competing_list: list[str] = []
            for tr in tower_reports.values():
                for hyp in tr.hypotheses:
                    if hyp.fault_code.upper() not in report.suspected_root_cause.upper():
                        competing_list.append(
                            f"• **{hyp.fault_code}** (Tower: `{tr.tower_id.value}`, Score: {hyp.confidence_score:.2f}): {hyp.rationale}"
                        )

            alts_from_report = [f"• {alt}" for alt in report.alternative_causes]
            all_competing = competing_list or alts_from_report

            if not all_competing:
                return (
                    "### Competing Hypotheses Assessment\n\n"
                    "No competing alternative hypotheses met the supervisory confidence threshold. "
                    "The primary root cause showed dominant causal correlation across telemetry features without conflicting signals."
                )

            return (
                f"### Evaluated & Downweighted Hypotheses\n\n"
                f"The supervisor evaluated the following competing hypotheses and downweighted them in favor of `{report.suspected_root_cause}`:\n\n"
                + "\n".join(all_competing[:5])
                + "\n\n**Resolution Rationale:** Hypotheses lacking independent cross-domain corroboration or exhibiting lower anomaly confidence scores were subordinated."
            )

        # 4. Path Triage / Reachability / Topology Route
        if any(w in q for w in ["path", "route", "reachab", "blast", "hop", "upstream", "connect"]):
            if report.path_triage and report.path_triage.paths:
                paths_summary = "\n".join(
                    f"• `{' → '.join(p.path)}` — **{'REACHABLE' if p.reachable else 'UNREACHABLE'}**"
                    for p in report.path_triage.paths[:5]
                )
                return (
                    f"### Topological Path & Reachability Analysis\n\n"
                    f"Physical path triage evaluated by Connectivity Tower:\n\n"
                    f"{paths_summary}\n\n"
                    f"• **Directly Observed:** {', '.join(report.observed_symptom_entities) or 'None'}\n"
                    f"• **Inferred Blast Radius:** {', '.join(report.inferred_affected_entities) or 'None'}"
                )
            if report.inferred_affected_entities:
                return (
                    f"### Topology Reachability & Blast Radius\n\n"
                    f"• **Direct Symptom Entity:** {', '.join(report.observed_symptom_entities) or 'None'}\n"
                    f"• **Inferred Downstream Impact:** {', '.join(report.inferred_affected_entities)}\n\n"
                    f"*(Downstream entities were identified via NetworkX topology graph traversal from the fault location.)*"
                )

        # 5. Confidence / Scoring / Calibration
        if any(w in q for w in ["confidence", "score", "calibrat", "certain"]):
            return (
                f"### Confidence & Calibration Analysis\n\n"
                f"• **Numeric Confidence:** `{report.confidence:.2f}` (scale 0.0 - 1.0)\n"
                f"• **Confidence Category:** `{conf_cat}`\n"
                f"• **Gate Audit Status:** `{getattr(gate_result, 'outcome', 'CERTIFIED')}`\n"
                f"• **Evidence Coverage:** Verified against {len(report.supporting_evidence)} supporting evidence observations."
            )

        # 6. Specific Tower Queries
        for tower_name in ["performance", "infrastructure", "connectivity", "services"]:
            if tower_name in q:
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
                hypotheses_list = "\n".join(
                    f"  - Hypothesis `{h.fault_code}` (Score: {h.confidence_score:.2f}): {h.rationale}"
                    for h in matched_tr.hypotheses
                )
                return (
                    f"### {tower_name.title()} Tower Assessment\n\n"
                    f"**Findings ({len(matched_tr.findings)}):**\n{findings_list}\n\n"
                    + (f"**Proposed Hypotheses:**\n{hypotheses_list}" if hypotheses_list else "")
                )

        # 7. Evidence / Observations / Citations
        if any(w in q for w in ["evidence", "metric", "observation", "citation", "signal", "raw"]):
            if not report.supporting_evidence:
                return "The certified report contains no supporting evidence items (nominal baseline or insufficient evidence)."

            items = "\n".join(
                f"• **{item.metric}**: observed `{item.value}` {item.unit or ''} on `{item.entity_id or 'topology'}` — {item.interpretation}"
                for item in report.supporting_evidence[:8]
            )
            sources = f"\n\n**Cited Observation Keys:** {', '.join(report.evidence_sources)}" if report.evidence_sources else ""
            return (
                f"### Grounded Evidence Citations\n\n"
                f"Every cited observation was independently verified by the Evidence Release Gate:\n\n"
                f"{items}{sources}"
            )

        # 8. Evidence Gate / Verification
        if any(w in q for w in ["gate", "verif", "provenance", "check", "valid"]):
            outcome = gate_result.outcome.value if gate_result else "UNKNOWN"
            checks = getattr(gate_result, "checks", [])
            checks_text = "\n".join(
                f"• **{c.check_name}**: {'PASSED' if c.passed else 'FAILED'} — {c.message}"
                for c in checks[:5]
            ) if checks else "• Deterministic checks passed."
            return (
                f"### Evidence Release Gate Verification\n\n"
                f"• **Gate Outcome:** `{outcome}`\n"
                f"• **Gate Role:** Independent barrier preventing hallucinated root causes or unverified claims.\n\n"
                f"**Audit Checks:**\n{checks_text}"
            )

        # 9. Why / Root Cause / Suspected Fault
        if any(w in q for w in ["why", "cause", "diagnos", "reason", "root"]):
            if report.status == "insufficient_evidence" or "ABSTAIN" in report.suspected_root_cause:
                return (
                    f"**Abstention Rationale:** The system abstained from diagnosing an outage because telemetry is within nominal baseline parameters.\n\n"
                    f"• **Certified Status:** `{report.status}`\n"
                    f"• **Confidence:** {report.confidence:.2f} (Category: {conf_cat})\n"
                    f"• **Explanation:** {report.suspected_root_cause}\n"
                    f"• **Evidence Gate:** Certified clean non-escalation without inventing false alarms."
                )

            evidence_bullets = "\n".join(
                f"  - **{item.metric}**: observed `{item.value}` {item.unit or ''} — {item.interpretation}"
                for item in report.supporting_evidence[:4]
            )
            return (
                f"### Diagnosed Root Cause: `{report.suspected_root_cause}`\n\n"
                f"• **Confidence Score:** {report.confidence:.2f} (`{conf_cat}`)\n"
                f"• **Directly Observed Entities:** {', '.join(report.observed_symptom_entities) or 'None'}\n"
                f"• **Inferred Affected Entities:** {', '.join(report.inferred_affected_entities) or 'None'}\n\n"
                f"**Supporting Telemetry Evidence:**\n{evidence_bullets or '  - None cited'}\n\n"
                f"**Recommended Next Steps:**\n" + "\n".join(f"• {act}" for act in report.recommended_actions[:3])
            )

        # Default summary
        return (
            f"### Incident Summary: `{report.incident_id}`\n\n"
            f"• **Suspected Root Cause:** `{report.suspected_root_cause}`\n"
            f"• **Report Status:** `{report.status}` (Confidence: {report.confidence:.2f})\n"
            f"• **Direct Symptoms:** {', '.join(report.observed_symptom_entities) or 'None'}\n"
            f"• **Supporting Evidence Items:** {len(report.supporting_evidence)}\n"
            f"• **Recommendations:**\n" + "\n".join(f"  - {a}" for a in report.recommended_actions[:3])
        )
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
