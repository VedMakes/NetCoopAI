import {
  AssistantResponse,
  AssistantTurn,
  DiagnosticTask,
  EvaluationResponse,
  ExecutionEvent,
  FinalReport,
  InvestigationSession,
  GateResultDetail,
  RunCreateRequest,
  RunStatusResponse,
  ScenarioDetail,
  ScenarioSummary,
  TelemetryResponse,
  TopologyGraph,
  TowerReportSummary,
  UploadRunRequest,
} from './types';

const API_BASE = '/api';

export async function getHealth(): Promise<{ status: string; components: Record<string, { status: string; details: string }> }> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.statusText}`);
  return res.json();
}

export async function getScenarios(): Promise<ScenarioSummary[]> {
  const res = await fetch(`${API_BASE}/scenarios`);
  if (!res.ok) throw new Error(`Failed to load scenarios: ${res.statusText}`);
  return res.json();
}

export async function getSessions(): Promise<InvestigationSession[]> {
  const res = await fetch(`${API_BASE}/sessions`);
  if (!res.ok) throw new Error(`Failed to load sessions: ${res.statusText}`);
  return res.json();
}

export async function createSession(title = 'Network investigation'): Promise<InvestigationSession> {
  const res = await fetch(`${API_BASE}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`Failed to create session: ${res.statusText}`);
  return res.json();
}

export async function getSession(sessionId: string): Promise<InvestigationSession> {
  const res = await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}`);
  if (!res.ok) throw new Error(`Failed to load session: ${res.statusText}`);
  return res.json();
}

export async function getScenarioDetail(scenarioId: string): Promise<ScenarioDetail> {
  const res = await fetch(`${API_BASE}/scenarios/${scenarioId}`);
  if (!res.ok) throw new Error(`Failed to load scenario ${scenarioId}: ${res.statusText}`);
  return res.json();
}

export async function getScenarioTopology(scenarioId: string): Promise<TopologyGraph> {
  const res = await fetch(`${API_BASE}/scenarios/${scenarioId}/topology`);
  if (!res.ok) throw new Error(`Failed to load topology for ${scenarioId}: ${res.statusText}`);
  return res.json();
}

export async function createRun(request: RunCreateRequest): Promise<RunStatusResponse> {
  const res = await fetch(`${API_BASE}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Failed to start run');
  }
  return res.json();
}

export async function createUploadedRun(request: UploadRunRequest): Promise<RunStatusResponse> {
  const res = await fetch(`${API_BASE}/runs/upload`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Failed to upload capture');
  }
  return res.json();
}

export async function getRunStatus(runId: string): Promise<RunStatusResponse> {
  const res = await fetch(`${API_BASE}/runs/${runId}`);
  if (!res.ok) throw new Error(`Failed to get run status: ${res.statusText}`);
  return res.json();
}

export async function getRunTelemetry(runId: string): Promise<TelemetryResponse> {
  const res = await fetch(`${API_BASE}/runs/${runId}/telemetry`);
  if (!res.ok) throw new Error(`Failed to get telemetry: ${res.statusText}`);
  return res.json();
}

export async function getRunTopology(runId: string): Promise<TopologyGraph> {
  const res = await fetch(`${API_BASE}/runs/${runId}/topology`);
  if (!res.ok) throw new Error(`Failed to get run topology: ${res.statusText}`);
  return res.json();
}

export async function getRunEvents(runId: string): Promise<ExecutionEvent[]> {
  const res = await fetch(`${API_BASE}/runs/${runId}/events`);
  if (!res.ok) throw new Error(`Failed to get events: ${res.statusText}`);
  return res.json();
}

export async function getRunFindings(runId: string): Promise<TowerReportSummary[]> {
  const res = await fetch(`${API_BASE}/runs/${runId}/findings`);
  if (!res.ok) throw new Error(`Failed to get tower findings: ${res.statusText}`);
  return res.json();
}

export async function getRunTasks(runId: string): Promise<DiagnosticTask[]> {
  const res = await fetch(`${API_BASE}/runs/${runId}/tasks`);
  if (!res.ok) throw new Error(`Failed to get tasks: ${res.statusText}`);
  return res.json();
}

export async function getRunReport(runId: string): Promise<FinalReport> {
  const res = await fetch(`${API_BASE}/runs/${runId}/report`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Final report not ready');
  }
  return res.json();
}

export async function getRunGate(runId: string): Promise<GateResultDetail> {
  const res = await fetch(`${API_BASE}/runs/${runId}/gate`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Gate verification not ready');
  }
  return res.json();
}

export async function getRunEvaluation(runId: string): Promise<EvaluationResponse> {
  const res = await fetch(`${API_BASE}/runs/${runId}/evaluation`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Evaluation unavailable');
  }
  return res.json();
}

export async function askAssistant(
  runId: string,
  question: string,
  llm: 'off' | 'auto' | 'on' = 'off'
): Promise<AssistantResponse> {
  const res = await fetch(`${API_BASE}/runs/${runId}/assistant`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, llm }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Assistant request failed');
  }
  return res.json();
}

export async function getAssistantHistory(runId: string): Promise<AssistantTurn[]> {
  const res = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}/assistant/history`);
  if (!res.ok) throw new Error(`Failed to load assistant history: ${res.statusText}`);
  return res.json();
}

export async function clearAssistantHistory(runId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}/assistant/history`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`Failed to clear assistant history: ${res.statusText}`);
}

export async function askSessionAssistant(
  sessionId: string,
  question: string,
  llm: 'off' | 'auto' | 'on' = 'off'
): Promise<AssistantResponse> {
  const res = await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/assistant`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, llm }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Assistant request failed');
  }
  return res.json();
}

export async function getSessionAssistantHistory(sessionId: string): Promise<AssistantTurn[]> {
  const res = await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/assistant/history`);
  if (!res.ok) throw new Error(`Failed to load session assistant history: ${res.statusText}`);
  return res.json();
}

export async function clearSessionAssistantHistory(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/assistant/history`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`Failed to clear session assistant history: ${res.statusText}`);
}
