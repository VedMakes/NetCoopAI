# NetCoop Decision Log

Record non-trivial decisions here. Do not silently change architecture, public contracts, phase ownership or data semantics.

Use this format:

```text
## DEC-XXX: Short title
- Date:
- Status: PROPOSED / ACCEPTED / REJECTED / SUPERSEDED
- Proposed by:
- Agreed by: Friend A / Friend B
- Context:
- Decision:
- Alternatives considered:
- Consequences and migration impact:
- Related files/tests:
```

## DEC-001: Python-first CLI modular monolith
- Date: 2026-10-31
- Status: ACCEPTED
- Agreed by: Initial project architecture
- Context: 24-hour hackathon and small two-person team.
- Decision: Use Python as the primary language, a local modular monolith, and Typer + Rich CLI. Low-level languages are permitted only after profiling and explicit agreement.
- Alternatives considered: Distributed microservices, web dashboard, low-level implementation.
- Consequences and migration impact: Keep module boundaries clear, but do not add deployment infrastructure to the MVP.

## DEC-002: Four deterministic domain towers with optional specialist reasoning
- Date: 2026-10-31
- Status: ACCEPTED
- Agreed by: Initial project architecture
- Context: Network evidence spans several domains and routine processing should not depend on LLMs.
- Decision: Implement Performance, Infrastructure, Connectivity, and Services/Configuration towers. Deterministic engines perform the routine analysis. Specialist LLM capabilities are conditional.
- Alternatives considered: One general-purpose agent, four continuously active LLM agents.
- Consequences and migration impact: All towers expose typed, testable interfaces and can operate in LLM-off mode.

## DEC-003: Supervisor authority and independent release gate
- Date: 2026-10-31
- Status: ACCEPTED
- Agreed by: Initial project architecture
- Context: A single case-level diagnosis must reconcile specialist findings without allowing unsupported claims.
- Decision: SupervisorRuntime controls workflow and task authority. SupervisoryRCAAgent proposes cross-domain diagnosis. EvidenceReleaseGate independently validates publication eligibility.
- Alternatives considered: Majority vote, one specialist owning final output, agent self-approval.
- Consequences and migration impact: Only SupervisorRuntime creates persistent investigation tasks. No diagnosis is published without a passing gate.

## DEC-004: Minimal local communication infrastructure
- Date: 2026-10-31
- Status: ACCEPTED
- Agreed by: Initial project architecture
- Context: Interoperability is important, but external infrastructure is not justified in a 24-hour MVP.
- Decision: Use Pydantic contracts, an in-process EventBus, a QueryRouter, a Supervisor-authorized TaskDispatcher, SQLite persistence, a static capability registry and a shared vocabulary file.
- Alternatives considered: Kafka, NATS, RabbitMQ, A2A server, MCP server.
- Consequences and migration impact: Keep interfaces transport-neutral so an external broker or A2A adapter can be added later.

## DEC-005: One topology graph and one database
- Date: 2026-10-31
- Status: ACCEPTED
- Agreed by: Initial project architecture
- Context: Avoid unnecessary state stores and graph infrastructure.
- Decision: Use one in-memory NetworkX graph for network topology and one SQLite database for incidents, events, findings, tasks, task results and reports. Store evidence relationships as typed records and references, not as a second graph database.
- Alternatives considered: Multiple graph databases, separate evidence graph, multiple persistence systems.
- Consequences and migration impact: Rebuild the in-memory topology graph from loaded inputs when starting a new run.

## DEC-006: Python 3.12 runtime and uv package manager
- Date: 2026-10-31
- Status: ACCEPTED
- Proposed by: Friend A
- Agreed by: Friend B
- Context: Need consistent Python environment isolation, reproducible dependency resolution, and fast tooling.
- Decision: Target Python 3.12+ (CPython 3.12.3 / 3.12.13) as primary runtime, with `uv` as project and environment manager.
- Alternatives considered: Poetry, Pipenv, raw venv + pip.
- Consequences and migration impact: Virtual environments are created with `uv venv --python 3.12` and locked via `pyproject.toml`.

## DEC-007: Organizer sample telemetry generator schema adoption
- Date: 2026-10-31
- Status: ACCEPTED
- Proposed by: Friend A
- Agreed by: Friend B
- Context: The challenge brief links to an official Google Colab notebook providing synthetic network telemetry.
- Decision: Adopt the organizer sample telemetry schema (`timestamp`, `device_id`, `metrics` dict with `cpu_utilization_pct`, `link_utilization_pct`, `packet_loss_pct`, `latency_ms`, `jitter_ms`, `queue_drops`, `interface_errors`, and top-level `status`) as the baseline input format for telemetry ingestion, while accommodating canonical observation extensions in Phase 1.
- Alternatives considered: Pure custom synthetic schema without organizer alignment.
- Consequences and migration impact: Ingestion and contracts will natively parse and validate this schema structure while mapping it cleanly to canonical typed observations.

## DEC-008: Preserve temporal evidence and consume bounded specialist artifacts
- Date: 2026-10-31
- Status: ACCEPTED
- Context: Runs on the repository's own generator correctly classified the seven presets, but a single fault-like sample in an otherwise healthy time series was diagnosed as confirmed congestion. Reports also mixed baseline observations into fault evidence. A merged DNS-plus-congestion capture was reduced to one primary cause, and delegated task results were only logged rather than passed back to the supervisor.
- Decision: Correlate congestion signals by sample time, require repeated pressure in a time series, keep a single complete snapshot low confidence, and identify sparse temporal support in report limitations. Cite only out-of-threshold observations and preserve their values, units, sources and timestamps. Allow disjoint fault hypotheses to appear as concurrent causes unless a known causal conflict requires investigation. Infer direct impact only from supplied topology and label it as inferred. Route tasks to the tower owning the declared capability, return a versioned diagnostic artifact, validate incident scope and contracts, then merge accepted findings into the supervisor dossier before arbitration.
- Research basis: This manager-owned workflow follows the manager pattern described in [OpenAI's orchestration guidance](https://developers.openai.com/api/docs/guides/agents/orchestration). The task lifecycle and separate result artifact are compatible with concepts in the [A2A specification](https://a2a-protocol.org/v1.0.0/), without claiming A2A wire-protocol conformance. The hierarchy, capability routing, task lifecycle and semantic vocabulary choices are also consistent with relevant design areas in [ETSI GS ZSM 022](https://www.etsi.org/deliver/etsi_gs/ZSM/001_099/022/01.01.01_60/gs_ZSM022v010101p.pdf), especially clauses 4.3, 5.3 and 5.4; this project does not claim ETSI conformance.
- Alternatives considered: Peak-only thresholding; treat every competing hypothesis as an alternative cause; dispatch based on the first tower mentioned in a conflict; keep specialist results as unvalidated log text.
- Consequences and migration impact: Diagnoses from sparse data are explicitly lower confidence. Concurrent faults remain visible in JSON and Markdown. Task handlers must use the shared artifact schema and report task failures instead of substituting unrelated defaults.

## DEC-009: Exercise and expose a bounded peer query in service incidents
- Date: 2026-10-31
- Status: ACCEPTED
- Context: The QueryRouter was implemented and unit-tested, but the ordinary diagnose path did not demonstrate a peer request affecting supervisory reasoning or report output.
- Decision: When DNS/DHCP hypotheses have a matching service dependency, Services asks Connectivity for a read-only path trace. Store the request, response, evidence references and warnings in the dossier and final report; use a completed path result when resolving DNS-versus-routing hypotheses.
- Evidence: The repository generator's DNS preset returns `reachable=true` for HOSTEL_ZONE_A to SRV_DNS_01, with four link evidence references; the DHCP preset now exercises the matching relay path too. A compound DNS+DHCP capture records both queries. The 21-case generator matrix (seven presets x three seeds) retained 100% exact class and target matches after this change.
- Research basis: ETSI GS ZSM 022 covers agent communication, task delegation and semantic interoperability (clause 5.3 and 5.4); this implementation borrows the bounded capability interaction pattern and does not claim conformance. [ETSI GS ZSM 022](https://www.etsi.org/deliver/etsi_gs/ZSM/001_099/022/01.01.01_60/gs_ZSM022v010101p.pdf).
- Alternatives considered: Keep peer queries as isolated API features; add unbounded tower-to-tower chat.
- Consequences and migration impact: Successful, unknown, skipped, and failed peer interactions are auditable in the report. Queries are limited to cases with a topology-declared DNS/DHCP dependency and capped at eight unique pairs per incident; missing topology does not trigger a guessed query, and incomplete topology does not make an absent route proof of an outage.

