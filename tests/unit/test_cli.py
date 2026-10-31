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


def test_cli_scenarios():
    result = runner.invoke(app, ["scenarios"])
    assert result.exit_code == 0
    assert "Available Benchmark Scenarios" in result.stdout
    assert "healthy" in result.stdout
    assert "link_congest" in result.stdout


def test_cli_diagnose_rich():
    scenario_path = Path("fixtures/scenarios/link_congestion")
    result = runner.invoke(app, ["diagnose", str(scenario_path)])
    assert result.exit_code == 0
    assert "NetCoop AI Diagnostic Synthesis" in result.stdout
    assert "Domain Tower Diagnostic Summary" in result.stdout
    assert "LINK_CONGESTION" in result.stdout
    assert "Evidence Release Gate Verification" in result.stdout


def test_cli_diagnose_json(tmp_path: Path):
    scenario_path = Path("fixtures/scenarios/healthy")
    out_file = tmp_path / "report.json"
    result = runner.invoke(app, ["diagnose", str(scenario_path), "--format", "json", "-o", str(out_file)])
    assert result.exit_code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert "incident_id" in data
    assert data["status"] in ("diagnosed", "insufficient_evidence", "abstain")
    assert "ABSTAIN" in data["suspected_root_cause"]


def test_cli_diagnose_markdown(tmp_path: Path):
    scenario_path = Path("fixtures/scenarios/weak_wifi")
    out_file = tmp_path / "report.md"
    result = runner.invoke(app, ["diagnose", str(scenario_path), "--format", "markdown", "-o", str(out_file)])
    assert result.exit_code == 0
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "# NetCoop AI Root Cause Analysis Report" in content
    assert "WEAK_WIFI" in content
    assert "Supporting Evidence & Verification" in content


def test_cli_inspect(tmp_path: Path):
    scenario_path = Path("fixtures/scenarios/link_congestion")
    db_file = tmp_path / "inspect_test.db"
    diag_res = runner.invoke(app, ["diagnose", str(scenario_path), "--db", str(db_file)])
    assert diag_res.exit_code == 0

    inspect_res = runner.invoke(app, ["inspect", "--db", str(db_file), "--incident-id", "INC-SYNTH-LINK-001"])
    assert inspect_res.exit_code == 0
    assert "Inspecting Database" in inspect_res.stdout
    assert "Persisted Findings" in inspect_res.stdout
    assert "Certified Final Report" in inspect_res.stdout


def test_cli_demo():
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 0
    assert "Demo Benchmark Execution Summary" in result.stdout
    assert "Healthy" in result.stdout
    assert "ABSTAIN" in result.stdout
    assert "Demo Completed Successfully" in result.stdout

