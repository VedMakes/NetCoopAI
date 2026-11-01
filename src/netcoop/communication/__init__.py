"""Communication infrastructure models, event fabric, and registry for NetCoop AI."""

from netcoop.communication.events import (
    DeliverySummary,
    DispatchSummary,
    EventBus,
    EventEnvelope,
    EventHandler,
)
from netcoop.communication.fabric import IntegrationFabric
from netcoop.communication.queries import (
    PeerQuery,
    PeerQueryResult,
    QueryHandler,
    QueryRouter,
)
from netcoop.communication.registry import CapabilityRegistry, TowerCapability, TowerProfile
from netcoop.communication.tasks import (
    InvalidTaskTransitionError,
    InvestigationTask,
    TaskDispatcher,
    TaskHandler,
    TaskResult,
    validate_task_transition,
)
from netcoop.communication.vocabulary import (
    VocabularyError,
    load_vocabulary,
    validate_fault_code,
    validate_finding_type,
    validate_metric_and_unit,
)

__all__ = [
    "CapabilityRegistry",
    "DeliverySummary",
    "DispatchSummary",
    "EventBus",
    "EventEnvelope",
    "EventHandler",
    "IntegrationFabric",
    "InvalidTaskTransitionError",
    "InvestigationTask",
    "PeerQuery",
    "PeerQueryResult",
    "QueryHandler",
    "QueryRouter",
    "TaskDispatcher",
    "TaskHandler",
    "TaskResult",
    "TowerCapability",
    "TowerProfile",
    "VocabularyError",
    "load_vocabulary",
    "validate_fault_code",
    "validate_finding_type",
    "validate_metric_and_unit",
    "validate_task_transition",
]
