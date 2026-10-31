"""Hypothesis models representing competing fault explanations."""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from netcoop.communication.vocabulary import validate_fault_code
from netcoop.models.enums import ConfidenceCategory


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware (UTC required).")
    return dt.astimezone(timezone.utc)


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    incident_id: str
    fault_code: str
    suspected_entities: list[str]
    supporting_finding_refs: list[str] = Field(default_factory=list)
    contradicting_finding_refs: list[str] = Field(default_factory=list)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    confidence_category: ConfidenceCategory
    rationale: str
    status: str = "active"
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)

    @field_validator("fault_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        validate_fault_code(v)
        return v
