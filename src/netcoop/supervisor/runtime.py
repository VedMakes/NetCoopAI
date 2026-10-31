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
from netcoop.models.observations import TopologyObservation
from netcoop.models.reports import ClaimEvidenceManifest, FinalReport, PathTriage, TowerReport
from netcoop.supervisor.agent import SupervisoryRCAAgent
from netcoop.supervisor.gate import EvidenceReleaseGate
from netcoop.supervisor.models import (
    GateOutcome,
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
    ) -> None:
        self.repo = repository
        self.fabric = fabric or IntegrationFabric(repository=self.repo)
        self.gate = gate or EvidenceReleaseGate(repository=self.repo)
        self.rca_agent = rca_agent or SupervisoryRCAAgent()
        self.budget = budget or InvestigationBudget()
        self.network_profile = network_profile

        # Operational state
        self.state = IncidentLifecycleState.CREATED
        self.supervisor_calls: int = 0
        self.investigation_rounds: int = 0
        self.tasks_dispatched: int = 0

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
        tower_reports: dict[TowerId, TowerReport] = self.fabric.run_all_towers(
            incident_id=incident_id, observations=observations
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

        # Step 5: Handle investigation requests if budget allows
        if proposal.decision == ProposalDecision.REQUEST_EVIDENCE:
            if (
                self.supervisor_calls < self.budget.max_supervisor_calls
                and
                self.investigation_rounds < self.budget.max_investigation_rounds
                and self.tasks_dispatched < self.budget.max_tasks
            ):
                self.state = IncidentLifecycleState.INVESTIGATING
                self.investigation_rounds += 1

                for task_req in proposal.requested_tasks:
                    if self.tasks_dispatched >= self.budget.max_tasks:
                        break

                    assignee = task_req.get("assignee")
                    capability = task_req.get("capability")
                    objective = task_req.get("objective", {})

                    if assignee and capability:
                        task = self.fabric.create_task(
                            requester="supervisor",
                            assignee=assignee,
                            capability=capability,
                            objective=objective,
                            incident_id=incident_id,
                        )
                        task_res = self.fabric.dispatch_task(task.task_id)
                        self.tasks_dispatched += 1

                        history_entry: dict[str, Any] = {
                            "task_id": task.task_id,
                            "assignee": task.assignee.value,
                            "capability": task.capability,
                            "status": task_res.status.value,
                            "result_schema": task_res.result_schema,
                            "result": task_res.result,
                            "finding_refs": task_res.finding_refs,
                            "evidence_refs": task_res.evidence_refs,
                            "warnings": task_res.warnings,
                            "limitations": task_res.limitations,
                        }
                        if task_res.result_schema != task.expected_result_schema:
                            history_entry["warnings"].append(
                                f"Result schema mismatch: expected {task.expected_result_schema}, got {task_res.result_schema}."
                            )
                        elif task_res.status.value == "COMPLETED" and task_res.result:
                            self._merge_task_artifact(
                                dossier,
                                task_res.result,
                                history_entry,
                                task_res.finding_refs,
                                task_res.evidence_refs,
                                {obs.observation_id for obs in observations},
                            )
                        dossier.task_history.append(history_entry)

                # Re-diagnose with updated task history in round 2
                dossier.investigation_round += 1
                self.state = IncidentLifecycleState.SUPERVISOR_REASONING
                proposal, manifest = self.rca_agent.diagnose(dossier)
                self.supervisor_calls += 1
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

        gate_result = self.gate.evaluate(
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
            return report

        if not gate_result.passed or gate_result.certified_final_report is None:
            self.state = IncidentLifecycleState.FAILED
            raise EvidenceGateRejectionError(
                f"EvidenceReleaseGate rejected proposed diagnosis with {len(gate_result.errors)} errors: "
                + "; ".join(gate_result.errors),
                errors=gate_result.errors,
            )

        # Publication verified
        self.state = IncidentLifecycleState.PUBLISHED
        final_report = gate_result.certified_final_report
        final_report = self._add_path_triage(final_report, incident_id, observations)

        if self.repo is not None:
            self.repo.insert_final_report(final_report)

        return final_report

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

    @staticmethod
    def _merge_task_artifact(
        dossier: IncidentDossier,
        artifact: dict[str, Any],
        history_entry: dict[str, Any],
        declared_finding_refs: list[str],
        declared_evidence_refs: list[str],
        known_observation_ids: set[str],
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
            unknown_observations = (actual_evidence_refs | finding_evidence_refs) - known_observation_ids
            if unknown_observations:
                raise ValueError(f"Task findings cite unknown observations: {sorted(unknown_observations)}")

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
