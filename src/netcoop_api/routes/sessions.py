"""Local investigation session management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from netcoop_api.assistant import assistant_service
from netcoop_api.schemas import (
    AssistantRequest,
    AssistantResponse,
    AssistantTurn,
    SessionDetail,
    SessionSummary,
)
from netcoop_api.service import run_manager

router = APIRouter(prefix="/api/sessions", tags=["Sessions"])


class CreateSessionRequest(BaseModel):
    title: str = Field(default="Network investigation", min_length=1, max_length=120)


@router.get("", response_model=list[SessionSummary])
def list_sessions() -> list[SessionSummary]:
    return run_manager.list_sessions()


@router.post("", response_model=SessionSummary, status_code=201)
def create_session(req: CreateSessionRequest) -> SessionSummary:
    return run_manager.create_session(req.title)


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: str) -> SessionDetail:
    session = run_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return session


@router.get("/{session_id}/assistant/history", response_model=list[AssistantTurn])
def get_session_assistant_history(session_id: str) -> list[AssistantTurn]:
    history = run_manager.get_session_assistant_history(session_id)
    if history is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return [AssistantTurn.model_validate(turn) for turn in history]


@router.delete("/{session_id}/assistant/history", status_code=204)
def clear_session_assistant_history(session_id: str) -> None:
    if not run_manager.clear_session_assistant_history(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@router.post("/{session_id}/assistant", response_model=AssistantResponse)
def ask_session_assistant(session_id: str, req: AssistantRequest) -> AssistantResponse:
    if run_manager.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return assistant_service.answer_session_question(session_id, req)
