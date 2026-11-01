"""Report formatting and rendering utilities for NetCoop AI."""

from __future__ import annotations

from typing import Any

from netcoop.models.reports import FinalReport


def render_markdown_report(report: FinalReport, gate_result: Any | None = None) -> str:
    """Formats a certified FinalReport into standard GitHub-Flavored Markdown."""
    lines: list[str] = [
        f"# NetCoop AI Root Cause Analysis Report: {report.incident_id}",
        "",
        f"- **Generated At:** {report.generated_at.isoformat()}",
        f"- **Investigation Status:** {report.status.upper()}",
        f"- **Confidence Score:** {report.confidence:.2f}",
        "",
        "---",
        "",
        "## 1. Executive Summary & Root Cause",
        "",
        f"**Primary Suspected Root Cause:** `{report.suspected_root_cause}`",
        "",
        "**Directly affected entities (supported by findings):**",
    ]

    if report.directly_affected_entities:
        for dev in report.directly_affected_entities:
            lines.append(f"- `{dev}`")
    else:
        lines.append("- None identified directly")

    lines.extend(["", "**Entities with cited symptom evidence:**"])
    if report.observed_symptom_entities:
        lines.extend(f"- `{entity}`" for entity in report.observed_symptom_entities)
    else:
        lines.append("- None identified from cited observations")

    if report.site_id:
        lines.extend(["", f"**Site:** `{report.site_id}`"])

    if report.concurrent_causes:
        lines.extend(["", "**Concurrent suspected causes:**"])
        lines.extend(f"- {cause}" for cause in report.concurrent_causes)

    if report.inferred_affected_entities:
        lines.extend([
            "", "**Predicted affected entities (inferred from topology):**",
            "These are predicted impact candidates, not confirmed user impact.",
        ])
        impacts_by_entity = {item.entity_id: item for item in report.predicted_impacts}
        for entity in report.inferred_affected_entities:
            impact = impacts_by_entity.get(entity)
            detail = (
                f" via `{impact.inferred_from}` ({impact.relation}; path `{' → '.join(impact.path)}`; "
                f"topology evidence {', '.join(impact.topology_evidence_refs)})" if impact else ""
            )
            lines.append(f"- `{entity}` — candidate{detail}")

    if report.operator_questions:
        lines.extend(["", "**Information needed from the operator:**"])
        lines.extend(f"- {question}" for question in report.operator_questions)

    if report.network_profile:
        lines.extend([
            "",
            f"**Network profile:** `{report.network_profile.get('profile_id', 'unknown')}` "
            f"v{report.network_profile.get('version', 'unknown')}",
        ])

    lines.extend([
        "",
        "---",
        "",
        "## 2. Supporting Evidence & Verification",
        "",
    ])

    if report.supporting_evidence:
        lines.append("| Metric / Check | Observed Value | Interpretation |")
        lines.append("|---|---|---|")
        for item in report.supporting_evidence:
            val_str = str(item.value) if item.value is not None else "N/A"
            unit = f" {item.unit}" if item.unit else ""
            when = f" at {item.observed_at.isoformat()}" if item.observed_at else ""
            lines.append(f"| `{item.metric}` | {val_str}{unit} | {item.interpretation}{when} |")
    else:
        lines.append("_No corroborating evidence required or supervisor abstained._")

    lines.extend([
        "",
        "---",
        "",
        "## 3. Alternative Causes Considered & Contradiction Disclosure",
        "",
    ])

    if report.alternative_causes:
        for alt in report.alternative_causes:
            lines.append(f"- {alt}")
    else:
        lines.append("- No conflicting hypotheses identified.")

    lines.extend([
        "",
        "---",
        "",
        "## 4. Recommended Actions",
        "",
    ])

    if report.recommended_actions:
        for i, act in enumerate(report.recommended_actions, 1):
            lines.append(f"{i}. {act}")
    else:
        lines.append("1. Continue standard monitoring.")

    lines.extend([
        "",
        "---",
        "",
        "## 5. Investigation Limitations",
        "",
    ])

    if report.limitations:
        for lim in report.limitations:
            lines.append(f"- {lim}")
    else:
        lines.append("- Full telemetry coverage; no significant limitations recorded.")

    if report.data_quality_warnings:
        lines.extend(["", "### Input data quality"])
        lines.extend(f"- {warning}" for warning in report.data_quality_warnings)

    if report.orchestration_warnings:
        lines.extend(["", "### Specialist investigation"])
        lines.extend(f"- {warning}" for warning in report.orchestration_warnings)

    if report.peer_interactions:
        lines.extend(["", "### Peer queries"])
        for interaction in report.peer_interactions:
            result = interaction.get("result") or {}
            reachable = result.get("reachable")
            outcome = f"reachable={reachable}" if isinstance(reachable, bool) else "result returned"
            lines.append(
                f"- `{interaction.get('requester')}` → `{interaction.get('recipient')}` "
                f"`{interaction.get('capability')}` on {interaction.get('scope')}: "
                f"{interaction.get('status')} ({outcome}); evidence {interaction.get('evidence_refs', [])}"
                f"{' [supplemental, post-diagnosis]' if interaction.get('supplementary') else ''}"
            )

    if report.path_triage:
        lines.extend(["", "---", "", "## 6. Supplemental Path Triage", ""])
        lines.append(f"**Status:** `{report.path_triage.status}`")
        lines.append("Reachability describes the recorded topology and does not establish causation.")
        if report.path_triage.paths:
            lines.extend(["", "| Source | Target | Reachability | Path | Evidence |", "|---|---|---|---|---|"])
            for item in report.path_triage.paths:
                reachable = (
                    "reachable" if item.reachable is True else
                    "not reachable in recorded topology" if item.reachable is False else "unknown"
                )
                path = " → ".join(item.path) or "No path returned"
                lines.append(
                    f"| `{item.source_entity}` | `{item.target_entity}` | {reachable} | {path} | "
                    f"{', '.join(item.evidence_refs) or 'none'} |"
                )
                if item.warning:
                    lines.append(f"\nNote for `{item.source_entity}` → `{item.target_entity}`: {item.warning}")
        if report.path_triage.limitations:
            lines.extend(["", "Limitations:"])
            lines.extend(f"- {limitation}" for limitation in report.path_triage.limitations)

    if report.symptom_reasoning:
        reasoning = report.symptom_reasoning
        lines.extend(["", "---", "", "## 7. Optional Symptom Cross-check", ""])
        lines.extend([
            f"**Caller-reported wording:** {reasoning.reported_symptom}",
            f"**Comparison:** `{reasoning.status}`",
            f"**Analysis mode:** `{reasoning.agent_mode}`",
            f"**Recognized categories:** {', '.join(reasoning.recognized_domains) or 'none'}",
            f"**Matched fault codes:** {', '.join(reasoning.matched_fault_codes) or 'none'}",
            "",
            reasoning.explanation,
        ])
        if reasoning.warnings:
            lines.extend(["", "Agent notes:"])
            lines.extend(f"- {warning}" for warning in reasoning.warnings)

    if gate_result is not None:
        lines.extend([
            "",
            "---",
            "",
            "## Evidence Release Gate Verification",
            "",
            f"- **Gate Outcome:** `{gate_result.outcome.value.upper()}`",
            f"- **Certification Passed:** `{'YES' if gate_result.passed else 'NO'}`",
            f"- **Checks Evaluated:** {len(gate_result.checks)} checks completed",
        ])

    return "\n".join(lines) + "\n"
