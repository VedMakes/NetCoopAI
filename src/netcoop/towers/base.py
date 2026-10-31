"""Base protocols and interfaces for diagnostic tower controllers."""

from typing import Any, Protocol, runtime_checkable

from netcoop.communication.queries import PeerQuery, PeerQueryResult
from netcoop.communication.registry import TowerCapability
from netcoop.communication.tasks import InvestigationTask, TaskResult
from netcoop.models.enums import TowerId
from netcoop.models.observations import CanonicalObservation
from netcoop.models.reports import TowerReport


def investigate_with_engine(
    engine: Any, repository: Any, task: InvestigationTask
) -> tuple[dict[str, Any], list[str], list[str], list[str]]:
    """Run a task against persisted incident observations and return a typed artifact payload."""
    if repository is None:
        return {
            "incident_id": task.incident_id,
            "capability": task.capability,
            "target_entities": task.objective.get("target_entities", []),
            "findings": [], "hypotheses": [], "finding_refs": [], "evidence_refs": [], "observation_count": 0,
            "summary": "No incident repository is configured.",
        }, [], [], ["Task could not inspect telemetry without a repository."]

    observations = repository.get_observations(task.incident_id)
    targets = (
        task.objective.get("target_entities")
        or task.objective.get("scope")
        or task.constraints.get("scope")
        or []
    )
    if targets:
        target_set = set(targets)
        observations = [
            obs for obs in observations
            if obs.entity_id in target_set
            or any(obs.entity_id.startswith(f"{target}:") for target in target_set)
            or (getattr(obs, "source_entity", None) in target_set)
            or (getattr(obs, "target_entity", None) in target_set)
        ]
    if not observations:
        return {
            "incident_id": task.incident_id,
            "capability": task.capability,
            "target_entities": targets,
            "findings": [], "hypotheses": [], "finding_refs": [], "evidence_refs": [], "observation_count": 0,
            "summary": "No telemetry matched the task scope.",
        }, [], [], ["No telemetry matched the task scope."]

    findings, hypotheses = engine.analyze(task.incident_id, observations)
    if targets:
        target_set = set(targets)
        findings = [f for f in findings if any(
            ent in target_set or any(ent.startswith(f"{target}:") for target in target_set)
            for ent in f.entity_refs
        )]
        hypotheses = [h for h in hypotheses if any(
            ent in target_set or any(ent.startswith(f"{target}:") for target in target_set)
            for ent in h.suspected_entities
        )]
    finding_refs = [f.finding_id for f in findings]
    evidence_refs = list(dict.fromkeys(ref for finding in findings for ref in finding.evidence_refs))
    result = {
        "incident_id": task.incident_id,
        "capability": task.capability,
        "target_entities": targets,
        "findings": [f.model_dump(mode="json") for f in findings],
        "hypotheses": [h.model_dump(mode="json") for h in hypotheses],
        "finding_refs": finding_refs,
        "evidence_refs": evidence_refs,
        "observation_count": len(observations),
        "summary": f"{len(findings)} finding(s) and {len(hypotheses)} hypothesis(es) returned for {len(observations)} scoped observations.",
    }
    return result, finding_refs, evidence_refs, []


@runtime_checkable
class TowerController(Protocol):
    """Protocol implemented by each of the four diagnostic tower controllers."""

    @property
    def tower_id(self) -> TowerId:
        ...

    @property
    def capabilities(self) -> list[TowerCapability]:
        ...

    def handle_query(self, query: PeerQuery) -> PeerQueryResult:
        """Executes a bounded, synchronous, read-only peer query."""
        ...

    def execute_task(self, task: InvestigationTask) -> TaskResult:
        """Executes a persistent, supervisor-authorized investigation task."""
        ...

    def analyze_incident(
        self, incident_id: str, observations: list[CanonicalObservation] | None = None
    ) -> TowerReport:
        """Runs the deterministic diagnostic engines on the incident scope and emits a TowerReport."""
        ...
