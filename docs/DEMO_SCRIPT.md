# NetCoop AI: 3-5 Minute Demonstration Script

This script provides an interactive, live demonstration walkthrough of the NetCoop AI Multi-Agent Network Root Cause Analysis system.

---

## Executive Summary & Narrative Hook (30 seconds)

> **Speaker / Presenter:**
> *"Campus and enterprise networks generate millions of telemetry signals every hour. When outages happen, Network Operations Centers (NOCs) are overwhelmed with cascading alarms across switches, Wi-Fi access points, and service daemons. NetCoop AI solves this using an autonomous multi-agent cooperative architecture. Four domain specialist towers collaborate across an asynchronous message fabric, synthesized by a Supervisory RCA Agent, and certified by a zero-hallucination Evidence Release Gate. Most importantly: NetCoop AI runs 100% offline, deterministically, with zero mandatory cloud LLM dependencies."*

---

## Act 1: System Health & Zero-Config Verification (30 seconds)

Demonstrate system readiness and architecture component verification using `netcoop doctor`.

### Command:
```bash
uv run netcoop doctor
```

### What to highlight:
- **Canonical Vocabulary:** 13 verified metrics loaded and mapped into domain vocabularies.
- **Capability Registry:** Four specialist domain towers (Performance, Infrastructure, Connectivity, Services) registered with explicit bounded competencies.
- **SQLite Knowledge Plane:** Ephemeral or persistent SQLite database for audit-grade findings and event persistence.
- **Evidence Release Gate:** Guardrail runtime ready to enforce provenance and citation validation before any report leaves the system.

---

## Act 2: Benchmark Scenarios & Ground Truth Catalog (30 seconds)

Display the synthetic benchmark scenarios packaged directly with the repository.

### Command:
```bash
uv run netcoop scenarios
```

### What to highlight:
- **7 Benchmark Scenarios:** Covering healthy baselines (`healthy`), performance degradation (`link_congestion`), edge wireless issues (`weak_wifi`), core switch resource exhaustion (`device_overload`), and service layer faults (`dns_failure`, `dhcp_failure`, `interface_fault`).
- **Separation of Concerns:** Ground truth files are strictly quarantined in `fixtures/scenarios/<scenario>/ground_truth.json` for benchmarking and never leaked to diagnosis agents.

---

## Act 3: Live Incident Diagnosis & Rich Visual Triage (90 seconds)

Run a live diagnosis on an active incident scenario (`link_congestion`), demonstrating multi-tower collaboration, hypothesis formation, and root cause synthesis.

### Command:
```bash
uv run netcoop diagnose fixtures/scenarios/link_congestion
```

### What to walk through:
1. **Header & Context:** Incident ID, telemetry observation count, timestamp range, and run mode (`OFFLINE_DETERMINISTIC`).
2. **Domain Specialist Tower Findings:**
   - **Performance Tower:** Identified sustained interface saturation (`97.2%`) on core uplink `SW_CORE_01:Gi0/1` combined with queue drops and packet loss.
   - **Infrastructure Tower:** Verified hardware health (CPU & memory nominal), ruling out device overheating or CPU exhaustion.
   - **Connectivity Tower:** Correlated blast radius across downstream hostel distribution switches.
   - **Services Tower:** Verified DNS and DHCP transactions remain nominal.
3. **Evidence Release Gate Verification:**
   - Shows the gate verifying that every single citation references a valid, unmodified canonical observation ID from the incident history.
   - Status: `PASS_WITH_CORRECTIONS` or `PASS`.
4. **Final Synthesized Diagnosis & Recommendations:**
   - Suspected Root Cause with calibrated confidence score (`0.65`).
   - Actionable remediation recommendations (e.g., dynamic QoS queue reprioritization or link aggregation).

### Exporting Reports (JSON & Markdown):
Show how reports can be exported for automation pipelines or human NOC handoff:
```bash
# Export Markdown for NOC incident management
uv run netcoop diagnose fixtures/scenarios/weak_wifi --format markdown -o report.md
cat report.md

# Export JSON for automated remediation orchestration
uv run netcoop diagnose fixtures/scenarios/device_overload --format json -o report.json
cat report.json | jq .
```

---

## Act 4: The Zero-Hallucination Evidence Gate & Clean Abstention (45 seconds)

Show how NetCoop AI handles normal, healthy telemetry without hallucinating false positive alarms.

### Command:
```bash
uv run netcoop diagnose fixtures/scenarios/healthy
```

### What to highlight:
- **Calibrated Abstention:** When metrics are within normal baseline thresholds, the system does not invent problems to look clever.
- **Outcome:** Gate Outcome `ABSTAIN` with confidence `0.0`.
- **NOC Value:** Drastically reduces alert fatigue by certifying healthy network operation.

---

## Act 5: Automated 5-Scenario Offline Benchmark Suite (45 seconds)

Execute the end-to-end multi-scenario benchmark with a single command to prove system consistency.

### Command:
```bash
uv run netcoop demo
```

### What to highlight:
- Runs automatically across all 5 primary benchmark scenarios:
  1. `Healthy Baseline` -> Diagnosed as `ABSTAIN` (clean non-escalation).
  2. `Link Congestion` -> Diagnosed as `LINK_CONGESTION` on `SW_CORE_01:Gi0/1`.
  3. `Weak Wi-Fi` -> Diagnosed as `WEAK_WIFI` on `AP_HOSTEL_01`.
  4. `Device Overload` -> Diagnosed as `DEVICE_OVERLOAD` on `SW_CORE_01`.
  5. `DNS Resolver Failure` -> Diagnosed as `DNS_FAILURE` on `SRV_DNS_01`.
- **Zero LLM Calls Required:** 100% deterministic, zero latency jitter, fully auditable.
- **All Findings Gate-Certified:** Zero hallucinations or ungrounded claims.

---

## Summary Takeaways for Judges / Reviewers

1. **True Specialist Architecture:** Not a monolithic prompt; four modular domain towers with bounded vocabularies and distinct responsibilities.
2. **Deterministic-First, LLM-Optional:** Works completely offline without API keys, but seamlessly upgrades with `--llm auto` or `--llm on` when keys are provided.
3. **Rigorous Guardrails:** The Evidence Release Gate programmatically rejects unverified or fabricated claims.
4. **Production-Grade Engineering:** Comprehensive test suite (132 unit tests), SQLite event/finding store, Rich terminal UI, and CLI automation.
