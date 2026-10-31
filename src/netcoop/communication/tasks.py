"""Investigation task contracts and lifecycle state-machine validation."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from netcoop.models.enums import TaskStatus, TowerId


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware (UTC required).")
    return dt.astimezone(timezone.utc)


class InvalidTaskTransitionError(ValueError):
    """Raised when an illegal investigation task status transition is attempted."""


ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.CREATED: {
        TaskStatus.ACCEPTED,
        TaskStatus.DECLINED,
        TaskStatus.COUNTER_PROPOSED,
        TaskStatus.CANCELLED,
        TaskStatus.TIMED_OUT,
    },
    TaskStatus.COUNTER_PROPOSED: {
        TaskStatus.ACCEPTED,
        TaskStatus.DECLINED,
        TaskStatus.CANCELLED,
        TaskStatus.TIMED_OUT,
    },
    TaskStatus.ACCEPTED: {
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
        TaskStatus.TIMED_OUT,
        TaskStatus.FAILED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.ESCALATED,
        TaskStatus.CANCELLED,
        TaskStatus.TIMED_OUT,
    },
}


def validate_task_transition(
    current: TaskStatus, target: TaskStatus, counter_proposal_count: int = 0
) -> None:
    """Validates state transitions according to INTERAGENT_COMMS Section 4.4.

    Rules:
    - Permitted paths:
        CREATED -> ACCEPTED | DECLINED | COUNTER_PROPOSED | CANCELLED | TIMED_OUT
        COUNTER_PROPOSED -> ACCEPTED | DECLINED | CANCELLED | TIMED_OUT
        ACCEPTED -> RUNNING | CANCELLED | TIMED_OUT | FAILED
        RUNNING -> COMPLETED | FAILED | ESCALATED | CANCELLED | TIMED_OUT
    - Maximum 1 COUNTER_PROPOSED transition per task.
    - Terminal states (DECLINED, COMPLETED, FAILED, ESCALATED, CANCELLED, TIMED_OUT)
      cannot transition further.
    """
    if current.is_terminal:
        raise InvalidTaskTransitionError(
            f"Cannot transition from terminal status '{current.value}' to '{target.value}'."
        )

    if target == TaskStatus.COUNTER_PROPOSED and counter_proposal_count >= 1:
        raise InvalidTaskTransitionError(
            f"Task already has {counter_proposal_count} counter-proposal(s). Maximum allowed is 1."
        )

    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidTaskTransitionError(
            f"Illegal task transition from '{current.value}' to '{target.value}'. Allowed: {[s.value for s in allowed]}"
        )


class InvestigationTask(BaseModel):
    """Persistent, supervisor-authorized multi-step investigation task."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    incident_id: str
    parent_task_id: str | None = None
    requester: str = "supervisor"
    assignee: TowerId
    capability: str
    objective: dict[str, Any]
    constraints: dict[str, Any] = Field(default_factory=dict)
    expected_result_schema: str
    status: TaskStatus = TaskStatus.CREATED
    counter_proposal_count: int = 0
    created_at: datetime
    updated_at: datetime
    deadline_at: datetime | None = None
    result_id: str | None = None
    error_code: str | None = None
    error_detail: str | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)

    @field_validator("deadline_at")
    @classmethod
    def validate_deadline_utc(cls, v: datetime | None) -> datetime | None:
        return _ensure_utc(v) if v is not None else None

    def transition_to(self, new_status: TaskStatus) -> "InvestigationTask":
        """Returns a copy of the task with the new status after validating the transition."""
        validate_task_transition(self.status, new_status, self.counter_proposal_count)
        new_count = self.counter_proposal_count + (1 if new_status == TaskStatus.COUNTER_PROPOSED else 0)
        return self.model_copy(
            update={
                "status": new_status,
                "counter_proposal_count": new_count,
                "updated_at": datetime.now(timezone.utc),
            }
        )


class TaskResult(BaseModel):
    """Structured output artifact produced upon task completion."""

    model_config = ConfigDict(extra="forbid")

    result_id: str
    task_id: str
    assignee: TowerId
    status: TaskStatus
    result_schema: str
    result: dict[str, Any] | None = None
    finding_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    completed_at: datetime

    @field_validator("completed_at")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)
