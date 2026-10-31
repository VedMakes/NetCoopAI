"""Shared pytest fixtures for NetCoop AI tests."""

from datetime import datetime, timezone

import pytest

from netcoop.models.enums import (
    FindingStatus,
    Severity,
    TowerId,
)
from netcoop.models.findings import Finding
from netcoop.models.observations import (
    MetricObservation,
)
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.utils.id_generator import DeterministicIdGenerator, set_id_generator


@pytest.fixture(autouse=True)
def reset_id_generator():
    """Resets the deterministic ID generator before each test."""
    gen = DeterministicIdGenerator(start=1)
    set_id_generator(gen)
    yield gen


@pytest.fixture
def memory_repo() -> SQLiteRepository:
    """Provides an isolated in-memory SQLite repository."""
    return SQLiteRepository(":memory:")


@pytest.fixture
def sample_utc_time() -> datetime:
    return datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample_metric_obs(sample_utc_time) -> MetricObservation:
    return MetricObservation(
        observation_id="OBS-000001",
        incident_id="INC-100",
        source="telemetry/synthetic",
        entity_id="SW_CAMPUS_1",
        metric_name="cpu_utilization_pct",
        value=85.5,
        unit="percent",
        timestamp=sample_utc_time,
        raw_reference={"source": "test"},
    )


@pytest.fixture
def sample_finding(sample_utc_time) -> Finding:
    return Finding(
        finding_id="F-000001",
        incident_id="INC-100",
        source_tower=TowerId.PERFORMANCE,
        producer="performance_detector",
        finding_type="congestion_candidate",
        severity=Severity.HIGH,
        status=FindingStatus.ACTIVE,
        entity_refs=["SW_CAMPUS_1:Gi0/1"],
        evidence_refs=["OBS-000001"],
        confidence=0.88,
        independence_group="group_telemetry",
        observed_at=sample_utc_time,
        created_at=sample_utc_time,
        description="High link utilization with correlated queue drops.",
    )
