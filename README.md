# NetCoop

NetCoop helps network operators investigate service problems from telemetry they already have. Give it a capture (and, when available, a topology map) and it produces an evidence-linked diagnosis, affected-entity summary, limitations, and next steps.

Use the **CLI** for quick local investigations and automation, or the **web dashboard** for a visual workflow with saved sessions, a topology view, and follow-up chat. Both interfaces use the same local session and run data.

> NetCoop analyzes supplied files. It does not connect to routers, switches, access points, or monitoring systems to collect live telemetry.

## Pick a way to get started

| I want to… | Start here |
| --- | --- |
| Install and run an investigation in a terminal | [CLI setup and guide](docs/CLI.md) |
| Start the API and browser dashboard | [Dashboard setup and guide](docs/DASHBOARD.md) |
| Check which telemetry and map formats work | [Input formats](docs/INPUT_FORMATS.md) |
| Adapt NetCoop to a site's field names and conventions | [Network profiles](docs/NETWORK_PROFILES.md) |
| Run a short demonstration | [Demo walkthrough](docs/DEMO_SCRIPT.md) |

## How an investigation works

1. **Load the capture.** NetCoop reads local JSON, JSON Lines, or CSV telemetry. A JSON topology map is optional. Parsers normalize supported fields and report malformed, missing, or unfamiliar data instead of silently inventing measurements.
2. **Analyze in specialist domains.** Performance, infrastructure, connectivity, and services specialists inspect the normalized evidence. They can exchange bounded, read-only requests through the integration fabric when a cross-domain check is relevant.
3. **Coordinate and verify.** The supervisor coordinates investigation tasks and synthesizes candidate causes. An independent evidence gate checks the proposal's evidence references and provenance before a diagnosis is published. If support is insufficient, NetCoop can abstain.
4. **Explain impact and limits.** The report distinguishes entities directly supported by observations from additional entities inferred through declared topology. It includes evidence, confidence, data limitations, and recommended follow-up checks.
5. **Continue in a session if useful.** A saved session can contain several analysis runs and a read-only assistant conversation. To add telemetry, explicitly start another run; chat text itself is not treated as telemetry or diagnosis evidence.

## What NetCoop can help with

- **Performance specialist:** checks supported signals such as interface utilization, queue drops, packet loss, retransmissions, jitter, and Wi-Fi RSSI/SNR.
- **Infrastructure specialist:** checks device resource pressure, interface state and errors, and supported system-log indicators.
- **Connectivity specialist:** uses declared physical links to reason about paths and possible downstream impact. It treats a missing path as meaningful only when the topology is marked complete.
- **Services specialist:** checks supported DNS, DHCP, and other service-health signals, including logical dependencies declared in a map.
- **Supervisor and evidence gate:** the supervisor coordinates scoped work and combines specialist proposals. A separate gate verifies evidence references and provenance before release; unsupported proposals can be rejected or abstained.
- **Agent communication:** specialists can exchange bounded, read-only peer checks through a typed integration fabric. The supervisor can request scoped follow-up analysis. Use the CLI's `--explain` option to watch findings, handoffs, task selection, and gate decisions as a run happens.
- **Reports and impact:** output includes diagnosis status, confidence, evidence, limitations, recommendations, and separate directly observed versus topology-inferred entities. JSON and Markdown reports are available from the CLI.
- **Optional symptom comparison:** `--symptom-chat` or the dashboard's symptom field compares a caller's description with the completed diagnosis after the evidence gate. It cannot steer or replace the diagnosis.
- **Sessions and follow-up:** CLI and dashboard share locally stored sessions. The session assistant can explain completed runs and compare results; it requires an LLM provider and cannot add new telemetry through chat.

Input profiles let an operator map supported telemetry field names, metric names/units, aliases, roles, and topology relationships to NetCoop's canonical format. They do not make arbitrary vendor payloads or new diagnostic metrics work automatically; see [Network profiles](docs/NETWORK_PROFILES.md) for adaptation limits.

## Important interpretation notes

- A topology-inferred affected entity is a **predicted impact candidate**, not proof that a user or device was actually affected. Directly observed and inferred impact are reported separately.
- An absent route is meaningful only when the topology is declared complete. Partial or unknown maps cannot establish a partition just because an edge is missing.
- A symptom is context for a post-diagnosis comparison, not evidence used to choose the diagnosis.
- NetCoop does not run live network probes. If a useful signal is absent from the capture, the result should state that limitation rather than claim to have measured it.
- Built-in scenarios and regression fixtures are synthetic development checks. They do not estimate accuracy on real production networks. See [the benchmark notes](docs/CLI.md#try-the-included-cases) and the input/profile guides for scope and adaptation limits.

## Requirements

- Python 3.12 or newer.
- For the browser dashboard: Node.js 18 or newer and npm.
- For LLM-assisted diagnosis, symptom comparison, or session chat: an OpenRouter API key. Core deterministic diagnosis runs locally without a key.

## Local data and privacy

Run records, reports, sessions, and assistant turns are stored locally under `data/netcoop/`, which is ignored by Git. LLM features send the information needed for that request to the configured model provider; deterministic diagnosis does not make model API calls. Do not send sensitive production data to an external provider unless your organization's policy allows it.
