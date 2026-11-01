# NetCoop demonstration

Use this short walkthrough to show a baseline, a diagnosed fault, the optional symptom note, and a topology path. The commands use the bundled sample cases and run offline.

## 1. Check the local installation

```bash
uv run netcoop doctor
```

This checks Python, local configuration, the capability registry, SQLite initialization, and tower startup.

## 2. Show a clean abstention

```bash
uv run netcoop triage fixtures/scenarios/healthy
```

NetCoop should abstain when the available observations do not support a fault. Use this to explain that the tool can report insufficient evidence instead of forcing a diagnosis.

## 3. Diagnose a fault and inspect its evidence

```bash
uv run netcoop triage fixtures/scenarios/link_congestion
```

Walk through the specialist summary, certified root cause, confidence, observed entities, predicted impact, evidence, limitations, and recommendations. Impact inferred from topology is a prediction, not confirmed user impact.

## 4. Add the caller's wording

```bash
uv run netcoop triage fixtures/scenarios/dns_failure \
  --symptom-chat "Users cannot resolve hostnames" \
  --format markdown -o dns-report.md
```

The symptom comparison runs after the evidence gate and requires a configured LLM. It never changes the diagnosis. Omit `--symptom-chat` to skip the optional comparison.

## 5. Use a separate site map

```bash
uv run netcoop triage ./office-capture \
  --site office-east \
  --sitemap ./office-east-topology.json \
  --symptom-chat "Wi-Fi drops in the second-floor meeting rooms"
```

The first path is local telemetry or a capture directory. The sitemap is read as topology context; it does not establish causation. See [Local Input Formats](INPUT_FORMATS.md) for the JSON structure and [Network Profiles](NETWORK_PROFILES.md) for site-specific mappings.

## 6. Export for other tools

```bash
uv run netcoop triage fixtures/scenarios/dhcp_failure \
  --format json -o dhcp-report.json --db incident.db
uv run netcoop inspect --db incident.db --incident-id INC-SYNTH-DHCP-001
```

Use JSON for automation, Markdown for an incident handoff, and `--db` when you need local persistence. Without `--db`, the command uses a temporary in-memory database.
