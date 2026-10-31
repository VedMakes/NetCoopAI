# NetCoop AI: Coding-Agent Implementation Playbook

**Purpose:** Build the NetCoop AI hackathon product from this specification, in small verified phases.

**Project constraint:** 24-hour hackathon  
**Primary language:** Python  
**Initial interface:** CLI only  
**Architecture:** Four deterministic diagnostic towers, four bounded specialist-agent capabilities, one Supervisory RCA Agent, and an independent deterministic evidence gate.  
**Implementation style:** Modular monolith, local-first, reproducible, read-only.

---

## 0. Instructions to the coding agent

You are the implementation agent for NetCoop AI. Treat this document as the source of truth for the first working version. Build a working diagnostic product, not a framework demonstration.

### 0.1 How to work

1. Inspect the existing repository before creating or modifying files. Preserve useful existing work. Do not overwrite a working implementation merely to match the proposed folder layout.
2. Read the challenge brief and any supplied sample telemetry generator or data files. The challenge brief is the authority for the hackathon acceptance criteria.
3. Implement in the phases in Section 12. Keep the application runnable after every phase.
4. After each phase, run the relevant tests and the CLI smoke test. Fix failures before starting the next phase.
5. Prefer the smallest working implementation. Do not introduce infrastructure, abstractions, services, dependencies, or frameworks without a concrete requirement.
6. Make reasonable reversible decisions yourself. Record them in `docs/DECISIONS.md` rather than stopping to ask about every detail.
7. Ask the user questions when an answer materially changes architecture, data interpretation, model-provider integration, or the demo. The project explicitly permits clarifying questions.
8. Never claim that a feature works unless a test or reproducible CLI run demonstrates it.

### 0.2 Question protocol

Ask questions only when the answer is genuinely blocking or would prevent a costly wrong assumption. Batch up to three related questions in one message. For each question:

- Explain briefly why it matters.
- Give a sensible default.
- State what you will implement if the user does not answer promptly.

Do not block deterministic core development while waiting for model-provider credentials or preferences.

Questions that may be worth asking after repository inspection:

1. Is there an organizer-provided sample telemetry generator or dataset beyond the problem statement PDF? Default: implement the documented canonical input format and synthetic fixtures, then add an adapter when the real format is available.
2. Which LLM provider and model should power the Supervisor Agent? Default: implement a provider-neutral interface and a deterministic stub; add a real provider only after the user chooses one or supplies credentials.
3. Is the hackathon demo expected to run on a machine with internet access? Default: the full deterministic demo must work offline. LLM mode is optional.

Do not ask these questions again if the repository, environment, or earlier conversation already answers them.

### 0.3 Parallel coding-agent protocol

If multiple coding agents are available, use separate branches or worktrees. Do not let multiple agents edit the same contract or orchestration files concurrently.

Suggested ownership after Phase 1 contracts are frozen:

| Branch / worktree | Ownership | May not change without integrator approval |
|---|---|---|
| `feat/contracts-ingestion` | Pydantic schemas, loaders, validation, SQLite repository | Public model fields and IDs after contract freeze |
| `feat/diagnostic-engines` | Features, rules, statistical detection, NetworkX topology | Shared message and finding schemas |
| `feat/towers-supervisor` | Tower controllers, event dispatcher, supervisor, release gate | Ingestion models and CLI command contracts |
| `feat/cli-evaluation` | Typer CLI, Rich display, scenario fixtures, integration tests | Core engine algorithms and schemas |

The integrating agent owns `main`, freezes contracts, reviews every merge, resolves integration conflicts, runs the full test suite, and verifies the final demo. Parallel work starts only after the shared interfaces compile and have tests.

---

# 1. Product objective

Build a CLI-first multi-agent network fault diagnosis tool for the NetCoop AI challenge. It must analyze heterogeneous network telemetry, identify probable fault causes, identify affected entities, show supporting evidence, express uncertainty, and recommend practical corrective actions.

The product should make the four-tower architecture visible to judges through a polished terminal experience. The intelligence must be real, not simulated agent chatter. Deterministic analysis does the routine work. Specialist agents and the Supervisor Agent are invoked selectively.

## 1.1 Required challenge behavior

The supplied challenge brief requires:

- At least two functional agents with distinct responsibilities.
- Structured communication and exchange of findings.
- An orchestrated unified diagnosis.
- Evidence-backed probable root cause and affected devices/segments where identifiable.
- Alternatives and uncertainty where appropriate.
- A confidence estimate or clearly defined confidence category.
- Recommended corrective actions.
- Handling of malformed, missing, or incompatible inputs.
- A reproducible run using supplied or documented test data.
- A structured JSON report.

The challenge scoring weights are:

| Evaluation criterion | Weight |
|---|---:|
| Agent interoperability and protocol design | 30% |
| Diagnostic accuracy and evidence quality | 25% |
| Agent orchestration and conflict resolution | 15% |
| Robustness to missing, inconsistent, or incompatible data | 15% |
| Code quality, documentation, demonstration | 5% |
| Innovation, usability, extensibility | 10% |

Do not sacrifice interoperability, evidence quality, or robustness to add decorative agent features.

## 1.2 Product success definition

A judge should be able to run one command, see the four towers investigate the same incident from their own domains, see the towers exchange structured findings, see the Supervisor Agent reconcile their results, and receive a verified diagnosis with evidence references.

The demo must also show at least one case where the system refuses to overstate a diagnosis because evidence is missing or contradictory.

---

# 2. Locked architecture for the hackathon

## 2.1 Main components

1. **Ingestion and normalization:** Load CSV/JSON inputs, validate them, map entity aliases, normalize timestamps and units, and preserve source references.
2. **Shared deterministic preprocessing:** Calculate derived metrics, identify data-quality issues, and deduplicate repeated events.
3. **Four diagnostic towers:** Each tower runs deterministic domain analyzers and exposes a bounded specialist-agent capability.
4. **In-process integration fabric:** Routes typed events and request/response messages between towers.
5. **Knowledge store:** Stores incident runs, observations/references, findings, tasks, messages, and reports in one SQLite database.
6. **In-memory topology:** One NetworkX graph represents the current network topology for a run.
7. **Supervisor runtime:** Deterministic state machine that creates cases, runs towers, tracks tasks, applies budgets, and invokes the Supervisor Agent when needed.
8. **Supervisory RCA Agent:** Owns cross-domain conflict resolution and the proposed case-level diagnosis.
9. **Evidence and Release Gate:** Deterministically validates the proposed diagnosis before it is published.
10. **CLI:** The only user interface for the MVP. It renders the incident timeline, tower activity, hypotheses, evidence, and final report.

## 2.2 Explicit simplifications

These are intentional decisions, not missing work.

| Concern | MVP decision | Do not add in the 24-hour build |
|---|---|---|
| Topology graph | One in-memory `networkx.MultiGraph` or `networkx.MultiDiGraph`; choose one after inspecting input directionality | Neo4j, Memgraph, Neptune, graph server, a second graph database |
| Evidence relationships | Typed SQLite rows and ID references; do not build a second graph database | Separate evidence graph service |
| Persistence | One SQLite database file | DuckDB plus SQLite plus Redis plus another database |
| Event communication | Synchronous in-process typed dispatcher | Kafka, NATS, RabbitMQ, Redis Streams |
| Orchestration | Plain Python supervisor state machine | LangGraph unless a concrete need emerges |
| Agent communication | Pydantic request/result contracts and bounded function calls | A2A server or MCP server |
| Ingestion | Local CSV/JSON files and synthetic scenarios | Live campus integrations, SNMP polling, gNMI collectors |
| User interface | Typer + Rich CLI | Streamlit, web app, FastAPI server |
| Deployment | Local Python environment; optional single Dockerfile only if time permits | Kubernetes, Helm, microservices |
| Time-series storage | Load and process the challenge-sized data in Pandas/NumPy | Dedicated TSDB |
| LLM | Provider interface; optional adapter; deterministic no-key mode | Multiple continuously running model instances |
| Low-level code | Python | C/C++/Rust optimization without measured bottleneck |

### 2.3 One graph only

Use one in-memory NetworkX graph for network structure. Store evidence references, support/contradiction relations, provenance, and hypothesis records as typed records in SQLite. Do not create a second graph database or a second NetworkX graph for the evidence ledger.

Use the simplest NetworkX graph type that fits the supplied topology. A `MultiGraph` supports undirected physical links and parallel links. A `MultiDiGraph` supports direction-sensitive logical paths and parallel edges. Document the selection in `docs/DECISIONS.md` and do not maintain both unless a test proves one graph type cannot represent the required inputs.

### 2.4 One local database only

Use one SQLite database, for example `data/netcoop.db`, with tables for runs/incidents, observations or raw references, findings, hypotheses, tasks, messages/events, and final reports. Use transactions for writes. Treat findings and evidence as append-only: supersede old records with new records rather than silently editing their meaning.

Large raw files remain in the input directory. Store a file path, record ID, row number, and optional content hash as provenance. Do not copy every raw row into prompts.

### 2.5 LLM policy

The system must run end-to-end with LLM disabled and no API key. This is a hard acceptance requirement.

Provide:

- `off`: zero model calls. Deterministic supervisor and template report only.
- `auto`: default. Invoke the Supervisor Agent only for material ambiguity, cross-tower contradiction, novel signatures, or a bounded evidence-planning task.
- `on`: invoke the Supervisor Agent for a final reasoning pass on each incident. Still enforce the same evidence gate and budgets.

Tower specialist LLM reviews are optional and only used when the Supervisor Agent requests a bounded review. Do not call every specialist model on every run.

The first implementation should expose an `LLMProvider` interface and a `FakeLLMProvider`. Add one real provider adapter only after the user chooses a provider and model. Credentials must come from environment variables. Never commit secrets.

---

# 3. Domain model and contracts

Freeze these contracts before parallel implementation. Use Pydantic v2 models, enums, strict validation where possible, and explicit schema versions. Do not allow arbitrary untyped dictionaries to become the main inter-agent protocol.

## 3.1 Canonical input records

Support the following normalized record types. The initial source adapter may accept CSV or JSON, but all internal processing must use these models.

### `MetricSample`

Required fields:

- `event_id: str`
- `timestamp: datetime` (timezone-aware; normalize to UTC)
- `source: str`
- `entity_id: str`
- `entity_type: str` (device, interface, AP, link, service, client, or unknown)
- `metric_name: str`
- `value: float`
- `unit: str`

Optional fields:

- `direction: str | None` (ingress, egress, bidirectional, unknown)
- `labels: dict[str, str]`
- `quality_flags: list[str]`
- `raw_ref: str | None`

### `LogEvent`

Required: `event_id`, timezone-aware `timestamp`, `source`, `entity_id`, `severity`, `message`.

Optional: `event_code`, `facility`, `labels`, `raw_ref`, `quality_flags`.

### `TopologyNode`

Required: `entity_id`, `entity_type`, `name`.

Optional: `site`, `segment`, `vendor`, `model`, `metadata`.

### `TopologyLink`

Required: `link_id`, `source_entity_id`, `target_entity_id`, `link_type`.

Optional: `source_interface`, `target_interface`, `bidirectional`, `capacity_bps`, `status`, `metadata`.

### Entity identity

Use canonical IDs internally. Do not rely on display names as identifiers. Support an explicit alias map in input/configuration. If two aliases map ambiguously, flag the record and do not guess.

## 3.2 Finding contract

Every deterministic analyzer and tower publishes the same `Finding` contract:

```json
{
  "schema_version": "1.0",
  "finding_id": "F-0001",
  "incident_id": "INC-0001",
  "source_tower": "performance",
  "producer": "congestion_rules",
  "finding_type": "high_utilization",
  "status": "provisional",
  "severity": "high",
  "entity_ids": ["sw-01:ge-0/0/1"],
  "observed_at": "2026-10-31T08:00:00Z",
  "time_window_start": "2026-10-31T07:55:00Z",
  "time_window_end": "2026-10-31T08:00:00Z",
  "summary_code": "SUSTAINED_UTILIZATION_ABOVE_THRESHOLD",
  "measurements": {
    "current_pct": 96.0,
    "baseline_pct": 47.0
  },
  "evidence_refs": ["E-0001", "E-0002"],
  "contradiction_refs": [],
  "independence_groups": ["prometheus:sw-01:ge-0/0/1:utilization"],
  "quality": {
    "data_coverage": 0.9,
    "warnings": []
  },
  "method": "rolling_threshold_and_mad",
  "method_version": "1.0",
  "supersedes_finding_id": null
}
```

The numeric values above are illustrative only. Do not hardcode them into the implementation.

Finding rules:

- Findings are derived records, not raw observations.
- Every finding must cite one or more observation or upstream finding IDs.
- A finding with missing/invalid data must include quality warnings.
- `independence_groups` identify evidence that shares the same underlying source or measurement path. They prevent false corroboration.
- `status` is one of `provisional`, `supported`, `challenged`, `rejected`, `inconclusive`, `superseded`.
- To revise a finding, publish a new finding with `supersedes_finding_id`.

## 3.3 Hypothesis contract

A `Hypothesis` includes:

- `hypothesis_id`, `incident_id`, `fault_code`, `label`.
- `affected_entity_ids`.
- `supporting_finding_ids` and `contradicting_finding_ids`.
- `mechanism`: short description of how this fault could generate the observations.
- `assumptions` and `missing_evidence`.
- `score` plus `scoring_method_version`, if a deterministic ranker is used.
- `confidence_category`: `high`, `moderate`, `low`, `insufficient`.
- `status`: `candidate`, `challenged`, `supported`, `rejected`, `inconclusive`.
- `created_by`, `created_at`.

A ranking score is not a probability. Do not display `0.86` as an 86% probability unless probability calibration has been evaluated on held-out incident scenarios. Use confidence categories for the hackathon.

## 3.4 Tower report contract

Each tower returns one `TowerReport`:

- `incident_id`, `tower_id`, `status`, `started_at`, `completed_at`.
- `findings: list[Finding]`.
- `hypotheses: list[Hypothesis]`.
- `coverage`: expected/observed source or metric counts where known.
- `missing_inputs`, `warnings`, `errors`.
- `requested_tasks` (normally empty; only the tower controller may request allowed tasks).

Possible report status: `completed`, `partial`, `failed`, `not_applicable`.

A tower must return a partial report rather than crash the entire incident when one optional data source is missing.

## 3.5 Message envelope

Use a common typed envelope for in-process messages:

```json
{
  "schema_version": "1.0",
  "message_id": "MSG-0001",
  "incident_id": "INC-0001",
  "message_type": "finding.published",
  "sender": "performance",
  "recipient": "broadcast",
  "created_at": "2026-10-31T08:01:00Z",
  "correlation_id": "INC-0001",
  "causation_id": "MSG-0000",
  "payload_ref": "F-0001"
}
```

Required message types for MVP:

- `observation.ingested`
- `finding.published`
- `hypothesis.updated`
- `task.requested`
- `task.accepted`
- `task.completed`
- `task.failed`
- `challenge.raised`
- `incident.status_changed`

Message rules:

- Persist the finding/task result before publishing the message that points to it.
- Subscribers must be idempotent. Processing the same `message_id` twice must not duplicate work or findings.
- Use `causation_id` and `correlation_id` for traceability.
- Keep payloads small. Use IDs and references, not copied raw telemetry arrays.
- Do not build a general distributed event platform. The in-process dispatcher is sufficient.

## 3.6 Task lifecycle

Allowed task states:

`created -> accepted -> running -> completed`

Terminal alternatives: `failed`, `cancelled`, `expired`.

Every task has:

- `task_id`, `incident_id`, `requester`, `assignee`, `task_type`.
- Typed `parameters`.
- `reason` and relevant `evidence_refs`.
- `created_at`, optional deadline, `status`, optional `result_ref` and `error`.

The supervisor may only issue task types listed in the capability registry. Each task has a timeout and a bounded retry count. Do not permit a model to generate arbitrary Python, shell commands, network addresses, or device writes.

---

# 4. The four towers: implementation requirements

Each tower implements a common Python interface, but its internal analyzers remain domain-specific.

```python
class TowerController(Protocol):
    tower_id: str

    def analyze(self, context: IncidentContext) -> TowerReport: ...
    def handle_task(self, task: TowerTask, context: IncidentContext) -> TaskResult: ...
    def supported_capabilities(self) -> set[str]: ...
```

The tower controller is deterministic by default. A separate optional specialist wrapper may use an LLM to review a bounded evidence packet. Do not force all tower controllers to inherit from an LLM framework.

## 4.1 Performance tower

Implement these first:

1. Counter-to-rate conversion with reset detection. For counters, calculate deltas only when samples are ordered and counter semantics are known. A negative delta must be treated as reset/wrap/invalid according to configured counter width, not as negative traffic.
2. Utilization from throughput and known link speed. If link speed is unknown, do not invent utilization.
3. Packet-drop and interface-error ratios with explicit denominators.
4. Rolling mean, median, MAD, min/max, P95, P99 where sample count is sufficient.
5. Robust Z-score with safe handling for `MAD == 0`.
6. EWMA or simple sustained-threshold detection.
7. Congestion signature requiring a combination of sustained high utilization and evidence of pressure such as queue drops or latency degradation. High utilization alone is not enough to diagnose congestion.
8. Optional weak-Wi-Fi signature when RSSI/SNR and retransmission data exist.

Do not implement every statistical algorithm in the first pass. MAD, rolling windows, and sustained thresholds are the minimum. Add CUSUM and seasonal baselines only after tests pass.

## 4.2 Infrastructure tower

Implement:

1. Device availability/status transitions.
2. Interface up/down and flap detection.
3. CRC/error/discard rate detection.
4. CPU and memory sustained threshold rules.
5. Syslog severity and keyword/event-code parsing.
6. Basic repeated-log deduplication by normalized message/entity/time bucket.
7. Fault signatures for interface fault and device overload.

Drain3 may be added if raw logs are sufficiently varied. Do not block the prototype on advanced log-template mining.

## 4.3 Connectivity tower

Implement:

1. Build one NetworkX topology graph from normalized nodes and links.
2. Map interface/device findings onto graph entities.
3. Test reachability between source/destination pairs when provided.
4. Extract relevant subgraphs around affected entities.
5. Find common upstream dependencies for two or more affected nodes.
6. Calculate shortest paths where graph directionality and edge semantics support it.
7. Identify disconnected components and articulation points when applicable.
8. Produce a finding that explains graph evidence and its limitations.

Do not label a common ancestor as a root cause without independent evidence that it is faulty. Topology provides location and dependency context, not causation by itself.

## 4.4 Services and configuration tower

Implement:

1. DNS transaction result analysis when DNS observations are available.
2. DHCP transaction/lease-stage analysis when DHCP observations are available.
3. Service reachability and response-time checks from provided test data.
4. Simple configuration snapshot diff for JSON/YAML inputs.
5. Rule-based detection of relevant changes before an incident.
6. Basic ACL/policy checks only when an explicit normalized representation is provided.

Do not attempt to parse every vendor configuration format in the hackathon. Create a small normalized config representation and clearly report unsupported raw inputs.

---

# 5. Inter-tower communication

The four towers must collaborate through a single in-process `EventBus` plus direct typed request/response methods. Do not add a broker.

## 5.1 Required behavior

- A tower publishes a `Finding` and then emits `finding.published`.
- Interested towers subscribe to specific event types.
- Towers can request specific deterministic checks from other towers.
- The supervisor can delegate a bounded task to a tower.
- Results are persisted and referenced by IDs.
- Duplicate events do not cause duplicate processing.
- Cross-tower communication is visible in the CLI timeline.

## 5.2 Initial subscriptions

| Published event | Subscribers | Expected reaction |
|---|---|---|
| `performance.latency_anomaly` | Connectivity, Services | Check affected paths and service impact |
| `performance.congestion_candidate` | Connectivity, Infrastructure | Find shared uplink and inspect interface/device health |
| `infrastructure.interface_down` | Connectivity, Performance, Services | Recompute affected paths and related service scope |
| `infrastructure.device_unhealthy` | Connectivity, Performance | Check downstream impact and performance symptoms |
| `connectivity.path_degraded` | Performance, Services | Inspect latency and service reachability on affected path |
| `services.dns_failure` | Connectivity, Performance | Check resolver reachability and response-time symptoms |
| `services.dhcp_failure` | Infrastructure, Connectivity | Check relay/server reachability and affected segment |
| `services.config_changed` | All towers | Compare event time and entities with active findings |

This table is a starting subscription map, not an exhaustive protocol. Keep subscriptions explicit in code and test them.

## 5.3 Loop prevention

Every message carries IDs and causation metadata. Use:

- Idempotency by `message_id`.
- A small maximum event reaction depth, for example 3.
- No republication of an unchanged finding.
- Only allow a new investigation when it adds a new evidence reference, changes a status, or answers a task.
- A per-incident maximum task count and time budget.

Prefer direct engine-to-engine messages for deterministic data. Use LLM-to-LLM/specialist communication only when interpretation is actually needed.

---

# 6. Supervisory RCA Agent and independent release gate

This is the defining coordination component of NetCoop.

## 6.1 Supervisor runtime versus Supervisor Agent

Keep these separate in code:

- `SupervisorRuntime`: deterministic Python code. It creates incident state, calls towers, tracks tasks, applies budgets, invokes the model if needed, and calls the verifier.
- `SupervisoryRCAAgent`: bounded reasoning capability. It receives compact structured tower reports and may propose a diagnosis, ask for a permitted task, or identify a conflict.
- `EvidenceReleaseGate`: deterministic verifier. It decides whether a proposed report is publishable.

The Supervisor Agent is not the workflow engine and is not the evidence database.

## 6.2 Supervisor input

Pass only a compact context packet:

- Incident ID, user symptom, time window.
- Affected entities and relevant topology subgraph summary.
- Four `TowerReport` objects or concise summaries.
- Current hypotheses, finding IDs, and evidence references.
- Missing-data and quality summary.
- Outstanding tasks and prior challenge results.
- Capability registry entries relevant to this incident.

Do not send the full raw dataset, all logs, the complete topology, or unrelated incidents to the model.

## 6.3 Supervisor output

Require structured output validated by Pydantic. Example fields:

```json
{
  "decision": "propose_diagnosis",
  "primary_hypothesis_id": "H-0001",
  "alternative_hypothesis_ids": ["H-0002"],
  "affected_entity_ids": ["sw-01:ge-0/0/1"],
  "reasoning_summary": "The shared uplink is consistent with the affected path and the performance findings.",
  "claim_manifest": [
    {
      "claim_id": "C-001",
      "claim_type": "observed_fact",
      "text": "Uplink utilization was above the configured threshold.",
      "evidence_refs": ["E-0001", "F-0002"]
    }
  ],
  "task_requests": [],
  "unresolved_conflicts": [],
  "limitations": ["Upstream interface metrics are unavailable."],
  "confidence_category": "moderate"
}
```

The model must not mint IDs or numeric measurements. It can only reference IDs present in its input context. Any unknown ID fails validation.

Allowed `decision` values:

- `propose_diagnosis`
- `request_evidence`
- `abstain`

Allowed task requests are selected from the registry. Free-form tool commands are not accepted.

## 6.4 Conflict resolution

The supervisor should classify disagreements before trying to resolve them:

1. Observation conflict: different values for what should be the same measurement.
2. Entity conflict: inconsistent mapping of device/interface identifiers.
3. Time conflict: observations are from different or misaligned windows.
4. Semantic conflict: different units, direction, counter meanings, or schema interpretations.
5. Domain interpretation conflict: towers interpret the same evidence differently.
6. Causal conflict: multiple suspected root causes could explain the symptoms.
7. Recommendation conflict: proposed actions have different consequences.

Resolve lower-level data conflicts deterministically first. For example, unit conversion or alias resolution should not be delegated to the LLM. Escalate only genuine interpretation or causal conflicts.

## 6.5 Bounded investigation

Default budgets for the hackathon:

- Maximum 2 supervisor model calls per incident.
- Maximum 2 investigation rounds after initial tower analysis.
- Maximum 6 delegated tower tasks per incident.
- Maximum 1 targeted specialist LLM review per tower per incident.
- Per-task timeout and maximum retry count of 1.

Make budgets configurable. The supervisor must stop when the budget is exhausted and produce a diagnosis with limitations or abstain.

## 6.6 Evidence and Release Gate

The gate is deterministic and independent of the Supervisor Agent. It validates structured output, not free-form prose. The report renderer should generate factual statements from the validated report object and claim manifest.

Required checks:

1. Every evidence reference exists in the current incident store.
2. Every cited finding exists and has not been superseded or rejected.
3. The evidence relates to the claimed entity or has an explicit valid dependency relationship.
4. Evidence timestamps overlap or are relevant to the incident window. Stale evidence is flagged.
5. Units, direction, and counter semantics are known and compatible with the claim.
6. Data-quality warnings and missing source coverage are reflected in the report.
7. Independent corroboration counts unique independence groups, not the number of agents repeating the same measurement.
8. Contradictory findings are resolved with referenced evidence or disclosed as unresolved.
9. Required report fields and allowed enums are valid.
10. Confidence category follows documented policy and is not fabricated by the model.
11. A diagnosis requiring a specific signature has the signature's required evidence.
12. No claim implies an exact root cause when the available evidence supports only a probable cause.

Gate outcomes:

- `PASS`: publish the proposed diagnosis.
- `PASS_WITH_LIMITATIONS`: publish with explicit limitations and reduced confidence category.
- `RETRY`: request bounded additional evidence or supervisor revision.
- `ABSTAIN`: publish an insufficient-evidence report, not a fabricated diagnosis.
- `REJECT`: invalid references, unsupported claims, malformed report, or policy violation.

The verifier cannot prove the semantic truth of arbitrary natural-language reasoning. That is why the model must provide a structured claim manifest and why the final factual report should be rendered from validated structured fields. The gate validates evidence existence, provenance, scope, freshness, semantics, and required support rules.

---

# 7. Fault-signature library and hypothesis ranking

Implement a small transparent fault-signature library. It is more valuable to have six reliable signatures than twenty shallow ones.

Minimum signatures:

| Fault code | Supporting evidence | Important counterevidence / caution |
|---|---|---|
| `LINK_CONGESTION` | Sustained high utilization plus queue pressure and/or latency/loss degradation on a relevant path | High utilization alone is not enough; check duration and direction |
| `WEAK_WIFI` | Poor RSSI/SNR plus retransmissions or association failures affecting wireless clients | Normal wireless signal plus wired degradation points elsewhere |
| `INTERFACE_FAULT` | Link flaps, CRC/error growth, resets, or carrier loss | Do not infer from one stale counter |
| `DEVICE_OVERLOAD` | Sustained CPU/memory/resource pressure plus correlated device symptoms | High CPU alone may be normal workload |
| `DNS_FAILURE` | DNS query failures/timeouts or error codes with successful direct-IP/reachability checks where available | A resolver unreachable due to path failure is not necessarily a DNS server fault |
| `DHCP_FAILURE` | Transaction/lease-stage failure or relay/server reachability failure | Do not classify solely from client connectivity complaints |
| `ROUTING_FAILURE` | Routing adjacency/route changes plus path or reachability failure | Route state alone does not prove user impact |

For each signature create:

- YAML or Python rule definition with a version.
- Required fields and thresholds.
- Supporting conditions.
- Contradicting conditions.
- Minimum duration/sample count where appropriate.
- Evidence required for the finding.
- Recommended read-only follow-up checks.

Do not use one global threshold for every device. Put thresholds in `config/rules.yaml`, with conservative defaults and comments. Keep a per-device override mechanism, but do not spend time building a full policy engine.

## 7.1 Confidence

Use `high`, `moderate`, `low`, and `insufficient` categories. Confidence should reflect:

- evidence coverage,
- evidence quality,
- independence of evidence sources,
- topology/path plausibility,
- temporal consistency,
- mechanism consistency,
- contradictory evidence,
- unresolved missing data.

A simple weighted score may rank hypotheses if weights are explicit and versioned. The score is a ranking aid, not a calibrated probability. Test confidence and abstention behavior against incident-level ground truth.

---

# 8. Input format, scenarios, and data quality

The challenge brief mentions metrics such as latency, jitter, packet loss, throughput, link utilization, CPU/memory, queue drops, interface errors, wireless signal measurements, timestamps and topology. It also names scenarios for normal operation, link congestion, weak Wi-Fi, interface fault, DNS/DHCP failure, and interoperability failure.

The exact organizer-generated sample schema may differ. Inspect any available generator before finalizing aliases. Do not silently assume missing fields.

## 8.1 Initial on-disk layout

```text
data/
  scenarios/
    normal/
      metrics.csv
      logs.jsonl
      topology.json
    congestion/
      metrics.csv
      logs.jsonl
      topology.json
    weak_wifi/
      metrics.csv
      logs.jsonl
      topology.json
    interface_fault/
      metrics.csv
      logs.jsonl
      topology.json
    dns_failure/
      metrics.csv
      topology.json
  netcoop.db          # generated at runtime, gitignored
reports/              # generated at runtime, gitignored
```

Keep the format small and documented. A scenario manifest may point to optional files and expected ground truth used by the evaluator. Ground truth must never be passed into the runtime diagnostic pipeline.

## 8.2 Synthetic scenario generator

Create reproducible synthetic scenarios with a fixed seed. Every generated scenario has:

- normalized topology nodes and links,
- metric samples with timestamps,
- optional structured log events,
- optional service/configuration events,
- hidden ground-truth fault label and affected entities in a separate evaluation-only file.

At minimum generate:

1. Normal operation.
2. Link congestion.
3. Weak Wi-Fi.
4. Interface fault.
5. Device overload.
6. DNS failure.
7. DHCP failure.
8. Routing/reachability failure.
9. Missing telemetry.
10. Schema/unit mismatch.
11. Red-herring configuration change.
12. Ambiguous/confounded incident.

Do not leak hidden ground truth into the input records or the supervisor context.

## 8.3 Data-quality policy

- Missing is not zero.
- Unknown unit is not silently converted.
- Naive timestamps must be interpreted only under an explicit configured timezone; otherwise flag them.
- Normalize timestamps to UTC after interpretation.
- Handle counter reset/wrap explicitly.
- Never derive utilization without known link speed and direction semantics.
- Preserve unrecognized fields in raw input references when possible.
- A malformed record should be quarantined with an error, not crash the entire dataset load.
- A bad optional source should produce a partial tower report.
- Ambiguous entity mapping must be reported, not fuzzy-guessed.
- Report source coverage and missing modalities.

---

# 9. CLI product requirements

The CLI is the product surface. It should look and feel like a small network-operations console, not a pile of Python print statements.

Use **Typer** for commands and **Rich** for tables, panels, status, progress and formatted logs. Do not add a web dashboard in the MVP.

## 9.1 Required commands

### `netcoop demo`

Runs a built-in scenario end to end.

Examples:

```bash
netcoop demo
netcoop demo --scenario congestion
netcoop demo --scenario weak-wifi --llm off
netcoop demo --scenario ambiguous --verbose
```

Default scenario should be a compelling congestion incident that demonstrates all four towers and the Supervisor Agent. It must be deterministic and offline.

### `netcoop validate`

Validates input records, schemas, timestamps, units, IDs, and topology references without running diagnosis.

```bash
netcoop validate --input data/scenarios/congestion
```

Return non-zero on fatal input errors. Warnings should be summarized separately.

### `netcoop diagnose`

Runs diagnosis against user-supplied files.

```bash
netcoop diagnose \
  --input data/scenarios/congestion \
  --llm auto \
  --output reports/
```

Support `--llm off|auto|on`, `--json`, `--no-color`, `--verbose`, and `--output`.

### `netcoop scenarios`

Lists available built-in scenarios and short descriptions.

### `netcoop inspect`

Displays a saved run by run/incident ID: findings, hypotheses, task history, tower reports, gate result and report path.

### `netcoop doctor`

Checks Python version, required package imports, input/output directory permissions, SQLite availability, and optional LLM configuration. It must not make a model call.

Optional if time remains: `netcoop replay --run-id ...` to render the event/finding sequence again from SQLite.

## 9.2 Demo output design

A single demo should visibly show:

1. NetCoop header and scenario name.
2. Input validation summary.
3. Topology summary: nodes, links, affected segment.
4. Four tower statuses and concise progress messages.
5. Inter-tower event timeline showing actual message types and destinations.
6. Ranked hypotheses with supporting/contradicting finding counts.
7. Supervisor action: invoked or skipped, and why.
8. Evidence gate result.
9. Final diagnosis, confidence category, affected entities, evidence references, limitations and recommendations.
10. Paths to JSON and Markdown reports.

Suggested visual language:

- green: passed/healthy,
- yellow: warning/partial/uncertain,
- red: critical/failure,
- cyan/blue: active processing or informational.

Use color only as a visual aid. All output must remain readable with `--no-color` and in captured logs.

Do not fabricate progress. The displayed tower activity and messages must correspond to actual executed methods and persisted events.

## 9.3 Final JSON report

The final report must include:

- `schema_version`
- `incident_id`, `run_id`, `created_at`
- `status`: `diagnosed`, `probable`, or `insufficient_evidence`
- `suspected_root_cause` and `fault_code` if supported
- `confidence_category`
- `affected_devices`, `affected_segments`, `affected_services`
- `supporting_evidence` with IDs, metrics, values, units, timestamps, entity and source references
- `contradicting_evidence`
- `alternative_causes`
- `recommended_actions` (read-only investigation/remediation advice only)
- `evidence_sources` and tower contributors
- `data_quality`, `coverage`, and `missing_sources`
- `limitations`
- `supervisor_invoked` and `llm_call_count`
- `verification`: gate outcome, checks, warnings and rejected claims

Create the report from validated structured data. The narrative renderer may add a concise summary, but must not add unsupported factual details.

---

# 10. Repository structure

Use a compact structure. Do not split every class into its own file. Adjust only when the repository already has a sensible structure.

```text
netcoop-ai/
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
├── config/
│   └── rules.yaml
├── data/
│   └── scenarios/
├── reports/
├── docs/
│   ├── DECISIONS.md
│   ├── INPUT_FORMAT.md
│   └── DEMO_SCRIPT.md
├── src/
│   └── netcoop/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── schemas.py
│       ├── loaders.py
│       ├── normalization.py
│       ├── repository.py
│       ├── event_bus.py
│       ├── context.py
│       ├── topology.py
│       ├── features.py
│       ├── detection.py
│       ├── rules.py
│       ├── correlation.py
│       ├── towers.py
│       ├── supervisor.py
│       ├── llm.py
│       ├── verification.py
│       ├── reporting.py
│       └── scenarios.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── scripts/
    └── generate_scenarios.py
```

A single `towers.py` is acceptable for the first version. Split into `towers/performance.py`, `infrastructure.py`, `connectivity.py`, and `services.py` only when it improves readability. The same applies to other modules.

---

# 11. Technology and coding standards

## 11.1 Runtime

- Python minimum: 3.12.
- Support a stable tested range through Python 3.14 if dependencies support it.
- Use a `pyproject.toml` and a lock file if the chosen package manager supports it.
- Primary implementation is Python. Do not introduce C/C++/Rust in the first version.

Python is preferred because the work is mostly data processing, rule evaluation, graph analysis, schema handling, and orchestration. Low-level code is permitted only after profiling demonstrates a bottleneck that materially harms the demo. If used, isolate it behind a small, tested Python interface.

## 11.2 Minimal dependencies

Runtime dependencies:

- `pydantic>=2,<3`
- `typer`
- `rich`
- `networkx`
- `numpy`
- `pandas`
- `PyYAML`

Development dependencies:

- `pytest`
- `pytest-cov`
- `ruff`

Optional dependencies:

- One LLM provider SDK selected by the user.
- `scikit-learn` only if DBSCAN or a classical classifier is actually used.
- `drain3` only if raw log volume and format justify it.

Before installing a dependency, ask: does it solve a current acceptance requirement, and can a small standard-library/Python implementation handle it? Avoid dependency sprawl.

## 11.3 Code quality

- Type hints on public functions and data structures.
- Pydantic models at input/output boundaries.
- Small pure functions for feature calculations and rule predicates.
- Explicit units in variable names or model fields.
- UTC-aware datetimes.
- Structured logging for diagnosis internals; Rich for CLI presentation.
- Deterministic IDs in tests or injectable ID factories.
- No hidden global state.
- No LLM calls inside statistical or topology functions.
- Catch expected validation and input errors. Do not blanket-catch all exceptions and continue silently.
- Keep raw and derived evidence distinct.
- Put thresholds and weights in configuration, not scattered literals.

## 11.4 LLM security and reliability

- Model output is untrusted input. Validate it with Pydantic.
- Do not expose unrestricted shell, filesystem, network, or device-write tools to agents.
- Give specialists only the evidence packet and task capabilities required for their role.
- Enforce model call, token, tool/task, retry and timeout limits.
- Do not include credentials, secrets or unrelated raw logs in model context.
- Log model request metadata and usage where available, but avoid logging secrets or full sensitive payloads.
- Use a deterministic fake provider in tests. Tests must not require network access or API keys.

---

# 12. Phased implementation plan for a 24-hour hackathon

The time allocations are targets, not permission to skip acceptance checks. Keep at least 2 hours for integration and recovery. Build a working vertical slice early.

## Phase 0: Repository reconnaissance and decisions (0.5 hour)

**Tasks**

- Inspect repository, existing code, uploaded challenge brief, and sample data/generator.
- Confirm available Python version and package manager.
- Identify existing useful assets and code.
- Write `docs/DECISIONS.md` with defaults and any unresolved questions.
- Do not create a complex architecture document inside the application repository.

**Exit criteria**

- Repository status and file map understood.
- Data-source format uncertainty documented.
- Python environment can be created.

## Phase 1: Scaffold and contracts (2 hours)

**Tasks**

- Create `pyproject.toml`, package skeleton, CLI entry point and `.gitignore`.
- Implement Pydantic models for metric, log, topology, finding, hypothesis, tower report, message, task, supervisor proposal and final report.
- Implement timestamp/unit validation helpers.
- Implement basic SQLite repository and run ID generation.
- Add a fixture with a tiny topology and at least three metrics.
- Add tests for model validation and serialization.

**Exit criteria**

- `netcoop --help` works.
- `netcoop validate` can load and validate the fixture.
- Contracts serialize to JSON and reject invalid schema versions/required fields.
- `pytest` passes.

## Phase 2: Deterministic vertical slice (3 hours)

**Build this before adding agent calls.**

**Tasks**

- Implement CSV/JSON loaders.
- Implement canonicalization and quality warnings.
- Build the single in-memory NetworkX topology graph.
- Implement throughput/utilization calculations where inputs allow.
- Implement rolling statistics, MAD, and sustained threshold detection.
- Implement initial congestion and interface-fault signatures.
- Implement evidence references and finding persistence.
- Generate one synthetic congestion incident with hidden ground truth.

**Exit criteria**

- One command runs deterministic congestion diagnosis without LLM.
- Findings cite existing input records.
- Missing link speed, missing timestamps, and invalid counters are handled explicitly.
- Topology identifies the relevant shared uplink for the demo.

## Phase 3: Four tower controllers and inter-tower communication (3 hours)

**Tasks**

- Implement four `TowerController` implementations.
- Implement a synchronous typed `EventBus`.
- Add explicit subscriptions from Section 5.2.
- Implement request/response for at least `check_shared_upstream`, `inspect_device_health`, `check_reachability`, and `inspect_service_health`.
- Add the task lifecycle and idempotent event handling.
- Persist messages and tasks in SQLite.
- Display real event flow in a basic Rich timeline.

**Exit criteria**

- All four towers run on the same incident context.
- At least two towers exchange messages and one tower requests a check from another.
- Duplicate message IDs do not duplicate findings or tasks.
- A partial/failed tower does not crash the entire run.

## Phase 4: Supervisory RCA Agent and evidence gate (3.5 hours)

**Tasks**

- Implement deterministic `SupervisorRuntime`.
- Implement `SupervisoryRCAAgent` interface and `FakeLLMProvider`.
- Add `off`, `auto`, and `on` modes.
- Implement structured `SupervisorProposal` and claim manifest validation.
- Implement conflict classification and bounded investigation requests.
- Implement `EvidenceReleaseGate`.
- Implement deterministic fallback that ranks known signatures and abstains when evidence is insufficient.
- Add an optional real LLM adapter only if the user selected a provider and credentials are available.

**Exit criteria**

- The supervisor receives all tower reports and owns the proposed final diagnosis.
- At least one contradictory/ambiguous test causes a targeted follow-up or abstention.
- The gate rejects an invented evidence ID and a superseded evidence reference.
- Every published diagnosis has a passing gate result.
- LLM-off mode is fully functional.

## Phase 5: Complete CLI and hackathon demo polish (3 hours)

**Tasks**

- Complete `demo`, `diagnose`, `validate`, `scenarios`, `inspect`, and `doctor` commands.
- Add Rich tables/panels for tower status, event timeline, hypotheses, evidence, and final report.
- Add `--json`, `--verbose`, `--no-color`, `--llm`, and `--output` options where relevant.
- Save JSON and Markdown reports.
- Add a deterministic normal scenario and at least three distinct fault scenarios.
- Write README setup/run instructions and a 3 to 5 minute demo script.

**Exit criteria**

- The demo can be run from a fresh clone using documented commands.
- It works offline with `--llm off`.
- The visual output reflects actual processing and message events.
- The final JSON conforms to the report schema.

## Phase 6: Robustness, evaluation, and integration (4 hours)

**Tasks**

- Add missing-data, schema-mismatch, duplicate-event, out-of-order-event, red-herring and ambiguous scenarios.
- Add unit tests for each deterministic engine and release-gate check.
- Add integration tests for all four towers and supervisor workflow.
- Evaluate top-1/top-3 root-cause accuracy and affected-device accuracy across scenarios.
- Verify no hidden ground truth leaks into the runtime.
- Measure LLM calls/tokens and percentage of incidents handled without LLM.
- Run lint, coverage, CLI smoke tests and fresh-environment setup.

**Exit criteria**

- All must-pass tests pass.
- The demo and reports are reproducible from a fixed seed.
- The system abstains on the ambiguous scenario.
- No unsupported diagnosis is published.

## Integration buffer (at least 2 hours)

Reserve time for merge conflicts, environment differences, dependency issues, and the final demo rehearsal. Do not use this buffer for adding optional features.

---

# 13. Must-pass test cases

1. **Normal network:** no false root cause; report healthy/normal or no incident.
2. **Link congestion:** utilization, queue pressure, latency and topology evidence support the same uplink hypothesis.
3. **Weak Wi-Fi:** wireless signal and retransmission findings dominate; do not blame the uplink without evidence.
4. **Interface fault:** rising errors or flaps produce an infrastructure finding and connectivity impact.
5. **DNS failure:** DNS failure is distinguished from general network unreachability when the supplied observations allow it.
6. **DHCP failure:** failed lease stages are distinguished from generic client connectivity complaints.
7. **Missing topology:** affected devices may be reported, but common-upstream/root-location claims are reduced or withheld.
8. **Unknown unit:** no invalid conversion; report a data-quality warning.
9. **Counter reset:** no negative throughput or false huge delta.
10. **Duplicate event:** no duplicated finding/task.
11. **Out-of-order event:** temporal inference uses timestamps, not arrival order.
12. **Red herring:** an unrelated configuration change is not blamed merely because it occurred near the incident.
13. **Conflicting towers:** supervisor must preserve or resolve the conflict with additional evidence.
14. **Fake evidence ID:** release gate rejects the report.
15. **Superseded evidence:** gate rejects or flags stale/superseded evidence references.
16. **Insufficient evidence:** report abstains with missing evidence listed.
17. **LLM unavailable:** system completes deterministic diagnosis and report.
18. **Malformed optional file:** affected tower is partial; remaining towers still run.

Use pytest fixtures and parameterized tests where useful. Keep scenario ground truth in evaluator-only structures. Do not pass it to the diagnosis runtime.

---

# 14. Evaluation metrics

Track at least:

- Root-cause top-1 accuracy.
- Root-cause top-3 accuracy.
- Affected-device/segment precision and recall.
- Evidence-reference validity rate.
- Release-gate rejection correctness.
- Abstention precision on ambiguous/insufficient cases.
- Inter-tower message delivery and task completion success.
- Duplicate handling correctness.
- End-to-end run latency.
- LLM call count and token usage.
- Percentage of incidents resolved without LLM invocation.

Do not optimize for a high no-LLM resolution percentage at the expense of correctness. Report accuracy and abstention alongside offload rate.

Split evaluation by scenario/incident, not by random telemetry rows, to avoid leakage between similar samples from one synthetic incident.

---

# 15. CLI command examples and expected behavior

```bash
# Install
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"

# Validate a scenario
netcoop validate --input data/scenarios/congestion

# Offline deterministic demo
netcoop demo --scenario congestion --llm off

# Supervisor automatic mode
netcoop demo --scenario congestion --llm auto

# Diagnose supplied data
netcoop diagnose --input path/to/scenario --llm off --output reports/

# List scenarios
netcoop scenarios

# Inspect a saved incident
netcoop inspect --run-id RUN_ID

# Check the local environment
netcoop doctor

# Tests and lint
pytest
ruff check .
ruff format --check .
```

The exact command signatures may be adjusted to the existing codebase, but keep the CLI names and capabilities recognizable.

---

# 16. Explicitly out of scope for the 24-hour MVP

Do not implement these unless all acceptance criteria are already passing and the user explicitly approves the added scope:

- Live production campus network access or polling.
- Configuration changes, remediation, or automatic device commands.
- Multiple graph databases or a graph database server.
- Separate microservices per tower.
- Kafka, NATS, RabbitMQ, Redis, Kubernetes, or service mesh.
- Dedicated time-series database.
- Vector database or RAG platform.
- MCP/A2A server implementation.
- Full SNMP/gNMI/NetFlow collectors.
- Parsing every vendor configuration language.
- A web dashboard.
- Mobile app or chat UI.
- C/C++/Rust acceleration without profiling evidence.
- Unbounded autonomous agent loops.

These are possible future extensions. They are not required to prove the core architecture.

---

# 17. Definition of done

The project is ready for the hackathon demo when all of the following are true:

- [ ] Fresh setup works from the README.
- [ ] `netcoop --help` and `netcoop doctor` work.
- [ ] `netcoop validate` handles valid and malformed inputs.
- [ ] `netcoop demo --scenario congestion --llm off` runs offline.
- [ ] Four towers produce domain-specific reports.
- [ ] At least two towers exchange typed events/findings and one requests evidence from another.
- [ ] The Supervisory RCA Agent receives the four tower reports and owns the proposed case-level diagnosis.
- [ ] The supervisor can identify a conflict and request a bounded follow-up.
- [ ] The release gate rejects unsupported or invalid evidence references.
- [ ] A missing-evidence scenario produces an explicit abstention or limited probable diagnosis.
- [ ] Final JSON includes cause/status, confidence category, affected entities, evidence, alternatives, recommendations, and limitations.
- [ ] A human-readable Markdown report is generated.
- [ ] The CLI shows the real tower/event/evidence timeline.
- [ ] Tests pass and the demo is reproducible.
- [ ] No code path can alter production network devices.

If time runs short, prioritize a trustworthy end-to-end congestion diagnosis, one contrasting scenario, correct tower communication, supervisor arbitration, and evidence-gate enforcement. A small reliable product is better than an incomplete platform.

---

# 18. Research and implementation references

These sources inform the architecture and implementation choices. Re-check versions and APIs during setup; do not pin a version solely because it appears in an old tutorial.

## Challenge and architecture

- NetCoop AI hackathon problem statement: supplied challenge brief. Its required scope includes multi-agent collaboration, documented interoperability, orchestration, evidence-backed diagnosis, uncertainty, robust input handling, reproducible tests, and structured JSON output.
- ETSI GS ZSM 022 V1.1.1 (2026-10), *Architectural Enhancements for Agent-based Network and Service Management*: https://www.etsi.org/deliver/etsi_gs/ZSM/001_099/022/01.01.01_60/gs_ZSM022v010101p.pdf
- ETSI ZSM group and published specifications: https://www.etsi.org/technical-groups/zsm/
- OpenAI Agents SDK, manager-style orchestration and handoffs: https://openai.github.io/openai-agents-python/agents/ and https://developers.openai.com/api/docs/guides/agents/orchestration
- OpenNMS ALEC, topology-aware alarm correlation: https://github.com/OpenNMS/alec
- Prometheus recording rules: https://prometheus.io/docs/prometheus/latest/configuration/recording_rules/
- Prometheus Alertmanager: https://prometheus.io/docs/alerting/latest/alertmanager/
- SuzieQ network observability: https://github.com/netenglabs/suzieq
- Batfish network configuration analysis: https://github.com/batfish/batfish

## Implementation libraries

- Python supported versions: https://devguide.python.org/versions/
- Pydantic: https://docs.pydantic.dev/latest/
- Typer: https://typer.tiangolo.com/
- Rich: https://rich.readthedocs.io/en/stable/
- NetworkX stable documentation: https://networkx.org/documentation/stable/
- NetworkX shortest paths: https://networkx.org/documentation/stable/reference/algorithms/shortest_paths.html
- pytest fixtures and parametrization: https://docs.pytest.org/en/stable/how-to/fixtures.html

---

## Final instruction to the coding agent

Build the smallest complete version of this system that demonstrates the architecture honestly. Keep deterministic processing below the tower controllers, keep cross-tower communication typed and observable, keep the Supervisor Agent bounded and evidence-grounded, and keep the release gate independent. CLI first. Python first. One NetworkX graph. One SQLite database. No infrastructure theatre.
