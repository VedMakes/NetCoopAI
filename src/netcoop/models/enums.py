"""Core enumerations for NetCoop AI models and communication contracts."""

from enum import Enum


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConfidenceCategory(str, Enum):
    INSUFFICIENT = "insufficient"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class FindingStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class TaskStatus(str, Enum):
    CREATED = "CREATED"
    ACCEPTED = "ACCEPTED"
    COUNTER_PROPOSED = "COUNTER_PROPOSED"
    DECLINED = "DECLINED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"

    @property
    def is_terminal(self) -> bool:
        return self in {
            TaskStatus.DECLINED,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.ESCALATED,
            TaskStatus.CANCELLED,
            TaskStatus.TIMED_OUT,
        }


class QueryStatus(str, Enum):
    COMPLETED = "completed"
    UNSUPPORTED = "unsupported"
    INVALID_SCOPE = "invalid_scope"
    UNAUTHORIZED = "unauthorized"
    TIMEOUT = "timeout"
    NEEDS_SUPERVISOR_TASK = "needs_supervisor_task"
    FAILED = "failed"


class TowerId(str, Enum):
    PERFORMANCE = "performance"
    INFRASTRUCTURE = "infrastructure"
    CONNECTIVITY = "connectivity"
    SERVICES = "services"


class ProposalDecision(str, Enum):
    PROPOSE_DIAGNOSIS = "propose_diagnosis"
    REQUEST_EVIDENCE = "request_evidence"
    ABSTAIN = "abstain"
