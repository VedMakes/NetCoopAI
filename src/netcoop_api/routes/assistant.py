"""Incident Explanation Assistant router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from netcoop_api.assistant import assistant_service
from netcoop_api.schemas import AssistantRequest, AssistantResponse, AssistantTurn
from netcoop_api.service import run_manager

router = APIRouter(prefix="/api/runs", tags=["Assistant"])


@router.get("/{run_id}/assistant/history", response_model=list[AssistantTurn])
def get_assistant_history(run_id: str) -> list[AssistantTurn]:
    """Returns this run's durable explanation-chat history."""
    history = run_manager.get_assistant_history(run_id)
    if history is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return [AssistantTurn.model_validate(turn) for turn in history]


@router.delete("/{run_id}/assistant/history", status_code=204)
def clear_assistant_history(run_id: str) -> None:
    if not run_manager.clear_assistant_history(run_id):
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")


@router.post("/{run_id}/assistant", response_model=AssistantResponse)
def ask_assistant(run_id: str, req: AssistantRequest) -> AssistantResponse:
    """Answers operator questions about a certified incident report and specialist findings."""
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if run.status != "completed":
        raise HTTPException(status_code=409, detail="Assistant is available after the run completes")

    return assistant_service.answer_question(run_id, req)
