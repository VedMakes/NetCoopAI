---
title: "NetCoop AI: Inter-Agent Communication Implementation Instructions"
subtitle: "Coding-agent execution brief for the supervisor, towers, event bus, query router and task dispatcher"
author: "NetCoop AI Engineering"
date: "31 October 2026"
version: "1.0"
geometry: margin=18mm
fontsize: 10pt
---

# 0. Mission

You are implementing the **inter-agent communication and hierarchy subsystem** for NetCoop AI. Your job is to make the four diagnostic towers collaborate through typed, reliable and bounded interactions under one Supervisory RCA Agent and a deterministic SupervisorRuntime.

This is a 24-hour hackathon product. Keep the implementation local, Python-first, CLI-first and small. Implement real communication semantics, not simulated agent dialogue.

## 0.1 Read these documents first

1. `NetCoop AI challenge brief` (the supplied problem statement PDF). It defines the competition acceptance criteria.
2. `NetCoop_Coding_Agent_Implementation_Playbook.md`. It defines the overall product, CLI, towers, deterministic diagnostics and phased build.
3. `NetCoop_Architecture_Communication_Hierarchy_v2.md`. It is the authoritative architecture for hierarchy and communication.
4. This document. It is the implementation directive for the communication subsystem and overrides earlier communication-specific simplifications where they conflict.

If the repository uses different file names, inspect the actual files and record the mapping in `docs/DECISIONS.md`.

## 0.2 Source-of-truth order

- Challenge brief: competition requirements.
- Architecture v2: system boundaries, hierarchy, communication rules and authority.
- Existing implementation playbook: all other product requirements not contradicted by Architecture v2.
- This file: implementation details for inter-agent communication and hierarchy.

Do not replace useful existing code just to match a proposed folder layout. Inspect before editing.

# 1. Non-negotiable architecture

## 1.1 Hierarchy

- One deterministic `SupervisorRuntime` owns incident lifecycle, task creation, scope expansion, budgets and routing policy.
- One `SupervisoryRCAAgent` owns cross-domain reasoning and the proposed case-level diagnosis.
- Four domain `TowerController` implementations exist: `performance`, `infrastructure`, `connectivity`, `services`.
- Each tower runs deterministic engines first. An optional specialist LLM capability may be added behind the tower interface, but it is not required for the communication core.
- `EvidenceReleaseGate` is independent of the Supervisor Agent and validates every final proposal.
- No tower may publish the final user-facing report or take over case ownership.

## 1.2 Communication mechanisms

Implement exactly three distinct mechanisms:

1. `EventBus`: publish/subscribe facts and state changes.
2. `QueryRouter`: one-hop direct request/response for short deterministic operations.
3. `TaskDispatcher`: persistent, supervisor-authorized multi-step investigations with lifecycle.

Do not implement one generic `send_message()` function that blurs events, queries and tasks.

## 1.3 Authority rules

- Only `SupervisorRuntime` may create persistent `InvestigationTask` records.
- Towers may publish findings/events and issue registered one-hop queries.
- Towers may not create child tasks or expand the incident scope.
- A tower that cannot finish within its declared capability returns `ESCALATED`; the supervisor decides whether to create a new task for another capability.
- The Supervisor Agent may request a task through a tool, but the runtime validates, persists and dispatches it.
- Peer queries are deterministic and do not start a peer LLM conversation.
- No unrestricted LLM-to-LLM chat.
- All diagnostic actions are read-only.

# 2. MVP technology constraints

Use:

- Python 3.11 or later.
- Pydantic v2 for contracts.
- SQLite for persistence.
- One in-process Python EventBus.
- Static YAML capability and vocabulary registries.
- NetworkX only for the network topology graph, not for message routing.
- Typer + Rich for CLI inspection and timeline.
- Pytest for tests.

Do not add Kafka, NATS, RabbitMQ, Redis Streams, Kubernetes, FastAPI, MCP, A2A, a graph database, a second NetworkX evidence graph or another database. Preserve transport-neutral contracts so these could be added later without changing semantics.

Use synchronous in-process dispatch for the hackathon unless repository inspection reveals a real I/O requirement. Do not add asyncio or concurrency solely to look modern. Keep handler execution deterministic and ordered. If any current integration is already async, preserve it and use one consistent adapter.

# 3. Required module boundaries

Adapt to the repository, but keep these responsibilities separate:

```text
src/netcoop/
  communication/
    __init__.py
    events.py          # EventEnvelope, EventBus, subscription models
    queries.py         # PeerQuery, PeerQueryResult, QueryRouter
    tasks.py           # InvestigationTask, TaskStatus, TaskResult, TaskDispatcher
    registry.py        # CapabilityRegistry and profile validation
    vocabulary.py      # canonical meanings, units, event/finding types
    persistence.py     # SQLite repository methods for comms records
  towers/
    base.py            # TowerController Protocol and shared helpers
    performance.py
    infrastructure.py
    connectivity.py
    services.py
  supervisor/
    runtime.py         # deterministic workflow owner
    agent.py           # SupervisoryRCAAgent interface/provider adapter
    verification.py    # EvidenceReleaseGate
  cli/
    ...
config/
  capabilities.yaml
  vocabulary.yaml
tests/
  unit/
  integration/
```

Avoid empty framework layers. If the existing repo is small, files may remain flatter while retaining the logical boundaries.

# 4. Contracts to implement

All external message/task payloads must be Pydantic models. Set `extra="forbid"` for protocol contracts unless an explicit forward-compatible extension bag is needed. Validate schema versions and all IDs. Do not use untyped `dict[str, Any]` for the full public contract; a small `data` payload may be a typed union or explicitly versioned model.

## 4.1 EventEnvelope

Use CloudEvents-inspired context attributes, but do not claim full CloudEvents conformance.

Required fields:

- `specversion: Literal["1.0"]`
- `id: str` unique event ID and idempotency key.
- `source: str` producer identity, such as `netcoop/performance`.
- `type: str` semantic event type, such as `performance.congestion_candidate`.
- `subject: str | None` canonical entity ID when relevant.
- `time: datetime` event creation time, timezone-aware UTC.
- `datacontenttype: Literal["application/json"]`
- `dataschema: str` schema URI/path and version.
- `correlationid: str` incident/investigation identifier.
- `causationid: str | None` event/task result that caused the event.
- `data: typed payload` compact references and metadata.

Do not put full telemetry arrays in an event. Use `finding_refs`, `evidence_refs`, `task_id` and compact status fields.

Example:

```json
{
  "specversion": "1.0",
  "id": "EVT-000104",
  "source": "netcoop/performance",
  "type": "performance.congestion_candidate",
  "subject": "SW-01:Gi0/1",
  "time": "2026-10-31T08:00:00Z",
  "datacontenttype": "application/json",
  "dataschema": "netcoop://schemas/events/congestion-candidate/1.0",
  "correlationid": "INC-104",
  "causationid": "EVT-000099",
  "data": {
    "incident_id": "INC-104",
    "source_tower": "performance",
    "finding_refs": ["F-101", "F-102"],
    "severity": "high"
  }
}
```

## 4.2 PeerQuery and PeerQueryResult

Queries are synchronous deterministic operations.

`PeerQuery` fields:

- `query_id`
- `incident_id`
- `requester`
- `recipient`
- `capability`
- `scope` (canonical entity IDs and optional UTC time window)
- `constraints` (read-only, timeout, result-size limit)
- `expected_schema`
- `created_at`

`PeerQueryResult` fields:

- `query_id`
- `status`: `completed`, `unsupported`, `invalid_scope`, `unauthorized`, `timeout`, `needs_supervisor_task`, `failed`
- `result`: typed capability-specific output or null
- `evidence_refs`
- `warnings`
- `completed_at`

One-hop rule: query handlers cannot call QueryRouter again and cannot create tasks. Enforce this by not injecting QueryRouter/TaskDispatcher into query handler context. If further investigation is needed, return `needs_supervisor_task`.

## 4.3 InvestigationTask

Fields:

- `task_id`
- `incident_id`
- `parent_task_id: str | None`
- `requester` (normally `supervisor`)
- `assignee` (tower ID)
- `capability`
- `objective` (typed scope, entities, time window and requested outcome)
- `constraints` (read-only, deadline, max attempts, max peer queries)
- `expected_result_schema`
- `status`
- `created_at`, `updated_at`, optional `deadline_at`
- optional `result_id`, `error_code`, `error_detail`

Natural-language objective text may be included for explanation, but executable behavior must be determined by the registered capability ID and typed parameters.

## 4.4 TaskStatus and allowed transitions

Statuses:

- `CREATED`
- `ACCEPTED`
- `COUNTER_PROPOSED`
- `DECLINED`
- `RUNNING`
- `COMPLETED`
- `FAILED`
- `ESCALATED`
- `CANCELLED`
- `TIMED_OUT`

Allowed transitions:

```text
CREATED -> ACCEPTED | DECLINED | COUNTER_PROPOSED | CANCELLED | TIMED_OUT
COUNTER_PROPOSED -> ACCEPTED | DECLINED | CANCELLED | TIMED_OUT
ACCEPTED -> RUNNING | CANCELLED | TIMED_OUT | FAILED
RUNNING -> COMPLETED | FAILED | ESCALATED | CANCELLED | TIMED_OUT
```

Terminal states: `DECLINED`, `COMPLETED`, `FAILED`, `ESCALATED`, `CANCELLED`, `TIMED_OUT`.

Permit at most one `COUNTER_PROPOSED` transition per task. A `COUNTER_PROPOSED` task must be resolved by the SupervisorRuntime or accepted under the bounded original policy. A task that escalates is finished; any follow-up must be a new task created by SupervisorRuntime with a new ID and optional `parent_task_id`.

Implement transitions in one function/service. Do not update task status from arbitrary call sites.

## 4.5 TaskResult

TaskResult is the structured output artifact, not a message string.

Fields:

- `result_id`
- `task_id`
- `assignee`
- `status` (must agree with terminal task status)
- `result_schema`
- typed `result` payload
- `finding_refs`
- `evidence_refs`
- `warnings`
- `limitations`
- `completed_at`

Persist findings and TaskResult before emitting the task-completed event.

### Implemented diagnostic artifact (`netcoop://schemas/tasks/diagnostic-artifact/1.0`)

Tower task handlers return a JSON object with these fields:

- `incident_id`, `capability`, `target_entities`
- `findings` and `hypotheses` as serialized canonical contracts (empty for topology-only results)
- `observation_count` and `summary` for telemetry investigations
- `analysis` for topology investigations, with the capability-specific result fields

`TaskResult.finding_refs` and `TaskResult.evidence_refs` repeat the artifact references for routing and audit. The runtime checks the declared result schema, validates finding and hypothesis contracts and incident IDs, then merges accepted findings into the supervisor dossier before its next reasoning pass. Failed, incomplete, or invalid task results remain in task history and are surfaced as orchestration warnings. The supervisor continues to own the incident conclusion.

## 4.6 Finding reference invariants

A finding is a persisted diagnostic record. Events and TaskResults reference it by ID.

Minimum fields should include:

- `finding_id`, `incident_id`, `source_tower`, `producer`
- `finding_type`, `severity`, `status`
- `entity_refs`, `evidence_refs`
- `derived_from`, `independence_group`
- `observed_at`, `created_at`
- `schema_version`, `rule_or_model_version`
- optional `supersedes_finding_id`

A finding is immutable. Create a new record to supersede or retract a finding.

## Implemented end-to-end peer query

For DNS/DHCP diagnoses with declared service dependencies, the Services tower requests `connectivity.trace_path` from Connectivity for each unique affected consumer/provider pair (up to eight queries per incident). The supervisor records typed requests and responses in `IncidentDossier.peer_query_history`, uses completed results to distinguish service failures from path failures, and publishes the exchanges in `FinalReport.peer_interactions`. Both DNS (`HOSTEL_ZONE_A` to `SRV_DNS_01`) and DHCP (`HOSTEL_ZONE_A` to `SRV_DHCP_01`) generator cases are covered; a compound case exercises both paths. Path evidence includes topology observation IDs. Missing dependency data produces no guessed query, and a missing path in partial or unknown topology returns `reachable: null` instead of claiming a partition.

# 5. EventBus requirements

Implement a small, deterministic in-process dispatcher.

Recommended interface:

```python
class EventBus:
    def subscribe(
        self,
        event_type: str,
        consumer_id: str,
        handler: EventHandler,
    ) -> None: ...

    def publish(self, event: EventEnvelope) -> DeliverySummary: ...

    def dispatch_pending(self, limit: int = 100) -> DispatchSummary: ...
```

`publish` should persist the event/outbox entry and then dispatch from the outbox. Do not call subscribers before persistence.

Requirements:

1. Explicit event-type subscriptions.
2. Deterministic subscriber ordering for reproducible runs.
3. Unique event ID.
4. Per-consumer idempotency key `(consumer_id, event_id)`.
5. A failed subscriber is recorded and does not prevent unrelated subscribers from receiving the event.
6. Subscriber failure is visible in CLI and SQLite.
7. A retry policy is bounded and does not retry invalid payloads forever.
8. Unchanged findings are not republished.
9. Event handlers receive only the dependencies they need.
10. Events reference stored findings, not copies of raw data.

Assume at-least-once delivery. Do not claim exactly-once delivery.

## 5.1 SQLite persistence and outbox

Implement the minimum reliable write path:

- In one SQLite transaction, write the finding/task state change and an outbox event.
- Commit.
- Dispatcher reads pending outbox records.
- For each subscriber, create or inspect a delivery row keyed by `(event_id, consumer_id)`.
- Invoke handler if not already completed.
- Mark delivery completed or failed and retain error details.

Suggested tables (adapt to existing schema):

- `events(event_id PRIMARY KEY, event_type, source, subject, correlation_id, causation_id, payload_json, created_at)`
- `outbox(outbox_id PRIMARY KEY, event_id UNIQUE, status, attempts, next_attempt_at, created_at)`
- `event_deliveries(event_id, consumer_id, status, attempts, error, updated_at, PRIMARY KEY(event_id, consumer_id))`
- `processed_events(consumer_id, event_id, processed_at, PRIMARY KEY(consumer_id, event_id))`

If a simpler schema already provides the same guarantees, preserve it. Do not create duplicate stores for identical information.

# 6. QueryRouter requirements

Recommended interface:

```python
class QueryRouter:
    def register(self, tower_id: str, capability_id: str, handler: QueryHandler) -> None: ...
    def request(self, query: PeerQuery) -> PeerQueryResult: ...
```

Requirements:

- Resolve the operation through CapabilityRegistry.
- Validate requester and recipient identity.
- Validate permission and read-only status.
- Validate input model and expected output schema.
- Enforce timeout/result-size constraints where practical.
- Track query ID and persist request/result for debugging.
- Never allow arbitrary method names, imports, shell commands or raw LLM-generated code.
- Do not let query handlers dispatch other queries or tasks.

Initial required handlers:

- Connectivity -> Infrastructure: `inspect_interface_health`.
- Services -> Connectivity: `verify_resolver_reachability`.
- Performance -> Connectivity: `get_paths_for_entities`.
- Infrastructure -> Connectivity: `get_affected_subgraph`.

At least two should be demonstrated end-to-end. All may be simple wrappers around existing deterministic engine methods.

# 7. TaskDispatcher requirements

Recommended interface:

```python
class TaskDispatcher:
    def create_task(self, requester: str, assignee: str, capability: str, objective: BaseModel, constraints: TaskConstraints) -> InvestigationTask: ...
    def accept(self, task_id: str) -> InvestigationTask: ...
    def decline(self, task_id: str, reason: str) -> InvestigationTask: ...
    def counter_propose(self, task_id: str, revised_constraints: TaskConstraints, reason: str) -> InvestigationTask: ...
    def execute(self, task_id: str) -> TaskResult: ...
    def cancel(self, task_id: str, reason: str) -> InvestigationTask: ...
    def get(self, task_id: str) -> InvestigationTask: ...
```

Only SupervisorRuntime may call `create_task`. Enforce this with dependency injection and an authorization check, not a comment alone.

Task execution should:

1. Load the task.
2. Validate task is in an executable state.
3. Resolve the capability.
4. Mark accepted/running through the transition service.
5. Execute the registered handler with a bounded context.
6. Persist findings and TaskResult.
7. Mark completed and emit status event.
8. On out-of-scope request, mark escalated and stop.
9. On exception, mark failed with a safe error code; do not swallow it.

A counterproposal may narrow the scope or relax an impossible constraint, but may not increase permissions, change the incident, add entities beyond authorized scope or turn a read-only task into a write task.

# 8. CapabilityRegistry and vocabulary

## 8.1 Capability registry

Implement startup loading from `config/capabilities.yaml` into validated Pydantic models.

Each tower profile must declare:

- `tower_id`, `domain`, `profile_version`.
- Event subscriptions.
- Capability IDs.
- Interaction kind: `query` or `task`.
- Input and output schema identifiers.
- Read-only permission.
- Maximum duration and result size.
- Whether a specialist LLM review is available (default false).

Minimum capability IDs:

**Performance**
- `calculate_link_utilization` (query)
- `inspect_queue_pressure` (query)
- `inspect_upstream_capacity` (task)
- `challenge_congestion_hypothesis` (task)

**Infrastructure**
- `inspect_interface_health` (query)
- `inspect_device_health` (query/task depending on scope)
- `challenge_device_overload_hypothesis` (task)

**Connectivity**
- `verify_resolver_reachability` (query)
- `get_paths_for_entities` (query)
- `inspect_common_upstream` (task)
- `extract_affected_subgraph` (query/task according to runtime)

**Services / Configuration**
- `test_dns_health` (query)
- `inspect_dhcp_exchange` (query)
- `compare_config_snapshots` (task)
- `challenge_service_failure_hypothesis` (task)

Avoid declaring a capability if there is no implementation behind it. The registry must reject missing handler registrations at application startup or report them as unavailable.

## 8.2 Vocabulary registry

Implement `config/vocabulary.yaml` with canonical metric names, units, directions, entity types, event types, finding types, fault classes, severity, confidence and status enums. Add aliases only when they are validated.

Do not use an LLM to dynamically infer metric units. Unknown semantics must produce a validation warning or rejection.

# 9. Tower controller interface

Use one common protocol. The exact method names may follow existing code, but the responsibilities must remain.

```python
class TowerController(Protocol):
    tower_id: str

    def analyze_incident(self, context: IncidentContext) -> TowerReport: ...
    def handle_query(self, query: PeerQuery) -> PeerQueryResult: ...
    def execute_task(self, task: InvestigationTask) -> TaskResult: ...
```

Towers should not need to know whether the caller is the Supervisor LLM or deterministic SupervisorRuntime. They receive typed inputs and return typed outputs.

`analyze_incident` runs deterministic analyzers. It may publish events after persisting findings. It returns `TowerReport` with:

- `tower_id`
- `status`: `completed`, `no_relevant_finding`, `partial`, `failed`
- `finding_refs`
- `hypothesis_refs`
- `coverage`
- `warnings`
- `unsupported_inputs`
- `llm_invoked: bool`

A tower must return explicit empty/no-relevance status instead of inventing findings.

# 10. SupervisorRuntime and SupervisoryRCAAgent

## 10.1 SupervisorRuntime owns the lifecycle

Suggested interface:

```python
class SupervisorRuntime:
    def create_incident(self, input_bundle: InputBundle) -> Incident: ...
    def run_initial_analysis(self, incident_id: str) -> IncidentRun: ...
    def build_incident_context(self, incident_id: str) -> IncidentContext: ...
    def delegate_task(self, task_request: TaskRequest) -> InvestigationTask: ...
    def arbitrate(self, incident_id: str) -> DiagnosisReport: ...
```

`delegate_task` must resolve capability, verify authorizations and budgets, create the task, execute/monitor it and persist every transition.

## 10.2 Supervisor Agent retains case ownership

Define a provider-neutral interface:

```python
class SupervisoryRCAAgent(Protocol):
    def propose(self, context: IncidentContext, tools: SupervisorTools) -> SupervisorProposal: ...
```

The LLM is optional. Implement `DeterministicSupervisor` or `FakeSupervisorAgent` so tests and offline demo work without credentials.

Expose bounded tools only:

- `get_tower_report(tower_id)`
- `get_finding(finding_id)`
- `get_evidence(evidence_id)`
- `get_related_findings(incident_id, entity_ids, time_window)`
- `request_investigation(assignee, capability, objective, constraints)`
- `request_tower_challenge(tower_id, hypothesis_id, evidence_refs)`

The LLM cannot call arbitrary Python, shell, filesystem, network or device-write operations.

## 10.3 Bounded invocation policy

Initial configuration:

- `llm_mode`: `off`, `auto`, `on`.
- Maximum 2 supervisory model calls per incident.
- Maximum 1 optional tower specialist LLM review per incident.
- Maximum 2 follow-up investigation rounds.
- Maximum 6 persistent tasks per incident.
- Maximum 2 peer queries per task.
- One retry for transient task failure.

These are implementation defaults, not industry standards. Make them configurable and record usage in the incident report.

## 10.4 Context minimization

Do not pass raw telemetry or the full topology to the LLM. Build a compact dossier containing:

- Incident ID and scope.
- TowerReport summaries.
- Top ranked hypotheses and score components.
- Relevant evidence excerpts and IDs.
- Material contradictions.
- Data-quality/coverage warnings.
- Available capability IDs.
- Current investigation budget.

The LLM can request more evidence by ID or by allowed capability. It cannot invent evidence references.

# 11. Conflict resolution protocol

The Supervisor must classify the conflict before trying to resolve it.

| Conflict | Check first | Owner to consult |
|---|---|---|
| Observation | Source, timestamp, sampling, counter reset, quality | Source-owning tower / ingestion |
| Entity identity | Canonical device/interface ID and topology mapping | Connectivity / inventory |
| Temporal | UTC, interval alignment, ingest delay, ordering | Ingestion + relevant towers |
| Semantic | Unit, direction, aggregation window, counter meaning | Semantic registry and domain owner |
| Domain interpretation | Failure mechanism and required discriminating test | Owning tower |
| Causal | Mechanism, temporal precedence, topology, alternate paths | Supervisor with relevant towers |
| Recommendation | Operational risk, evidence and read-only policy | Supervisor; human review for future action |

No majority voting. The Supervisor should compare evidence and source independence. Repeated findings derived from one raw measurement are not independent corroboration.

A challenge response must include:

- `hypothesis_id`
- `challenge_type`
- `supporting_finding_refs`
- `contradicting_finding_refs`
- `requested_checks` (capability IDs only)
- `outcome`: `supported`, `contradicted`, `inconclusive`
- `limitations`

# 12. EvidenceReleaseGate integration

The gate is a deterministic Python component. Do not add another LLM verifier.

The Supervisor Agent returns `SupervisorProposal` with structured claims. Every claim should include:

- `claim_id`, `claim_type`
- `subject_refs`, `time_window`
- `evidence_refs`, `finding_refs`
- `derivation_ref` where relevant
- `contradiction_refs` and disposition
- `confidence_category` and scoring policy

Gate checks:

1. References exist and belong to the incident.
2. Current/superseded status is handled correctly.
3. Entity/time scope matches.
4. Provenance and derivation exist.
5. Units and vocabulary are recognized.
6. Conflicts are surfaced and dispositioned.
7. Same-source evidence is not double-counted.
8. Required fault-signature conditions are present.
9. Confidence category follows documented policy.
10. Output schema is valid.
11. Recommendations are not described as executed actions.

Gate outcomes: `PASS`, `RETURN_FOR_EVIDENCE`, `ABSTAIN_INSUFFICIENT_EVIDENCE`, `ABSTAIN_UNRESOLVED_CONFLICT`, `REJECT_INVALID_REPORT`.

The gate cannot prove the truth of unrestricted prose. The final JSON must be rendered from validated structured claims. Any narrative should be generated from those fields or labelled as interpretation.

# 13. CLI observability requirements

The CLI must expose actual inter-agent communication. Add or extend:

```bash
netcoop demo --scenario congestion --llm off --verbose
netcoop diagnose data/scenarios/incident_001/ --llm auto --verbose
netcoop inspect INC-104 --events
netcoop inspect INC-104 --tasks
netcoop inspect INC-104 --messages
netcoop inspect INC-104 --evidence
```

Show:

- Event ID, type, publisher, subscribers and delivery status.
- Query ID, requester, recipient, capability and result status.
- Task ID, requester, assignee, capability and each state transition.
- Finding IDs referenced by events/results.
- Supervisor LLM invocations and tool/task calls.
- Gate outcome and reason.

Never print pretend messages. Every displayed line must map to a persisted event, query, task or finding.

# 14. Implementation phases

Do not build all phases simultaneously. Keep the CLI working after each phase.

## Phase 0: Repository reconnaissance and contract freeze (30-45 minutes)

- Inspect existing modules, schemas, tests and CLI.
- Read the overall playbook and architecture v2.
- Identify any existing message/task abstractions worth retaining.
- Record decisions and conflicts in `docs/DECISIONS.md`.
- Agree final Pydantic fields and enum values before parallel work.

Exit: contracts are written and have validation tests.

## Phase 1: Registry and contracts (60-90 minutes)

- Implement event, query, task, task-result, capability-profile and tower-report models.
- Implement task transition validator.
- Load and validate `capabilities.yaml` and `vocabulary.yaml`.
- Add sample registry for all four towers.

Exit: all schemas parse; invalid capability or transition is rejected.

## Phase 2: SQLite repository, outbox and EventBus (90 minutes)

- Add events/outbox/delivery/processed-event persistence.
- Implement event subscriptions and deterministic handler order.
- Implement idempotent event delivery.
- Add failure visibility and bounded retry.
- Add event timeline query methods.

Exit: one persisted finding produces one event; re-dispatch does not duplicate side effects.

## Phase 3: QueryRouter (45-60 minutes)

- Register query handlers by capability ID.
- Add input/output schema validation and access checks.
- Enforce one-hop and read-only constraints.
- Implement at least two cross-tower queries end-to-end.

Exit: a query returns typed result or explicit error; no peer query cascade is possible.

## Phase 4: TaskDispatcher and SupervisorRuntime (90-120 minutes)

- Implement task persistence and lifecycle transitions.
- Enforce SupervisorRuntime-only task creation.
- Implement accept, decline, one counterproposal, run, complete, fail, escalate, cancel and timeout.
- Persist result before completion event.
- Add task status timeline.

Exit: full task lifecycle test suite passes and tower escalation terminates the original task.

## Phase 5: Supervisory RCA Agent and Evidence Gate (90-120 minutes)

- Implement Supervisor Agent interface and a fake/deterministic provider.
- Build compact IncidentContext.
- Expose bounded read-only tools.
- Add task request tool that routes through SupervisorRuntime.
- Implement conflict classification and structured SupervisorProposal.
- Integrate EvidenceReleaseGate.

Exit: LLM-off diagnosis works, fake evidence is rejected, and one ambiguous case triggers a bounded investigation or abstention.

## Phase 6: CLI integration and robustness (90 minutes)

- Show real event/query/task timeline in Rich.
- Add inspect flags.
- Add duplicate, ordering, subscriber failure, unsupported capability, task negotiation, escalation, timeout and budget-exhaustion tests.
- Re-run all product tests and demo.

Exit: deterministic replay produces the same final report and communication history.

Keep at least two hours of the total hackathon window for integration, dependency fixes and final rehearsal. If behind schedule, cut optional specialist LLM capability before cutting contracts, task lifecycle, evidence gate or tests.

# 15. Parallel coding-agent ownership

Parallel agents may work only after shared contracts are frozen.

| Worktree/branch | Owns | Must not edit concurrently |
|---|---|---|
| `feat/comms-contracts` | Pydantic event/query/task schemas, YAML registries | Supervisor runtime and tower logic |
| `feat/eventbus` | EventBus, SQLite outbox, delivery/idempotency | Public contract definitions without approval |
| `feat/task-query` | QueryRouter, TaskDispatcher, lifecycle persistence | Event schema and SupervisorRuntime |
| `feat/supervisor-integration` | SupervisorRuntime, tools, Supervisor Agent interface, gate wiring | Contracts and repository migrations without coordination |
| `feat/cli-comms` | Rich timelines, inspect flags, comms integration tests | Core dispatcher logic |

The integration lead owns `main`, approves contract changes, merges only tested branches, runs the full suite and performs the final CLI demo. Do not allow two coding agents to edit the same contract or orchestration file at once.

# 16. Questions the coding agent should ask

Ask the user only when a decision is blocking or a wrong assumption would cause expensive rework. Give a default and continue non-blocked work.

Potential questions after repository inspection:

1. Does the repository already contain a message/event schema that external evaluators expect? Default: retain compatible fields and add required metadata without breaking existing inputs.
2. Which LLM provider/model should be used for the Supervisor? Default: implement provider-neutral interface plus fake provider; do not block the deterministic core.
3. Are any tasks expected to be long-running or I/O-bound in the demo? Default: synchronous local task execution with persistent lifecycle; preserve method boundaries for a later async adapter.
4. Do organizer datasets include log/config/service records or only metrics and topology? Default: implement optional typed input adapters and mark unavailable domains as `no_data`, not failed diagnosis.

Do not ask questions already answered by the repository or conversation. Do not wait for answers to continue contracts, EventBus, QueryRouter or deterministic test work.

# 17. Definition of done

The communication hierarchy is complete when:

- One supervisor runtime controls every incident.
- One Supervisory RCA Agent owns the case-level proposal.
- Four towers expose distinct domain controllers and registered capabilities.
- Towers publish typed findings as events.
- Subscribed towers react without LLM relay.
- At least two typed peer queries work end-to-end.
- Only the supervisor can create persistent tasks.
- Tasks support accept/decline/counterproposal/run/complete/fail/escalate/cancel/timeout.
- Task results and findings persist before completion events.
- Duplicate event delivery is idempotent.
- No tower can take ownership of final reporting.
- The Evidence Gate independently validates the supervisor proposal.
- CLI shows real communication and task history.
- LLM-off mode works.
- Unit and integration tests cover all critical contracts and transitions.

# 18. Final instruction

Implement the smallest correct communication fabric that expresses a modern hierarchical multi-agent system without introducing distributed infrastructure. Use events for shared awareness, one-hop queries for deterministic facts, and supervisor-authorized tasks for investigations. Keep tower ownership clear, task lifecycle persistent, contracts typed and evidence references auditable. The Supervisor proposes; the Evidence Gate controls publication.
