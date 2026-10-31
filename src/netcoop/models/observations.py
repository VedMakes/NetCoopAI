"""Canonical observation contracts for NetCoop AI.

All observation models are strictly validated and enforce timezone-aware timestamps
and canonical vocabulary mappings.
"""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from netcoop.communication.vocabulary import validate_metric_and_unit


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware (UTC required).")
    return dt.astimezone(timezone.utc)


class BaseObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str
    incident_id: str
    source: str
    entity_id: str
    timestamp: datetime
    schema_version: str = "1.0"

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_tz(cls, v: datetime) -> datetime:
        return _ensure_utc(v)


class MetricObservation(BaseObservation):
    observation_type: Literal["metric"] = "metric"
    metric_name: str
    value: float
    unit: str
    raw_reference: dict[str, Any] | None = None

    @field_validator("unit")
    @classmethod
    def validate_metric_vocabulary(cls, unit: str, info: Any) -> str:
        values = info.data
        metric_name = values.get("metric_name")
        value = values.get("value")
        if metric_name and value is not None:
            validate_metric_and_unit(metric_name, unit, float(value))
        return unit


class LogObservation(BaseObservation):
    observation_type: Literal["log"] = "log"
    log_level: str
    message: str
    facility: str | None = None
    raw_reference: dict[str, Any] | None = None


class TopologyObservation(BaseObservation):
    observation_type: Literal["topology"] = "topology"
    source_entity: str
    target_entity: str
    relationship_type: str  # e.g., 'connected_to', 'uplink_of'
    link_speed_mbps: float | None = None
    interface_name: str | None = None
    raw_reference: dict[str, Any] | None = None


class ConfigObservation(BaseObservation):
    observation_type: Literal["config"] = "config"
    config_key: str
    config_value: str
    previous_value: str | None = None
    raw_reference: dict[str, Any] | None = None


# Discriminated union of canonical observations
CanonicalObservation = Annotated[
    Union[MetricObservation, LogObservation, TopologyObservation, ConfigObservation],
    Field(discriminator="observation_type"),
]
