# Rubric Evidence and Evaluation Limits

This page maps the challenge brief's evaluation criteria to project artifacts and reproducible checks. The results below are local regression evidence, not an independent audit or a prediction of judge scoring.

## Reproduce the current checks

From the repository root:

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests
uv run python scripts/evaluate_generator.py
```

The package generator evaluation uses seven presets and seeds `7`, `42`, and `2026` (21 runs total). The runtime does not read the generator's `evaluation/ground_truth.json`; the evaluation script reads labels after each diagnosis.

At the working revision associated with this report, the unit suite returns **214 passed** and Ruff passes.

Latest recorded generator run:

- Exact fault-class accuracy: **21/21 (100%)**.
- Intended target included in affected-device output: **21/21 (100%)**.
- Affected-device set vs. generator annotations: precision **83.3%**, recall **100%**, F1 **90.9%**, exact set match **15/21 (71.4%)**.

These numbers are limited to the organizer-style synthetic generator: seven fault presets, one topology, and one injected fault class per run. They do not establish production accuracy, confidence calibration, or performance on unrelated vendors and networks.

## Rubric mapping

| Brief criterion | Weight | Evidence in repository | Current evidence and limits |
|---|---:|---|---|
| Agent interoperability and protocol design | 30% | Typed event, peer-query, task, finding, and report contracts in `src/netcoop/communication/`; `tests/unit/test_contracts.py`; `tests/unit/test_fabric.py` | Tests cover field validation, one-hop authorization, supervisor-only task dispatch, event ordering/idempotency, and four-tower shared-incident execution. This verifies local contracts; there is no cross-process interoperability test. |
| Diagnostic accuracy and evidence quality | 25% | `src/netcoop/towers/`, `src/netcoop/supervisor/gate.py`; `tests/unit/test_benchmarks_and_robustness.py`; `scripts/evaluate_generator.py` | Generator results above; gate tests cover unknown, cross-incident, superseded, and retracted evidence. Most labeled accuracy evidence remains synthetic. |
| Agent orchestration and conflict resolution | 15% | `src/netcoop/supervisor/runtime.py`, `src/netcoop/supervisor/agent.py`; `tests/unit/test_supervisor.py` | Tests cover conflict classification, bounded tasks, task ranking, unavailable signals, duplicate suppression, one gate retry, and abstention when retry does not resolve a gate issue. |
| Robustness to missing, inconsistent, or incompatible data | 15% | `src/netcoop/ingestion/`, `src/netcoop/configuration/profile.py`; `tests/unit/test_loaders.py`, `tests/unit/test_profiles.py`, `tests/unit/test_benchmarks_and_robustness.py` | Tests include malformed-record quarantine, unknown/incomplete topology, incompatible units/vendor fields, high-utilization red herring, compound faults, and impact separation. Synthetic transformations do not substitute for real captures. |
| Code quality, documentation, and demonstration | 5% | `README.md`, `docs/INPUT_FORMATS.md`, `docs/NETWORK_PROFILES.md`, `docs/ARCHITECTURE.md`, `docs/DEMO_SCRIPT.md`; pytest and Ruff commands above | Setup and CLI instructions are present. The brief requests a 3–5 minute demo video; whether a recording exists is **Unknown**. |
| Innovation, usability, and extensibility | 10% | `netcoop triage`, `--explain`, profile-init/profile-validate commands, `src/netcoop/configuration/profile.py` | The CLI demonstrates live agent handoffs and supports site-specific field, unit, alias, and topology mappings. Usability and adaptation effort have not been measured with external operators. |

## Adversarial and ambiguity checks

The following named tests exercise cases beyond the seven basic presets:

- `test_red_herring_high_utilization_alone_does_not_diagnose_congestion`: high utilization without queue drops or packet loss must not become a congestion diagnosis.
- `test_generated_compound_dns_and_congestion_preserves_both_causes`: co-occurring injected faults should remain visible as concurrent causes.
- `test_service_peer_query_reports_unknown_for_missing_path_in_unknown_topology`: missing edges in an unknown-completeness map are not treated as proof of a route failure.
- `test_cli_ingestion_quarantine_is_preserved_in_final_report`: malformed input is quarantined and the quality warning reaches the report.
- `test_task_result_rejects_mismatched_observation_provenance`: a task cannot attach mismatched timestamps, sources, values, or observation references.
- `test_unavailable_signal_becomes_specific_operator_question` and `test_stored_only_task_skips_when_required_signal_is_unavailable`: unavailable stored telemetry is named explicitly; no live probe is implied.

## Optional LLM path boundary

The RCA adapter sends a `system` message and a structured `user` message to the OpenRouter Chat Completions API. The optional symptom adapter also sends a system message, but runs after the evidence gate and cannot change the diagnosis. Prompts are guidance; code and the independent release gate enforce the actual boundary.

The RCA controller remains authoritative: if deterministic arbitration requests evidence or abstains, the LLM request is skipped. For an eligible deterministic diagnosis, model output cannot alter the decision, root cause, affected entities, confidence, alternatives, evidence references, or manifest. Its only accepted contribution is a bounded read-only recommendation that uses known incident identifiers. Tests for these properties are in `tests/unit/test_openrouter.py`; gate rejection of an undisclosed hypothesis is covered in `tests/unit/test_supervisor.py`.

LLM network calls are not part of the deterministic test suite. Prompt construction and response handling are tested with mocked responses. Provider-specific behavior can vary by model and API version.

## Evidence still needed

- Authorized, production-like captures or an independent network simulator with separately reviewed labels.
- A broader multi-vendor/profile evaluation, with per-field normalization and failure rates reported.
- Confidence calibration and abstention metrics on ambiguous, incomplete, and conflicting cases.
- Operator usability feedback and a recorded 3–5 minute demonstration, if the team has not already made one.
- A repeatable evaluation of the optional LLM path using saved, privacy-safe cases and fixed model identifiers; do not count one live model response as a stable accuracy result.
