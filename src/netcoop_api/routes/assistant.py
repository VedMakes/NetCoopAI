"""Incident Explanation Assistant router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from netcoop_api.assistant import assistant_service
from netcoop_api.schemas import AssistantRequest, AssistantResponse
from netcoop_api.service import run_manager

router = APIRouter(prefix="/api/runs", tags=["Assistant"])


@router.post("/{run_id}/assistant", response_model=AssistantResponse)
def ask_assistant(run_id: str, req: AssistantRequest) -> AssistantResponse:
    """Answers operator questions about a certified incident report and specialist findings."""
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    return assistant_service.answer_question(run_id, req)
