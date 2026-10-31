"""SupervisorRuntime orchestrating incident state, task authorization, and report release.

Deterministic controller managing the lifecycle of an incident from intake through
tower execution, RCA reasoning, task budgeting, and evidence gate verification.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from netcoop.communication.fabric import IntegrationFabric
from netcoop.communication.queries import PeerQuery
from netcoop.communication.tasks import DiagnosticTaskArtifact
from netcoop.models.enums import ConfidenceCategory, ProposalDecision, TowerId
from netcoop.models.findings import Finding
from netcoop.models.hypotheses import Hypothesis
from netcoop.models.observations import (
    ConfigObservation,
    LogObservation,
    MetricObservation,
    TopologyObservation,
)
from netcoop.models.reports import ClaimEvidenceManifest, FinalReport, PathTriage, TowerReport
from netcoop.supervisor.agent import SupervisoryRCAAgent
from netcoop.supervisor.gate import EvidenceReleaseGate
from netcoop.supervisor.models import (
    GateOutcome,
    GateResult,
    IncidentDossier,
    IncidentLifecycleState,
    InvestigationBudget,
)
from netcoop.supervisor.supplementary import build_path_triage
from netcoop.utils.id_generator import generate_id

if TYPE_CHECKING:
    from netcoop.models.observations import CanonicalObservation
    from netcoop.storage.sqlite import SQLiteRepository

logger = logging.getLogger(__name__)


class EvidenceGateRejectionError(Exception):
    """Raised when the independent EvidenceReleaseGate rejects a proposed diagnosis."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class SupervisorRuntime:
    """Deterministic runtime owning incident state machine, budgets, and publication."""

    def __init__(
        self,
        fabric: IntegrationFabric | None = None,
        repository: SQLiteRepository | None = None,
        rca_agent: SupervisoryRCAAgent | None = None,
        gate: EvidenceReleaseGate | None = None,
        budget: InvestigationBudget | None = None,
        network_profile: dict[str, str] | None = None,
        explain: Any | None = None,
    ) -> None:
        self.repo = repository
        self.fabric = fabric or IntegrationFabric(repository=self.repo)
        self.gate = gate or EvidenceReleaseGate(repository=self.repo)
        self.rca_agent = rca_agent or SupervisoryRCAAgent()
        self.budget = budget or InvestigationBudget()
        self.network_profile = network_profile
        self.explain = explain

        # Operational state
        self.state = IncidentLifecycleState.CREATED
        self.supervisor_calls: int = 0
        self.investigation_rounds: int = 0
        self.tasks_dispatched: int = 0
        self._task_fingerprints: set[tuple[str, str, str, tuple[str, ...], tuple[str, ...]]] = set()

    @property
    def budget_used(self) -> dict[str, int]:
        return {
            "supervisor_calls": self.supervisor_calls,
            "investigation_rounds": self.investigation_rounds,
            "tasks_dispatched": self.tasks_dispatched,
        }

    def run_incident(
        self,
        incident_id: str,
        observations: list[CanonicalObservation],
        symptom: str = "",
        time_window: dict[str, Any] | None = None,
        data_quality_warnings: list[str] | None = None,
    ) -> FinalReport:
        """Runs full end-to-end incident investigation workflow deterministically."""
        self._explain("intake", f"Loaded {len(observations)} normalized observations; {len(data_quality_warnings or [])} data quality warning(s).")
        for warning in (data_quality_warnings or [])[:20]:
            self._explain("intake warning", warning)
        if len(data_quality_warnings or []) > 20:
            self._explain("intake warning", f"{len(data_quality_warnings or []) - 20} additional warning(s) omitted from the live trace; see report.")
        # Step 1: Initialize incident record
        self.state = IncidentLifecycleState.CREATED
        if self.repo is not None:
            self.repo.record_incident(
                incident_id=incident_id,
                status="active",
                description=symptom or "Network incident investigation",
            )
            for obs in observations:
                self.repo.insert_observation(obs)

        # Step 2: Run all four diagnostic towers
        self.state = IncidentLifecycleState.TOWERS_RUNNING
        def explain_tower(tower_id: TowerId, tower_report: TowerReport) -> None:
            if self.explain is None:
                return
            summary = f"{len(tower_report.findings)} finding(s), {len(tower_report.hypotheses)} hypothesis(es)."
            for finding in tower_report.findings:
                summary += (
                    f"\n  {finding.severity.value} {finding.finding_type} ({finding.confidence:.2f}): "
                    f"{finding.description}; entities={', '.join(finding.entity_refs) or 'unspecified'}; "
                    f"evidence={', '.join(finding.evidence_refs)}"
                )
                related_metrics = [
                    observation for observation in observations
                    if isinstance(observation, MetricObservation)
                    and observation.entity_id in finding.entity_refs
                ]
                by_sample: dict[tuple[str, str, datetime], list[MetricObservation]] = {}
                for observation in related_metrics:
                    by_sample.setdefault(
                        (observation.entity_id, observation.metric_name, observation.timestamp), []
                    ).append(observation)
                for (entity, metric, timestamp), samples in by_sample.items():
                    if len({sample.value for sample in samples}) > 1:
                        values = ", ".join(
                            f"{sample.value:g} {sample.unit} [{sample.observation_id}, {sample.source}]"
                            for sample in samples
                        )
                        summary += f"\n  CONFLICT {entity}.{metric} at {timestamp.isoformat()}: {values}"
            self._explain("specialist", f"{tower_id.value} analyzed the shared observation set. {summary}")

        tower_reports: dict[TowerId, TowerReport] = self.fabric.run_all_towers(
            incident_id=incident_id, observations=observations,
            on_tower_complete=explain_tower if self.explain is not None else None,
        )
        if self.repo is not None:
            for report in tower_reports.values():
                self.repo.insert_tower_report(report)

        self.state = IncidentLifecycleState.TOWERS_EVALUATED

        # Step 3: Construct compact incident context (dossier)
        dossier = self._build_dossier(
            incident_id=incident_id,
            symptom=symptom,
            time_window=time_window,
            tower_reports=tower_reports,
            observations=observations,
            data_quality_warnings=data_quality_warnings or [],
        )

        # Services asks Connectivity to verify the physical path to a resolver/relay
        # when a service fault is present. Keep the request and response in the dossier
        # so the supervisor can use and disclose the result.
        self._run_service_reachability_queries(dossier, observations)

        # Step 4: Supervisory reasoning loop
        self.state = IncidentLifecycleState.SUPERVISOR_REASONING
        proposal, manifest = self.rca_agent.diagnose(dossier)
        self.supervisor_calls += 1
        self._explain("supervisor", f"Supervisor returned {proposal.decision.value}; confidence={proposal.confidence_category.value}; claim={manifest.claim}")

        # Step 5: Handle investigation requests if budget allows
        if proposal.decision == ProposalDecision.REQUEST_EVIDENCE:
            if (
                self.supervisor_calls < self.budget.max_supervisor_calls
                and self.investigation_rounds < self.budget.max_investigation_rounds
                and self.tasks_dispatched < self.budget.max_tasks
            ):
                self.state = IncidentLifecycleState.INVESTIGATING
                self.investigation_rounds += 1
                self._dispatch_task_requests(proposal, dossier, incident_id, observations)

                # Re-diagnose with updated task history in round 2
                dossier.investigation_round += 1
                self.state = IncidentLifecycleState.SUPERVISOR_REASONING
                proposal, manifest = self.rca_agent.diagnose(dossier)
                self.supervisor_calls += 1
                self._explain("supervisor", f"Supervisor reconsidered after specialist response: {proposal.decision.value}; confidence={proposal.confidence_category.value}; claim={manifest.claim}")
            else:
                proposal = proposal.model_copy(update={
                    "decision": ProposalDecision.ABSTAIN,
                    "suspected_root_cause": None,
                    "confidence_category": ConfidenceCategory.INSUFFICIENT,
                    "recommended_actions": ["Collect the requested discriminating telemetry and rerun diagnosis."],
                    "abstain_reason": "Investigation could not be completed within the configured orchestration budget.",
                    "requested_tasks": [],
                })
                manifest = ClaimEvidenceManifest(
                    incident_id=incident_id,
                    claim="Abstained because the conflict investigation budget was exhausted.",
                    claimed_entities=proposal.affected_entities,
                    finding_ids=[], observation_ids=[], independence_groups=[],
                    contradiction_ids=proposal.alternative_causes,
                    contradiction_disclosures=[],
                )

        if proposal.decision == ProposalDecision.REQUEST_EVIDENCE:
            proposal = self._abstain_for_budget(
                proposal, reason="The supervisor still requires evidence after the allowed investigation round."
            )
            manifest = self._abstention_manifest(proposal, incident_id)

        # Step 6: Evidence and Release Gate verification
        self.state = IncidentLifecycleState.PROPOSED
        self.state = IncidentLifecycleState.GATE_EVALUATING

        # Extract competing hypotheses across towers
        competing_hypotheses = [
            f"{h.fault_code}: {h.suspected_entities}"
            for h in dossier.hypotheses
        ]
        orchestration_warnings = [
            f"Task {entry.get('task_id')} ({entry.get('capability')}) {entry.get('status')}: {warning}"
            for entry in dossier.task_history
            for warning in entry.get("warnings", []) + entry.get("limitations", [])
        ]
        orchestration_warnings.extend(
            f"Task {entry.get('task_id')} ({entry.get('capability')}) ended {entry.get('status')}."
            for entry in dossier.task_history if entry.get("status") != "COMPLETED"
        )
        orchestration_warnings.extend(
            f"Peer query {entry.get('query_id')} ({entry.get('capability')}) {entry.get('status')}: {warning}"
            for entry in dossier.peer_query_history
            for warning in entry.get("warnings", [])
        )

        def evaluate_gate() -> GateResult:
            return self.gate.evaluate(
                proposal=proposal,
                manifest=manifest,
                incident_id=incident_id,
                known_observations=observations,
                known_findings=dossier.findings,
                competing_hypotheses=competing_hypotheses,
                data_quality_warnings=data_quality_warnings,
                orchestration_warnings=orchestration_warnings,
                peer_interactions=dossier.peer_query_history,
                network_profile=self.network_profile,
            )

        gate_result = evaluate_gate()
        gate_retries = 0
        if not gate_result.passed:
            for check in gate_result.checks:
                check_status = "PASS" if check.passed else "WARN" if check.severity == "warning" else "FAIL"
                self._explain("gate attempt 1", f"{check_status} {check.check_name}: {check.message}")
        if (
            not gate_result.passed
            and gate_result.issues
            and any(issue.retryable for issue in gate_result.issues)
            and gate_retries < self.budget.max_retries
        ):
            gate_retries += 1
            dossier.gate_feedback = [issue.model_dump(mode="json") for issue in gate_result.issues]
            orchestration_warnings.append(
                "Gate retry requested: "
                + "; ".join(f"{issue.code}: {issue.message}" for issue in gate_result.issues)
            )
            self._explain(
                "gate retry",
                "Gate rejected the proposal with actionable issue(s); requesting one bounded supervisor review: "
                + "; ".join(f"{issue.code}: {issue.message}" for issue in gate_result.issues),
            )
            if self.supervisor_calls < self.budget.max_supervisor_calls:
                proposal, manifest = self.rca_agent.diagnose(dossier)
                self.supervisor_calls += 1
                self._explain("supervisor", f"Gate-feedback review returned {proposal.decision.value}; confidence={proposal.confidence_category.value}.")
                if proposal.decision == ProposalDecision.REQUEST_EVIDENCE:
                    if (
                        self.investigation_rounds < self.budget.max_investigation_rounds
                        and self.tasks_dispatched < self.budget.max_tasks
                    ):
                        self.investigation_rounds += 1
                        self.state = IncidentLifecycleState.INVESTIGATING
                        self._dispatch_task_requests(proposal, dossier, incident_id, observations)
                        dossier.investigation_round += 1
                        if self.supervisor_calls < self.budget.max_supervisor_calls:
                            proposal, manifest = self.rca_agent.diagnose(dossier)
                            self.supervisor_calls += 1
                    else:
                        proposal = self._abstain_for_budget(proposal)
                        manifest = self._abstention_manifest(proposal, incident_id)
                if proposal.decision == ProposalDecision.REQUEST_EVIDENCE:
                    proposal = self._abstain_for_budget(
                        proposal, reason="The gate retry did not resolve the requested evidence gap."
                    )
                    manifest = self._abstention_manifest(proposal, incident_id)
                gate_result = evaluate_gate()

        for check in gate_result.checks:
            check_status = "PASS" if check.passed else "WARN" if check.severity == "warning" else "FAIL"
            self._explain("gate final", f"{check_status} {check.check_name}: {check.message}")
        self._explain("gate", f"Release outcome: {gate_result.outcome.value}; {len(gate_result.errors)} error(s), {len(gate_result.warnings)} warning(s).")

        # Persist proposal and gate result
        if self.repo is not None:
            self.repo.insert_supervisor_proposal(proposal)
            self.repo.insert_gate_result(incident_id, gate_result)

        # Step 7: Gate Decision Resolution
        if gate_result.outcome == GateOutcome.ABSTAIN:
            self.state = IncidentLifecycleState.ABSTAINED
            report = gate_result.certified_final_report or FinalReport(
                incident_id=incident_id,
                status="insufficient_evidence",
                suspected_root_cause=f"ABSTAIN: {proposal.abstain_reason or 'Diagnostic ambiguity'}",
                confidence=0.0,
                affected_devices=proposal.affected_entities,
                supporting_evidence=[],
                alternative_causes=proposal.alternative_causes,
                recommended_actions=proposal.recommended_actions,
                evidence_sources=[],
                limitations=["Supervisor abstained due to ambiguity or insufficient evidence."],
                generated_at=proposal.created_at,
            )
            report = self._add_path_triage(report, incident_id, observations)
            if self.repo is not None:
                self.repo.insert_final_report(report)
            self._explain_final_report(report, gate_result)
            return report

        if not gate_result.passed or gate_result.certified_final_report is None:
            self.state = IncidentLifecycleState.ABSTAINED
            report = FinalReport(
                incident_id=incident_id,
                status="insufficient_evidence",
                suspected_root_cause="ABSTAIN: Evidence gate could not certify the diagnosis.",
                confidence=0.0,
                confidence_category=ConfidenceCategory.INSUFFICIENT,
                affected_devices=[],
                directly_affected_entities=proposal.affected_entities,
                supporting_evidence=[],
                alternative_causes=proposal.alternative_causes,
                operator_questions=proposal.operator_questions,
                recommended_actions=["Resolve the evidence-gate issues and collect any missing discriminating telemetry."],
                evidence_sources=[],
                limitations=gate_result.errors or gate_result.warnings,
                data_quality_warnings=data_quality_warnings or [],
                generated_at=datetime.now(timezone.utc),
            )
            report = self._add_path_triage(report, incident_id, observations)
            if self.repo is not None:
                self.repo.insert_gate_result(incident_id, gate_result)
                self.repo.insert_final_report(report)
            self._explain_final_report(report, gate_result)
            return report

        # Publication verified
        self.state = IncidentLifecycleState.PUBLISHED
        final_report = gate_result.certified_final_report
        final_report = self._add_path_triage(final_report, incident_id, observations)

        if self.repo is not None:
            self.repo.insert_final_report(final_report)

        self._explain_final_report(final_report, gate_result)
        return final_report

    def _explain_final_report(self, report: FinalReport, gate_result: GateResult) -> None:
        """Show the certified report after gate processing and supplemental path context."""
        warning_text = "; ".join([*gate_result.warnings, *gate_result.limitations]) or "none"
        self._explain(
            "published report",
            f"status={report.status}; gate={gate_result.outcome.value}; "
            f"diagnosis={report.suspected_root_cause}; confidence="
            f"{report.confidence_category.value} ({report.confidence:.2f}); "
            f"affected={', '.join(report.affected_devices) or 'none'}; "
            f"limitations={'; '.join(report.limitations) or 'none'}; warnings={warning_text}",
        )

    def _dispatch_task_requests(
        self,
        proposal: Any,
        dossier: IncidentDossier,
        incident_id: str,
        observations: list[CanonicalObservation],
    ) -> int:
        """Dispatch only the supervisor's bounded, capability-routed read-only tasks."""
        dispatched = 0
        known_observations = {observation.observation_id: observation for observation in observations}
        indexed_requests = [
            (self._task_value(request, list(known_observations.values())), index, request)
            for index, request in enumerate(proposal.requested_tasks)
        ]
        indexed_requests.sort(key=lambda item: item[0], reverse=True)
        for rank, (selection_score, original_index, task_request) in enumerate(indexed_requests, start=1):
            if self.tasks_dispatched >= self.budget.max_tasks:
                break
            assignee = task_request.get("assignee")
            capability = task_request.get("capability")
            objective = task_request.get("objective", {})
            if not assignee or not capability or not isinstance(objective, dict):
                dossier.task_history.append({
                    "capability": capability,
                    "status": "REJECTED",
                    "warnings": ["Malformed task request; assignee, capability, and object are required."],
                    "limitations": [],
                })
                continue
            objective = dict(objective)
            objective.setdefault("estimated_cost", 1.0)
            objective.setdefault("expected_information_gain", 0.5)
            objective["selection_rank"] = rank
            objective["selection_score"] = selection_score
            targets = objective.get("target_entities", [])
            relevant_observations = [
                observation for observation in known_observations.values()
                if not targets or observation.entity_id in targets
                or any(observation.entity_id.startswith(f"{target}:") for target in targets)
            ]
            required_signals = objective.get("required_signals", [])
            if (
                objective.get("evidence_mode") == "stored_observations_only"
                and required_signals
                and not self._has_required_signal(required_signals, relevant_observations)
            ):
                dossier.task_history.append({
                    "assignee": str(assignee), "capability": capability,
                    "status": "SIGNAL_UNAVAILABLE", "objective": objective,
                    "result": {
                        "summary": "Required signal is absent from the stored incident observations; no probe or source connector is configured.",
                        "unavailable_signals": required_signals,
                    },
                    "warnings": ["This capability can inspect stored observations only; it did not run a live network probe."],
                    "limitations": ["No configured read-only source can collect the required signal."],
                    "new_evidence_refs": [],
                })
                self._explain(
                    "task selection",
                    f"Skipped {assignee} / {capability}: required signal unavailable in stored evidence; "
                    "no live connector exists, so asking the operator is more useful than re-analysis.",
                )
                continue
            self._explain(
                "task selection",
                f"Selected rank {rank} (candidate {original_index + 1}) {assignee} / {capability}; "
                f"heuristic information-value/cost={objective['selection_score']:.2f}; "
                f"discriminator={objective.get('discriminating_measurement') or objective.get('question', 'unspecified')}.",
            )
            relevant_ids = tuple(sorted(
                observation.observation_id for observation in relevant_observations
            ))
            fingerprint = (
                str(assignee).casefold(),
                str(capability),
                str(objective.get("hypothesis_code", "")),
                tuple(sorted(str(entity) for entity in targets)),
                relevant_ids,
            )
            if fingerprint in self._task_fingerprints:
                dossier.task_history.append({
                    "capability": capability,
                    "assignee": str(assignee),
                    "status": "SKIPPED_DUPLICATE",
                    "warnings": ["Repeated task request skipped; no new evidence would be added."],
                    "limitations": [],
                })
                continue
            try:
                evidence_before_task = set(known_observations)
                task = self.fabric.create_task(
                    requester="supervisor",
                    assignee=assignee,
                    capability=capability,
                    objective=objective,
                    incident_id=incident_id,
                )
                result = self.fabric.dispatch_task(task.task_id)
                self._task_fingerprints.add(fingerprint)
                if self.repo is not None:
                    known_observations.update({
                        observation.observation_id: observation
                        for observation in self.repo.get_observations(incident_id)
                    })
            except (ValueError, KeyError, PermissionError) as exc:
                dossier.task_history.append({
                    "capability": capability,
                    "assignee": str(assignee),
                    "status": "REJECTED",
                    "warnings": [f"Task request rejected: {exc}"],
                    "limitations": [],
                })
                self._explain("handoff", f"Task rejected for {assignee} / {capability}: {exc}")
                continue

            self.tasks_dispatched += 1
            dispatched += 1
            history_entry: dict[str, Any] = {
                "task_id": task.task_id,
                "assignee": task.assignee.value,
                "capability": task.capability,
                "status": result.status.value,
                "result_schema": result.result_schema,
                "result": result.result,
                "finding_refs": result.finding_refs,
                "evidence_refs": result.evidence_refs,
                "warnings": result.warnings,
                "limitations": result.limitations,
                "objective": objective,
                "selection_score": objective["selection_score"],
            }
            new_evidence_refs = sorted(set(result.evidence_refs) - evidence_before_task)
            history_entry["new_evidence_refs"] = new_evidence_refs
            if result.result_schema != task.expected_result_schema:
                history_entry["warnings"].append(
                    f"Result schema mismatch: expected {task.expected_result_schema}, got {result.result_schema}."
                )
            elif result.status.value == "COMPLETED" and result.result:
                self._merge_task_artifact(
                    dossier, result.result, history_entry,
                    result.finding_refs, result.evidence_refs, known_observations,
                )
            review_summaries = [
                review.get("summary", "")
                for review in history_entry.get("hypothesis_reviews", [])
                if isinstance(review, dict)
            ]
            temporal_summaries = [
                summary
                for review in history_entry.get("hypothesis_reviews", [])
                if isinstance(review, dict)
                for summary in review.get("temporal_summaries", [])
                if isinstance(summary, dict)
            ]
            temporal_preview = "; ".join(
                f"{summary.get('entity_id')}.{summary.get('signal')}: "
                f"{summary.get('time_point_count')} time point(s), {summary.get('source_count')} source(s), "
                f"range={summary.get('min_value')}..{summary.get('max_value')}, "
                f"conflict_times={summary.get('conflicting_time_points')}"
                for summary in temporal_summaries[:6]
            ) or "none"
            for review in history_entry.get("hypothesis_reviews", []):
                review["new_evidence_refs"] = sorted(
                    set(review.get("inspected_evidence_refs", [])) & set(new_evidence_refs)
                )
            evidence_context = history_entry.get("result", {}).get("evidence_context", [])
            unavailable_signals = history_entry.get("result", {}).get("unavailable_signals", [])
            provenance_preview = "; ".join(
                f"{item.get('observation_id')} {item.get('entity_id')}.{item.get('signal')}="
                f"{item.get('value')} [{item.get('source')} @ {item.get('observed_at')}]"
                for item in evidence_context[:5]
                if isinstance(item, dict)
            ) or "none"
            if len(evidence_context) > 5:
                provenance_preview += f"; +{len(evidence_context) - 5} item(s) omitted"
            self._explain(
                "handoff",
                f"supervisor -> {assignee} / {capability}; status={result.status.value}; "
                f"evidence={', '.join(result.evidence_refs) or 'none'}; "
                f"review={'; '.join(review_summaries) or 'no structured hypothesis review'}; "
                f"temporal={temporal_preview}; "
                f"new_evidence={len(history_entry['new_evidence_refs'])}; "
                f"provenance={len(evidence_context)} item(s); "
                f"sample={provenance_preview}; "
                f"unavailable={'; '.join(unavailable_signals) or 'none'}; "
                f"warnings={'; '.join(result.warnings) or 'none'}",
            )
            dossier.task_history.append(history_entry)
        return dispatched

    @staticmethod
    def _task_value(
        task_request: dict[str, Any], observations: list[CanonicalObservation] | None = None
    ) -> float:
        """Rank task candidates by a declared heuristic value-per-cost (not formal entropy)."""
        objective = task_request.get("objective", {})
        try:
            information_gain = max(0.0, min(1.0, float(objective.get("expected_information_gain", 0.5))))
            required_signals = set(objective.get("required_signals", []))
            targets = objective.get("target_entities", [])
            if observations and required_signals:
                scoped = [
                    observation for observation in observations
                    if (not targets or observation.entity_id in targets
                        or any(observation.entity_id.startswith(f"{target}:") for target in targets))
                ]
                represented = {
                    signal for signal in required_signals
                    if SupervisorRuntime._has_required_signal([signal], scoped)
                }
                relevant = [
                    observation for observation in scoped
                    if SupervisorRuntime._observation_matches_signal(observation, required_signals)
                ]
                coverage = len(represented) / len(required_signals)
                temporal = min(1.0, len({item.timestamp for item in relevant}) / 3.0)
                source_diversity = min(1.0, len({item.source for item in relevant}) / 2.0)
                information_gain = min(
                    1.0,
                    coverage * 0.5 + temporal * 0.25 + source_diversity * 0.25,
                )
                by_time_metric: dict[tuple[str, str, datetime], set[float]] = {}
                for item in relevant:
                    by_time_metric.setdefault((item.entity_id, item.metric_name, item.timestamp), set()).add(item.value)
                if any(len(values) > 1 for values in by_time_metric.values()):
                    information_gain = min(1.0, information_gain + 0.15)
            decision_impact = max(0.0, min(1.0, float(objective.get("decision_impact", 1.0))))
            estimated_cost = max(0.01, float(objective.get("estimated_cost", 1.0)))
        except (TypeError, ValueError):
            return 0.0
        return information_gain * decision_impact / estimated_cost

    @staticmethod
    def _has_required_signal(required_signals: list[str], observations: list[CanonicalObservation]) -> bool:
        return any(
            SupervisorRuntime._observation_matches_signal(observation, required_signals)
            for observation in observations
        )

    @staticmethod
    def _observation_matches_signal(
        observation: CanonicalObservation, required_signals: list[str] | set[str]
    ) -> bool:
        normalized = {str(signal).casefold() for signal in required_signals}
        if isinstance(observation, MetricObservation):
            return observation.metric_name.casefold() in normalized
        if isinstance(observation, ConfigObservation):
            return (
                "config_current_value" in normalized and bool(observation.config_value)
            ) or (
                "config_baseline" in normalized and observation.previous_value is not None
            )
        if isinstance(observation, LogObservation):
            message = observation.message.casefold()
            if "dns_response_code" in normalized:
                dns_markers = ("dns", "servfail", "nxdomain", "refused", "resolver")
                if any(marker in message for marker in dns_markers):
                    return True
            if "dhcp_lease_events" in normalized:
                dhcp_markers = ("dhcp", "lease", "scope", "pool", "nak", "discover", "offer")
                if any(marker in message for marker in dhcp_markers):
                    return True
            return "service_error_logs" in normalized and any(
                marker in message for marker in ("dns", "dhcp", "resolver", "lease", "pool")
            )
        # Topology proves configured relationships, not live route or data-plane state.
        return False

    @staticmethod
    def _abstain_for_budget(
        proposal: Any,
        reason: str = "Investigation could not be completed within the configured orchestration budget.",
    ):
        return proposal.model_copy(update={
            "decision": ProposalDecision.ABSTAIN,
            "suspected_root_cause": None,
            "confidence_category": ConfidenceCategory.INSUFFICIENT,
            "recommended_actions": ["Collect the requested discriminating telemetry and rerun diagnosis."],
            "abstain_reason": reason,
            "requested_tasks": [],
        })

    @staticmethod
    def _abstention_manifest(proposal: Any, incident_id: str) -> ClaimEvidenceManifest:
        return ClaimEvidenceManifest(
            incident_id=incident_id,
            claim=f"Abstained: {proposal.abstain_reason or 'insufficient evidence'}",
            claimed_entities=proposal.affected_entities,
            finding_ids=[],
            observation_ids=[],
            independence_groups=[],
            contradiction_ids=proposal.alternative_causes,
            contradiction_disclosures=[],
        )

    def _add_path_triage(
        self, report: FinalReport, incident_id: str, observations: list[CanonicalObservation]
    ) -> FinalReport:
        """Attach topology context after gate publication without revising its claims."""
        try:
            triage, interactions, warnings = build_path_triage(
                report, incident_id, observations, self.fabric
            )
            return report.model_copy(update={
                "path_triage": triage,
                "peer_interactions": [*report.peer_interactions, *interactions],
                "orchestration_warnings": [*report.orchestration_warnings, *warnings],
            })
        except Exception as exc:  # The supplemental path view must never block diagnosis.
            triage = PathTriage(
                status="unavailable",
                limitations=[f"Supplementary path triage failed safely: {exc}"],
            )
            return report.model_copy(update={"path_triage": triage})

    def _build_dossier(
        self,
        incident_id: str,
        symptom: str,
        time_window: dict[str, Any] | None,
        tower_reports: dict[TowerId, TowerReport],
        observations: list[CanonicalObservation],
        data_quality_warnings: list[str] | None = None,
    ) -> IncidentDossier:
        """Constructs a compact structured dossier minimizing context for RCA."""
        all_findings = []
        all_hypotheses = []
        affected_entities = set()

        for report in tower_reports.values():
            all_findings.extend(report.findings)
            all_hypotheses.extend(report.hypotheses)
            for f in report.findings:
                affected_entities.update(f.entity_refs)
            for h in report.hypotheses:
                affected_entities.update(h.suspected_entities)

        # Collect available capabilities from registry
        available_caps = list(self.fabric.registry._capabilities.keys())

        return IncidentDossier(
            incident_id=incident_id,
            symptom=symptom,
            time_window=time_window,
            affected_entities=sorted(list(affected_entities)),
            tower_reports=tower_reports,
            findings=all_findings,
            hypotheses=all_hypotheses,
            topology_summary={
                "relationships": [
                    {
                        "source": obs.source_entity,
                        "target": obs.target_entity,
                        "type": obs.relationship_type,
                        "interface": obs.interface_name,
                    }
                    for obs in observations if isinstance(obs, TopologyObservation)
                ]
            },
            conflicts=[],
            investigation_round=1,
            task_history=[],
            peer_query_history=[],
            available_capabilities=available_caps,
            data_quality_warnings=data_quality_warnings or [],
        )

    def _run_service_reachability_queries(
        self, dossier: IncidentDossier, observations: list[CanonicalObservation]
    ) -> None:
        dependency_faults = {"dns": "DNS_FAILURE", "dhcp": "DHCP_FAILURE"}
        fault_codes = {hyp.fault_code for hyp in dossier.hypotheses}
        dependencies = sorted({
            (obs.relationship_type.casefold(), obs.source_entity, obs.target_entity)
            for obs in observations
            if isinstance(obs, TopologyObservation)
            and obs.relationship_type.casefold() in dependency_faults
            and dependency_faults[obs.relationship_type.casefold()] in fault_codes
        })
        max_queries = 8
        for dependency_type, consumer, provider in dependencies[:max_queries]:
            query = PeerQuery(
                query_id=generate_id("QRY"),
                incident_id=dossier.incident_id,
                requester="services",
                recipient="connectivity",
                capability="connectivity.trace_path",
                scope=[consumer, provider],
                expected_schema="netcoop://schemas/capabilities/connectivity-trace-path-output/1.0",
                created_at=datetime.now(timezone.utc),
            )
            result = self.fabric.query_peer(query)
            self._explain("handoff", f"{query.requester} -> {query.recipient} / {query.capability} scope={', '.join(query.scope)}; status={result.status.value}; result={result.result}; evidence={', '.join(result.evidence_refs) or 'none'}")
            dossier.peer_query_history.append({
                "query_id": query.query_id,
                "requester": query.requester,
                "recipient": query.recipient,
                "capability": query.capability,
                "scope": query.scope,
                "status": result.status.value,
                "result": result.result,
                "evidence_refs": result.evidence_refs,
                "warnings": result.warnings,
            })
        if len(dependencies) > max_queries:
            dossier.peer_query_history.append({
                "requester": "services",
                "recipient": "connectivity",
                "capability": "connectivity.trace_path",
                "status": "skipped",
                "scope": [],
                "result": None,
                "evidence_refs": [],
                "warnings": [
                    f"Reached the limit of {max_queries} service reachability queries; "
                    f"{len(dependencies) - max_queries} declared dependencies were not queried."
                ],
            })

    def _explain(self, stage: str, message: str) -> None:
        """Emit a live, user-facing workflow event when explain mode is enabled."""
        if self.explain is not None:
            self.explain(stage, message)

    @staticmethod
    def _merge_task_artifact(
        dossier: IncidentDossier,
        artifact: dict[str, Any],
        history_entry: dict[str, Any],
        declared_finding_refs: list[str],
        declared_evidence_refs: list[str],
        known_observations: dict[str, CanonicalObservation],
    ) -> None:
        """Validate specialist findings before adding them to supervisor context."""
        try:
            artifact = DiagnosticTaskArtifact.model_validate(artifact).model_dump()
            parsed_findings = [Finding.model_validate(raw) for raw in artifact.get("findings", [])]
            parsed_hypotheses = [Hypothesis.model_validate(raw) for raw in artifact.get("hypotheses", [])]
            actual_finding_refs = {finding.finding_id for finding in parsed_findings}
            finding_evidence_refs = {
                ref for finding in parsed_findings for ref in finding.evidence_refs
            }
            actual_evidence_refs = set(artifact.get("evidence_refs", []))
            if actual_finding_refs != set(declared_finding_refs) or actual_finding_refs != set(artifact.get("finding_refs", [])):
                raise ValueError("Task finding references do not match the returned finding artifacts.")
            if actual_evidence_refs != set(declared_evidence_refs):
                raise ValueError("Task evidence references do not match the TaskResult envelope.")
            unknown_observations = (actual_evidence_refs | finding_evidence_refs) - set(known_observations)
            if unknown_observations:
                raise ValueError(f"Task findings cite unknown observations: {sorted(unknown_observations)}")
            context_by_id = {
                item["observation_id"]: item for item in artifact.get("evidence_context", [])
            }
            if set(context_by_id) != actual_evidence_refs:
                raise ValueError("Task evidence context must describe every and only cited observation.")
            for observation_id, context in context_by_id.items():
                observation = known_observations[observation_id]
                expected_signal = getattr(observation, "metric_name", observation.observation_type)
                expected_value = getattr(observation, "value", None)
                if expected_value is None:
                    expected_value = getattr(observation, "message", None)
                if isinstance(observation, LogObservation):
                    expected_value = {
                        "level": observation.log_level,
                        "message": observation.message,
                        "facility": observation.facility,
                    }
                elif isinstance(observation, ConfigObservation):
                    expected_value = {
                        "key": observation.config_key,
                        "current": observation.config_value,
                        "previous": observation.previous_value,
                    }
                elif isinstance(observation, TopologyObservation):
                    expected_value = {
                        "source_entity": observation.source_entity,
                        "target_entity": observation.target_entity,
                        "relationship_type": observation.relationship_type,
                        "interface_name": observation.interface_name,
                        "link_speed_mbps": observation.link_speed_mbps,
                    }
                if (
                    context["observed_at"] != observation.timestamp
                    or context["source"] != observation.source
                    or context["entity_id"] != observation.entity_id
                    or context["signal"] != expected_signal
                    or context.get("value") != expected_value
                ):
                    raise ValueError(f"Task evidence provenance does not match observation '{observation_id}'.")
            review_refs = {
                ref
                for review in artifact.get("hypothesis_reviews", [])
                for ref in (
                    review.get("supporting_evidence_refs", [])
                    + review.get("contradicting_evidence_refs", [])
                    + review.get("inspected_evidence_refs", [])
                )
            }
            if not review_refs.issubset(actual_evidence_refs):
                raise ValueError("Hypothesis review references are missing from the task evidence envelope.")
            history_entry["hypothesis_reviews"] = artifact.get("hypothesis_reviews", [])

            existing_finding_ids = {finding.finding_id for finding in dossier.findings}
            task_finding_ids = actual_finding_refs | existing_finding_ids
            for finding in parsed_findings:
                if finding.incident_id != dossier.incident_id:
                    raise ValueError(f"Finding {finding.finding_id} belongs to another incident.")
            for hypothesis in parsed_hypotheses:
                if hypothesis.incident_id != dossier.incident_id:
                    raise ValueError(f"Hypothesis {hypothesis.hypothesis_id} belongs to another incident.")
                missing_findings = set(hypothesis.supporting_finding_refs) - task_finding_ids
                if missing_findings:
                    raise ValueError(f"Hypothesis {hypothesis.hypothesis_id} cites unknown findings: {sorted(missing_findings)}")
        except Exception as exc:
            history_entry["warnings"].append(f"Task artifact validation failed: {exc}")
            return

        finding_by_key = {
            (finding.source_tower, finding.finding_type, tuple(finding.entity_refs)): finding
            for finding in dossier.findings
        }
        finding_ids = {finding.finding_id for finding in dossier.findings}
        finding_id_remap: dict[str, str] = {}
        accepted_findings = 0
        for finding in parsed_findings:
            key = (finding.source_tower, finding.finding_type, tuple(finding.entity_refs))
            existing = finding_by_key.get(key)
            if existing is not None:
                finding_id_remap[finding.finding_id] = existing.finding_id
            elif finding.finding_id not in finding_ids:
                dossier.findings.append(finding)
                finding_by_key[key] = finding
                finding_ids.add(finding.finding_id)
                finding_id_remap[finding.finding_id] = finding.finding_id
                accepted_findings += 1

        hypothesis_by_key = {
            (hypothesis.fault_code, tuple(hypothesis.suspected_entities)): hypothesis
            for hypothesis in dossier.hypotheses
        }
        hypothesis_ids = {hypothesis.hypothesis_id for hypothesis in dossier.hypotheses}
        accepted_hypotheses = 0
        for hypothesis in parsed_hypotheses:
            key = (hypothesis.fault_code, tuple(hypothesis.suspected_entities))
            if key in hypothesis_by_key or hypothesis.hypothesis_id in hypothesis_ids:
                continue
            mapped_refs = [finding_id_remap.get(ref, ref) for ref in hypothesis.supporting_finding_refs]
            if not set(mapped_refs).issubset(finding_ids):
                history_entry["warnings"].append(
                    f"Task hypothesis {hypothesis.hypothesis_id} was omitted because its finding references were not merged."
                )
                continue
            hypothesis = hypothesis.model_copy(update={"supporting_finding_refs": mapped_refs})
            dossier.hypotheses.append(hypothesis)
            hypothesis_by_key[key] = hypothesis
            hypothesis_ids.add(hypothesis.hypothesis_id)
            accepted_hypotheses += 1
        history_entry["accepted_findings"] = accepted_findings
        history_entry["accepted_hypotheses"] = accepted_hypotheses
