"""Base protocols and interfaces for diagnostic tower controllers."""

from typing import Protocol, runtime_checkable

from netcoop.communication.queries import PeerQuery, PeerQueryResult
from netcoop.communication.registry import TowerCapability
from netcoop.communication.tasks import InvestigationTask, TaskResult
from netcoop.models.enums import TowerId
from netcoop.models.observations import CanonicalObservation
from netcoop.models.reports import TowerReport


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
