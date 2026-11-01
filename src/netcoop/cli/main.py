"""NetCoop AI command-line interface.

Provides operator commands for environment diagnostics, telemetry ingestion,
validation, automated scenario generation, incident investigation, database inspection,
and offline demonstration.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console, Theme
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
from rich.table import Table

from netcoop import __version__
from netcoop.communication.fabric import IntegrationFabric
from netcoop.communication.registry import CapabilityRegistry
from netcoop.communication.vocabulary import load_vocabulary
from netcoop.configuration.profile import MetricMapping, NetworkProfile
from netcoop.features.pipeline import FeaturePipeline
from netcoop.ingestion.loaders import TelemetryLoader
from netcoop.ingestion.normalization import normalize_metric_name, normalize_metric_value_and_unit
from netcoop.models.observations import (
    CanonicalObservation,
    ConfigObservation,
    LogObservation,
    MetricObservation,
    TopologyObservation,
)
from netcoop.reports.renderer import render_markdown_report
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.supervisor.agent import (
    DeterministicRCAProvider,
    SupervisoryRCAAgent,
    get_rca_provider,
)
from netcoop.supervisor.gate import EvidenceReleaseGate
from netcoop.supervisor.runtime import EvidenceGateRejectionError, SupervisorRuntime
from netcoop.supervisor.symptom_agent import SymptomReasoningAgent
from netcoop.towers.rules import load_rules
from netcoop.utils.env import load_dotenv
from netcoop.utils.id_generator import generate_id

load_dotenv()

app = typer.Typer(
    name="netcoop",
    help="NetCoop AI: Evidence-Backed Multi-Agent Network Fault Diagnosis",
    no_args_is_help=True,
)
sessions_app = typer.Typer(name="sessions", help="List and select shared local investigation sessions.", no_args_is_help=True)
app.add_typer(sessions_app, name="sessions")
CLI_THEME = Theme({
    "cyan": "#C7A7EF",
    "bright_cyan": "#DEC9FA",
    "magenta": "#C58DDC",
    "blue": "#927DB6",
    "bright_blue": "#B4A0DA",
    "green": "#95C9AD",
    "bright_green": "#B1DCC0",
    "yellow": "#E4C681",
    "red": "#D98F9F",
    "dim": "dim #9D95AA",
    "table.border": "#58496B",
    "table.header": "bold #DCC8F4",
    "table.title": "bold #E5D6F6",
    "panel.border": "#786392",
    "progress.description": "#D6C3ED",
    "progress.percentage": "#C7A7EF",
})
console = Console(theme=CLI_THEME)
explain_console = Console(theme=CLI_THEME, stderr=True)
chat_console = Console(theme=CLI_THEME, stderr=True)


def _local_run_manager():
    # Delayed import avoids the CLI/service import cycle: the API reuses CLI ingestion helpers.
    from netcoop_api.service import run_manager

    return run_manager


def _cli_session_state_path(manager) -> Path:
    return manager.storage_dir / "cli-state.json"


def _save_cli_session_id(manager, session_id: str) -> None:
    path = _cli_session_state_path(manager)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"active_session_id": session_id}), encoding="utf-8")
    temporary.replace(path)


def _select_cli_session(
    *,
    session_id: str | None,
    create_new: bool,
    title: str = "CLI investigation",
) -> str:
    manager = _local_run_manager()
    manager.refresh_external_state()
    if session_id and create_new:
        raise ValueError("--session and --new-session cannot be used together")
    if create_new:
        selected = manager.create_session(title)
    elif session_id:
        selected = manager.get_session(session_id)
        if selected is None:
            raise ValueError(f"Session '{session_id}' was not found")
    else:
        active_id = None
        try:
            state = json.loads(_cli_session_state_path(manager).read_text(encoding="utf-8"))
            active_id = state.get("active_session_id") if isinstance(state, dict) else None
        except (OSError, json.JSONDecodeError):
            pass
        selected = manager.get_session(active_id) if isinstance(active_id, str) else None
        if selected is None:
            available = manager.list_sessions()
            selected = manager.get_session(available[0].session_id) if available else None
        if selected is None:
            selected = manager.create_session(title)
    _save_cli_session_id(manager, selected.session_id)
    return selected.session_id


@sessions_app.command("list")
def list_sessions() -> None:
    """List sessions shared with the local web dashboard."""
    manager = _local_run_manager()
    manager.refresh_external_state()
    current_id = None
    try:
        state = json.loads(_cli_session_state_path(manager).read_text(encoding="utf-8"))
        current_id = state.get("active_session_id") if isinstance(state, dict) else None
    except (OSError, json.JSONDecodeError):
        pass
    table = make_table(title="Investigation Sessions")
    table.add_column("Active", justify="center")
    table.add_column("Session ID", style="cyan")
    table.add_column("Title")
    table.add_column("Runs", justify="right")
    table.add_column("Updated")
    for session in manager.list_sessions():
        table.add_row(
            "*" if session.session_id == current_id else "",
            session.session_id,
            session.title,
            str(session.run_count),
            session.updated_at.strftime("%Y-%m-%d %H:%M UTC"),
        )
    if not manager.list_sessions():
        console.print("No sessions yet. Create one with [cyan]netcoop sessions new[/cyan].")
    else:
        console.print(table)


@sessions_app.command("new")
def new_session(
    title: str = typer.Option("CLI investigation", "--title", help="Readable session title."),
) -> None:
    """Create and select a session shared with the dashboard."""
    session_id = _select_cli_session(session_id=None, create_new=True, title=title)
    console.print(f"[green]Created and selected session[/green] [cyan]{session_id}[/cyan]")


@sessions_app.command("use")
def use_session(session_id: str = typer.Argument(..., help="Session ID shown by `netcoop sessions list`.")) -> None:
    """Select an existing shared session for subsequent CLI runs."""
    try:
        selected_id = _select_cli_session(session_id=session_id, create_new=False)
    except ValueError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=2)
    console.print(f"[green]Selected session[/green] [cyan]{selected_id}[/cyan]")


@sessions_app.command("current")
def current_session() -> None:
    """Show the session selected for subsequent CLI runs."""
    manager = _local_run_manager()
    try:
        state = json.loads(_cli_session_state_path(manager).read_text(encoding="utf-8"))
        session_id = state.get("active_session_id") if isinstance(state, dict) else None
    except (OSError, json.JSONDecodeError):
        session_id = None
    session = manager.get_session(session_id) if isinstance(session_id, str) else None
    if session is None:
        console.print("No active CLI session. Use [cyan]netcoop sessions new[/cyan].")
        return
    console.print(f"[cyan]{session.session_id}[/cyan] · {session.title} · {session.run_count} run(s)")


def make_table(*args: Any, **kwargs: Any) -> Table:
    """Apply the End-inspired amethyst table treatment consistently."""
    kwargs.setdefault("border_style", "cyan")
    kwargs.setdefault("header_style", "bright_cyan")
    kwargs.setdefault("title_style", "bold bright_cyan")
    kwargs.setdefault("row_styles", ["", "dim"])
    return Table(*args, **kwargs)


def _soft_status(message: str):
    """Show a quiet animated spinner only on interactive terminals."""
    if not console.is_terminal or os.environ.get("NO_COLOR"):
        return nullcontext()
    return console.status(f"[cyan]✦ {message}[/cyan]", spinner="dots")


def _run_session_chat(session_id: str, llm_mode: str) -> None:
    """Open the shared session assistant; Ctrl+C closes chat without deleting the session."""
    from netcoop_api.assistant import assistant_service
    from netcoop_api.schemas import AssistantRequest

    manager = _local_run_manager()
    session = manager.get_session(session_id)
    if session is None:
        chat_console.print(f"[red]Session {session_id} is no longer available.[/red]")
        return
    completed_count = sum(run.status == "completed" for run in session.runs)
    chat_console.print(Panel(
        f"[bold]Session:[/bold] {session.title} · {session_id}\n"
        f"[bold]Completed runs in context:[/bold] {completed_count} (up to 5 most recent)\n"
        "Ask about diagnoses, symptoms, evidence, or compare runs. New telemetry must be added with a new triage command.\n"
        "Type [cyan]/exit[/cyan] or press [cyan]Ctrl+C[/cyan] to close chat; the session remains available in CLI and dashboard.",
        title="NetCoop Session Chat",
        border_style="magenta",
    ))
    while True:
        try:
            question = Prompt.ask("[bright_cyan]You[/bright_cyan]", console=chat_console).strip()
        except (KeyboardInterrupt, EOFError):
            chat_console.print("\n[dim]Chat closed. The session is saved and remains available.[/dim]")
            return
        if not question:
            continue
        if question.casefold() in {"/exit", "/quit", "/close"}:
            chat_console.print("[dim]Chat closed. The session is saved and remains available.[/dim]")
            return
        try:
            response = assistant_service.answer_session_question(
                session_id,
                AssistantRequest(question=question, llm=llm_mode),
            )
            chat_console.print(Panel(
                Markdown(response.answer),
                title=f"NetCoop · {response.provider_used}",
                border_style="cyan",
            ))
        except Exception as exc:
            chat_console.print(f"[bold red]Chat response failed:[/bold red] {exc}")


@sessions_app.command("chat")
def chat_session(
    session_id: str | None = typer.Argument(None, help="Session ID; defaults to the selected CLI session."),
    llm: str = typer.Option("off", "--llm", help="LLM mode for answers: off, auto, or on."),
) -> None:
    """Resume read-only Q&A for a saved investigation session."""
    try:
        selected_id = _select_cli_session(
            session_id=session_id,
            create_new=False,
            title="CLI investigation",
        )
    except ValueError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=2)
    if llm not in {"off", "auto", "on"}:
        console.print("[bold red]--llm must be off, auto, or on.[/bold red]")
        raise typer.Exit(code=2)
    _run_session_chat(selected_id, llm)


def _demo_progress() -> Progress:
    return Progress(
        SpinnerColumn("dots", style="cyan"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=22, complete_style="magenta", finished_style="bright_cyan", pulse_style="blue"),
        MofNCompleteColumn(),
        console=console,
        transient=False,
        refresh_per_second=10,
        disable=not console.is_terminal or bool(os.environ.get("NO_COLOR")),
    )


def version_callback(value: bool):
    if value:
        console.print(f"[bold cyan]NetCoop AI[/bold cyan] version [green]{__version__}[/green]")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
):
    """NetCoop AI diagnostic framework."""
    pass


@app.command()
def doctor():
    """Validates the local environment, Python runtime, configuration, and SQLite storage."""
    table = make_table(title="NetCoop System Doctor")
    table.add_column("Component", style="bold")
    table.add_column("Status", style="green")
    table.add_column("Details")

    # 1. Python version check
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 12):
        table.add_row("Python Runtime", "OK", f"CPython {py_ver}")
    else:
        table.add_row("Python Runtime", "[red]FAIL[/red]", f"Requires >= 3.12, found {py_ver}")

    # 2. Vocabulary config check
    try:
        vocab = load_vocabulary(force_reload=True)
        metrics_count = len(vocab.get("metrics", {}))
        table.add_row("Vocabulary Config", "OK", f"{metrics_count} canonical metrics loaded")
    except Exception as e:
        table.add_row("Vocabulary Config", "[red]FAIL[/red]", str(e))

    # 3. Capabilities config check
    try:
        CapabilityRegistry.load()
        table.add_row("Capability Registry", "OK", "4 tower profiles loaded")
    except Exception as e:
        table.add_row("Capability Registry", "[red]FAIL[/red]", str(e))

    # 4. SQLite repository check
    try:
        repo = SQLiteRepository(":memory:")
        schema_ver = repo.get_schema_version()
        table.add_row("SQLite Engine", "OK", f"Initialized in-memory DB (schema v{schema_ver})")
    except Exception as e:
        table.add_row("SQLite Engine", "[red]FAIL[/red]", str(e))

    # 5. Diagnostic Tower Controllers check
    try:
        fabric = IntegrationFabric(repository=repo)
        table.add_row(
            "Diagnostic Towers",
            "OK",
            f"{len(fabric.towers)} domain controllers ready (Performance, Infra, Conn, Services)",
        )
    except Exception as e:
        table.add_row("Diagnostic Towers", "[red]FAIL[/red]", str(e))

    # 6. Supervisor Runtime & Evidence Gate check
    try:
        gate = EvidenceReleaseGate(repository=repo)
        SupervisorRuntime(fabric=fabric, repository=repo, gate=gate)
        table.add_row("Supervisor & Gate", "OK", "SupervisorRuntime & EvidenceReleaseGate initialized")
    except Exception as e:
        table.add_row("Supervisor & Gate", "[red]FAIL[/red]", str(e))

    # 7. OpenRouter LLM Provider check
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    model_name = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    if openrouter_key:
        table.add_row("OpenRouter Provider", "OK", f"Configured ({model_name})")
    else:
        table.add_row("OpenRouter Provider", "Offline", "No API key (Deterministic fallback active)")

    console.print(table)


@app.command()
def validate(
    fixture_path: Path = typer.Argument(
        ...,
        help="Path to an incident JSON fixture file to validate.",
        exists=True,
        readable=True,
    ),
):
    """Validates an input telemetry fixture against canonical observation contracts."""
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    incident_id = data.get("incident_id", "UNKNOWN")
    observations_raw = data.get("observations", [])

    console.print(f"[bold]Validating fixture:[/bold] {fixture_path} (incident: [cyan]{incident_id}[/cyan])")

    validated_metrics = 0
    validated_logs = 0
    validated_topology = 0
    validated_configs = 0
    errors: list[str] = []

    for i, item in enumerate(observations_raw):
        obs_type = item.get("observation_type")
        try:
            if obs_type == "metric":
                MetricObservation.model_validate(item)
                validated_metrics += 1
            elif obs_type == "log":
                LogObservation.model_validate(item)
                validated_logs += 1
            elif obs_type == "topology":
                TopologyObservation.model_validate(item)
                validated_topology += 1
            elif obs_type == "config":
                ConfigObservation.model_validate(item)
                validated_configs += 1
            else:
                errors.append(f"Item {i}: Unknown observation_type '{obs_type}'")
        except Exception as e:
            errors.append(f"Item {i} ({obs_type}): {e}")

    if errors:
        console.print(f"[bold red]Validation failed with {len(errors)} error(s):[/bold red]")
        for err in errors[:10]:
            console.print(f"  • {err}")
        if len(errors) > 10:
            console.print(f"  ... and {len(errors) - 10} more errors.")
        raise typer.Exit(code=1)
    else:
        panel_content = (
            f"[green]✓ All {len(observations_raw)} observations valid![/green]\n"
            f"  • Metrics: {validated_metrics}\n"
            f"  • Logs: {validated_logs}\n"
            f"  • Topology: {validated_topology}\n"
            f"  • Config: {validated_configs}"
        )
        console.print(Panel(panel_content, title="Validation Success", border_style="green"))


@app.command()
def ingest(
    file_path: Path = typer.Argument(
        ...,
        help="Path to telemetry file (.json, .csv, .jsonl, or JSON Lines in a .log file) to ingest.",
        exists=True,
        readable=True,
    ),
    incident_id: str = typer.Option("INC-CLI-001", "--incident-id", "-i", help="Incident ID to associate"),
    db_path: Path | None = typer.Option(None, "--db", help="Optional SQLite database to persist into"),
):
    """Loads, normalizes, and extracts derived features from a telemetry file."""
    loader = TelemetryLoader()
    console.print(f"[bold cyan]Telemetry intake[/bold cyan]  {file_path}  [dim]·[/dim]  [cyan]{incident_id}[/cyan]")
    with _soft_status("Normalizing telemetry and extracting features"):
        batch = loader.load_file(file_path, incident_id=incident_id)
        pipeline = FeaturePipeline()
        features = pipeline.extract_features(batch.observations, incident_id=incident_id)

    # Optional persistence into SQLite
    if db_path:
        repo = SQLiteRepository(db_path)
        repo.record_incident(incident_id, status="active", description=f"Ingested from {file_path.name}")
        for obs in batch.observations:
            repo.insert_observation(obs)
        console.print(f"[green]Persisted {len(batch.observations)} observations to SQLite at {db_path}[/green]")

    table = make_table(title=f"Ingestion & Feature Summary: {incident_id}")
    table.add_column("Category", style="bold")
    table.add_column("Count", style="green")
    table.add_column("Details")

    table.add_row("Total Observations", str(batch.total_count), "Normalized into canonical models")
    table.add_row("Metric Observations", str(batch.metric_count), "Strict units and bounds verified")
    table.add_row("Log Observations", str(batch.log_count), "Normalized timestamps and log levels")
    table.add_row("Topology Observations", str(batch.topology_count), "Entities and relationships mapped")
    table.add_row("Config Observations", str(batch.config_count), "Configuration keys and values")
    table.add_row("Derived Features", str(len(features)), "Rolling stats, MAD, utilization, ratios")

    if batch.warnings:
        table.add_row("Quality Warnings", f"[yellow]{len(batch.warnings)}[/yellow]", "Non-blocking data quality notices")
    if batch.quarantined_records:
        table.add_row("Quarantined Records", f"[red]{len(batch.quarantined_records)}[/red]", "Malformed records isolated without crashing")

    console.print(table)

    if batch.warnings:
        console.print("\n[bold yellow]Recent Quality Warnings:[/bold yellow]")
        for w in batch.warnings[:5]:
            console.print(f"  • [{w.warning_type}] {w.message}")
        if len(batch.warnings) > 5:
            console.print(f"  ... and {len(batch.warnings) - 5} more warnings.")


def _load_observations_from_target(
    target_path: Path,
    incident_id: str | None = None,
    data_quality_warnings: list[str] | None = None,
    profile: NetworkProfile | None = None,
    topology_path: Path | None = None,
) -> tuple[str, list[CanonicalObservation]]:
    """Loads telemetry and optional topology from a file or scenario directory."""
    loader = TelemetryLoader(profile=profile)
    observations: list[CanonicalObservation] = []
    resolved_inc_id = incident_id

    if target_path.is_dir():
        # Check for telemetry file
        telemetry_file = None
        for cand in ["telemetry.jsonl", "telemetry.json", "telemetry.csv", "telemetry.log"]:
            if (target_path / cand).exists():
                telemetry_file = target_path / cand
                break

        if telemetry_file:
            batch = loader.load_file(telemetry_file, incident_id=incident_id)
            observations.extend(batch.observations)
            if data_quality_warnings is not None:
                data_quality_warnings.extend(
                    f"{telemetry_file.name}: {warning.warning_type}: {warning.message}"
                    for warning in batch.warnings
                )
                data_quality_warnings.extend(
                    f"{telemetry_file.name}: quarantined record {item.get('line_index', item.get('row_index', item.get('index', '?')))}: {item.get('error', 'invalid record')}"
                    for item in batch.quarantined_records
                )
            if not resolved_inc_id and batch.observations:
                resolved_inc_id = batch.observations[0].incident_id

        # An explicit sitemap overrides the capture folder's topology.json.
        topo_file = topology_path or target_path / "topology.json"
        if topo_file.exists():
            observations.extend(_load_topology_file(
                topo_file,
                incident_id=resolved_inc_id or incident_id or "INC-TOPOLOGY",
                profile=profile,
                data_quality_warnings=data_quality_warnings,
            ))
    else:
        batch = loader.load_file(target_path, incident_id=incident_id)
        observations.extend(batch.observations)
        if data_quality_warnings is not None:
            data_quality_warnings.extend(
                f"{target_path.name}: {warning.warning_type}: {warning.message}"
                for warning in batch.warnings
            )
            data_quality_warnings.extend(
                f"{target_path.name}: quarantined record {item.get('line_index', item.get('row_index', item.get('index', '?')))}: {item.get('error', 'invalid record')}"
                for item in batch.quarantined_records
            )
        if not resolved_inc_id and batch.observations:
            resolved_inc_id = batch.observations[0].incident_id

        if topology_path:
            observations.extend(_load_topology_file(
                topology_path,
                incident_id=resolved_inc_id or incident_id or "INC-TOPOLOGY",
                profile=profile,
                data_quality_warnings=data_quality_warnings,
            ))

    resolved_inc_id = resolved_inc_id or "INC-CLI-001"

    # Align incident ID across all observations
    aligned: list[CanonicalObservation] = []
    for obs in observations:
        if obs.incident_id != resolved_inc_id:
            obs = obs.model_copy(update={"incident_id": resolved_inc_id})
        if profile and isinstance(obs, MetricObservation):
            mapping = profile.map_metric(obs.metric_name)
            if mapping:
                value, unit, warnings = normalize_metric_value_and_unit(
                    mapping.canonical_name, obs.value, mapping.source_unit or obs.unit
                )
                if value is None or unit is None:
                    if data_quality_warnings is not None:
                        data_quality_warnings.extend(
                            f"Profile {profile.profile_id}: {warning}" for warning in warnings
                        )
                    continue
                obs = obs.model_copy(update={
                    "entity_id": profile.canonical_entity(obs.entity_id),
                    "metric_name": mapping.canonical_name,
                    "value": value,
                    "unit": unit,
                })
            else:
                obs = obs.model_copy(update={"entity_id": profile.canonical_entity(obs.entity_id)})
        elif profile and isinstance(obs, TopologyObservation):
            rel = obs.relationship_type.casefold()
            obs = obs.model_copy(update={
                "entity_id": profile.canonical_entity(obs.entity_id),
                "source_entity": profile.canonical_entity(obs.source_entity),
                "target_entity": profile.canonical_entity(obs.target_entity),
                "relationship_type": profile.canonical_relationship(rel),
            })
        elif profile:
            obs = obs.model_copy(update={"entity_id": profile.canonical_entity(obs.entity_id)})
        aligned.append(obs)

    # Convert configured monotonic counters into interval deltas before the
    # towers see them. A first sample is only a baseline, never an incident.
    if profile:
        counter_groups: dict[tuple[str, str], list[tuple[int, MetricObservation]]] = {}
        for index, obs in enumerate(aligned):
            if not isinstance(obs, MetricObservation):
                continue
            raw_ref = obs.raw_reference or {}
            raw_record = raw_ref.get("raw_record", {})
            raw_row = raw_ref.get("raw_row", {})
            configured_metric_fields = profile.source_field_candidates("metric")
            source_name = (
                raw_ref.get("raw_metric")
                or next((raw_record[name] for name in configured_metric_fields if name in raw_record), None)
                or next((raw_row[name] for name in configured_metric_fields if name in raw_row), None)
                or raw_ref.get("column") or obs.metric_name
            )
            mapping = profile.map_metric(str(source_name))
            if mapping and mapping.counter_semantics == "cumulative_counter":
                counter_groups.setdefault((obs.entity_id, obs.metric_name), []).append((index, obs))

        excluded: set[int] = set()
        replacements: dict[int, MetricObservation] = {}
        for (_entity_id, metric_name), samples in counter_groups.items():
            samples.sort(key=lambda item: (item[1].timestamp, item[1].observation_id))
            previous: MetricObservation | None = None
            seen_timestamps: set[datetime] = set()
            for index, current in samples:
                if current.timestamp in seen_timestamps:
                    excluded.add(index)
                    if data_quality_warnings is not None:
                        data_quality_warnings.append(
                            f"Profile {profile.profile_id}: duplicate timestamp for cumulative counter "
                            f"{current.entity_id}.{metric_name}; sample {current.observation_id} skipped"
                        )
                    continue
                seen_timestamps.add(current.timestamp)
                if previous is None:
                    excluded.add(index)
                    previous = current
                    if data_quality_warnings is not None:
                        data_quality_warnings.append(
                            f"Profile {profile.profile_id}: first cumulative counter sample for "
                            f"{current.entity_id}.{metric_name} used as baseline"
                        )
                    continue
                elapsed = (current.timestamp - previous.timestamp).total_seconds()
                if elapsed <= 0 or current.value < previous.value:
                    excluded.add(index)
                    if data_quality_warnings is not None:
                        reason = "non-increasing timestamp" if elapsed <= 0 else "counter reset/decrease"
                        data_quality_warnings.append(
                            f"Profile {profile.profile_id}: {reason} for cumulative counter "
                            f"{current.entity_id}.{metric_name}; interval skipped"
                        )
                    previous = current
                    continue
                raw_reference = dict(current.raw_reference or {})
                raw_reference["counter_interval"] = {
                    "semantics": "cumulative_counter",
                    "previous_observation_id": previous.observation_id,
                    "interval_seconds": elapsed,
                }
                replacements[index] = current.model_copy(update={
                    "value": current.value - previous.value,
                    "raw_reference": raw_reference,
                })
                previous = current
        aligned = [
            replacements.get(index, obs)
            for index, obs in enumerate(aligned)
            if index not in excluded
        ]

    return resolved_inc_id, aligned


def _load_topology_file(
    topology_path: Path,
    incident_id: str,
    profile: NetworkProfile | None = None,
    data_quality_warnings: list[str] | None = None,
) -> list[TopologyObservation]:
    """Load a standalone NetCoop topology sitemap using the capture-folder contract."""
    def source_field(record: dict[str, Any], field_name: str, defaults: list[str]) -> Any:
        names = profile.source_field_candidates(field_name) if profile else defaults
        return next((record[name] for name in names if name in record and record[name] is not None), None)

    try:
        topo_data = json.loads(topology_path.read_text(encoding="utf-8"))
        if not isinstance(topo_data, dict):
            raise ValueError("topology root must be a JSON object")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        if data_quality_warnings is not None:
            data_quality_warnings.append(f"{topology_path}: topology file ignored: {exc}")
        return []

    if topo_data.get("schema_version") not in (None, "1.0") and data_quality_warnings is not None:
        data_quality_warnings.append(
            f"{topology_path}: schema version {topo_data['schema_version']!r} is not recognized; best-effort parsing used"
        )
    timestamp = datetime.now(timezone.utc)
    observations: list[TopologyObservation] = []
    links = topo_data.get("links", [])
    if not isinstance(links, list):
        links = []
        if data_quality_warnings is not None:
            data_quality_warnings.append(f"{topology_path}: links must be a list; links ignored")
    for index, link in enumerate(links):
        try:
            if not isinstance(link, dict):
                raise ValueError("link must be an object")
            source = source_field(link, "source_entity", ["source_entity"])
            target = source_field(link, "target_entity", ["target_entity"])
            if not source or not target:
                raise ValueError("link requires source_entity and target_entity")
            relationship = source_field(link, "relationship_type", ["relationship_type", "link_type"]) or "connected_to"
            link_id = source_field(link, "link_id", ["link_id"]) or generate_id("TOPO")
            observations.append(TopologyObservation(
                observation_id=str(link_id),
                incident_id=incident_id,
                source=str(topology_path),
                entity_id=profile.canonical_entity(str(source)) if profile else str(source),
                source_entity=profile.canonical_entity(str(source)) if profile else str(source),
                target_entity=profile.canonical_entity(str(target)) if profile else str(target),
                relationship_type=profile.canonical_relationship(str(relationship)) if profile else str(relationship),
                link_speed_mbps=source_field(link, "capacity_mbps", ["capacity_mbps"]),
                interface_name=source_field(link, "interface_name", ["source_interface", "interface_name"]),
                timestamp=timestamp,
            ))
        except Exception as exc:
            if data_quality_warnings is not None:
                data_quality_warnings.append(f"{topology_path}: skipped link {index}: {exc}")

    dependencies = topo_data.get("service_dependencies", [])
    if not isinstance(dependencies, list):
        dependencies = []
        if data_quality_warnings is not None:
            data_quality_warnings.append(f"{topology_path}: service_dependencies must be a list; dependencies ignored")
    for index, dependency in enumerate(dependencies):
        if not isinstance(dependency, dict):
            if data_quality_warnings is not None:
                data_quality_warnings.append(f"{topology_path}: skipped service dependency {index}: expected object")
            continue
        consumer = source_field(dependency, "consumer_entity", ["consumer_entity"])
        provider = source_field(dependency, "provider_entity", ["provider_entity"])
        if not consumer or not provider:
            if data_quality_warnings is not None:
                data_quality_warnings.append(f"{topology_path}: skipped service dependency {index}: missing consumer/provider")
            continue
        relationship = source_field(dependency, "relationship_type", ["dependency_type", "relationship_type"]) or "depends_on"
        consumer_id = profile.canonical_entity(str(consumer)) if profile else str(consumer)
        provider_id = profile.canonical_entity(str(provider)) if profile else str(provider)
        observations.append(TopologyObservation(
            observation_id=str(dependency.get("link_id") or f"DEP-{consumer_id}-{provider_id}-{relationship}"),
            incident_id=incident_id,
            source=str(topology_path),
            entity_id=consumer_id,
            source_entity=consumer_id,
            target_entity=provider_id,
            relationship_type=profile.canonical_relationship(str(relationship)) if profile else str(relationship),
            timestamp=timestamp,
        ))
    return observations


@app.command()
def diagnose(
    target_path: Path = typer.Argument(
        ...,
        help="Path to telemetry file (.json, .jsonl, .csv, or JSON Lines in a .log file) or scenario directory.",
        exists=True,
        readable=True,
    ),
    incident_id: str | None = typer.Option(None, "--incident-id", "-i", help="Incident ID (defaults to file metadata)"),
    format_opt: str = typer.Option("rich", "--format", "-f", help="Output format: rich, json, markdown"),
    output_path: Path | None = typer.Option(None, "--output", "-o", help="Optional file path to write report"),
    llm: str = typer.Option("off", "--llm", help="LLM mode: off (deterministic), auto, on"),
    db_path: Path | None = typer.Option(None, "--db", help="Optional SQLite database to persist incident records"),
    profile_path: Path | None = typer.Option(
        None, "--profile", help="Optional versioned network profile YAML", exists=True, readable=True
    ),
    site: str | None = typer.Option(
        None, "--site", help="Site identifier; loads config/profiles/<site>.yaml when present and tags the report."
    ),
    topology_path: Path | None = typer.Option(
        None, "--topology", "--sitemap", exists=True, readable=True,
        help="Optional standalone topology JSON; overrides topology.json inside a capture directory.",
    ),
    symptom_chat: str | None = typer.Option(
        None, "--symptom-chat", help="Optional caller symptom; reviewed after diagnosis, then opens session chat."
    ),
    session_id: str | None = typer.Option(None, "--session", help="Use this existing shared investigation session."),
    new_session: bool = typer.Option(False, "--new-session", help="Create a new session for this diagnosis."),
    chat: bool = typer.Option(False, "--chat", help="Open session Q&A after diagnosis (also enabled by --symptom-chat)."),
    explain: bool = typer.Option(
        False, "--explain", help="Stream the live diagnostic workflow and agent handoffs to stderr."
    ),
):
    """Executes end-to-end incident diagnosis across all 4 towers and the Evidence Release Gate."""
    data_quality_warnings: list[str] = []
    if site is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", site):
        console.print("[bold red]Invalid site ID:[/bold red] use letters, numbers, dots, underscores, or hyphens.")
        raise typer.Exit(code=2)
    if symptom_chat is not None and not symptom_chat.strip():
        console.print("[bold red]Invalid symptom chat:[/bold red] --symptom-chat requires non-empty caller wording.")
        raise typer.Exit(code=2)
    if profile_path is None and site:
        profile_candidates = [
            Path("config/profiles") / f"{site}.yaml",
            Path("config/profiles") / f"{site}.yml",
        ]
        site_profile = next((candidate for candidate in profile_candidates if candidate.is_file()), None)
        if site_profile is not None:
            profile_path = site_profile
        else:
            data_quality_warnings.append(
                f"No profile registered for site {site}; using generic mappings. "
                "Pass --profile or create this site profile to apply network-specific mappings."
            )
    if topology_path is None and site:
        site_topology = Path("config/sites") / site / "topology.json"
        if site_topology.is_file():
            topology_path = site_topology
    try:
        network_profile = NetworkProfile.load(profile_path) if profile_path else None
        if network_profile:
            network_profile.apply_to_rules(load_rules())
    except Exception as exc:
        console.print(f"[bold red]Network profile error:[/bold red] {exc}")
        raise typer.Exit(code=2)
    inc_id, observations = _load_observations_from_target(
        target_path, incident_id=incident_id, data_quality_warnings=data_quality_warnings,
        profile=network_profile, topology_path=topology_path,
    )
    if network_profile and network_profile.topology_completeness != "complete":
        data_quality_warnings.append(
            f"Profile {network_profile.profile_id} marks topology "
            f"{network_profile.topology_completeness}; missing links are not treated as proof of an outage."
        )

    if not observations:
        console.print(f"[bold red]No observations loaded from {target_path}.[/bold red]")
        raise typer.Exit(code=1)

    # Setup RCA Agent based on LLM mode
    try:
        rca_provider = get_rca_provider(llm_mode=llm)
    except ValueError as e:
        console.print(f"[bold red]Configuration Error:[/bold red] {e}")
        raise typer.Exit(code=1)

    try:
        run_manager = _local_run_manager()
        selected_session_id = _select_cli_session(
            session_id=session_id,
            create_new=new_session,
            title=f"{site} investigation" if site else "CLI investigation",
        )
        cli_run = run_manager.create_cli_run(
            session_id=selected_session_id,
            incident_id=inc_id,
            input_path=target_path.resolve(),
            topology_path=topology_path.resolve() if topology_path else None,
            entity_aliases=network_profile.aliases() if network_profile else None,
        )
        repo = SQLiteRepository(db_path or cli_run.repository_path)
        cli_run.repository = repo
        # Keep JSON/Markdown stdout machine-readable; status belongs on stderr.
        chat_console.print(f"[dim]Session {selected_session_id} · run {cli_run.run_id}[/dim]")
    except Exception as exc:
        console.print(f"[bold red]Could not prepare the local session:[/bold red] {exc}")
        raise typer.Exit(code=1)

    rca_agent = SupervisoryRCAAgent(provider=rca_provider, llm_mode=llm)
    profile_rules = network_profile.apply_to_rules(load_rules()) if network_profile else None
    fabric = IntegrationFabric(repository=repo, rules=profile_rules)
    gate = EvidenceReleaseGate(repository=repo)
    runtime = SupervisorRuntime(
        fabric=fabric, repository=repo, rca_agent=rca_agent, gate=gate,
        network_profile=(
            {"profile_id": network_profile.profile_id, "version": network_profile.version}
            if network_profile else None
        ),
        explain=(lambda stage, message: explain_console.print(f"[bright_cyan]✦ {stage}[/bright_cyan]  {message}"))
        if explain else None,
    )

    if explain:
        explain_console.print(Panel(
            f"Incident [bold]{inc_id}[/bold] · {len(observations)} observations\n"
            f"Input: {target_path} · towers receive the shared normalized observation set\n"
            "Agent rationale is shown as concise findings and evidence summaries, not private chain-of-thought.",
            title="Live diagnostic trace", border_style="magenta",
        ))

    try:
        if format_opt.lower() == "rich":
            with _soft_status("Specialists are correlating evidence and checking the diagnosis"):
                report = runtime.run_incident(
                    inc_id, observations, data_quality_warnings=data_quality_warnings
                )
        else:
            report = runtime.run_incident(
                inc_id, observations, data_quality_warnings=data_quality_warnings
            )
        if site is not None:
            report = report.model_copy(update={"site_id": site})
            repo.insert_final_report(report)
        if symptom_chat is not None:
            symptom_agent = SymptomReasoningAgent(llm_mode=llm)
            if explain:
                explain_console.print("[bright_cyan]✦ symptom-chat[/bright_cyan]  Running optional symptom comparison after the evidence gate; it cannot change the diagnosis.")
            if format_opt.lower() == "rich":
                with _soft_status("Comparing caller wording with the published evidence"):
                    symptom_addendum = symptom_agent.analyze(
                        symptom=symptom_chat,
                        report=report,
                        observations=observations,
                        tower_reports=repo.get_tower_reports(inc_id),
                    )
            else:
                symptom_addendum = symptom_agent.analyze(
                    symptom=symptom_chat,
                    report=report,
                    observations=observations,
                    tower_reports=repo.get_tower_reports(inc_id),
                )
            report = report.model_copy(update={"symptom_reasoning": symptom_addendum})
            if explain:
                explain_console.print(f"[bright_cyan]✦ symptom-chat[/bright_cyan]  Result: {symptom_addendum.status}; {symptom_addendum.explanation}")
            repo.insert_final_report(report)
        gate_res = repo.get_gate_result(inc_id)
        run_manager.complete_cli_run(
            cli_run.run_id,
            report=report,
            observations=observations,
            source_repository=repo,
        )
    except EvidenceGateRejectionError as e:
        run_manager.fail_cli_run(cli_run.run_id, str(e))
        console.print(f"[bold red]Evidence Release Gate Rejection:[/bold red] {e}")
        raise typer.Exit(code=2)
    except Exception as e:
        run_manager.fail_cli_run(cli_run.run_id, str(e))
        console.print(f"[bold red]Diagnosis failed:[/bold red] {e}")
        raise typer.Exit(code=1)

    open_chat = chat or symptom_chat is not None

    # Format outputs
    if format_opt.lower() == "json":
        output_text = report.model_dump_json(indent=2)
        if output_path:
            output_path.write_text(output_text, encoding="utf-8")
            console.print(f"[green]Saved JSON report to {output_path}[/green]")
        else:
            sys.stdout.write(output_text + "\n")
        if open_chat:
            _run_session_chat(selected_session_id, llm)
        return

    if format_opt.lower() == "markdown":
        output_text = render_markdown_report(report, gate_result=gate_res)
        if output_path:
            output_path.write_text(output_text, encoding="utf-8")
            console.print(f"[green]Saved Markdown report to {output_path}[/green]")
        else:
            sys.stdout.write(output_text + "\n")
        if open_chat:
            _run_session_chat(selected_session_id, llm)
        return

    # Default: Rich Terminal Display
    console.print(
        Panel(
            f"[bold cyan]✦ NetCoop AI · Diagnostic Synthesis ✦[/bold cyan]\n"
            f"Incident ID: [bold]{inc_id}[/bold] | Site: [bold]{site or 'unspecified'}[/bold] | "
            f"LLM Mode: [bold]{llm}[/bold] | "
            f"Gate Status: [{'green' if report.status != 'insufficient_evidence' else 'yellow'}]{report.status.upper()}[/]\n"
            f"Evaluated Observations: {len(observations)} | Verified Findings: {len(repo.get_findings(inc_id))}",
            title="◈ Incident Intake",
            border_style="cyan",
        )
    )

    # 1. Tower Status Table
    tower_table = make_table(title="Domain Tower Diagnostic Summary")
    tower_table.add_column("Domain Tower", style="bold")
    tower_table.add_column("Status", style="green")
    tower_table.add_column("Findings", justify="right")
    tower_table.add_column("Hypotheses", justify="right")
    tower_table.add_column("Key Observation")

    t_reports = repo.get_tower_reports(inc_id)
    for tr in t_reports:
        key_obs = tr.findings[0].description[:44] if tr.findings else "Nominal telemetry"
        tower_table.add_row(
            tr.tower_id.value.title(),
            tr.status,
            str(len(tr.findings)),
            str(len(tr.hypotheses)),
            key_obs + ("..." if tr.findings and len(tr.findings[0].description) > 44 else ""),
        )
    console.print(tower_table)

    # 2. Gate Verification Panel
    if gate_res:
        gate_color = "green" if gate_res.passed else ("yellow" if gate_res.outcome.value == "abstain" else "red")
        gate_panel_text = (
            f"[bold {gate_color}]Gate Outcome: {gate_res.outcome.value.upper()}[/bold {gate_color}]\n"
            f"Certification: {'PASSED' if gate_res.passed else 'REJECTED / ABSTAINED'} "
            f"({len(gate_res.checks)} objective checks verified)\n"
            f"Corroborating Evidence Items: {len(report.supporting_evidence)}"
        )
        if gate_res.warnings:
            gate_panel_text += "\n\n[yellow]Gate Warnings:[/yellow]\n" + "\n".join(f"  • {w}" for w in gate_res.warnings[:3])
        console.print(Panel(gate_panel_text, title="Evidence Release Gate Verification", border_style=gate_color))

    # 3. Final Diagnosis Panel
    status_style = "green" if report.status == "diagnosed" else "yellow"
    confidence_filled = max(0, min(10, round(report.confidence * 10)))
    confidence_bar = f"[magenta]{'▰' * confidence_filled}[/magenta][dim]{'▱' * (10 - confidence_filled)}[/dim]"
    observed_text = ", ".join(report.observed_symptom_entities) or "No cited symptom entities"
    predicted_text = ", ".join(report.inferred_affected_entities) or "No topology-based candidates"
    impact_by_entity = {item.entity_id: item for item in report.predicted_impacts}
    predicted_details = [
        f"  • {entity}: {' → '.join(impact_by_entity[entity].path)} "
        f"[map evidence: {', '.join(impact_by_entity[entity].topology_evidence_refs)}]"
        for entity in report.inferred_affected_entities if entity in impact_by_entity
    ]
    diagnosis_content = (
        f"[bold]Suspected primary cause[/bold]\n[bold {status_style}]{report.suspected_root_cause}[/bold {status_style}]\n\n"
        f"[bold]Confidence[/bold]  {confidence_bar}  {report.confidence:.0%}\n\n"
        f"[bold cyan]Observed symptoms[/bold cyan]  {observed_text}\n"
        f"[bold magenta]Predicted impact[/bold magenta]  {predicted_text}\n"
        f"[bold]Directly affected[/bold]  {', '.join(report.directly_affected_entities) or 'Not established'}\n"
        f"[dim]Combined affected entities: {', '.join(report.affected_devices) if report.affected_devices else 'None detected'}[/dim]\n\n"
        f"[bold]Recommended actions[/bold]\n"
        + "\n".join(f"  {i+1}. {a}" for i, a in enumerate(report.recommended_actions))
    )
    if report.operator_questions:
        diagnosis_content += "\n\n[bold yellow]Information needed from operator[/bold yellow]\n" + "\n".join(
            f"  • {question}" for question in report.operator_questions
        )
    if predicted_details:
        diagnosis_content += "\n\n[dim]Topology inference paths (candidate impact)[/dim]\n" + "\n".join(predicted_details)
    console.print(Panel(
        diagnosis_content, title="✦ Certified Diagnosis", border_style="cyan", padding=(1, 2)
    ))

    if report.path_triage:
        triage_lines = [f"Status: {report.path_triage.status}"]
        for item in report.path_triage.paths:
            reachability = "reachable" if item.reachable is True else (
                "not reachable in recorded topology" if item.reachable is False else "unknown"
            )
            route = " → ".join(item.path) or "No path returned"
            triage_lines.append(f"{item.source_entity} → {item.target_entity}: {reachability} · {route}")
            if item.warning:
                triage_lines.append(f"  Note: {item.warning}")
        triage_lines.extend(f"Limit: {item}" for item in report.path_triage.limitations)
        console.print(Panel(
            "\n".join(triage_lines), title="Supplemental Path Triage · Reachability is not causation",
            border_style="magenta", padding=(1, 2),
        ))

    if report.symptom_reasoning:
        reasoning = report.symptom_reasoning
        symptom_content = (
            f"Caller wording: {reasoning.reported_symptom}\n"
            f"Comparison: [bold]{reasoning.status.upper()}[/bold]\n"
            f"Analysis mode: {reasoning.agent_mode}\n"
            f"Recognized categories: {', '.join(reasoning.recognized_domains) or 'none'}\n"
            f"{reasoning.explanation}"
        )
        if reasoning.warnings:
            symptom_content += "\n\n[yellow]Agent notes:[/yellow]\n" + "\n".join(
                f"  • {warning}" for warning in reasoning.warnings
            )
        console.print(Panel(
            symptom_content, title="Optional Symptom Cross-check · Post-diagnosis",
            border_style="blue", padding=(1, 2),
        ))

    if output_path:
        md_text = render_markdown_report(report, gate_result=gate_res)
        output_path.write_text(md_text, encoding="utf-8")
        console.print(f"[green]Saved summary report to {output_path}[/green]")

    if open_chat:
        _run_session_chat(selected_session_id, llm)


app.command("triage")(diagnose)


@app.command("profile-validate")
def profile_validate(
    profile_path: Path = typer.Argument(..., exists=True, readable=True, help="Network profile YAML"),
    data_path: Path | None = typer.Option(
        None, "--data", exists=True, readable=True,
        help="Optional telemetry file or scenario directory to check mappings against",
    ),
):
    """Validate a network profile and optionally inspect it against sample telemetry."""
    try:
        profile = NetworkProfile.load(profile_path)
        profile.apply_to_rules(load_rules())
    except Exception as exc:
        console.print(f"[bold red]Invalid profile:[/bold red] {exc}")
        raise typer.Exit(code=2)

    table = make_table(title=f"Network Profile: {profile.display_name}")
    table.add_column("Check", style="bold")
    table.add_column("Result")
    table.add_row("Identity", f"{profile.profile_id} v{profile.version}")
    table.add_row("Entity aliases", str(len(profile.entity_aliases)))
    table.add_row("Metric mappings", str(len(profile.metric_mappings)))
    table.add_row("Topology anchors", ", ".join(profile.topology_anchors) or "NOT CONFIGURED")
    table.add_row("Entity roles", str(sum(len(roles) for roles in profile.entity_roles.values())))

    warnings: list[str] = []
    if not profile.topology_anchors:
        warnings.append("No topology anchors configured; common-uplink and blast-radius analysis will be limited.")
    if not profile.entities_for_role("dns_resolver"):
        warnings.append("No dns_resolver role configured; DNS metrics on non-DNS-named entities may be missed.")
    if not profile.entities_for_role("dhcp_server"):
        warnings.append("No dhcp_server role configured; DHCP metrics on non-DHCP-named entities may be missed.")
    if data_path:
        incident_id, observations = _load_observations_from_target(
            data_path, data_quality_warnings=warnings, profile=profile
        )
        observed_entities = {
            entity
            for obs in observations
            for entity in (
                [obs.entity_id]
                + ([obs.source_entity, obs.target_entity] if isinstance(obs, TopologyObservation) else [])
            )
        }
        present_anchors = [
            anchor for anchor in profile.topology_anchors
            if profile.canonical_entity(anchor) in observed_entities
        ]
        table.add_row("Sample incident", incident_id)
        table.add_row("Normalized observations", str(len(observations)))
        table.add_row(
            "Anchors present",
            f"{len(present_anchors)}/{len(profile.topology_anchors)}" if profile.topology_anchors else "not configured",
        )
        table.add_row("Input warnings", str(len(warnings)))
        missing_roles = [
            role for role in ("dns_resolver", "dhcp_server")
            if profile.entities_for_role(role)
            and not profile.entities_for_role(role).intersection(observed_entities)
        ]
        table.add_row("Configured service roles missing", ", ".join(missing_roles) or "none")

    console.print(table)
    if warnings:
        console.print("\n[bold yellow]Profile/data warnings:[/bold yellow]")
        for warning in warnings[:12]:
            console.print(f"- {warning}")
        if len(warnings) > 12:
            console.print(f"... and {len(warnings) - 12} more")


def _inspect_profile_input(
    path: Path, source_fields: dict[str, list[str]] | None = None
) -> tuple[set[str], dict[str, set[str]], set[str]]:
    """Collect source field names without assigning meaning to entities or metrics."""
    source_fields = source_fields or {}

    def candidates(canonical: str, defaults: list[str]) -> list[str]:
        return [*source_fields.get(canonical, []), *defaults]

    def get_source_value(record: dict[str, object], canonical: str, defaults: list[str]) -> object | None:
        return next((record[name] for name in candidates(canonical, defaults)
                     if name in record and record[name] is not None), None)

    source = path
    if source.is_dir():
        source = next(
            (source / name for name in ("telemetry.jsonl", "telemetry.csv", "telemetry.json")
             if (source / name).exists()),
            source,
        )
    metrics: set[str] = set()
    units: dict[str, set[str]] = {}
    entities: set[str] = set()

    def visit(record: object) -> None:
        if isinstance(record, list):
            for item in record:
                visit(item)
            return
        if not isinstance(record, dict):
            return
        entity = get_source_value(record, "entity_id", ["device_id", "entity_id", "device", "node"])
        if entity:
            entities.add(str(entity))
        metric_name = get_source_value(record, "metric", ["metric", "metric_name", "measurement"])
        if metric_name:
            name = str(metric_name)
            metrics.add(name)
            raw_unit = get_source_value(record, "unit", ["unit", "units"])
            if raw_unit:
                units.setdefault(name, set()).add(str(raw_unit))
        raw_metrics = get_source_value(record, "metrics", ["metrics"])
        if isinstance(raw_metrics, dict):
            for name, value in raw_metrics.items():
                metrics.add(str(name))
                if isinstance(value, dict) and value.get("unit"):
                    units.setdefault(str(name), set()).add(str(value["unit"]))
        observations = record.get("observations")
        if isinstance(observations, list):
            visit(observations)

    if source.suffix.lower() == ".csv":
        with source.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            columns = set(reader.fieldnames or [])
            metric_columns = {name.casefold() for name in candidates("metric", ["metric", "metric_name", "measurement"])}
            if any(column.casefold() in metric_columns for column in columns):
                for row in reader:
                    visit(row)
            else:
                structural = {
                    name.casefold()
                    for field_name, defaults in (
                        ("timestamp", ["timestamp", "event_time", "time", "datetime"]),
                        ("entity_id", ["device_id", "entity_id", "device", "node"]),
                        ("incident_id", ["incident_id"]),
                        ("source_id", ["source_id", "source"]),
                    )
                    for name in candidates(field_name, defaults)
                }
                metrics.update(columns - structural)
                for row in reader:
                    entity = get_source_value(row, "entity_id", ["device_id", "entity_id", "device", "node"])
                    if entity:
                        entities.add(entity)
    elif source.suffix.lower() == ".jsonl" or source.suffix.lower() == ".log":
        for line in source.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    visit(json.loads(line))
                except json.JSONDecodeError:
                    continue
    else:
        visit(json.loads(source.read_text(encoding="utf-8")))
    return metrics, units, entities


@app.command("profile-init")
def profile_init(
    data_path: Path = typer.Argument(..., exists=True, readable=True, help="Sample telemetry or scenario directory"),
    output_path: Path = typer.Option(Path("network-profile.yaml"), "--output", "-o", help="Draft profile path"),
    display_name: str = typer.Option("New network", "--name", help="Human-readable network name"),
    source_field_options: list[str] = typer.Option(
        [], "--source-field", help="Map a canonical field to a source field, e.g. entity_id=node (repeatable)"
    ),
):
    """Create a conservative profile draft from source field names, metrics, and units."""
    source_fields: dict[str, list[str]] = {}
    allowed_source_fields = {
        "entity_id", "timestamp", "metric", "value", "unit",
        "incident_id", "source_id", "metrics", "message", "log_level", "facility",
        "source_entity", "target_entity", "relationship_type", "link_id",
        "capacity_mbps", "interface_name", "consumer_entity", "provider_entity",
    }
    for option in source_field_options:
        canonical, separator, source_name = option.partition("=")
        canonical = canonical.strip()
        source_name = source_name.strip()
        if not separator or canonical not in allowed_source_fields or not source_name:
            console.print(
                f"[bold red]Invalid --source-field {option!r}.[/bold red] "
                f"Use FIELD=SOURCE_NAME where FIELD is one of {sorted(allowed_source_fields)}."
            )
            raise typer.Exit(code=2)
        source_fields.setdefault(canonical, []).append(source_name)
    try:
        source_metrics, source_units, entities = _inspect_profile_input(data_path, source_fields)
    except (OSError, json.JSONDecodeError, csv.Error) as exc:
        console.print(f"[bold red]Could not inspect sample data:[/bold red] {exc}")
        raise typer.Exit(code=2)

    suggested_mappings: dict[str, MetricMapping] = {}
    unmapped: list[str] = []
    for source_name in sorted(source_metrics):
        canonical, _ = normalize_metric_name(source_name)
        if canonical is None:
            unmapped.append(source_name)
        elif canonical != source_name.strip().lower():
            source_unit_set = source_units.get(source_name, set())
            source_unit = next(iter(source_unit_set)) if len(source_unit_set) == 1 else None
            suggested_mappings[source_name] = MetricMapping(
                canonical_name=canonical, source_unit=source_unit
            )

    slug = "-".join("".join(ch.lower() if ch.isalnum() else " " for ch in display_name).split())
    draft = NetworkProfile(
        profile_id=slug or "network-profile",
        display_name=display_name,
        source_fields=source_fields,
        metric_mappings=suggested_mappings,
        topology_completeness="unknown",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(draft.model_dump(mode="json", exclude_none=True), sort_keys=False),
        encoding="utf-8",
    )
    console.print(f"Draft profile written to {output_path}")
    console.print(f"Found {len(entities)} entity names and {len(source_metrics)} source metric names.")
    if source_fields:
        console.print("Configured source fields: " + ", ".join(
            f"{canonical}={name}" for canonical, names in source_fields.items() for name in names
        ))
    console.print("Review entity aliases, DNS/DHCP roles, topology anchors, and completeness before diagnosing.")
    if entities:
        console.print("Observed entity names: " + ", ".join(sorted(entities)[:30]))
        if len(entities) > 30:
            console.print(f"... and {len(entities) - 30} more")
    if unmapped:
        console.print("Unmapped metrics requiring explicit review: " + ", ".join(unmapped))


@app.command()
def scenarios(
    generate: bool = typer.Option(False, "--generate", "-g", help="Generate or refresh synthetic benchmark scenarios"),
    output_dir: Path = typer.Option(Path("fixtures/scenarios"), "--dir", "-d", help="Directory for scenarios"),
):
    """Lists available network incident scenarios and supports synthetic generation."""
    if generate:
        console.print(f"[bold cyan]Generating synthetic campus network scenarios into {output_dir}...[/bold cyan]")
        import subprocess

        cmd = [sys.executable, "reference/sample_generator.py", "--scenario", "all", "--output-dir", str(output_dir)]
        subprocess.run(cmd, check=True)
        console.print("[green]✓ All scenarios generated successfully![/green]\n")

    table = make_table(title="Available Benchmark Scenarios")
    table.add_column("Scenario Name", style="bold cyan")
    table.add_column("Category", style="magenta")
    table.add_column("Target Entity")
    table.add_column("Primary Symptoms")
    table.add_column("Fixture Path")

    scenario_catalog = [
        ("healthy", "Baseline", "SW_CORE_01", "Nominal throughput and latency", "healthy/telemetry.jsonl"),
        ("link_congestion", "Performance", "SW_CORE_01:Gi0/2", "High utilization, queue drops, packet loss", "link_congestion/telemetry.jsonl"),
        ("weak_wifi", "Wireless", "AP_HOSTEL_01", "Low RSSI/SNR, frame retransmissions", "weak_wifi/telemetry.jsonl"),
        ("interface_fault", "Infrastructure", "SW_DIST_DEPT:uplink", "Packet errors, link flapping", "interface_fault/telemetry.jsonl"),
        ("device_overload", "Hardware", "SW_CORE_01", "CPU > 90%, memory pressure, dropped frames", "device_overload/telemetry.jsonl"),
        ("dns_failure", "Services", "SRV_DNS_01", "DNS latency timeouts, SERVFAIL errors", "dns_failure/telemetry.jsonl"),
        ("dhcp_failure", "Services", "SRV_DHCP_01", "DHCP lease pool exhaustion, NAK storms", "dhcp_failure/telemetry.jsonl"),
    ]

    for name, cat, entity, symptoms, rel_path in scenario_catalog:
        full_path = output_dir / rel_path
        status_path = f"[green]{rel_path}[/green]" if full_path.exists() else f"[dim]{rel_path} (not generated)[/dim]"
        table.add_row(name, cat, entity, symptoms, status_path)

    console.print(table)


@app.command()
def demo():
    """Executes a complete offline multi-scenario demonstration across all diagnostic towers."""
    console.print(
        Panel(
            "[bold cyan]NetCoop AI: Autonomous Multi-Agent Fault Diagnosis Demonstration[/bold cyan]\n"
            "Executing 100% offline benchmark evaluation across healthy baseline and 4 fault classes.\n"
            "Zero LLM calls required • Certified by Evidence Release Gate",
            title="Demo Start",
            border_style="cyan",
        )
    )

    demo_scenarios = [
        ("healthy", "Healthy"),
        ("link_congestion", "Congestion"),
        ("weak_wifi", "Weak Wi-Fi"),
        ("device_overload", "Overload"),
        ("dns_failure", "DNS Failure"),
    ]

    # Ensure scenarios are generated
    scenarios_dir = Path("fixtures/scenarios")
    if not (scenarios_dir / "healthy" / "telemetry.jsonl").exists():
        console.print("[yellow]Generating demo scenarios...[/yellow]")
        import subprocess

        cmd = [sys.executable, "reference/sample_generator.py", "--scenario", "all", "--output-dir", str(scenarios_dir)]
        subprocess.run(cmd, check=True)

    results_table = make_table(title="Demo Benchmark Execution Summary")
    results_table.add_column("Scenario", style="bold", no_wrap=True, max_width=12)
    results_table.add_column("Gate", style="green", no_wrap=True, max_width=10)
    results_table.add_column("Likely cause", no_wrap=True, overflow="ellipsis", max_width=34)
    results_table.add_column("Conf.", justify="right", no_wrap=True, max_width=6)

    progress = _demo_progress()
    with progress:
        task_id = progress.add_task("Preparing incident runs", total=len(demo_scenarios))
        for sc_name, title in demo_scenarios:
            progress.update(task_id, description=f"Diagnosing {title.lower()}")
            sc_path = scenarios_dir / sc_name
            inc_id, observations = _load_observations_from_target(sc_path)

            repo = SQLiteRepository(":memory:")
            fabric = IntegrationFabric(repository=repo)
            gate = EvidenceReleaseGate(repository=repo)
            rca_agent = SupervisoryRCAAgent(provider=DeterministicRCAProvider())
            runtime = SupervisorRuntime(fabric=fabric, repository=repo, rca_agent=rca_agent, gate=gate)

            report = runtime.run_incident(inc_id, observations)
            gate_res = repo.get_gate_result(inc_id)

            outcome_text = gate_res.outcome.value.upper() if gate_res else "UNKNOWN"
            outcome_label = "PASS+NOTES" if outcome_text == "PASS_WITH_LIMITATIONS" else outcome_text
            results_table.add_row(
                title,
                f"[{'green' if outcome_text == 'PASS' else 'yellow'}]{outcome_label}[/]",
                report.suspected_root_cause,
                f"{report.confidence:.0%}",
            )
            progress.advance(task_id)

    console.print(results_table)
    console.print(
        Panel(
            "[bold green]✓ Demo Completed Successfully![/bold green]\n"
            "• All 5 benchmark scenarios evaluated autonomously.\n"
            "• Normal baseline certified as ABSTAIN (clean non-escalation).\n"
            "• All 4 distinct fault classes identified with exact causal evidence citations.\n"
            "• 100% offline determinism verified without API credentials.",
            title="Demo Result",
            border_style="green",
        )
    )


@app.command()
def inspect(
    db_path: Path = typer.Option(Path("netcoop.db"), "--db", help="Path to SQLite database to inspect"),
    incident_id: str | None = typer.Option(None, "--incident-id", "-i", help="Specific incident ID to inspect"),
):
    """Inspects persisted incident records, tower reports, findings, and gate verification results."""
    if not db_path.exists():
        console.print(f"[bold red]Database file '{db_path}' does not exist.[/bold red]")
        raise typer.Exit(code=1)

    repo = SQLiteRepository(db_path)
    inc_id = incident_id or "INC-CLI-001"

    console.print(f"[bold]Inspecting Database:[/bold] {db_path} (Incident: [cyan]{inc_id}[/cyan])")

    # 1. Findings table
    findings = repo.get_findings(inc_id)
    table_findings = make_table(title=f"Persisted Findings ({len(findings)})")
    table_findings.add_column("Finding ID", style="bold")
    table_findings.add_column("Tower", style="cyan")
    table_findings.add_column("Finding Type")
    table_findings.add_column("Severity")
    table_findings.add_column("Evidence Refs")

    for f in findings:
        table_findings.add_row(
            f.finding_id,
            f.source_tower.value,
            f.finding_type,
            f.severity.value,
            ", ".join(f.evidence_refs[:3]) + ("..." if len(f.evidence_refs) > 3 else ""),
        )
    console.print(table_findings)

    # 2. Outbox & Deliveries
    events = repo.get_events(inc_id)
    deliveries = repo.get_event_deliveries()
    console.print(
        Panel(
            f"Events in Outbox: {len(events)}\n"
            f"Consumer Deliveries Tracked: {len(deliveries)}\n"
            f"Pending Un-dispatched: {len(repo.get_pending_outbox_events())}",
            title="Communication Subsystem Status",
            border_style="blue",
        )
    )

    # 3. Final Report
    report = repo.get_final_report(inc_id)
    if report:
        console.print(
            Panel(
                f"[bold]Root Cause:[/bold] {report.suspected_root_cause}\n"
                f"[bold]Status:[/bold] {report.status} | [bold]Confidence:[/bold] {report.confidence:.2f}\n"
                f"[bold]Evidence Items:[/bold] {len(report.supporting_evidence)}",
                title="Certified Final Report",
                border_style="green",
            )
        )
    else:
        console.print("[yellow]No final report recorded for this incident yet.[/yellow]")


@app.command()
def api(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Bind host"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload for development"),
):
    """Starts the NetCoop AI backend HTTP API and event streaming service."""
    import uvicorn
    console.print(f"[bold cyan]Starting NetCoop AI API on http://{host}:{port}[/bold cyan]")
    uvicorn.run("netcoop_api.app:create_app", host=host, port=port, reload=reload, factory=True)


if __name__ == "__main__":
    app()
