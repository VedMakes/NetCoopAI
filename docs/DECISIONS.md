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

