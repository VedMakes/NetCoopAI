"""Unit tests for the Typer CLI commands."""

import json
from pathlib import Path

from typer.testing import CliRunner

from netcoop.cli.main import app

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "NetCoop AI" in result.stdout
    assert "doctor" in result.stdout
    assert "validate" in result.stdout


def test_cli_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "NetCoop AI version" in result.stdout


def test_cli_doctor():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Python Runtime" in result.stdout
    assert "Vocabulary Config" in result.stdout
    assert "Capability Registry" in result.stdout
    assert "SQLite Engine" in result.stdout


def test_cli_validate_success(tmp_path: Path):
    fixture_data = {
        "incident_id": "INC-TEST-01",
        "observations": [
            {
                "observation_id": "OBS-01",
                "incident_id": "INC-TEST-01",
                "observation_type": "metric",
                "source": "test",
                "entity_id": "SW_1",
                "metric_name": "cpu_utilization_pct",
                "value": 45.0,
                "unit": "percent",
                "timestamp": "2026-10-31T12:00:00Z",
            }
        ],
    }
    fixture_file = tmp_path / "valid_fixture.json"
    fixture_file.write_text(json.dumps(fixture_data), encoding="utf-8")

    result = runner.invoke(app, ["validate", str(fixture_file)])
    assert result.exit_code == 0
    assert "All 1 observations valid" in result.stdout


def test_cli_validate_failure(tmp_path: Path):
    fixture_data = {
        "incident_id": "INC-TEST-FAIL",
        "observations": [
            {
                "observation_id": "OBS-INVALID",
                "incident_id": "INC-TEST-FAIL",
                "observation_type": "metric",
                "source": "test",
                "entity_id": "SW_1",
                "metric_name": "cpu_utilization_pct",
                "value": 150.0,  # Invalid: > 100%
                "unit": "percent",
                "timestamp": "2026-10-31T12:00:00Z",
            }
        ],
    }
    fixture_file = tmp_path / "invalid_fixture.json"
    fixture_file.write_text(json.dumps(fixture_data), encoding="utf-8")

    result = runner.invoke(app, ["validate", str(fixture_file)])
    assert result.exit_code != 0
    assert "Validation failed" in result.stdout


def test_cli_ingest_success(tmp_path: Path):
    fixture_path = Path("fixtures/sample_incident.json")
    db_path = tmp_path / "cli_test.db"

    result = runner.invoke(app, ["ingest", str(fixture_path), "--incident-id", "INC-INGEST-CLI", "--db", str(db_path)])
    assert result.exit_code == 0
    assert "Ingestion & Feature Summary: INC-INGEST-CLI" in result.stdout
    assert "Persisted 9 observations to SQLite" in result.stdout
    assert db_path.exists()
