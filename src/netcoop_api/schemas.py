"""Pydantic v2 schemas for NetCoop AI FastAPI backend."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScenarioSummary(BaseModel):
    scenario_id: str
    name: str
    category: str
    suite: Literal["challenge", "netcoop", "edge"] = "challenge"
    description: str
    fixture_path: str
    symptoms_summary: str


class ScenarioDetail(ScenarioSummary):
    node_count: int = 0
    link_count: int = 0
    has_ground_truth: bool = False


class TopologyNode(BaseModel):
    id: str
    name: str
    role: str
    type: str = "device"
    status: str = "nominal"  # nominal | symptom | impacted | probable_root_cause


class TopologyLink(BaseModel):
    id: str
    source: str
    target: str
    relationship: str = "connected_to"
    status: str = "nominal"  # nominal | degraded | congested | down


class TopologyGraph(BaseModel):
    topology_id: str = "TOPO-NETCOOP-01"
    nodes: list[TopologyNode] = Field(default_factory=list)
    links: list[TopologyLink] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str | None = None
    incident_id: str | None = Field(default=None, max_length=160)
    session_id: str | None = Field(default=None, max_length=160)
    llm: Literal["off", "auto", "on"] = "off"
    symptom_chat: str | None = Field(default=None, max_length=2000)
    site: str | None = Field(default=None, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

    @field_validator("symptom_chat")
    @classmethod
    def symptom_chat_must_contain_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("symptom_chat must contain non-whitespace text")
        return value


class UploadRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telemetry_filename: str = Field(min_length=1, max_length=255)
    telemetry_content: str = Field(min_length=1, max_length=20_000_000)
    topology_filename: str | None = Field(default=None, max_length=255)
    topology_content: str | None = Field(default=None, max_length=5_000_000)
    incident_id: str | None = Field(default=None, max_length=160)
    session_id: str | None = Field(default=None, max_length=160)
    llm: Literal["off", "auto", "on"] = "off"
    symptom_chat: str | None = Field(default=None, max_length=2000)
    site: str | None = Field(default=None, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

    @field_validator("symptom_chat")
    @classmethod
    def symptom_chat_must_contain_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("symptom_chat must contain non-whitespace text")
        return value


class RunStatusResponse(BaseModel):
    run_id: str
    incident_id: str
    session_id: str | None = None
    scenario_id: str | None = None
    status: str = "queued"  # queued | running | completed | failed
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class SessionSummary(BaseModel):
    session_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    current_run_id: str | None = None
    run_count: int = 0


class SessionDetail(SessionSummary):
    runs: list[RunStatusResponse] = Field(default_factory=list)


class ExecutionEventModel(BaseModel):
    event_id: str
    run_id: str
    incident_id: str
    timestamp: datetime
    event_type: str
    source_component: str
    status: str = "info"
    entity_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class TelemetryObservationModel(BaseModel):
    observation_id: str
    incident_id: str
    entity_id: str
    entity_type: str = "device"
    timestamp: datetime
    metric_name: str | None = None
    value: float | None = None
    unit: str | None = None
    source: str | None = None
    observation_type: str = "metric"  # metric | log | topology | config
    message: str | None = None


class DerivedFeatureModel(BaseModel):
    feature_id: str
    incident_id: str
    entity_id: str
    feature_name: str
    value: float
    unit: str | None = None
    time_window_start: datetime
    time_window_end: datetime
    source_observation_ids: list[str] = Field(default_factory=list)


class TelemetryResponse(BaseModel):
    observations: list[TelemetryObservationModel] = Field(default_factory=list)
    features: list[DerivedFeatureModel] = Field(default_factory=list)
    total_observations: int = 0
    total_features: int = 0


class TowerReportSummary(BaseModel):
    tower_id: str
    findings_count: int
    hypotheses_count: int
    findings: list[dict[str, Any]] = Field(default_factory=list)
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)


class GateCheckResultModel(BaseModel):
    check_name: str
    passed: bool
    message: str
    severity: str = "error"


class GateResultDetail(BaseModel):
    incident_id: str
    outcome: str
    passed: bool
    checks: list[GateCheckResultModel] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evaluated_at: str | None = None


class GateResultSummary(BaseModel):
    incident_id: str
    outcome: str
    passed: bool
    verified_evidence_count: int
    rejected_evidence_count: int
    data_quality_warnings: list[str] = Field(default_factory=list)
    contradictions_disclosed: list[str] = Field(default_factory=list)


class EvaluationResponse(BaseModel):
    run_id: str
    incident_id: str
    scenario_id: str
    injected_fault_class: str
    diagnosed_root_cause: str
    class_match: bool
    target_entity: str | None = None
    target_match: bool = False
    intended_affected_entities: list[str] = Field(default_factory=list)
    reported_affected_entities: list[str] = Field(default_factory=list)
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0


class AssistantTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AssistantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    llm: Literal["off", "auto", "on"] = "off"


class AssistantResponse(BaseModel):
    question: str
    answer: str
    cited_evidence_ids: list[str] = Field(default_factory=list)
    cited_findings: list[str] = Field(default_factory=list)
    provider_used: str = "deterministic"
