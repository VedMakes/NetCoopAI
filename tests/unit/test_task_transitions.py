"""Unit tests for task state-machine transitions and invariant enforcement."""

import pytest

from netcoop.communication.tasks import (
    InvalidTaskTransitionError,
    InvestigationTask,
    validate_task_transition,
)
from netcoop.models.enums import TaskStatus, TowerId


def test_valid_task_lifecycle_happy_path(sample_utc_time):
    task = InvestigationTask(
        task_id="TASK-001",
        incident_id="INC-100",
        assignee=TowerId.PERFORMANCE,
        capability="performance.detect_congestion",
        objective={"entity": "SW_1"},
        expected_result_schema="netcoop://schemas/tasks/congestion-output/1.0",
        status=TaskStatus.CREATED,
        created_at=sample_utc_time,
        updated_at=sample_utc_time,
    )
    assert task.status == TaskStatus.CREATED

    # 1. Accept
    task = task.transition_to(TaskStatus.ACCEPTED)
    assert task.status == TaskStatus.ACCEPTED

    # 2. Run
    task = task.transition_to(TaskStatus.RUNNING)
    assert task.status == TaskStatus.RUNNING

    # 3. Complete
    task = task.transition_to(TaskStatus.COMPLETED)
    assert task.status == TaskStatus.COMPLETED
    assert task.status.is_terminal


def test_task_counter_proposal_lifecycle(sample_utc_time):
    task = InvestigationTask(
        task_id="TASK-002",
        incident_id="INC-100",
        assignee=TowerId.CONNECTIVITY,
        capability="connectivity.trace_path",
        objective={"from": "SW_1", "to": "SW_2"},
        expected_result_schema="netcoop://schemas/tasks/trace-output/1.0",
        status=TaskStatus.CREATED,
        created_at=sample_utc_time,
        updated_at=sample_utc_time,
    )

    # First counter proposal -> Allowed
    task = task.transition_to(TaskStatus.COUNTER_PROPOSED)
    assert task.status == TaskStatus.COUNTER_PROPOSED
    assert task.counter_proposal_count == 1

    # Counter proposal -> Accepted by supervisor
    task = task.transition_to(TaskStatus.ACCEPTED)
    assert task.status == TaskStatus.ACCEPTED

    task = task.transition_to(TaskStatus.RUNNING)
    task = task.transition_to(TaskStatus.COMPLETED)
    assert task.status == TaskStatus.COMPLETED


def test_counter_proposal_limit_enforced():
    # Attempting a second counter-proposal must be rejected
    with pytest.raises(InvalidTaskTransitionError, match="Maximum allowed is 1"):
        validate_task_transition(
            current=TaskStatus.CREATED,
            target=TaskStatus.COUNTER_PROPOSED,
            counter_proposal_count=1,
        )


@pytest.mark.parametrize(
    "current,target",
    [
        (TaskStatus.CREATED, TaskStatus.COMPLETED),  # Skipping execution
        (TaskStatus.CREATED, TaskStatus.RUNNING),    # Cannot run before accepting
        (TaskStatus.ACCEPTED, TaskStatus.COMPLETED), # Cannot complete before running
        (TaskStatus.COMPLETED, TaskStatus.RUNNING),  # Terminal cannot transition
        (TaskStatus.DECLINED, TaskStatus.ACCEPTED),  # Terminal cannot transition
        (TaskStatus.FAILED, TaskStatus.RUNNING),     # Terminal cannot transition
        (TaskStatus.ESCALATED, TaskStatus.RUNNING),  # Terminal cannot transition
        (TaskStatus.CANCELLED, TaskStatus.RUNNING),  # Terminal cannot transition
        (TaskStatus.TIMED_OUT, TaskStatus.RUNNING),  # Terminal cannot transition
    ],
)
def test_illegal_task_transitions_rejected(current, target):
    with pytest.raises(InvalidTaskTransitionError):
        validate_task_transition(current, target)


def test_task_escalation_path(sample_utc_time):
    task = InvestigationTask(
        task_id="TASK-003",
        incident_id="INC-100",
        assignee=TowerId.SERVICES,
        capability="services.check_dns",
        objective={"resolver": "10.0.0.53"},
        expected_result_schema="netcoop://schemas/tasks/dns-output/1.0",
        status=TaskStatus.CREATED,
        created_at=sample_utc_time,
        updated_at=sample_utc_time,
    )
    task = task.transition_to(TaskStatus.ACCEPTED)
    task = task.transition_to(TaskStatus.RUNNING)
    # Tower cannot complete within scope; escalates to supervisor
    task = task.transition_to(TaskStatus.ESCALATED)
    assert task.status == TaskStatus.ESCALATED
    assert task.status.is_terminal
