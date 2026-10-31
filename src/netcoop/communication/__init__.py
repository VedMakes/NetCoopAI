"""Communication infrastructure models and registry for NetCoop AI."""

from netcoop.communication.events import EventEnvelope
from netcoop.communication.queries import PeerQuery, PeerQueryResult
from netcoop.communication.registry import CapabilityRegistry, TowerCapability, TowerProfile
from netcoop.communication.tasks import (
    InvalidTaskTransitionError,
    InvestigationTask,
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
    "EventEnvelope",
    "InvestigationTask",
    "InvalidTaskTransitionError",
    "PeerQuery",
    "PeerQueryResult",
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
