"""SupervisorRuntime orchestrating incident state, task authorization, and report release.

Deterministic controller managing the lifecycle of an incident from intake through
tower execution, RCA reasoning, task budgeting, and evidence gate verification.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from netcoop.communication.fabric import IntegrationFabric
from netcoop.models.enums import ProposalDecision, TowerId
from netcoop.models.reports import FinalReport, TowerReport
from netcoop.supervisor.agent import SupervisoryRCAAgent
from netcoop.supervisor.gate import EvidenceReleaseGate
from netcoop.supervisor.models import (
    GateOutcome,
    IncidentDossier,
    IncidentLifecycleState,
    InvestigationBudget,
)

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
    ) -> None:
        self.repo = repository
        self.fabric = fabric or IntegrationFabric(repository=self.repo)
        self.gate = gate or EvidenceReleaseGate(repository=self.repo)
        self.rca_agent = rca_agent or SupervisoryRCAAgent()
        self.budget = budget or InvestigationBudget()

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
        )

        # Step 4: Supervisory reasoning loop
        self.state = IncidentLifecycleState.SUPERVISOR_REASONING
        proposal, manifest = self.rca_agent.diagnose(dossier)
        self.supervisor_calls += 1

        # Step 5: Handle investigation requests if budget allows
        if proposal.decision == ProposalDecision.REQUEST_EVIDENCE:
            if (
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

                        dossier.task_history.append(
                            {
                                "task_id": task.task_id,
                                "assignee": task.assignee,
                                "capability": task.capability,
                                "status": task_res.status.value,
                                "result": task_res.result,
                            }
                        )

                # Re-diagnose with updated task history in round 2
                dossier.investigation_round += 1
                self.state = IncidentLifecycleState.SUPERVISOR_REASONING
                proposal, manifest = self.rca_agent.diagnose(dossier)
                self.supervisor_calls += 1

        # Step 6: Evidence and Release Gate verification
        self.state = IncidentLifecycleState.PROPOSED
        self.state = IncidentLifecycleState.GATE_EVALUATING

        # Extract competing hypotheses across towers
        competing_hypotheses = [
            f"{h.fault_code}: {h.suspected_entities}"
            for h in dossier.hypotheses
        ]

        gate_result = self.gate.evaluate(
            proposal=proposal,
            manifest=manifest,
            incident_id=incident_id,
            known_observations=observations,
            known_findings=dossier.findings,
            competing_hypotheses=competing_hypotheses,
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

        if self.repo is not None:
            self.repo.insert_final_report(final_report)

        return final_report

    def _build_dossier(
        self,
        incident_id: str,
        symptom: str,
        time_window: dict[str, Any] | None,
        tower_reports: dict[TowerId, TowerReport],
        observations: list[CanonicalObservation],
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
            topology_summary={},
            conflicts=[],
            investigation_round=1,
            task_history=[],
            available_capabilities=available_caps,
            data_quality_warnings=[],
        )
