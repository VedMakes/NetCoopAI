# CLI setup and field guide

Use the CLI to analyze a local capture, save reports, adapt a site's input fields, or automate repeatable checks. Diagnosis defaults to deterministic local analysis, so the basic workflow does not need an API key.

## 1. Install NetCoop

Requirements: Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) (recommended).

From a terminal:

```bash
git clone https://github.com/VedMakes/NetCoopAI.git
cd NetCoopAI
uv sync
uv run netcoop doctor
```

If you do not use `uv`, install in a virtual environment instead:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
netcoop doctor
```

## 2. Run your first diagnosis

Point `triage` (an alias for `diagnose`) at a telemetry file or a directory containing one. JSON, JSONL, CSV, and JSON Lines stored in a `.log` file are supported. A map is optional.

```text
office-capture/
├── telemetry.jsonl
└── topology.json       # optional network map
```

```bash
uv run netcoop triage ./office-capture --site office-east --explain
```

The command prints the diagnosis and evidence report. `--explain` streams a readable account of specialist findings, agent handoffs, task choices, gate checks, and other workflow events to stderr; the report stays on stdout so JSON output remains usable in scripts. It exposes concise rationale summaries, not private model chain-of-thought. Task scores are heuristics, not probabilities.

For a one-off capture and separate topology file:

```bash
uv run netcoop triage ./office-capture/telemetry.jsonl \
  --site office-east \
  --sitemap ./office-east-topology.json
```

The input directory can include `topology.json`; `--sitemap` or `--topology` overrides it. With `--site`, NetCoop looks for `config/sites/<site>/topology.json` and `config/profiles/<site>.yaml` (or `.yml`) when available. Use `--profile` to choose a different profile. See [input formats](INPUT_FORMATS.md) and [network profiles](NETWORK_PROFILES.md).

## Understand the result

The report combines the four specialist domains—performance, infrastructure, connectivity, and services—under a supervisor, then sends the proposal through an independent evidence gate. The gate checks evidence references and provenance. If the capture does not support a reliable cause, the system can abstain.

Pay particular attention to:

- **Status and confidence:** a diagnosis may be published, or the system may abstain for insufficient evidence.
- **Observed entities:** devices or segments directly supported by cited telemetry.
- **Inferred affected entities:** topology-based candidates that may be downstream of a finding. These are predictions, not confirmed impact.
- **Evidence and limitations:** cited observations, data-quality warnings, missing measurements, and uncertainty.
- **Recommended checks:** follow-up steps supported by the investigation. NetCoop does not perform live device probes.

An absent path in a partial or unknown map is not proof of a network partition. Only a map explicitly marked complete can support that interpretation.

## Add an optional caller symptom

The symptom comparison runs after the diagnosis is decided. It cannot steer the towers or change the gate result. The flag also opens session chat after the run:

```bash
uv run netcoop triage ./office-capture \
  --symptom-chat "Wi-Fi drops in the second-floor meeting rooms"
```

This optional feature requires a configured LLM provider. It compares the caller's wording with the diagnosis and labels the relationship as aligned, mismatched, or unclear. Treat caller wording as context, not telemetry.

## Optional LLM diagnosis

Deterministic diagnosis works offline. To enable the optional model-assisted recommendation path, configure OpenRouter:

```bash
export OPENROUTER_API_KEY="your-key"
# Optional overrides:
export OPENROUTER_MODEL="provider/model"
export OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"

uv run netcoop triage ./office-capture --llm auto
```

`--llm auto` uses the model path when configured; `--llm on` requires it; `--llm off` keeps diagnosis deterministic. The deterministic runtime retains control of the diagnosis, affected entities, confidence, and evidence references. Model-assisted recommendations are bounded and cannot override abstentions. The model and base URL have application defaults.

Session chat always requires a working LLM configuration. If the provider fails, NetCoop reports that failure instead of substituting a deterministic chat response.

## Save reports and automate

Choose a format and optional output path:

```bash
uv run netcoop triage ./office-capture --format markdown --output report.md
uv run netcoop triage ./office-capture --format json --output report.json
```

Other useful commands:

```bash
uv run netcoop scenarios
uv run netcoop demo
uv run netcoop validate path/to/data.jsonl
uv run netcoop ingest path/to/data.jsonl --incident-id INC-001 --db incident.db
uv run netcoop inspect --db incident.db --incident-id INC-001
```

Run `uv run netcoop --help` or `uv run netcoop <command> --help` for current command options.

## Reuse site-specific input mappings

If your collector uses different names or units, create and validate a profile before relying on it:

```bash
uv run netcoop profile-init ./office-capture \
  --name "Office East" \
  --output config/profiles/office-east.yaml

uv run netcoop profile-validate config/profiles/office-east.yaml \
  --data ./office-capture

uv run netcoop triage ./office-capture --site office-east
```

Review generated profiles: they can suggest recognized metric mappings, but they cannot infer every vendor's semantics, service roles, topology anchors, or map completeness. Profiles support known canonical metrics; an entirely new signal still needs analyzer support. More detail: [Network profiles](NETWORK_PROFILES.md).

## Try the included cases

`fixtures/scenarios/` contains seven provided challenge scenarios and 21 NetCoop regression captures: seven scenario presets with three seeds each (7, 42, and 2026). Five additional `edge_*` captures exercise selected tricky conditions such as mixed DNS/DHCP issues, a misleading high-utilization signal, malformed input, and broken topology. The edge cases are demonstrations, not scored benchmarks.

These are synthetic regression checks, not a representative estimate of real-world accuracy. The provided generator uses a fixed campus topology, a narrow observation schema, and one injected fault class per run. Its score cannot establish production performance. For a short live demo, see [Demo walkthrough](DEMO_SCRIPT.md).

## Shared local sessions

CLI and dashboard sessions share run history and conversation data stored locally under `data/netcoop/`:

```bash
uv run netcoop sessions new --title "Office East"
uv run netcoop sessions list
uv run netcoop sessions use session-<id>
uv run netcoop sessions current
uv run netcoop sessions chat
```

Attach a diagnosis to an existing session or start a fresh one:

```bash
uv run netcoop triage ./office-capture --session session-<id>
uv run netcoop triage ./another-capture --new-session --chat
```

Without `--session` or `--new-session`, the CLI reuses its selected session, or selects the most recently updated session. `--chat` opens read-only Q&A after diagnosis; `--symptom-chat` also opens it. Type `/exit` or press Ctrl+C to close chat. To add more data, run `triage` again with the capture and same session ID. Chat text is never ingested as telemetry.
