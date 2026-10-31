# NetCoop AI Frontend & Integration Architecture
**Architecture Specification, Technology Trade-offs & Selection Proposal**

---

## 1. Frontend Technology Stack Comparison & Recommendation

We evaluated three potential technology paths for the NetCoop AI web dashboard:

| Dimension | Option A: React + Vite + Tailwind (Recommended) | Option B: Next.js (App Router) | Option C: Streamlit |
|---|---|---|---|
| **Topology Graph Visualization** | **Excellent.** Full Canvas/SVG access with D3 or React Flow for custom dark-mode campus topology. | **Good.** Supported, but server-component / hydration boundaries add complexity. | **Poor / Limited.** Rigid component layout, difficult custom graph interaction. |
| **Telemetry Playback & Simulation** | **Superior.** High-performance client-side state machine (scrub, pause, step) with 60fps chart rendering. | **Good.** Requires `"use client"` across all interactive panels. | **Poor.** Full page reruns on interaction make fluid 60fps playback impossible. |
| **Multi-Panel NOC Layout** | **Exceptional.** Flexible grid with independent sub-second panel updates for towers and logs. | **Good.** Solid layout engine, but heavier runtime footprint. | **Constrained.** Top-to-bottom widget flow, limited multi-column density. |
| **Build & Dev Speed** | **Instant.** Vite HMR (<50ms), minimal bundle, simple static output. | **Moderate.** Slower Turbopack/Webpack compilation and SSR overhead. | **Fast prototyping, low ceiling.** Python-only, but quickly hits styling limits. |
| **Architectural Separation** | **Clean.** Decoupled static frontend served directly or proxied; zero backend leakage. | **Mixed.** Server actions blur boundaries between client and backend Python. | **Coupled.** Runs in Python interpreter, risking coupling to diagnosis runtime. |

### Recommendation
**Option A: React 18 + Vite + Tailwind CSS + Lucide Icons.**
- Allows building a high-density, professional Dark-theme Network Operations Center (NOC) dashboard.
- Provides precise control over graph rendering (NetworkX topology layout) and canvas animations for packet flows and affected paths.
- Guarantees zero risk of running diagnostic logic in the browser: clean client-server contract over HTTP.

---

## 2. Backend API Architecture: Thin FastAPI Service Layer

### Core Principles
1. **Zero Duplicate Logic:** The API layer is strictly an adapter around existing Python services (`SupervisorRuntime`, `TelemetryLoader`, `FeaturePipeline`, SQLite store). It never re-implements diagnosis or calculations.
2. **Deterministic & Isolated Execution:** Runs are executed asynchronously in local thread pools via `asyncio.to_thread` to prevent blocking the event loop.
3. **Quarantined Ground Truth:** Ground truth files (`evaluation/ground_truth.json`) are quarantined and only accessible via `/api/runs/{id}/evaluation` *after* the diagnostic report status is finalized (`diagnosed` or `insufficient_evidence`).
4. **Safety & Security:** Read-only access to filesystem outside `fixtures/scenarios` is rejected. No secrets or `.env` keys exposed.

### Proposed Endpoints

| HTTP Method | Endpoint Path | Function & Backend Mapping |
|---|---|---|
| `GET` | `/api/health` | System health check (`netcoop doctor` equivalent) |
| `GET` | `/api/scenarios` | Lists 7 benchmark scenarios with symptom summaries and metadata |
| `GET` | `/api/scenarios/{id}/topology` | Returns scenario NetworkX topology graph (nodes, links, interfaces) |
| `POST` | `/api/runs` | Triggers a diagnostic run on a scenario or custom capture directory |
| `GET` | `/api/runs/{id}` | Status polling: `queued`, `running`, `completed`, `failed` |
| `GET` | `/api/runs/{id}/telemetry` | Returns timestamped raw observations and computed derived features |
| `GET` | `/api/runs/{id}/topology` | Returns annotated topology (identifying observed symptoms vs inferred impact) |
| `GET` | `/api/runs/{id}/events` | Returns structured workflow execution event log |
| `GET` | `/api/runs/{id}/events/stream` | Server-Sent Events (SSE) live execution stream |
| `GET` | `/api/runs/{id}/findings` | Returns specialist tower findings (Performance, Infra, Conn, Services) |
| `GET` | `/api/runs/{id}/tasks` | Returns task dispatcher lifecycle and peer query records |
| `GET` | `/api/runs/{id}/report` | Returns certified `FinalReport` (JSON and rendered Markdown) |
| `GET` | `/api/runs/{id}/evaluation` | Evaluates run against hidden ground truth (only accessible post-diagnosis) |
| `POST` | `/api/runs/{id}/assistant` | Multi-turn read-only explanation assistant (explains report, evidence, gate) |

---

## 3. Event Delivery Strategy: Server-Sent Events (SSE) with Polling Fallback

### Comparison
- **WebSockets:** Bidirectional protocol; unnecessary complexity for one-way server-to-client telemetry and task execution events.
- **HTTP Polling:** Simple, but introduces 500ms–1s latency jitter during multi-agent investigation.
- **Server-Sent Events (SSE) (Recommended):**
  - Standard HTTP, native browser `EventSource` API, zero extra client dependencies.
  - One-way streaming perfectly matches the diagnostic lifecycle: backend publishes typed events (`run.started`, `tower.completed`, `gate.check.completed`, `report.published`), browser renders live pipeline progress.
  - If SSE connection drops or is blocked by proxies, client gracefully falls back to `/api/runs/{id}` and `/api/runs/{id}/events` polling.

---

## 4. Proposed Repository Directory Structure

```text
NetCoopAI-dashboard/
├── src/
│   ├── netcoop/                    # EXISTING BACKEND PYTHON CODE (Untouched diagnostic core)
│   │   ├── cli/
│   │   ├── communication/
│   │   ├── features/
│   │   ├── ingestion/
│   │   ├── models/
│   │   ├── storage/
│   │   ├── supervisor/
│   │   └── towers/
│   └── netcoop_api/                # NEW: THIN BACKEND HTTP ADAPTER (Phase 2)
│       ├── __init__.py
│       ├── app.py                  # FastAPI application entrypoint and CORS config
│       ├── events.py               # In-memory execution event queue & SSE broadcaster
│       ├── routes/
│       │   ├── assistant.py        # Read-only incident explanation assistant endpoint
│       │   ├── health.py           # System status endpoint
│       │   ├── runs.py             # Diagnostic run management and artifact retrieval
│       │   └── scenarios.py        # Scenario catalog and topology retrieval
│       └── schemas.py              # Pydantic v2 request/response schemas
├── web/                            # NEW: REACT + VITE FRONTEND APPLICATION (Phase 3-5)
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── src/
│   │   ├── App.tsx                 # Root layout, navigation shell, header
│   │   ├── index.css               # Tailwind & Dark NOC color palette
│   │   ├── api/                    # Typed API client and SSE event listener hooks
│   │   ├── components/
│   │   │   ├── common/             # Badges, modals, cards, tabs, confidence meters
│   │   │   ├── layout/             # Sidebar, Header, Breadcrumbs
│   │   │   ├── topology/           # Interactive network graph canvas (nodes, links, paths)
│   │   │   ├── telemetry/          # Time-series charts, metric scrubbers, playback controls
│   │   │   ├── investigation/      # Tower cards, message fabric log, task dispatcher
│   │   │   ├── gate/               # Evidence Release Gate verification card
│   │   │   ├── report/             # FinalReport summary and Markdown renderer
│   │   │   └── assistant/          # Incident Explanation Assistant drawer
│   │   ├── pages/
│   │   │   ├── NetworkSimulation.tsx  # Page 1: Scenario selector, topology, playback
│   │   │   └── IncidentIntelligence.tsx # Page 2: Telemetry, towers, gate, final report
│   │   └── types/                  # TypeScript contract definitions matching Pydantic schemas
│   └── public/
├── docs/                           # Documentation and Phase Plans
│   ├── FRONTEND_ARCHITECTURE.md
│   ├── FRONTEND_PROJECT_PLAN.md
│   └── FRONTEND_CHANGELOG.md
└── tests/
    ├── unit/                       # Existing backend unit tests (all 214 passing)
    └── api/                        # NEW: FastAPI endpoint regression tests (Phase 2)
```

---

## 5. Security & Safety Boundaries

1. **Local by Default:** API binds to `127.0.0.1:8000` with strict CORS origins restricted to local development ports (`http://localhost:5173`).
2. **Filesystem Sandbox:** Scenario loading is restricted to validated directories (`fixtures/scenarios/` and explicitly provided capture paths). Path traversal (`..`) attempts are blocked.
3. **Quarantined Ground Truth:** The assistant and diagnostic towers cannot access ground truth files. Only the evaluator route can read `ground_truth.json`, and strictly after report publication.
4. **Credential Isolation:** The frontend bundle contains zero API keys. OpenRouter requests are handled exclusively on the backend via server-side environment variables.
5. **Read-Only Assistant Guardrails:** The explanation assistant cannot mutate reports, restart investigations, dispatch tasks, or alter gate outcomes.
