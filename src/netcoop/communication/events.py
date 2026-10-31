"""Event models and envelope for NetCoop AI publish/subscribe communication."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware (UTC required).")
    return dt.astimezone(timezone.utc)


class EventEnvelope(BaseModel):
    """CloudEvents-inspired typed event envelope for publish/subscribe event distribution."""

    model_config = ConfigDict(extra="forbid")

    specversion: Literal["1.0"] = "1.0"
    id: str = Field(..., description="Unique event identifier and idempotency key")
    source: str = Field(..., description="Producer identity e.g. netcoop/performance")
    type: str = Field(..., description="Semantic event type e.g. performance.congestion_candidate")
    subject: str | None = Field(default=None, description="Canonical entity ID when relevant")
    time: datetime = Field(..., description="Event creation timestamp in timezone-aware UTC")
    datacontenttype: Literal["application/json"] = "application/json"
    dataschema: str = Field(..., description="URI or schema identifier for the payload")
    correlationid: str = Field(..., description="Incident or investigation identifier")
    causationid: str | None = Field(default=None, description="Causal event or task ID")
    data: dict[str, Any] = Field(..., description="Compact payload containing references and metadata")

    @field_validator("time")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)
