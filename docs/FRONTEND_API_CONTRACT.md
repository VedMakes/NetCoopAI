# NetCoop AI Frontend API Contract
**FastAPI HTTP Endpoints, Server-Sent Events & Data Schemas**

---

## 1. Overview
The NetCoop AI API is a lightweight, asynchronous HTTP service wrapping the existing diagnostic runtime and SQLite Knowledge Plane.

- **Base URL:** `http://127.0.0.1:8000`
- **Interactive Documentation:** `http://127.0.0.1:8000/docs` (OpenAPI Swagger UI)
- **CORS Allowed Origins:** `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:3000`
- **CLI Startup:** `netcoop api --port 8000` or `uv run netcoop api`

---

## 2. Endpoints Specification

### 2.1 System Health
`GET /api/health`
Returns backend health status across Python runtime, canonical vocabulary, capability registry, SQLite engine, 4 towers, and supervisor runtime.

**Response `200 OK`:**
```json
{
  "status": "healthy",
  "components": {
    "runtime": { "status": "OK", "details": "Cpython 3.12.13" },
    "vocabulary": { "status": "OK", "details": "13 canonical metrics loaded" },
    "capability_registry": { "status": "OK", "details": "4 tower profiles loaded" },
    "sqlite": { "status": "OK", "details": "Initialized in-memory DB (schema v1)" },
    "towers": { "status": "OK", "details": "4 domain controllers ready (Performance, Infra, Conn, Services)" },
    "supervisor_gate": { "status": "OK", "details": "SupervisorRuntime & EvidenceReleaseGate initialized" }
  }
}
```

---

### 2.2 Scenarios Catalog & Topology

`GET /api/scenarios`
Returns the list of available synthetic benchmark scenarios.

**Response `200 OK`:**
```json
[
  {
    "scenario_id": "link_congestion",
    "name": "Core Uplink Congestion",
    "category": "Performance",
    "description": "High link utilization on core switch Gi0/2 resulting in buffer queue drops and packet loss.",
    "fixture_path": "fixtures/scenarios/link_congestion",
    "symptoms_summary": "Interface saturation (>95%), severe queue drops, and TCP retransmissions."
  }
]
```

`GET /api/scenarios/{scenario_id}`
Returns metadata, node count, and link count for a scenario. Evaluator ground truth is strictly quarantined and omitted.

`GET /api/scenarios/{scenario_id}/topology`
Returns the NetworkX topology graph representation:
```json
{
  "topology_id": "TOPO-IIT-CAMPUS-01",
  "nodes": [
    { "id": "GW_EDGE_01", "name": "Campus Edge Gateway", "role": "gateway", "type": "device", "status": "nominal" },
    { "id": "SW_CORE_01", "name": "Campus Core Backbone Switch", "role": "core_switch", "type": "device", "status": "nominal" }
  ],
  "links": [
    { "id": "LINK-01", "source": "GW_EDGE_01", "target": "SW_CORE_01", "relationship": "connected_to", "status": "nominal" }
  ],
  "metadata": { "source": "fixtures/scenarios/link_congestion/topology.json" }
}
```

---

### 2.3 Diagnostic Runs & Lifecycle

`POST /api/runs`
Initiates a new diagnostic run on a scenario or custom capture directory.

**Request:**
```json
{
  "scenario_id": "link_congestion",
  "llm": "off",
  "symptom": null
}
```

**Response `201 Created`:**
```json
{
  "run_id": "run-a1b2c3d4e5",
  "incident_id": "INC-link_congestion-78f9a0",
  "scenario_id": "link_congestion",
  "status": "queued",
  "created_at": "2026-11-01T03:30:00Z"
}
```

`GET /api/runs/{run_id}`
Returns status: `"queued"`, `"running"`, `"completed"`, or `"failed"`.

`GET /api/runs/{run_id}/telemetry`
Returns raw canonical observations and computed derived features (SMA, EWMA, MAD Z-scores).

`GET /api/runs/{run_id}/topology`
Returns topology annotated with `symptom` (observed in telemetry), `impacted` (topology blast radius prediction), or `probable_root_cause`.

`GET /api/runs/{run_id}/events`
Returns historical list of structured execution events.

`GET /api/runs/{run_id}/events/stream`
Server-Sent Events (SSE) live event stream:
```text
data: {"event_id": "...", "run_id": "...", "event_type": "run.started", ...}

data: {"event_id": "...", "run_id": "...", "event_type": "tower.completed", ...}

event: done
data: {"status": "completed"}
```

`GET /api/runs/{run_id}/findings`
Returns specialist tower reports and findings from Performance, Infrastructure, Connectivity, and Services towers.

`GET /api/runs/{run_id}/tasks`
Returns supervisor task dispatcher assignments, transitions, and peer queries.

`GET /api/runs/{run_id}/report`
Returns certified `FinalReport` object. Returns `400 Bad Request` if run has not finished.

`GET /api/runs/{run_id}/evaluation`
Evaluates the run against held-out ground truth. Strictly returns `400 Bad Request` if requested before diagnosis finishes.

---

### 2.4 Incident Explanation Assistant

`POST /api/runs/{run_id}/assistant`
Read-only multi-turn Q&A answering operator questions regarding certified reports, tower findings, gate checks, and limitations.

**Request:**
```json
{
  "question": "Why did Performance tower suspect link congestion?",
  "history": [],
  "llm": "off"
}
```

**Response `200 OK`:**
```json
{
  "question": "Why did Performance tower suspect link congestion?",
  "answer": "### Diagnosed Root Cause: `LINK_CONGESTION: ...`\n\n• **Confidence Score:** 0.65 (`probable`)\n...",
  "cited_evidence_ids": ["OBS-001", "OBS-002"],
  "cited_findings": ["CRITICAL LINK_CONGESTION: Repeated high interface utilization..."],
  "provider_used": "deterministic"
}
```
