"""Pydantic v2 schemas for NetCoop AI FastAPI backend."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ScenarioSummary(BaseModel):
    scenario_id: str
    name: str
    category: str
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
    scenario_id: str | None = None
    target_path: str | None = None
    incident_id: str | None = None
    llm: str = "off"  # off | auto | on
    symptom: str | None = None
    site: str | None = None


class RunStatusResponse(BaseModel):
    run_id: str
    incident_id: str
    scenario_id: str | None = None
    status: str = "queued"  # queued | running | completed | failed
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


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
    role: str  # user | assistant
    content: str


class AssistantRequest(BaseModel):
    question: str
    history: list[AssistantTurn] = Field(default_factory=list)
    llm: str = "off"  # off | auto | on


class AssistantResponse(BaseModel):
    question: str
    answer: str
    cited_evidence_ids: list[str] = Field(default_factory=list)
    cited_findings: list[str] = Field(default_factory=list)
    provider_used: str = "deterministic"
