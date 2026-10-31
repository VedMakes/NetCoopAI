"""Data models for derived network features and metrics."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware (UTC required).")
    return dt.astimezone(timezone.utc)


class DerivedFeature(BaseModel):
    """Normalized derived feature computed from one or more raw telemetry observations."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    incident_id: str
    entity_id: str
    feature_name: str
    value: float
    unit: str
    time_window_start: datetime
    time_window_end: datetime
    source_observation_ids: list[str] = Field(
        ..., min_length=1, description="Source observations from which this feature was derived"
    )
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("time_window_start", "time_window_end")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)
