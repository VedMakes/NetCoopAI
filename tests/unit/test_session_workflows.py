"""Shared CLI and dashboard investigation session workflows."""

from __future__ import annotations

import time
from pathlib import Path

from typer.testing import CliRunner

import netcoop.cli.main as cli
import netcoop_api.assistant as assistant
from netcoop_api.app import create_app
from netcoop_api.schemas import UploadRunRequest
from netcoop_api.service import RunManager

runner = CliRunner()


def test_cli_session_commands_select_shared_sessions(tmp_path: Path, monkeypatch) -> None:
    manager = RunManager(storage_dir=tmp_path)
    monkeypatch.setattr(cli, "_local_run_manager", lambda: manager)

    created = runner.invoke(cli.app, ["sessions", "new", "--title", "Office East"])
    assert created.exit_code == 0, created.output
    session_id = manager.list_sessions()[0].session_id

    listed = runner.invoke(cli.app, ["sessions", "list"])
    assert listed.exit_code == 0, listed.output
    assert session_id in listed.output

    selected = runner.invoke(cli.app, ["sessions", "current"])
    assert selected.exit_code == 0, selected.output
    assert session_id in selected.output

    other = manager.create_session("Branch Office")
    switched = runner.invoke(cli.app, ["sessions", "use", other.session_id])
    assert switched.exit_code == 0, switched.output
    current = runner.invoke(cli.app, ["sessions", "current"])
    assert other.session_id in current.output


def test_cli_symptom_chat_run_persists_for_dashboard_and_can_add_upload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = RunManager(storage_dir=tmp_path)
    monkeypatch.setattr(cli, "_local_run_manager", lambda: manager)
    monkeypatch.setattr(assistant, "run_manager", manager)
    answers = iter(["What failed?"])

    def answer_then_interrupt(*args, **kwargs):
        try:
            return next(answers)
        except StopIteration:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli.Prompt, "ask", answer_then_interrupt)

    result = runner.invoke(
        cli.app,
        [
            "triage",
            "fixtures/scenarios/dns_failure",
            "--format",
            "json",
            "--new-session",
            "--symptom-chat",
            "Users cannot resolve names",
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.lstrip().startswith("{")

    session = manager.list_sessions()[0]
    detail = manager.get_session(session.session_id)
    assert detail is not None
    assert len(detail.runs) == 1
    assert detail.runs[0].status == "completed"
    report = manager.get_run_report(detail.runs[0].run_id)
    assert report is not None and report.symptom_reasoning is not None
    history = manager.get_session_assistant_history(session.session_id)
    assert [turn["role"] for turn in history or []] == ["user", "assistant"]

    # Ctrl+C closes the chat prompt while leaving its turns in the session.
    resumed_answers = iter(["Compare this with the latest run", "/exit"])
    monkeypatch.setattr(cli.Prompt, "ask", lambda *args, **kwargs: next(resumed_answers))
    resumed = runner.invoke(cli.app, ["sessions", "chat", "--llm", "off"])
    assert resumed.exit_code == 0, resumed.output
    history = manager.get_session_assistant_history(session.session_id)
    assert [turn["role"] for turn in history or []] == ["user", "assistant", "user", "assistant"]

    telemetry = Path("fixtures/scenarios/dns_failure/telemetry.jsonl").read_text(encoding="utf-8")
    uploaded = manager.create_uploaded_run(
        UploadRunRequest(
            telemetry_filename="telemetry.jsonl",
            telemetry_content=telemetry,
            session_id=session.session_id,
        )
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        status = manager.get_run(uploaded.run_id)
        assert status is not None
        if status.status in {"completed", "failed"}:
            break
        time.sleep(0.1)
    assert status.status == "completed", status.error

    # A separate manager simulates the API process reloading shared local state.
    dashboard_manager = RunManager(storage_dir=tmp_path)
    dashboard_session = dashboard_manager.get_session(session.session_id)
    assert dashboard_session is not None
    assert len(dashboard_session.runs) == 2
    assert {run.status for run in dashboard_session.runs} == {"completed"}
    assert dashboard_manager.get_run_report(detail.runs[0].run_id) is not None
    restored_history = dashboard_manager.get_session_assistant_history(session.session_id)
    assert restored_history == history


def test_api_schema_exposes_shared_sessions_and_symptom_chat_field() -> None:
    schema = create_app().openapi()
    assert "/api/sessions" in schema["paths"]
    assert "/api/sessions/{session_id}/assistant" in schema["paths"]
    for request_name in ("RunCreateRequest", "UploadRunRequest"):
        properties = schema["components"]["schemas"][request_name]["properties"]
        assert "symptom_chat" in properties
        assert "symptom" not in properties
