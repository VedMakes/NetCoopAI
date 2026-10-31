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
        "**Affected Entities & Devices:**",
    ]

    if report.affected_devices:
        for dev in report.affected_devices:
            lines.append(f"- `{dev}`")
    else:
        lines.append("- None detected / not applicable")

    lines.extend([
        "",
        "---",
        "",
        "## 2. Supporting Evidence & Verification",
        "",
    ])

    if report.supporting_evidence:
        lines.append("| Metric / Check | Observed Value | Clinical Interpretation |")
        lines.append("|---|---|---|")
        for item in report.supporting_evidence:
            val_str = str(item.value) if item.value is not None else "N/A"
            lines.append(f"| `{item.metric}` | {val_str} | {item.interpretation} |")
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

    if gate_result is not None:
        lines.extend([
            "",
            "---",
            "",
            "## 6. Evidence Release Gate Verification",
            "",
            f"- **Gate Outcome:** `{gate_result.outcome.value.upper()}`",
            f"- **Certification Passed:** `{'YES' if gate_result.passed else 'NO'}`",
            f"- **Checks Evaluated:** {len(gate_result.checks)} checks completed",
        ])

    return "\n".join(lines) + "\n"
