# Web dashboard setup and guide

The dashboard is for visual investigations: choose a bundled scenario or upload a capture, watch the run progress, inspect findings and topology, then continue in a saved session.

## Requirements

- Python 3.12 or newer and `uv`.
- Node.js 18 or newer and npm.
- An OpenRouter API key only for LLM diagnosis options, symptom comparison, and session chat. Basic deterministic diagnosis runs without it.

## Install

From the repository root:

```bash
uv sync
cd web
npm ci
cd ..
```

`npm ci` installs the frontend dependencies from the checked-in lockfile.

## Start the API and dashboard

Run these in two terminals, from the repository root unless noted.

**Terminal 1 — backend API:**

```bash
uv run netcoop api --host 127.0.0.1 --port 8000
```

**Terminal 2 — frontend:**

```bash
cd web
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Stop either process with Ctrl+C. The Vite development server proxies API requests to the local backend.

## Run an investigation

### Use a bundled scenario

Choose a scenario from the picker and start analysis. The catalog contains seven challenge cases, 21 regression variants, and five additional diagnostic-only edge captures. Edge captures are exploratory examples and have no ground-truth score.

### Upload your own telemetry

In the simulation page, choose **Analyze your network data** and explicitly select or drop a telemetry file. Supported files are `.json`, `.jsonl`, `.csv`, or `.log` containing JSON Lines. Telemetry is required and limited to 20 MB. A `.log` suffix does not mean arbitrary raw syslog text is supported.

You may also attach a topology JSON file, up to 5 MB. A topology is optional but can help identify paths, segments, and predicted impact. The dashboard accepts file contents; it does not connect to your network or accept server filesystem paths. See [Input formats](INPUT_FORMATS.md) for examples and limitations.

### Follow progress and interpret the report

During a run, the dashboard displays activity as the investigation proceeds. When complete, inspect the diagnosis, confidence/status, supporting evidence, specialist results, recommendations, and data-quality or limitation notes. The topology graph can be dragged and zoomed; it helps navigate the declared structure, but a graph path alone is not proof of causation.

Impact is separated into directly observed entities and topology-inferred candidates. Predicted impact is not confirmed user impact. An absent path in a partial or unknown topology cannot establish a partition.

## Sessions and assistant chat

The session selector lets you create and return to multiple local investigations. Each session can contain several analysis runs and its own assistant conversation. Sessions, reports, run history, and assistant turns are shared with the CLI and stored under the repository's ignored `data/netcoop/` directory.

The assistant can explain published diagnoses, answer questions using the session's run history, and compare runs. It is read-only: chat text does not become telemetry or alter a diagnosis. To provide new evidence:

1. Use **Add telemetry & re-analyze** to open the explicit upload flow.
2. Select a new telemetry capture and, optionally, a topology map.
3. Start the new analysis. It is added as another run in the same session.
4. Return to chat, which receives the updated run history.

Chat requires an LLM provider. If a request fails, the application reports the failure; it does not present a deterministic answer as if it came from the model. The symptom field is optional and runs a comparison after diagnosis. It cannot steer the diagnostic decision.

## Efficient model configuration

Set the key in the environment before starting the backend:

```bash
export OPENROUTER_API_KEY="your-key"
# Configuration overrides:
export OPENROUTER_MODEL="provider/model"
export OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"

uv run netcoop api --host 127.0.0.1 --port 8000
```

Defaults are provided for the model and base URL. Keep keys out of source control. Model requests send the context needed for that feature to the configured provider; use only data permitted by your organization's policy.

## Troubleshooting

- **Dashboard cannot reach the backend:** make sure the API is running on `127.0.0.1:8000` and reload the page.
- **Chat or symptom review says no model is configured:** set `OPENROUTER_API_KEY` in the same environment used to start the API, then restart it.
- **A prior CLI-created session is missing:** use the dashboard's refresh control to reload the local session list.
- **A run is interrupted after stopping the API:** restart the API and reopen the session. An active run interrupted by process shutdown is marked interrupted; completed runs remain available.
- **A file is rejected:** check the supported formats, telemetry/topology size limits, and the examples in [Input formats](INPUT_FORMATS.md).
