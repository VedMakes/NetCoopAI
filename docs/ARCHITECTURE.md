# How NetCoop works

NetCoop is a local, read-only network diagnosis tool. It combines telemetry, optional topology, and specialist analyses into an evidence-backed report. It does not log in to devices, change network configuration, or automatically repair faults.

## Diagnosis flow

```mermaid
flowchart LR
    Input[Telemetry and optional topology] --> Normalize[Normalize and validate]
    Normalize --> Towers[Performance, Infrastructure, Connectivity, Services]
    Towers --> Supervisor[Supervisor compares findings]
    Supervisor --> Gate[Evidence gate checks citations and scope]
    Gate --> Report[Report with cause, impact, evidence, uncertainty, actions]
    Report --> Paths[Optional post-decision path traces]
    Report --> Symptom[Optional --symptom cross-check]
```

### 1. Input and normalization

Telemetry can come from JSON, JSONL, or CSV. A capture directory can also include a `topology.json` map. Network profiles map local field names, entity aliases, units, roles, and known thresholds into NetCoop's supported observation model.

Malformed or incompatible data is reported as a warning or quarantined record. Missing data is not replaced with guessed measurements.

### 2. Specialist analysis

Four deterministic towers look at different evidence:

- **Performance:** link pressure, packet loss, latency, and wireless signal quality.
- **Infrastructure:** CPU, memory, interface errors, and device logs.
- **Connectivity:** recorded paths, partitions, and topology-based impact.
- **Services:** DNS, DHCP, and configuration signals.

Towers share the incident observations and can use bounded, typed queries for targeted checks. Query handlers inspect the observations persisted for this incident and the supplied topology; they do not poll live devices. Their findings preserve source and evidence references. When the supervisor detects a supported conflict, relevant specialists can receive structured hypothesis reviews with supporting, contradicting, inspected, and missing-signal fields. Task artifacts (schema 1.1) attach timestamps, source names, values, and limitations to every cited observation; the runtime validates that provenance against the incident store. Reviews over the current store are explicitly marked as re-analysis with no new evidence.

### 3. Diagnosis and evidence gate

The supervisor compares tower findings, resolves supported conflicts, and proposes a diagnosis or abstains. Candidate tasks are ranked by a transparent evidence-coverage, temporal-sampling, source-diversity, decision-impact, and cost heuristic; this is a priority estimate, not a calibrated information-gain probability. If a stored-only capability needs a signal absent from the capture, NetCoop records that signal as unavailable and produces a targeted operator question rather than implying a live probe occurred. Repeated tasks are skipped for an unchanged evidence set; new observation IDs allow a later task attempt. If competing reviews remain inconclusive without new evidence, the supervisor abstains. The independent evidence gate checks claims and remains the publication authority; it returns stable issue codes and allows one bounded retry. The gate itself never selects or writes a diagnosis.

When the optional OpenRouter RCA adapter is enabled, deterministic arbitration still owns the decision and evidence. The model is skipped whenever arbitration requests evidence or abstains. For an approved diagnosis, the adapter accepts only bounded read-only follow-up recommendations; root cause, affected entities, confidence, alternatives, citations, and manifest remain controller-owned. Recommendation actions must use known incident identifiers and pass a read-only action check. The evidence gate rejects an undisclosed competing hypothesis.

Reports separate directly affected entities from topology-inferred candidates. Impact inference follows declared service dependencies or recorded physical links for at most three hops, with at most 50 candidates. Each candidate includes the full entity path, relationship sequence, and topology observation references. Dependency traversal stays within dependency edges to avoid spreading a service fault across unrelated physical links. These remain candidates, not confirmed user impact.

### 4. Supplemental context

After the gate decision, NetCoop may query recorded topology for paths between observed entities and predicted impact candidates. A path means the supplied map contains a route; it does not prove that route caused the reported issue. Partial or unknown topology can make a negative path result inconclusive.

The `--symptom` option invokes a separate context agent after publication. It receives the reported wording, published report, specialist findings, relevant observations, and path results. It can label the wording aligned, mismatched, or unclear, but it cannot revise the diagnosis or send feedback to the supervisor or gate. Without `--symptom`, this agent does not run.

## Reading the impact fields

Reports separate:

- `observed_symptom_entities`: entities tied to cited observation evidence.
- `inferred_affected_entities`: impact candidates inferred from the supplied topology.
- `affected_devices`: compatibility field containing the combined set.

Predicted impact is not confirmation that users experienced an outage. Validate it against operator reports or independent monitoring.

## Outputs and local state

The CLI prints a Rich terminal report by default, or writes JSON and Markdown with `--format json` and `--format markdown`. `--db` stores incident records and reports in SQLite. Without `--db`, the database is temporary and held in memory for the command run.

See the [local input guide](INPUT_FORMATS.md) for file layouts and [network profiles](NETWORK_PROFILES.md) for site adaptation.
