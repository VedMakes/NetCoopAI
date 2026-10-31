"""Integration Fabric for NetCoop AI.

Coordinates the typed in-process EventBus, QueryRouter, TaskDispatcher,
and all four diagnostic TowerControllers with transactional persistence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from netcoop.communication.events import EventBus, EventEnvelope
from netcoop.communication.queries import PeerQuery, PeerQueryResult, QueryRouter
from netcoop.communication.registry import CapabilityRegistry
from netcoop.communication.tasks import (
    DIAGNOSTIC_TASK_ARTIFACT_SCHEMA,
    InvestigationTask,
    TaskDispatcher,
    TaskResult,
)
from netcoop.models.enums import TowerId
from netcoop.utils.id_generator import generate_id

if TYPE_CHECKING:
    from netcoop.models.observations import CanonicalObservation
    from netcoop.models.reports import TowerReport
    from netcoop.storage.sqlite import SQLiteRepository
    from netcoop.towers.base import TowerController


class IntegrationFabric:
    """Integration fabric wiring EventBus, QueryRouter, TaskDispatcher, and all four towers."""

    def __init__(
        self,
        repository: SQLiteRepository | None = None,
        registry: CapabilityRegistry | None = None,
        rules: dict[str, Any] | None = None,
    ) -> None:
        from netcoop.towers.connectivity import ConnectivityTower
        from netcoop.towers.infrastructure import InfrastructureTower
        from netcoop.towers.performance import PerformanceTower
        from netcoop.towers.services import ServicesTower

        self.repo = repository
        self.registry = registry or CapabilityRegistry.load()
        self.rules = rules

        # 1. Initialize core communication primitives
        self.event_bus = EventBus(repository=self.repo)
        self.query_router = QueryRouter(registry=self.registry, repository=self.repo)
        self.task_dispatcher = TaskDispatcher(
            repository=self.repo,
            event_bus=self.event_bus,
            registry=self.registry,
        )

        # 2. Initialize the four TowerControllers
        self.towers: dict[TowerId, TowerController] = {
            TowerId.PERFORMANCE: PerformanceTower(repository=self.repo, rules=self.rules),
            TowerId.INFRASTRUCTURE: InfrastructureTower(repository=self.repo, rules=self.rules),
            TowerId.CONNECTIVITY: ConnectivityTower(repository=self.repo, rules=self.rules),
            TowerId.SERVICES: ServicesTower(repository=self.repo, rules=self.rules),
        }

        # 3. Track cross-domain event notifications
        self.received_events: dict[str, list[EventEnvelope]] = {
            "performance": [],
            "infrastructure": [],
            "connectivity": [],
            "services": [],
        }

        # 4. Register handlers and subscriptions
        self._register_tower_capabilities()
        self._setup_event_subscriptions()

    def get_tower(self, tower_id: TowerId | str) -> TowerController:
        """Retrieves a TowerController instance by its enum or string identifier."""
        t_id = tower_id if isinstance(tower_id, TowerId) else TowerId(tower_id.lower())
        if t_id not in self.towers:
            raise KeyError(f"Tower '{t_id.value}' not found in IntegrationFabric.")
        return self.towers[t_id]

    def _register_tower_capabilities(self) -> None:
        """Registers query and task capabilities for each tower controller."""
        for tower_id, tower in self.towers.items():
            for cap in tower.capabilities:
                # Register query capability
                self.query_router.register(
                    tower_id=tower_id,
                    capability_id=cap.id,
                    handler=tower.handle_query,
                )
                # Register task capability
                self.task_dispatcher.register_handler(
                    tower_id=tower_id,
                    capability=cap.id,
                    handler=tower.execute_task,
                )

        # Register task aliases supported by towers
        task_aliases: dict[TowerId, list[str]] = {
            TowerId.PERFORMANCE: [
                "INVESTIGATE_CONGESTION",
                "ANALYZE_WIFI_QUALITY",
                "performance.inspect_upstream_capacity",
                "performance.challenge_congestion_hypothesis",
                "performance.challenge_wifi_hypothesis",
            ],
            TowerId.INFRASTRUCTURE: [
                "INVESTIGATE_DEVICE",
                "ANALYZE_INTERFACE",
                "infrastructure.challenge_device_overload_hypothesis",
                "infrastructure.challenge_interface_hypothesis",
            ],
            TowerId.CONNECTIVITY: [
                "INVESTIGATE_TOPOLOGY",
                "ANALYZE_REACHABILITY",
                "connectivity.inspect_common_upstream",
            ],
            TowerId.SERVICES: [
                "INVESTIGATE_DNS",
                "INVESTIGATE_DHCP",
                "ANALYZE_CONFIG_DRIFT",
                "services.compare_config_snapshots",
                "services.challenge_service_failure_hypothesis",
                "services.challenge_config_hypothesis",
            ],
        }

        for tower_id, aliases in task_aliases.items():
            tower = self.towers[tower_id]
            for alias in aliases:
                self.task_dispatcher.register_handler(
                    tower_id=tower_id,
                    capability=alias,
                    handler=tower.execute_task,
                )

    def _setup_event_subscriptions(self) -> None:
        """Configures cross-domain event subscriptions between towers and the system."""
        # Performance tower subscribes to infrastructure degradation and topology partitions
        self.event_bus.subscribe(
            event_type="infrastructure.interface_degradation",
            consumer_id="tower/performance",
            handler=lambda evt: self.received_events["performance"].append(evt),
        )
        self.event_bus.subscribe(
            event_type="connectivity.topology_partition",
            consumer_id="tower/performance",
            handler=lambda evt: self.received_events["performance"].append(evt),
        )

        # Connectivity tower subscribes to performance congestion
        self.event_bus.subscribe(
            event_type="performance.congestion_candidate",
            consumer_id="tower/connectivity",
            handler=lambda evt: self.received_events["connectivity"].append(evt),
        )

        # Services tower subscribes to connectivity partitions
        self.event_bus.subscribe(
            event_type="connectivity.topology_partition",
            consumer_id="tower/services",
            handler=lambda evt: self.received_events["services"].append(evt),
        )

        # Infrastructure tower subscribes to hardware errors
        self.event_bus.subscribe(
            event_type="infrastructure.device_overload",
            consumer_id="tower/infrastructure",
            handler=lambda evt: self.received_events["infrastructure"].append(evt),
        )

    def run_all_towers(
        self, incident_id: str, observations: list[CanonicalObservation] | None = None,
        on_tower_complete: Any | None = None,
    ) -> dict[TowerId, TowerReport]:
        """Runs diagnostic engines across all four towers on the specified incident context.

        Publishes findings notification events to the EventBus upon discovery.
        """
        reports: dict[TowerId, TowerReport] = {}

        for tower_id, tower in self.towers.items():
            report = tower.analyze_incident(incident_id, observations=observations)
            reports[tower_id] = report
            if on_tower_complete is not None:
                on_tower_complete(tower_id, report)

            if report.findings:
                evt = EventEnvelope(
                    id=generate_id("EVT-FINDINGS"),
                    source=f"netcoop/{tower_id.value}",
                    type=f"{tower_id.value}.findings_published",
                    subject=incident_id,
                    time=report.generated_at,
                    dataschema="netcoop://schemas/events/findings-published/1.0",
                    correlationid=incident_id,
                    causationid=report.report_id,
                    data={
                        "report_id": report.report_id,
                        "tower_id": tower_id.value,
                        "findings_count": len(report.findings),
                        "hypotheses_count": len(report.hypotheses),
                        "finding_ids": [f.finding_id for f in report.findings],
                    },
                )
                self.event_bus.publish(evt)

        return reports

    def query_peer(self, query: PeerQuery) -> PeerQueryResult:
        """Executes a bounded, synchronous, read-only peer query."""
        return self.query_router.request(query)

    def create_task(
        self,
        requester: str,
        assignee: TowerId | str,
        capability: str,
        objective: dict[str, Any],
        constraints: dict[str, Any] | None = None,
        deadline_at: Any | None = None,
        parent_task_id: str | None = None,
        incident_id: str = "INC-ACTIVE",
    ) -> InvestigationTask:
        """Creates a supervisor-authorized investigation task."""
        return self.task_dispatcher.create_task(
            requester=requester,
            assignee=assignee,
            capability=capability,
            objective=objective,
            constraints=constraints,
            deadline_at=deadline_at,
            parent_task_id=parent_task_id,
            expected_result_schema=DIAGNOSTIC_TASK_ARTIFACT_SCHEMA,
            incident_id=incident_id,
        )

    def dispatch_task(self, task_id: str) -> TaskResult:
        """Executes a persistent investigation task."""
        return self.task_dispatcher.execute(task_id)
