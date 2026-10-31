export interface ScenarioSummary {
  scenario_id: string;
  name: string;
  category: string;
  description: string;
  fixture_path: string;
  symptoms_summary: string;
}

export interface ScenarioDetail extends ScenarioSummary {
  node_count: number;
  link_count: number;
  has_ground_truth: boolean;
}

export interface TopologyNode {
  id: string;
  name: string;
  role: string;
  type: string;
  status: 'nominal' | 'symptom' | 'impacted' | 'probable_root_cause';
  x?: number;
  y?: number;
}

export interface TopologyLink {
  id: string;
  source: string;
  target: string;
  relationship: string;
  status: 'nominal' | 'degraded' | 'congested' | 'down';
}

export interface TopologyGraph {
  topology_id: string;
  nodes: TopologyNode[];
  links: TopologyLink[];
  metadata?: Record<string, any>;
}

export interface RunCreateRequest {
  scenario_id?: string;
  target_path?: string;
  incident_id?: string;
  llm?: 'off' | 'auto' | 'on';
  symptom?: string;
  site?: string;
}

export interface RunStatusResponse {
  run_id: string;
  incident_id: string;
  scenario_id?: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  created_at: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
}

export interface ExecutionEvent {
  event_id: string;
  run_id: string;
  incident_id: string;
  timestamp: string;
  event_type: string;
  source_component: string;
  status: string;
  entity_refs: string[];
  evidence_refs: string[];
  payload: Record<string, any>;
}

export interface TelemetryObservation {
  observation_id: string;
  incident_id: string;
  entity_id: string;
  entity_type: string;
  timestamp: string;
  metric_name?: string;
  value?: number;
  unit?: string;
  source?: string;
  observation_type: 'metric' | 'log' | 'topology' | 'config';
  message?: string;
}

export interface DerivedFeature {
  feature_id: string;
  incident_id: string;
  entity_id: string;
  feature_name: string;
  value: number;
  unit?: string;
  time_window_start: string;
  time_window_end: string;
  source_observation_ids: string[];
}

export interface TelemetryResponse {
  observations: TelemetryObservation[];
  features: DerivedFeature[];
  total_observations: number;
  total_features: number;
}

export interface TowerFinding {
  finding_id: string;
  finding_type: string;
  severity: string;
  confidence: number;
  description: string;
  entity_refs: string[];
  evidence_refs: string[];
}

export interface TowerHypothesis {
  hypothesis_id: string;
  fault_code: string;
  confidence: number;
  confidence_category: string;
  rationale: string;
  suspected_entities: string[];
  supporting_finding_refs: string[];
  contradicting_finding_refs: string[];
}

export interface TowerReportSummary {
  tower_id: string;
  findings_count: number;
  hypotheses_count: number;
  findings: TowerFinding[];
  hypotheses: TowerHypothesis[];
}

export interface SupportingEvidenceItem {
  metric: string;
  value: any;
  interpretation: string;
  entity_id?: string;
  unit?: string;
  observed_at?: string;
  source?: string;
}

export interface PredictedImpactItem {
  entity_id: string;
  relation: string;
  inferred_from: string;
  path: string[];
  hops: number;
  certainty: string;
  topology_evidence_refs?: string[];
}

export interface PathTraceItem {
  source_entity: string;
  target_entity: string;
  reachable: boolean;
  path: string[];
  evidence_refs: string[];
  warning?: string | null;
}

export interface PathTriageReport {
  status: string;
  paths: PathTraceItem[];
  limitations: string[];
}

export interface FinalReport {
  incident_id: string;
  status: string;
  suspected_root_cause: string;
  confidence: number;
  confidence_category?: string;
  affected_devices: string[];
  directly_affected_entities: string[];
  observed_symptom_entities: string[];
  inferred_affected_entities: string[];
  supporting_evidence: SupportingEvidenceItem[];
  alternative_causes: string[];
  concurrent_causes?: string[];
  recommended_actions: string[];
  evidence_sources: string[];
  limitations?: string[];
  predicted_impacts?: PredictedImpactItem[];
  path_triage?: PathTriageReport | null;
  peer_interactions?: any[];
  operator_questions?: string[];
  data_quality_warnings?: string[];
  orchestration_warnings?: string[];
  generated_at?: string;
}

export interface GateCheckResult {
  check_name: string;
  passed: boolean;
  message: string;
  severity: 'error' | 'warning';
}

export interface GateResultDetail {
  incident_id: string;
  outcome: string;
  passed: boolean;
  checks: GateCheckResult[];
  errors: string[];
  warnings: string[];
  limitations: string[];
  evaluated_at?: string;
}

export interface DiagnosticTask {
  task_id: string;
  incident_id: string;
  assigned_tower: string;
  task_type: string;
  status: string;
  priority: number;
  created_at: string;
  description: string;
}

export interface EvaluationResponse {
  run_id: string;
  incident_id: string;
  scenario_id: string;
  injected_fault_class: string;
  diagnosed_root_cause: string;
  class_match: boolean;
  target_entity?: string;
  target_match: boolean;
  intended_affected_entities: string[];
  reported_affected_entities: string[];
  precision: number;
  recall: number;
  f1: number;
}

export interface AssistantTurn {
  role: 'user' | 'assistant';
  content: string;
}

export interface AssistantResponse {
  question: string;
  answer: string;
  cited_evidence_ids: string[];
  cited_findings: string[];
  provider_used: string;
}
