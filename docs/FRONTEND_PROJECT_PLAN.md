# NetCoop AI Frontend Project Plan
**Dashboard, Backend Integration & Incident Explanation Assistant**

---

## 1. Executive Summary & Baselines

- **Project:** NetCoop AI — Multi-Agent Network Root Cause Analysis Dashboard
- **Backend Protected Branch:** `hackathon/team-integration` (remains untouched during dashboard development)
- **Frontend Dedicated Branch:** `feature/netcoop-dashboard`
- **Git Worktree Path:** `/Users/abhisuryawanshi/Netcoop /NetCoopAI-dashboard`
- **Backend Baseline Commit:** `6b4437e` (`bug fixes and system prompt improved`)
- **Remote Synchronization:** Up to date with `origin/hackathon/team-integration`
- **Backend Test Status:** 214 of 214 tests passing (`pytest -q`), `ruff check .` clean, `netcoop doctor` all OK

---

## 2. Current Architecture & Existing Capabilities

The existing backend is a fully featured, deterministic, multi-agent network incident diagnosis platform:

1. **Ingestion & Normalization (`src/netcoop/ingestion/`):**
   - Multi-format parsing: JSON, JSONL, narrow & wide CSV.
   - Timestamp normalization to UTC, entity alias remapping, unit standardization.
   - Strict malformed record quarantine.
2. **Feature Engineering Pipeline (`src/netcoop/features/`):**
   - Monotonic counter-rate calculation with 32-bit and 64-bit wrap/reset handling.
   - Rolling statistics (SMA, EWMA), and robust anomaly detection (MAD Z-scores).
3. **Knowledge Plane (`src/netcoop/storage/sqlite.py`):**
   - Relational SQLite schema persisting observations, derived features, inter-agent messages, tower findings, hypotheses, supervisor proposals, gate check results, and final reports.
4. **Integration Fabric (`src/netcoop/communication/`):**
   - `EventBus`: Priority-ordered topic publish/subscribe with deduplication.
   - `QueryRouter`: Bounded 1-hop read-only peer queries (e.g., Services asks Connectivity to trace a service path).
   - `TaskDispatcher`: Supervisor-to-tower delegation with counter-proposal lifecycle.
5. **Specialist Diagnostic Towers (`src/netcoop/towers/`):**
   - `PerformanceTower`: Saturation, queue drops, packet loss, Wi-Fi RSSI/SNR attenuation.
   - `InfrastructureTower`: CPU/memory saturation, link flaps, CRC errors, syslog bursts.
   - `ConnectivityTower`: Graph topology, blast radius, partition isolation, uplink chokepoints.
   - `ServicesTower`: DNS latency/SERVFAIL, DHCP lease exhaustion, config drift.
6. **Supervisory Synthesis & Evidence Release Gate (`src/netcoop/supervisor/`):**
   - `SupervisorRuntime` & `SupervisoryRCAAgent`: Cross-domain conflict arbitration, bounded investigation budgeting, hypothesis pruning.
   - `EvidenceReleaseGate`: Independent gatekeeper that strictly verifies cited observation IDs before releasing any diagnosis, eliminating hallucination.
   - `SymptomContextAgent` & `Supplementary`: Post-gate supplemental path reachability analysis and user-reported symptom comparison.
7. **Existing Interfaces (`src/netcoop/cli/main.py`):**
   - Commands: `doctor`, `validate`, `ingest`, `diagnose`, `triage`, `scenarios`, `demo`, `inspect`, `profile-init`, `profile-validate`.
   - Formats: Terminal Rich UI, Markdown report generator, structured JSON export.

---

## 3. Frontend Integration Gaps

1. **No HTTP / Web Service Layer:** Current execution is exclusively triggered via Typer CLI or direct Python import. An asynchronous, lightweight HTTP API layer is required to bridge the browser and backend services.
2. **Execution Event Streaming:** CLI currently writes Rich terminal output and `--explain` logs to stderr. Web clients need typed, structured JSON execution events (via Server-Sent Events or polling) without parsing terminal ANSI text.
3. **Topology Graph Rendering:** NetworkX topology models must be serialized to node/link graph structures suitable for interactive browser visualization (e.g., Canvas / SVG / Force-directed layout).
4. **Interactive Telemetry Playback:** Stored scenario observations need a visual playback controller (start, pause, scrub, step) that simulates time-series arrival without misrepresenting it as live network telemetry.
5. **Incident Explanation Assistant Interface:** A read-only multi-turn Q&A panel operating on actual incident artifacts (findings, evidence, gate results, supervisor decisions) with optional OpenRouter support and local deterministic fallback.

---

## 4. Planned Development Phases

- **Phase 0 — Repository Audit & Frontend Branch Establishment** *(Current)*
  - Establish `feature/netcoop-dashboard` worktree at baseline `6b4437e`.
  - Verify baseline tests (214/214 passing) and CLI stability.
  - Create project plan and initial changelog.
- **Phase 1 — Technology & Integration Architecture**
  - Compare frontend stacks (React+Vite vs. Next.js vs. Streamlit).
  - Design lightweight backend HTTP adapter (FastAPI) and event transport (SSE).
  - Define directory structure, API contracts, and safety boundaries.
  - Submit recommendation to user for technology stack selection.
- **Phase 2 — Backend Integration & API Foundation**
  - Implement FastAPI application service layer wrapping existing `SupervisorRuntime`, `TelemetryLoader`, and SQLite repository.
  - Expose endpoints for scenarios, runs, topology, telemetry, findings, gate audit, and structured execution events.
  - Implement SSE / polling event stream.
  - Add API integration test suite and verify CLI regression.
- **Phase 3 — Frontend Foundation & Page 1: Network Simulation & Topology**
  - Scaffold approved frontend application shell with dark NOC visual design.
  - Build Page 1: Scenario selector, NetworkX topology graph visualization, node/link state highlighting, and timestamped playback controls.
- **Phase 4 — Page 2: Incident Intelligence**
  - Build Page 2: Telemetry time-series charts, raw/derived evidence inspector, four tower finding cards, integration fabric message logs, supervisor conflict arbitration, Evidence Release Gate verification card, and certified FinalReport renderer.
- **Phase 5 — Incident Explanation Assistant (Option A)**
  - Contextual multi-turn side drawer operating strictly on certified incident artifacts.
  - Read-only Q&A explaining findings, supervisor decisions, gate checks, and limitations.
  - Optional OpenRouter LLM integration with deterministic rule-based fallback; zero RAG.
- **Phase 6 — End-to-End Testing & Hardening**
  - Full backend regression, API test suite, frontend component/e2e testing.
  - Safety verification: zero ground-truth leakage, read-only assistant guardrails, offline diagnosis durability.
- **Phase 7 — Judge Demonstration & Documentation**
  - Author live walkthrough script `docs/FRONTEND_DEMO_SCRIPT.md`.
  - Prepare documentation packages and README guides for reproducible evaluation.
