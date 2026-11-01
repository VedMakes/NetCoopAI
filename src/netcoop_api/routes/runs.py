"""Diagnostic run execution, lifecycle monitoring, and artifact retrieval routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from netcoop.models.reports import FinalReport
from netcoop_api.events import event_sink
from netcoop_api.schemas import (
    EvaluationResponse,
    ExecutionEventModel,
    GateResultDetail,
    RunCreateRequest,
    RunStatusResponse,
    TelemetryResponse,
    TopologyGraph,
    TowerReportSummary,
    UploadRunRequest,
)
from netcoop_api.service import run_manager

router = APIRouter(prefix="/api/runs", tags=["Runs"])


@router.post("", response_model=RunStatusResponse, status_code=201)
def create_run(req: RunCreateRequest) -> RunStatusResponse:
    """Starts a new diagnostic run on a packaged scenario."""
    try:
        return run_manager.create_run(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("", response_model=list[RunStatusResponse])
def list_runs() -> list[RunStatusResponse]:
    """Returns recent local runs, including those restored after a restart."""
    return run_manager.list_runs()


@router.post("/upload", response_model=RunStatusResponse, status_code=201)
def create_uploaded_run(req: UploadRunRequest) -> RunStatusResponse:
    """Starts a run from bounded telemetry text and an optional JSON topology map."""
    try:
        return run_manager.create_uploaded_run(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{run_id}", response_model=RunStatusResponse)
def get_run_status(run_id: str) -> RunStatusResponse:
    """Returns lifecycle status of an ongoing or completed run."""
    status = run_manager.get_run(run_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return status


@router.get("/{run_id}/telemetry", response_model=TelemetryResponse)
def get_run_telemetry(run_id: str) -> TelemetryResponse:
    """Returns raw canonical observations and computed derived features for a run."""
    telemetry = run_manager.get_run_telemetry(run_id)
    if telemetry is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return telemetry


@router.get("/{run_id}/topology", response_model=TopologyGraph)
def get_run_topology(run_id: str) -> TopologyGraph:
    """Returns the run topology annotated with observed symptoms and inferred impact."""
    topo = run_manager.get_run_topology(run_id)
    if not topo:
        raise HTTPException(status_code=404, detail=f"Topology for run '{run_id}' not found")
    return topo


@router.get("/{run_id}/events", response_model=list[ExecutionEventModel])
def get_run_events(run_id: str) -> list[ExecutionEventModel]:
    """Returns the historical list of structured execution events for a run."""
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return event_sink.get_events(run_id)


@router.get("/{run_id}/events/stream")
async def stream_run_events(run_id: str) -> StreamingResponse:
    """Streams live execution events via Server-Sent Events (SSE)."""
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    return StreamingResponse(
        event_sink.subscribe(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{run_id}/findings", response_model=list[TowerReportSummary])
def get_run_findings(run_id: str) -> list[TowerReportSummary]:
    """Returns specialist tower reports and findings for a run."""
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run_manager.get_run_findings(run_id)


@router.get("/{run_id}/tasks")
def get_run_tasks(run_id: str) -> list[dict[str, Any]]:
    """Returns task dispatcher history and peer query transactions for a run."""
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run_manager.get_run_tasks(run_id)


@router.get("/{run_id}/report", response_model=FinalReport)
def get_run_report(run_id: str) -> FinalReport:
    """Returns the certified FinalReport published after Evidence Release Gate verification."""
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    report = run_manager.get_run_report(run_id)
    if not report:
        raise HTTPException(status_code=400, detail="Report not ready: diagnosis is still in progress or failed")
    return report


@router.get("/{run_id}/gate", response_model=GateResultDetail)
def get_run_gate(run_id: str) -> GateResultDetail:
    """Returns Evidence Release Gate verification results and check breakdowns."""
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    gate = run_manager.get_run_gate(run_id)
    if not gate:
        raise HTTPException(status_code=400, detail="Gate verification not available: run pending or failed")
    return gate


@router.get("/{run_id}/evaluation", response_model=EvaluationResponse)
def get_run_evaluation(run_id: str) -> EvaluationResponse:
    """Evaluates run outcome against hidden ground truth strictly after diagnosis completion."""
    try:
        return run_manager.get_run_evaluation(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
