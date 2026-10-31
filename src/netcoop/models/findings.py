"""Finding contract for diagnostic conclusions emitted by towers."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from netcoop.communication.vocabulary import validate_finding_type
from netcoop.models.enums import FindingStatus, Severity, TowerId


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware (UTC required).")
    return dt.astimezone(timezone.utc)


class Finding(BaseModel):
    """Immutable diagnostic record emitted by a tower with provenance references."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str
    incident_id: str
    source_tower: TowerId
    producer: str
    finding_type: str
    severity: Severity
    status: FindingStatus = FindingStatus.ACTIVE
    entity_refs: list[str]
    evidence_refs: list[str] = Field(
        ..., min_length=1, description="Must reference at least one observation or finding ID"
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    derived_from: list[str] = Field(default_factory=list)
    independence_group: str
    observed_at: datetime
    created_at: datetime
    schema_version: str = "1.0"
    rule_or_model_version: str = "1.0"
    supersedes_finding_id: str | None = None
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("observed_at", "created_at")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)

    @field_validator("finding_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        validate_finding_type(v)
        return v
