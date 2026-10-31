"""Supervisor subsystem for NetCoop AI.

Provides the deterministic SupervisorRuntime, SupervisoryRCAAgent, and independent EvidenceReleaseGate.
"""

from netcoop.supervisor.agent import (
    DeterministicRCAProvider,
    FakeLLMProvider,
    RCAProvider,
    SupervisoryRCAAgent,
    get_rca_provider,
)
from netcoop.supervisor.gate import EvidenceReleaseGate
from netcoop.supervisor.models import (
    ConflictItem,
    ConflictType,
    GateCheckResult,
    GateOutcome,
    GateResult,
    IncidentDossier,
    IncidentLifecycleState,
    InvestigationBudget,
)
from netcoop.supervisor.openrouter import OpenRouterProvider
from netcoop.supervisor.runtime import EvidenceGateRejectionError, SupervisorRuntime

__all__ = [
    "ConflictItem",
    "ConflictType",
    "DeterministicRCAProvider",
    "EvidenceGateRejectionError",
    "EvidenceReleaseGate",
    "FakeLLMProvider",
    "GateCheckResult",
    "GateOutcome",
    "GateResult",
    "IncidentDossier",
    "IncidentLifecycleState",
    "InvestigationBudget",
    "OpenRouterProvider",
    "RCAProvider",
    "SupervisorRuntime",
    "SupervisoryRCAAgent",
    "get_rca_provider",
]
