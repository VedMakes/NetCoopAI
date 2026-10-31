# NetCoop Two-Person Phase Plan

**Project constraint:** 24-hour hackathon  
**Team:** Friend A and Friend B  
**Working mode:** alternating phase ownership, push, independent review, then handoff  
**Shared branch:** `hackathon/team-integration`

## 1. Collaboration model

Each phase has exactly one implementation owner and one reviewer. The owner implements and pushes a coherent increment. The reviewer pulls that exact commit, independently checks the diff, runs tests and records a verdict. The original owner fixes requested changes. The next phase starts only after acceptance.

This is intentionally sequential at the integration boundary. It is safer than two people editing shared contracts or orchestration code in parallel during a 24-hour hackathon. The non-owner can prepare test cases, inspect likely failure modes or review documentation, but must not modify the active owner's implementation files without agreement.

## 2. Phase ownership and time budget

| Phase | Target time | Owner | Reviewer | Main deliverable |
|---|---:|---|---|---|
| 0. Repo reconnaissance and baseline | 0.5 h | Friend A | Friend B | Clean branch, repository map, decisions, working Python setup |
| 1. Scaffold, contracts and SQLite foundation | 1.5 h | Friend B | Friend A | Runnable package, Pydantic contracts, SQLite repository and tests |
| 2. Ingestion, normalization and features | 2 h | Friend A | Friend B | CSV/JSON loaders, validation, canonicalization, derived metrics |
| 3. Performance and infrastructure engines | 2 h | Friend B | Friend A | Statistical detectors, performance signatures, logs/device/interface findings |
| 4. Connectivity and services/config engines | 2 h | Friend A | Friend B | NetworkX topology analysis, reachability, DNS/DHCP/config checks |
| 5. Integration fabric and tower controllers | 3 h | Friend B | Friend A | EventBus, QueryRouter, TaskDispatcher, registries and four controllers |
| 6. Supervisor runtime, RCA agent and evidence gate | 3 h | Friend A | Friend B | Deterministic runtime, optional Supervisor Agent, conflict process and release gate |
| 7. CLI, report and demo experience | 2.5 h | Friend B | Friend A | Rich CLI timeline, JSON/Markdown report, polished demo commands |
| 8. Integration, robustness and release readiness | 4 h | Friend A | Friend B | Full regression, scenario evaluation, bug fixes, fresh-clone demo |
| Integration/recovery buffer | 2 h minimum | Both | Both | Merge/environment recovery and final rehearsal |

The target allocations total 20.5 hours before the 2-hour integration buffer. They are planning limits, not reasons to skip acceptance criteria. Keep at least two hours for the final integration/recovery buffer. If behind schedule, cut optional LLM integrations and decorative features before cutting contracts, deterministic diagnosis, communication correctness, evidence verification or tests.

## 3. Phase details and exit criteria

### Phase 0: Repository reconnaissance and baseline

**Owner: Friend A. Reviewer: Friend B.**

Tasks:
- Inspect existing repository, branch, uncommitted changes, source files, tests and dependency setup.
- Read `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_PLAYBOOK.md` and `docs/INTERAGENT_COMMS.md`.
- Confirm available Python version and package manager.
- Identify organizer sample input/generator and existing useful assets.
- Create or update `docs/DECISIONS.md` with only decisions needed before implementation.
- Create the shared branch `hackathon/team-integration` from the agreed base branch if it does not exist.
- Add team tracking files if they are not already present.

Exit:
- Repository map and current Git state documented.
- No existing work is overwritten.
- Python environment can be created.
- Shared branch is pushed and both humans can fetch it.
- Friend B independently confirms the baseline.

### Phase 1: Scaffold, contracts and SQLite foundation

**Owner: Friend B. Reviewer: Friend A.**

Tasks:
- Add `pyproject.toml`, package skeleton, CLI entry point and `.gitignore` if absent.
- Implement Pydantic models: canonical observations, findings, hypotheses, tower reports, event envelope, peer query/result, investigation task/result, supervisor proposal, final report and claim-evidence manifest.
- Implement enums and task transition validation.
- Add versioned `config/capabilities.yaml` and `config/vocabulary.yaml` for the four towers.
- Implement one SQLite repository with schema initialization/migrations or a simple schema-version table.
- Add deterministic ID injection for tests.
- Add a small fixture and tests for valid/invalid serialization and schema versions.

Exit:
- Package imports and `netcoop --help` works.
- Contracts serialize/validate.
- Invalid required fields, units or task transitions are rejected.
- SQLite read/write round trip works.
- `pytest` passes.
- Public contracts are frozen for subsequent phases. Any later change requires a decision-log entry and a compatibility test.

### Phase 2: Ingestion, normalization and features

**Owner: Friend A. Reviewer: Friend B.**

Tasks:
- Implement CSV/JSON adapters for the agreed input shape.
- Normalize timestamps to timezone-aware UTC.
- Normalize supported units and preserve original units/source references.
- Resolve entity aliases to canonical IDs where evidence supports the mapping.
- Represent missing, invalid, stale and unsupported values explicitly. Never convert missing to zero.
- Detect counter resets/wraps before rate calculation.
- Derive throughput, utilization, packet/error/drop ratios and rolling statistics where inputs allow.
- Preserve raw input references.

Exit:
- A sample incident can be loaded and validated.
- Unit conversion and counter edge cases have tests.
- Malformed or missing inputs produce actionable warnings, not silent coercion.
- Feature values have explicit units and source references.

### Phase 3: Performance and infrastructure engines

**Owner: Friend B. Reviewer: Friend A.**

Performance tasks:
- Rolling statistics and configurable thresholds.
- MAD/robust Z-score and EWMA; CUSUM only if time permits.
- Congestion/capacity and queue-pressure signatures.
- Finding emission with evidence references.

Infrastructure tasks:
- Device availability and status checks.
- Interface state/error/flap analysis.
- CPU/memory and hardware warning signatures where input exists.
- Basic structured log parsing; Drain3 is optional, not mandatory.

Exit:
- Congestion and interface-fault fixtures create expected findings.
- Normal telemetry does not trigger a high-severity fault.
- Each finding references valid observations.
- No LLM dependency exists in either engine.

### Phase 4: Connectivity and services/configuration engines

**Owner: Friend A. Reviewer: Friend B.**

Connectivity tasks:
- Build exactly one in-memory NetworkX topology graph.
- Add canonical device/interface/link nodes and relationships from the supplied schema.
- Implement reachability, path lookup, common upstream dependency and affected-subgraph extraction.
- Handle missing or ambiguous links without inventing a path.

Services/configuration tasks:
- Implement deterministic DNS/DHCP health checks from supplied observations or synthetic fixtures.
- Implement basic configuration diff and relevant-change correlation if snapshots are available.
- Implement simple service/configuration fault signatures.

Exit:
- Shared upstream dependency scenario works.
- DNS failure is distinguished from general transport failure where data permits.
- Missing topology reduces claims rather than causing fabricated paths.
- Every emitted finding cites valid input observations.

### Phase 5: Integration fabric and tower controllers

**Owner: Friend B. Reviewer: Friend A.**

Tasks:
- Implement typed in-process EventBus with deterministic subscriber ordering.
- Persist events before dispatch or use a SQLite outbox so a committed finding cannot silently lose its notification.
- Implement idempotent event processing.
- Implement QueryRouter with capability allowlists, typed input/output validation, read-only checks and one-hop restriction.
- Implement TaskDispatcher with SQLite persistence, lifecycle validation, supervisor-only task creation, accept/decline and one counterproposal, run/complete/fail/escalate/cancel/timeout.
- Persist task results before publishing completion events.
- Implement four `TowerController` instances that wrap the deterministic engines and expose declared capabilities.
- Add subscriptions for cross-domain findings.
- Ensure tower-to-tower peer queries cannot create persistent tasks.

Exit:
- Four towers run on one incident context.
- Publish/subscribe works and produces real persisted event records.
- At least two peer queries work end-to-end.
- Only the SupervisorRuntime can create persistent tasks.
- Duplicate event delivery is idempotent.
- Declined, failed and timed-out tasks are visible and do not crash the incident.

### Phase 6: Supervisor runtime, RCA agent and evidence gate

**Owner: Friend A. Reviewer: Friend B.**

Tasks:
- Implement deterministic SupervisorRuntime and incident state machine.
- Collect tower reports and construct compact incident context.
- Implement supervisor task authorization and investigation budgets.
- Implement `SupervisoryRCAAgent` interface with a deterministic fake provider first.
- Add optional provider adapter only if the human selects a provider and credentials are available.
- Implement structured conflict classification and competing hypothesis proposal.
- Implement claim-to-evidence manifest.
- Implement independent `EvidenceReleaseGate` checking evidence existence, incident scope, freshness, supersession, provenance, contradiction disclosure, required fields and status consistency.
- Ensure LLM-off path can produce a deterministic report or abstain.

Exit:
- Supervisor receives all four tower reports and owns the proposal.
- At least one contradictory/ambiguous fixture triggers verification or abstention.
- Invented, stale, superseded or wrong-incident evidence references are rejected.
- No report is published without a passing gate.
- LLM-off mode works.

### Phase 7: CLI, reports and demo experience

**Owner: Friend B. Reviewer: Friend A.**

Tasks:
- Complete `demo`, `diagnose`, `validate`, `scenarios`, `inspect` and `doctor` commands.
- Use Rich panels/tables to show four tower status, event/query/task timeline, hypotheses, evidence and supervisor decision.
- Show real persisted communication events only. Never print simulated agent chatter.
- Add JSON output and optional Markdown report rendering from the validated report object.
- Add a normal scenario and at least three clear fault scenarios.
- Add `--llm off|auto|on` if supported by the selected provider adapter.
- Write concise README instructions and a 3-5 minute demo script.

Exit:
- Fresh-clone install and CLI commands work.
- Demo runs offline in LLM-off mode.
- CLI output matches persisted events/tasks/findings.
- JSON conforms to the final report schema.

### Phase 8: Integration, robustness and release readiness

**Owner: Friend A. Reviewer: Friend B.**

Tasks:
- Run full unit/integration suite and fix regressions.
- Add missing-data, incompatible-schema, duplicate, out-of-order, subscriber-failure, unsupported-capability, rejected-task, counterproposal, timeout, cancellation, red-herring and ambiguous scenarios.
- Verify deterministic replay and fixed-seed reproducibility.
- Measure root-cause top-1/top-3, affected-device accuracy, evidence-reference validity, abstention behavior, number of LLM calls/tokens and percentage resolved without LLM.
- Check for leakage of scenario ground truth into runtime logic.
- Run lint and fresh-environment installation.
- Freeze optional features and rehearse the demo.

Exit:
- All mandatory acceptance checks pass.
- Ambiguous scenarios abstain.
- No unsupported report can pass the gate.
- Final demo runs from a clean checkout.
- Final known limitations are documented.

## 4. Git protocol

### Branch

Use one sequential integration branch:

```text
hackathon/team-integration
```

Friend A creates it in Phase 0 if it does not exist. Both developers push to this branch only when it is their turn. Do not push directly to `main`.

### Owner handoff

```bash
git fetch origin
git switch hackathon/team-integration
git pull --ff-only origin hackathon/team-integration
# implement only the assigned phase
pytest
ruff check .
git status --short
git add <scoped-files> docs/PHASE_STATUS.md docs/COLLAB_LOG.md
git commit -m "phase-N: concise description"
git push origin hackathon/team-integration
```

Record the actual resulting SHA in the handoff log. If `git push` fails, state that honestly and do not mark the handoff as pushed.

### Reviewer handoff

```bash
git fetch origin
git switch hackathon/team-integration
git pull --ff-only origin hackathon/team-integration
git show --stat --oneline HEAD
git diff HEAD~1..HEAD
pytest
ruff check .
```

The reviewer records a verdict in `docs/COLLAB_LOG.md` and updates `docs/PHASE_STATUS.md`. A review sign-off may be its own small commit. The next phase owner starts only after acceptance.

### Git safety

- Never force-push.
- Never amend a pushed commit.
- Never reset hard or discard another person's work.
- Never commit `.env`, API keys, credentials, private datasets or generated large artifacts unless explicitly required.
- If the shared branch diverges, stop and report the exact commits. Do not improvise a destructive merge/rebase.

## 5. Definition of a valid handoff

A handoff is valid only if it contains:

- Phase and owner/reviewer.
- Base and result commit SHAs.
- Scope completed.
- Files changed.
- Tests and exact commands actually run.
- Results, including failures.
- Known limitations and unverified areas.
- Architecture/contract deviations and decision references.
- Next phase owner.

## 6. Scope cuts if behind schedule

Cut in this order:

1. Optional LLM provider integration.
2. Extra anomaly algorithms beyond MAD/EWMA.
3. Advanced log-template mining.
4. Advanced configuration analysis.
5. Cosmetic CLI animation and optional report formatting.

Do not cut:

- Pydantic contracts.
- Four meaningful domain controllers.
- Typed inter-tower communication.
- Supervisor-owned task delegation.
- Evidence provenance.
- Independent evidence gate.
- LLM-off deterministic demo.
- At least one malformed/missing/incompatible input test.
- Reproducible CLI run.

## 7. Change-control rule

If either teammate changes architecture, phase ownership, task authority, public message fields, or data semantics:

1. Stop affected work.
2. Add a decision record to `docs/DECISIONS.md`.
3. Describe migration and compatibility impact.
4. Obtain agreement from both humans.
5. Update the architecture/contract documents and tests in the same phase.

Never make a silent breaking contract change.
