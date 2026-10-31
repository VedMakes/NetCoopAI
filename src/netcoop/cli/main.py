"""NetCoop AI command-line interface."""

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from netcoop import __version__
from netcoop.communication.registry import CapabilityRegistry
from netcoop.communication.vocabulary import load_vocabulary
from netcoop.features.pipeline import FeaturePipeline
from netcoop.ingestion.loaders import TelemetryLoader
from netcoop.models.observations import (
    ConfigObservation,
    LogObservation,
    MetricObservation,
    TopologyObservation,
)
from netcoop.storage.sqlite import SQLiteRepository

app = typer.Typer(
    name="netcoop",
    help="NetCoop AI: Multi-Agent Network Fault Diagnosis and Interoperability",
    no_args_is_help=True,
)
console = Console()


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
    table = Table(title="NetCoop System Doctor")
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
        help="Path to telemetry file (.json, .csv, .jsonl) to ingest.",
        exists=True,
        readable=True,
    ),
    incident_id: str = typer.Option("INC-CLI-001", "--incident-id", "-i", help="Incident ID to associate"),
    db_path: Path | None = typer.Option(None, "--db", help="Optional SQLite database to persist into"),
):
    """Loads, normalizes, and extracts derived features from a telemetry file."""
    loader = TelemetryLoader()
    console.print(f"[bold]Ingesting:[/bold] {file_path} for incident [cyan]{incident_id}[/cyan]...")

    batch = loader.load_file(file_path, incident_id=incident_id)

    # Run feature extraction pipeline
    pipeline = FeaturePipeline()
    features = pipeline.extract_features(batch.observations, incident_id=incident_id)

    # Optional persistence into SQLite
    if db_path:
        repo = SQLiteRepository(db_path)
        repo.record_incident(incident_id, status="active", description=f"Ingested from {file_path.name}")
        for obs in batch.observations:
            repo.insert_observation(obs)
        console.print(f"[green]Persisted {len(batch.observations)} observations to SQLite at {db_path}[/green]")

    table = Table(title=f"Ingestion & Feature Summary: {incident_id}")
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


if __name__ == "__main__":
    app()
