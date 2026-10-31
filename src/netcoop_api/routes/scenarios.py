"""Scenario catalog and topology routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from netcoop_api.schemas import ScenarioDetail, ScenarioSummary, TopologyGraph
from netcoop_api.service import run_manager

router = APIRouter(prefix="/api/scenarios", tags=["Scenarios"])


@router.get("", response_model=list[ScenarioSummary])
def list_scenarios() -> list[ScenarioSummary]:
    """Lists available benchmark incident scenarios."""
    return run_manager.list_scenarios()


@router.get("/{scenario_id}", response_model=ScenarioDetail)
def get_scenario_metadata(scenario_id: str) -> ScenarioDetail:
    """Returns metadata for a specific scenario without leaking hidden ground truth."""
    scenario = run_manager.get_scenario(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")
    return scenario


@router.get("/{scenario_id}/topology", response_model=TopologyGraph)
def get_scenario_topology(scenario_id: str) -> TopologyGraph:
    """Returns network topology graph (nodes and links) for a scenario."""
    topo = run_manager.get_scenario_topology(scenario_id)
    if not topo:
        raise HTTPException(status_code=404, detail=f"Topology for scenario '{scenario_id}' not found")
    return topo
