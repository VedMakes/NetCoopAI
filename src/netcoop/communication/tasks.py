"""Investigation task contracts and lifecycle state-machine validation."""

from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from netcoop.communication.events import EventEnvelope
from netcoop.models.enums import TaskStatus, TowerId
from netcoop.utils.id_generator import generate_id

DIAGNOSTIC_TASK_ARTIFACT_SCHEMA = "netcoop://schemas/tasks/diagnostic-artifact/1.1"


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware (UTC required).")
    return dt.astimezone(timezone.utc)


class InvalidTaskTransitionError(ValueError):
    """Raised when an illegal investigation task status transition is attempted."""


class InvestigationDisposition(str, Enum):
    """Typed next-step contract for evidence review and orchestration control."""

    RESOLVED = "resolved"
    CONTINUE_WITH_NEW_TASK = "continue_with_new_task"
    SIGNAL_UNAVAILABLE = "signal_unavailable"
    OPERATOR_INPUT_NEEDED = "operator_input_needed"
    ABSTAIN = "abstain"


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


class EvidenceSignalSummary(BaseModel):
    """Bounded temporal summary used to distinguish persistence from a snapshot."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    signal: str
    sample_count: int
    time_point_count: int
    source_count: int
    first_seen: datetime
    last_seen: datetime
    min_value: float
    max_value: float
    conflicting_time_points: int = 0

    @field_validator("first_seen", "last_seen")
    @classmethod
    def validate_summary_timestamps(cls, value: datetime) -> datetime:
        return _ensure_utc(value)


class HypothesisReview(BaseModel):
    """Evidence-grounded review of a hypothesis, including what could falsify it."""

    model_config = ConfigDict(extra="forbid")

    fault_code: str
    status: Literal["supported", "weakened", "inconclusive"]
    supporting_evidence_refs: list[str] = Field(default_factory=list)
    contradicting_evidence_refs: list[str] = Field(default_factory=list)
    inspected_evidence_refs: list[str] = Field(default_factory=list)
    new_evidence_refs: list[str] = Field(default_factory=list)
    missing_measurements: list[str] = Field(default_factory=list)
    unavailable_signals: list[str] = Field(default_factory=list)
    disposition: InvestigationDisposition = InvestigationDisposition.CONTINUE_WITH_NEW_TASK
    discriminating_measurement: str
    temporal_summaries: list[EvidenceSignalSummary] = Field(default_factory=list)
    summary: str


class TaskEvidenceItem(BaseModel):
    """Provenance-rich reference to an observation used by a specialist task."""

    model_config = ConfigDict(extra="forbid")

    observation_id: str
    observed_at: datetime
    source: str
    entity_id: str
    signal: str
    value: Any = None
    unit: str | None = None
    limitation: str | None = None

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        return _ensure_utc(value)


class DiagnosticTaskArtifact(BaseModel):
    """Versioned result contract shared by bounded tower investigations."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    capability: str
    target_entities: list[str] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    finding_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    observation_count: int | None = None
    summary: str
    analysis: dict[str, Any] | None = None
    hypothesis_reviews: list[HypothesisReview] = Field(default_factory=list)
    evidence_context: list[TaskEvidenceItem] = Field(default_factory=list)
    unavailable_signals: list[str] = Field(default_factory=list)


TaskHandler = Callable[[InvestigationTask], TaskResult]


class TaskDispatcher:
    """Dispatcher for supervisor-authorized investigation tasks with persistent lifecycle management."""

    def __init__(
        self,
        repository: Any | None = None,
        event_bus: Any | None = None,
        registry: Any | None = None,
    ) -> None:
        self.repo = repository
        self.event_bus = event_bus
        self.registry = registry
        # Map (assignee_str, capability_str) -> TaskHandler
        self._handlers: dict[tuple[str, str], TaskHandler] = {}
        # In-memory store fallback if repo is None
        self._tasks: dict[str, InvestigationTask] = {}
        self._results: dict[str, TaskResult] = {}

    def register_handler(
        self, tower_id: TowerId | str, capability: str, handler: TaskHandler
    ) -> None:
        t_id = tower_id.value.lower() if isinstance(tower_id, TowerId) else tower_id.lower()
        self._handlers[(t_id, capability)] = handler

    def create_task(
        self,
        requester: str,
        assignee: TowerId | str,
        capability: str,
        objective: dict[str, Any],
        constraints: dict[str, Any] | None = None,
        deadline_at: datetime | None = None,
        parent_task_id: str | None = None,
        expected_result_schema: str = "netcoop://schemas/tasks/generic-result/1.0",
        incident_id: str = "INC-ACTIVE",
    ) -> InvestigationTask:
        """Creates and persists an investigation task. ONLY 'supervisor' may call this."""
        if requester != "supervisor":
            raise PermissionError(
                f"Unauthorized task creation attempt by '{requester}'. "
                f"Only 'supervisor' may create persistent investigation tasks."
            )

        assignee_id = assignee if isinstance(assignee, TowerId) else TowerId(assignee.lower())
        now = datetime.now(timezone.utc)
        task_id = generate_id("TASK")

        task = InvestigationTask(
            task_id=task_id,
            incident_id=incident_id,
            parent_task_id=parent_task_id,
            requester=requester,
            assignee=assignee_id,
            capability=capability,
            objective=objective,
            constraints=constraints or {},
            expected_result_schema=expected_result_schema,
            status=TaskStatus.CREATED,
            counter_proposal_count=0,
            created_at=now,
            updated_at=now,
            deadline_at=deadline_at,
        )

        self._save_task(task)

        if self.event_bus is not None:
            self._publish_task_event("task.created", task)

        return task

    def get(self, task_id: str) -> InvestigationTask:
        if self.repo is not None:
            task = self.repo.get_task_by_id(task_id)
            if task is not None:
                return task
        elif task_id in self._tasks:
            return self._tasks[task_id]
        raise KeyError(f"Investigation task '{task_id}' not found.")

    def accept(self, task_id: str) -> InvestigationTask:
        task = self.get(task_id)
        updated = task.transition_to(TaskStatus.ACCEPTED)
        self._save_task(updated)
        if self.event_bus is not None:
            self._publish_task_event("task.accepted", updated)
        return updated

    def decline(self, task_id: str, reason: str) -> InvestigationTask:
        task = self.get(task_id)
        updated = task.transition_to(TaskStatus.DECLINED).model_copy(
            update={"error_detail": reason}
        )
        self._save_task(updated)
        if self.event_bus is not None:
            self._publish_task_event("task.declined", updated)
        return updated

    def counter_propose(
        self, task_id: str, revised_constraints: dict[str, Any], reason: str
    ) -> InvestigationTask:
        task = self.get(task_id)
        updated = task.transition_to(TaskStatus.COUNTER_PROPOSED).model_copy(
            update={
                "constraints": revised_constraints,
                "error_detail": reason,
            }
        )
        self._save_task(updated)
        if self.event_bus is not None:
            self._publish_task_event("task.counter_proposed", updated)
        return updated

    def cancel(self, task_id: str, reason: str) -> InvestigationTask:
        task = self.get(task_id)
        updated = task.transition_to(TaskStatus.CANCELLED).model_copy(
            update={"error_detail": reason}
        )
        self._save_task(updated)
        if self.event_bus is not None:
            self._publish_task_event("task.cancelled", updated)
        return updated

    def execute(self, task_id: str) -> TaskResult:
        task = self.get(task_id)
        now = datetime.now(timezone.utc)

        # 1. State transition
        if task.status == TaskStatus.CREATED:
            task = self.accept(task_id)

        if task.status != TaskStatus.ACCEPTED:
            raise InvalidTaskTransitionError(
                f"Cannot execute task in status '{task.status.value}'. Must be in ACCEPTED state."
            )

        running_task = task.transition_to(TaskStatus.RUNNING)
        self._save_task(running_task)

        # 2. Handler lookup
        assignee_str = running_task.assignee.value.lower()
        handler = self._handlers.get((assignee_str, running_task.capability))
        if handler is None:
            escalated_task = running_task.transition_to(TaskStatus.ESCALATED).model_copy(
                update={"error_detail": f"No handler registered for {assignee_str}/{running_task.capability}"}
            )
            self._save_task(escalated_task)
            result = TaskResult(
                result_id=generate_id("RES"),
                task_id=task_id,
                assignee=running_task.assignee,
                status=TaskStatus.ESCALATED,
                result_schema=running_task.expected_result_schema,
                warnings=[f"Capability '{running_task.capability}' not supported by assignee."],
                completed_at=now,
            )
            self._save_result(result)
            if self.event_bus is not None:
                self._publish_task_event("task.escalated", escalated_task)
            return result

        # 3. Execution with failure safety
        try:
            result = handler(running_task)
            terminal_status = result.status if result.status.is_terminal else TaskStatus.COMPLETED
            completed_task = running_task.transition_to(terminal_status).model_copy(
                update={"result_id": result.result_id}
            )
            self._save_task(completed_task)
            self._save_result(result)
            if self.event_bus is not None:
                self._publish_task_event("task.completed", completed_task)
            return result
        except Exception as exc:
            failed_task = running_task.transition_to(TaskStatus.FAILED).model_copy(
                update={"error_code": "EXECUTION_ERROR", "error_detail": str(exc)}
            )
            self._save_task(failed_task)
            result = TaskResult(
                result_id=generate_id("RES"),
                task_id=task_id,
                assignee=running_task.assignee,
                status=TaskStatus.FAILED,
                result_schema=running_task.expected_result_schema,
                warnings=[f"Execution failed: {exc}"],
                completed_at=datetime.now(timezone.utc),
            )
            self._save_result(result)
            if self.event_bus is not None:
                self._publish_task_event("task.failed", failed_task)
            return result

    def _save_task(self, task: InvestigationTask) -> None:
        if self.repo is not None:
            existing = self.repo.get_task_by_id(task.task_id)
            if existing is None:
                self.repo.insert_task(task)
            else:
                self.repo.update_task(task)
        else:
            self._tasks[task.task_id] = task

    def _save_result(self, result: TaskResult) -> None:
        if self.repo is not None:
            self.repo.insert_task_result(result)
        else:
            self._results[result.task_id] = result

    def _publish_task_event(self, event_type: str, task: InvestigationTask) -> None:
        if self.event_bus is None:
            return
        now = datetime.now(timezone.utc)
        evt = EventEnvelope(
            id=generate_id("EVT"),
            source=f"netcoop/{task.assignee.value}",
            type=event_type,
            subject=task.task_id,
            time=now,
            dataschema="netcoop://schemas/events/task-lifecycle/1.0",
            correlationid=task.incident_id,
            causationid=task.task_id,
            data={
                "task_id": task.task_id,
                "status": task.status.value,
                "capability": task.capability,
                "assignee": task.assignee.value,
                "result_id": task.result_id,
                "error_code": task.error_code,
            },
        )
        self.event_bus.publish(evt)
