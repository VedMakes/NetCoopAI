"""Health check router for NetCoop AI backend status."""

from __future__ import annotations

import sys
from typing import Any

from fastapi import APIRouter

from netcoop.cli.main import load_rules, load_vocabulary
from netcoop.communication.registry import CapabilityRegistry
from netcoop.models.enums import TowerId
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.supervisor.agent import SupervisoryRCAAgent
from netcoop.supervisor.gate import EvidenceReleaseGate
from netcoop.supervisor.runtime import SupervisorRuntime
from netcoop.towers import (
    ConnectivityTower,
    InfrastructureTower,
    PerformanceTower,
    ServicesTower,
)

router = APIRouter(prefix="/api/health", tags=["Health"])


@router.get("")
def get_system_health() -> dict[str, Any]:
    components: dict[str, dict[str, str]] = {}

    # 1. Python runtime
    components["runtime"] = {
        "status": "OK",
        "details": f"{sys.implementation.name.capitalize()} {sys.version.split()[0]}",
    }

    # 2. Vocabulary
    try:
        vocab = load_vocabulary()
        count = len(vocab.get("metrics", vocab)) if isinstance(vocab, dict) else len(vocab)
        components["vocabulary"] = {
            "status": "OK",
            "details": f"{count} canonical metrics loaded",
        }
    except Exception as exc:
        components["vocabulary"] = {"status": "ERROR", "details": str(exc)}

    # 3. Registry
    try:
        profiles = [CapabilityRegistry.get_profile(t) for t in TowerId]
        loaded_count = sum(1 for p in profiles if p is not None)
        components["capability_registry"] = {
            "status": "OK",
            "details": f"{loaded_count} tower profiles loaded",
        }
    except Exception as exc:
        components["capability_registry"] = {"status": "ERROR", "details": str(exc)}

    # 4. SQLite
    try:
        repo = SQLiteRepository(":memory:")
        repo.record_incident("INC-HEALTH-CHECK", "active", "Self test")
        components["sqlite"] = {
            "status": "OK",
            "details": "Initialized in-memory DB (schema v1)",
        }
    except Exception as exc:
        components["sqlite"] = {"status": "ERROR", "details": str(exc)}

    # 5. Diagnostic Towers
    try:
        rules = load_rules()
        _towers = [
            PerformanceTower(rules=rules),
            InfrastructureTower(rules=rules),
            ConnectivityTower(rules=rules),
            ServicesTower(rules=rules),
        ]
        components["towers"] = {
            "status": "OK",
            "details": "4 domain controllers ready (Performance, Infra, Conn, Services)",
        }
    except Exception as exc:
        components["towers"] = {"status": "ERROR", "details": str(exc)}

    # 6. Supervisor & Gate
    try:
        repo = SQLiteRepository(":memory:")
        _supervisor = SupervisorRuntime(
            repository=repo,
            rca_agent=SupervisoryRCAAgent(),
            gate=EvidenceReleaseGate(repository=repo),
        )
        components["supervisor_gate"] = {
            "status": "OK",
            "details": "SupervisorRuntime & EvidenceReleaseGate initialized",
        }
    except Exception as exc:
        components["supervisor_gate"] = {"status": "ERROR", "details": str(exc)}

    all_ok = all(c["status"] == "OK" for c in components.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "components": components,
    }
