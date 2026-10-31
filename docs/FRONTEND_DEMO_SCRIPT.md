# NetCoop AI — Judge Demonstration Walkthrough Script

**Platform:** NetCoop AI — Cooperative Multi-Agent Network Incident Diagnosis & Explanation Platform  
**Target Audience:** Hackathon Judges, Senior Network Architects, and NOC Evaluators  
**Presentation Time:** 3 – 5 minutes  
**Primary Branch:** `feature/netcoop-dashboard`

---

## 1. Executive Summary & Elevator Pitch (30 Seconds)

> *"In enterprise and campus networks, an outage triggers thousands of noisy telemetry alerts across disparate devices. Network engineers suffer alert fatigue, while generic LLMs hallucinate plausible-sounding but unverified causes.*
> 
> *NetCoop AI solves this with an **evidence-backed, cooperative multi-agent diagnostic platform**. Four specialist towers—**Performance, Infrastructure, Connectivity, and Services**—collaborate through an Integration Fabric. A supervisory agent synthesizes findings into a candidate diagnosis, but **no report is ever released to operators until an independent Evidence Release Gate verifies every observation reference against the SQLite Knowledge Plane**.*
> 
> *Today we are demonstrating NetCoop's dark-mode NOC dashboard, interactive NetworkX topology simulation, audit gate verification, and grounded read-only explanation assistant."*

---

## 2. One-Command Setup & Launch (15 Seconds)

NetCoop AI compiles into a unified FastAPI + React 18 production bundle that requires zero external cloud dependencies.

### Step 1: Start the unified backend & web dashboard

```bash
# In the repository root
uv run netcoop api --port 8000
```

### Step 2: Open the dashboard

Navigate to **`http://127.0.0.1:8000/ui`** in any modern web browser.

*(For active frontend development with hot-reloading: run `cd web && npm run dev` and navigate to `http://127.0.0.1:5173`.)*

### Step 3: Quick System Health Check

Point out the live status indicator in the top header:
- Backend: **Online (`/api/health`)**
- Engine: **CPython 3.12 (schema v1, 13 canonical metrics)**
- Towers: **4 Domain Controllers Active**
- Evidence Gate: **Deterministic Release Barrier Ready**

---

## 3. Live Demonstration Walkthrough (3 – 4 Minutes)

Follow this structured step-by-step sequence to deliver a high-impact, rubric-aligned presentation.

---

### Act I: Network Simulation & Interactive Topology (Page 1)

1. **Select Scenario:**
   - In the **Benchmark Scenario Selector**, click **`link_congestion`** (*Core Uplink Congestion*).
   - Note the scenario description: *"High link utilization on core switch Gi0/2 resulting in buffer queue drops and packet loss."*
   - Note the benchmark badge: **12 Nodes, 14 Links, Ground Truth Isolated**.

2. **Inspect Campus Topology Visualization:**
   - Highlight the interactive SVG network topology graph:
     - **Gateway:** `GW_EDGE_01` (Campus Edge Gateway)
     - **Backbone Core:** `SW_CORE_01` (Core Switch)
     - **Distribution:** `SW_DIST_HOSTEL`, `SW_DIST_DEPT_A`, `SW_DIST_DEPT_B`
     - **Access Points:** `AP_HOSTEL_A`, `AP_HOSTEL_B`, `AP_DEPT_A`
     - **Critical Services:** `SRV_DNS_01`, `SRV_DHCP_01`
   - Click on `SW_CORE_01` to show the **Node Inspector card** displaying device role, type, and nominal status.

3. **Trigger Autonomous Multi-Agent Diagnosis:**
   - Set LLM Mode to **`Auto`** (or **`Off`** for 100% offline determinism).
   - Click the cyan **"Run Multi-Agent Diagnosis"** button.
   - Point out the **Live Status Bar**:
     - Status transitions from `Queued` → `Running` → `Completed`.
     - Event Ticker streams real-time Integration Fabric milestones:
       - `ingestion.completed` (1,156 observations ingested)
       - `features.computed` (Monotonic counter rates, SMA, EWMA, MAD Z-scores)
       - `towers.started` (Performance, Infrastructure, Connectivity, Services towers dispatched)
       - `tower.completed` (Performance tower identifies critical congestion candidate)
       - `gate.check.completed` (Independent Evidence Release Gate audit)
       - `report.published` (Final certified report published)

4. **Observe Dynamic Topology Propagation:**
   - In the topology view, point out that nodes automatically update:
     - **`SW_CORE_01:Gi0/2`** glows red as **Probable Root Cause**.
     - **`SW_DIST_HOSTEL`**, **`AP_HOSTEL_A`**, **`AP_HOSTEL_B`**, and **`HOSTEL_ZONE_A`** turn purple/amber as **Inferred Blast Radius**.

5. **Demonstrate Telemetry Playback Controller:**
   - Below the topology graph, point out the **Timeline Playback Bar** (Steps 0 to 15).
   - Click **Play** to watch observations stream across time.
   - Scrub the slider to Step 8 (the moment buffer queues overflowed).
   - Note the disclaimer pill: *"Visual replay of timestamped scenario observations"*.

---

### Act II: Incident Intelligence & Verification Audit (Page 2)

Click the **"Incident Intelligence & Evidence"** tab in the top navigation bar.

1. **Executive NOC Incident Brief:**
   - **Diagnosed Root Cause:** `LINK_CONGESTION: Repeated high utilization and link pressure support congestion on SW_CORE_01:Gi0/2 (8 correlated samples)`.
   - **Confidence Score:** **65% (`moderate`)** — calibrated, realistic confidence bounded by evidence coverage.
   - **Affected Devices Breakdown:**
     - *Directly Affected:* `SW_CORE_01:Gi0/2`
     - *Inferred Blast Radius:* `SW_DIST_HOSTEL`, `AP_HOSTEL_A`, `AP_HOSTEL_B`, `HOSTEL_ZONE_A`
   - **Predicted Topology Impacts Table:**
     - Shows multi-hop propagation: `SW_CORE_01:Gi0/2` → `SW_DIST_HOSTEL` (1 hop) → `AP_HOSTEL_A` (2 hops) → `HOSTEL_ZONE_A` (3 hops).
   - **Prioritized Remediation Actions:**
     1. Inspect interface QoS queue policies and drop statistics on affected link.
     2. Review top talkers and traffic flows traversing the congested interface.
     3. Evaluate traffic shaping or rerouting paths away from saturated uplink.

2. **The Evidence Release Gate Verification Card:**
   - **Highlight this key architectural differentiator to judges:**
     > *"Most AI systems send prompts directly to an LLM and show the output to the user. NetCoop AI places an independent, non-LLM verification gatekeeper between the supervisor and the operator."*
   - Show the **Gate Outcome Badge:** `PASS_WITH_LIMITATIONS`.
   - Point out the 4 objective deterministic checks:
     - `root_cause_present`: PASSED
     - `confidence_sufficient`: PASSED
     - `supporting_findings_present`: PASSED (1 cited finding reference)
     - `contradiction_disclosure`: PASSED (competing hypotheses disclosed)
   - Show the transparent **System Limitations & Caveats**:
     - *"Diagnosis based on a single evidence stream without independent cross-domain corroboration."*

3. **Specialist Diagnostic Towers Matrix (Tab 2):**
   - Click the **"Specialist Towers"** sub-tab.
   - Point out that 4 distinct towers ran compartmentalized investigations:
     - **Performance Tower:** Identified `critical` congestion candidate with 0.94 anomaly confidence.
     - **Infrastructure Tower:** Reported nominal hardware health (no CPU overload, no power faults).
     - **Connectivity Tower:** Validated reachability graph and computed downstream blast radius.
     - **Services Tower:** Confirmed DNS/DHCP operational.
   - Click on the Performance Tower card to expand findings and hypotheses.

4. **Telemetry & Evidence Inspector (Tab 3):**
   - Click the **"Telemetry & Evidence"** sub-tab.
   - Show the **SVG Time-Series Chart**:
     - Filter by metric: `link_utilization_pct` (shows peak utilization at **97.2%**).
     - Point out the **Red 90% Threshold Alert Line**.
     - Hover over data points to inspect timestamps and exact readings.
   - Show the **Evidence Inspector**:
     - Toggle between **Raw Observations** (1,156 records with observation IDs like `OBS-000321`) and **Derived Features** (rates, EWMA, MAD Z-scores).
     - Click an observation tag on a derived feature to demonstrate 100% provenance traceability.

5. **Supervisor Dispute Resolution & Path Triage:**
   - In Tab 1, scroll down to the **Conflict Arbitration Card**:
     - Shows why alternative hypotheses were downweighted (e.g. secondary CRC errors vs buffer overflow).
     - Shows the **Path Triage Reachability Table** (`HOSTEL_ZONE_A → AP_HOSTEL_A → SW_DIST_HOSTEL → SW_CORE_01: reachable`).

6. **Benchmark Accuracy Evaluation (Tab 5):**
   - Click the **"Benchmark Evaluation"** sub-tab.
   - Show the post-diagnosis evaluation against the quarantined ground-truth file:
     - **Class Match:** `MATCH` (`LINK_CONGESTION` == `LINK_CONGESTION`)
     - **Target Entity:** `LOCALIZED` (`SW_CORE_01:Gi0/2`)
     - **Precision / Recall / F1:** `100% / 100% / 100%`
   - Emphasize to judges: Ground truth was strictly quarantined until diagnosis completed.

---

### Act III: Incident Explanation Assistant (Side Drawer)

Click the **"Incident Assistant"** button in the header.

1. **Highlight the Architecture:**
   - Explain to judges: **Option A (Read-Only Execution Explanation & Report Q&A)**.
   - Zero RAG, zero document hallucination, grounded strictly in certified incident artifacts.

2. **Demonstrate Multi-Turn Inquiries:**
   - Click the preset pill: **"Why was this root cause diagnosed?"**
     - Assistant explains the peak link utilization (97.2%), queue drops (346), and packet loss (3.71%) on `SW_CORE_01:Gi0/2`.
   - Click: **"What remediation steps should be taken first?"**
     - Assistant returns the 3 prioritized mitigation actions with operational notes.
   - Click: **"What are the limitations or uncertainties of this report?"**
     - Assistant discloses that diagnosis is based on a single telemetry stream without cross-domain corroboration.
   - Click: **"Why were competing alternative causes rejected?"**
     - Assistant explains supervisory downweighting.
   - Custom follow-up: Type *"What did the Infrastructure tower find?"*
     - Assistant answers that Infrastructure tower reported nominal CPU and memory health.

3. **Provider Mode Switcher:**
   - Point out the mode pill in the drawer:
     - `Auto LLM` (uses OpenRouter Nemotron-3.5-Lightning when configured).
     - `Deterministic` (100% offline local rule engine, 0ms external latency).

---

### Act IV: Clean Safe Abstention Baseline (Page 1)

1. Return to the **Network Simulation** tab.
2. Select the **`healthy`** scenario (*Normal Campus Baseline*).
3. Click **"Run Multi-Agent Diagnosis"**.
4. Show the outcome:
   - Status: **`insufficient_evidence`**
   - Diagnosed Cause: **`ABSTAIN: Normal telemetry: no significant anomalies detected.`**
   - Confidence: **`0%`**
   - Gate Outcome: **`ABSTAIN (PASSED)`**
5. **Key Takeaway for Judges:**
   > *"NetCoop AI possesses safe abstention. It does not hallucinate faults on nominal networks. It reports insufficient evidence, preventing costly false alarms and unnecessary engineer dispatches."*

---

## 4. Key Architectural Q&A for Judges

| Question | NetCoop AI Answer |
|---|---|
| **How do you prevent LLM hallucinations?** | The LLM does not publish reports. Diagnoses pass through the deterministic **Evidence Release Gate**, which asserts that every cited observation ID exists in SQLite, verifies confidence calibration, and validates that contradictions were disclosed. |
| **Why is there no RAG in this implementation?** | RAG retrieves external text documents that can hallucinate incident facts. NetCoop AI grounds explanations directly in verified runtime incident artifacts (observations, derived features, tower findings, gate audits). |
| **How do you ensure ground-truth isolation?** | Ground truth files are strictly quarantined in `evaluation/`. The diagnostic engine operates without access to them. An automated test (`test_zero_leakage_of_ground_truth_into_runtime`) scans the codebase with AST checks to ensure zero runtime leaks. |
| **What happens if OpenRouter is unreachable or offline?** | NetCoop AI is 100% durable offline. Both the diagnostic engine and the explanation assistant have deterministic fallback implementations that run entirely locally. |
| **What test coverage exists?** | **229 passing automated pytest tests** covering the full stack (towers, fabric, supervisor, evidence gate, FastAPI endpoints, SSE streaming, and CLI commands). |

---

## 5. Quick CLI Commands Reference

Judges who prefer terminal inspection can run:

```bash
# System integrity check
uv run netcoop doctor

# 5-scenario autonomous benchmark evaluation
uv run netcoop demo

# List all 7 benchmark scenarios
uv run netcoop scenarios

# Diagnose a specific scenario with terminal Rich output
uv run netcoop diagnose fixtures/scenarios/link_congestion

# Run diagnostic pipeline with live event trace on stderr
uv run netcoop diagnose fixtures/scenarios/link_congestion --explain

# Run full automated test suite (229 tests)
uv run pytest -q
```
