"""Application service coordinator managing scenarios, runs, and incident artifacts."""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from netcoop.cli.main import (
    _load_observations_from_target,
    load_rules,
)
from netcoop.communication.fabric import IntegrationFabric
from netcoop.configuration.profile import NetworkProfile
from netcoop.features.models import DerivedFeature
from netcoop.features.pipeline import FeaturePipeline
from netcoop.models.enums import TowerId
from netcoop.models.observations import (
    CanonicalObservation,
    ConfigObservation,
    LogObservation,
    MetricObservation,
    TopologyObservation,
)
from netcoop.models.reports import FinalReport, TowerReport
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.supervisor.agent import SupervisoryRCAAgent
from netcoop.supervisor.gate import EvidenceReleaseGate
from netcoop.supervisor.runtime import SupervisorRuntime
from netcoop.supervisor.symptom_agent import SymptomReasoningAgent
from netcoop_api.events import event_sink
from netcoop_api.schemas import (
    DerivedFeatureModel,
    EvaluationResponse,
    ExecutionEventModel,
    GateCheckResultModel,
    GateResultDetail,
    RunCreateRequest,
    RunStatusResponse,
    ScenarioDetail,
    ScenarioSummary,
    SessionDetail,
    SessionSummary,
    TelemetryObservationModel,
    TelemetryResponse,
    TopologyGraph,
    TopologyLink,
    TopologyNode,
    TowerReportSummary,
    UploadRunRequest,
)

logger = logging.getLogger(__name__)
_RUN_ID_RE = re.compile(r"run-[a-f0-9]{10}\Z")
_SESSION_ID_RE = re.compile(r"session-[a-f0-9]{12}\Z")

SCENARIO_CATALOG_META = {
    "healthy": {
        "name": "Healthy Baseline",
        "category": "Baseline",
        "description": "Nominal campus network traffic with baseline loads, zero packet loss, and healthy Wi-Fi/DNS.",
        "symptoms": "Nominal throughput and latency across all core and distribution switches.",
    },
    "link_congestion": {
        "name": "Core Uplink Congestion",
        "category": "Performance",
        "description": "High link utilization on core switch Gi0/2 resulting in buffer queue drops and packet loss.",
        "symptoms": "Interface saturation (>95%), severe queue drops, and TCP retransmissions.",
    },
    "weak_wifi": {
        "name": "Hostel Wireless Attenuation",
        "category": "Wireless",
        "description": "Severe RF signal attenuation and low SNR on hostel access points causing frame drops.",
        "symptoms": "Low RSSI (-85dBm), poor SNR, elevated wireless retry rates.",
    },
    "interface_fault": {
        "name": "Switch Interface CRC Drops",
        "category": "Infrastructure",
        "description": "Physical layer interface degradation causing CRC errors and periodic link state flaps.",
        "symptoms": "Rising CRC error counters, link state flaps, and frame drops.",
    },
    "device_overload": {
        "name": "Core Switch CPU Exhaustion",
        "category": "Hardware",
        "description": "Control plane CPU utilization spike (>92%) and memory pressure on core backbone switch.",
        "symptoms": "High CPU utilization, buffer allocation failures, processing delays.",
    },
    "dns_failure": {
        "name": "Campus DNS Resolver Timeout",
        "category": "Services",
        "description": "DNS daemon response timeouts and SERVFAIL error spikes on campus primary DNS server.",
        "symptoms": "DNS resolution latency >2000ms, SERVFAIL responses, query timeouts.",
    },
    "dhcp_failure": {
        "name": "DHCP Address Pool Exhaustion",
        "category": "Services",
        "description": "DHCP lease pool exhaustion in student hostel VLAN resulting in NAK storms.",
        "symptoms": "DHCP NAK storms, address request failures, zero available leases.",
    },
}


class RunRecord:
    def __init__(
        self,
        run_id: str,
        incident_id: str,
        scenario_id: str | None,
        target_path: Path,
        repository_path: Path,
        session_id: str,
        topology_path: Path | None = None,
        entity_aliases: dict[str, str] | None = None,
    ):
        self.run_id = run_id
        self.incident_id = incident_id
        self.scenario_id = scenario_id
        self.target_path = target_path
        self.repository_path = repository_path
        self.session_id = session_id
        self.topology_path = topology_path
        self.entity_aliases = entity_aliases or {}
        self.status = "queued"
        self.created_at = datetime.now(timezone.utc)
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None
        self.error: str | None = None

        self.observations: list[CanonicalObservation] = []
        self.features: list[DerivedFeature] = []
        self.report: FinalReport | None = None
        self.tower_reports: dict[TowerId, TowerReport] = {}
        self.gate_result: Any = None
        self.repository: SQLiteRepository | None = None
        self.assistant_history: list[dict[str, str]] = []


class RunManager:
    """Coordinates benchmark scenarios, runs, and artifacts."""

    def __init__(self, scenarios_dir: Path | None = None, storage_dir: Path | None = None):
        self.scenarios_dir = (
            scenarios_dir
            if scenarios_dir is not None
            else Path(__file__).resolve().parents[2] / "fixtures" / "scenarios"
        ).resolve()
        self.storage_dir = (
            storage_dir
            if storage_dir is not None
            else Path(__file__).resolve().parents[2] / "data" / "netcoop"
        ).resolve()
        self.uploads_dir = self.storage_dir / "uploads"
        self.runs_dir = self.storage_dir / "runs"
        self.sessions_dir = self.storage_dir / "sessions"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._runs: dict[str, RunRecord] = {}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._persist_lock = threading.Lock()
        self._restore_sessions()
        self._restore_runs()

    def _session_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def _persist_session(self, session: dict[str, Any]) -> None:
        path = self._session_path(session["session_id"])
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(session), encoding="utf-8")
        temporary.replace(path)

    def _restore_sessions(self, *, only_missing: bool = False) -> None:
        for path in sorted(self.sessions_dir.glob("session-*.json")):
            try:
                session = json.loads(path.read_text(encoding="utf-8"))
                session_id = session.get("session_id") if isinstance(session, dict) else None
                if (
                    isinstance(session_id, str)
                    and _SESSION_ID_RE.fullmatch(session_id)
                    and path.stem == session_id
                ):
                    if only_missing:
                        with self._lock:
                            if session_id in self._sessions:
                                continue
                    session["title"] = str(session.get("title") or "Network investigation")[:120]
                    now = datetime.now(timezone.utc).isoformat()
                    for timestamp_key in ("created_at", "updated_at"):
                        try:
                            datetime.fromisoformat(session.get(timestamp_key, ""))
                        except (TypeError, ValueError):
                            session[timestamp_key] = now
                    session["run_ids"] = [
                        run_id for run_id in session.get("run_ids", [])
                        if isinstance(run_id, str) and _RUN_ID_RE.fullmatch(run_id)
                    ] if isinstance(session.get("run_ids", []), list) else []
                    history = session.get("assistant_history", [])
                    session["assistant_history"] = [
                        {"role": turn["role"], "content": turn["content"][:4000]}
                        for turn in history[-40:]
                        if isinstance(turn, dict)
                        and turn.get("role") in {"user", "assistant"}
                        and isinstance(turn.get("content"), str)
                    ] if isinstance(history, list) else []
                    if not isinstance(session.get("current_run_id"), str):
                        session["current_run_id"] = None
                    self._sessions[session_id] = session
            except Exception:
                logger.exception("Failed to restore session metadata from %s", path)

    def create_session(self, title: str = "Network investigation") -> SessionSummary:
        now = datetime.now(timezone.utc)
        session = {
            "session_id": f"session-{uuid.uuid4().hex[:12]}",
            "title": title.strip() or "Network investigation",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "current_run_id": None,
            "run_ids": [],
            "assistant_history": [],
        }
        with self._lock:
            self._sessions[session["session_id"]] = session
            self._persist_session(session)
        return self._session_summary(session)

    @staticmethod
    def _session_summary(session: dict[str, Any]) -> SessionSummary:
        return SessionSummary(
            session_id=session["session_id"],
            title=session["title"],
            created_at=session["created_at"],
            updated_at=session["updated_at"],
            current_run_id=session.get("current_run_id"),
            run_count=len(session.get("run_ids", [])),
        )

    def refresh_external_state(self) -> None:
        """Import sessions and completed runs created by another local CLI/API process."""
        self._restore_sessions(only_missing=True)
        self._restore_runs(only_missing=True)
        with self._lock:
            session_ids = list(self._sessions)
        for session_id in session_ids:
            path = self._session_path(session_id)
            try:
                disk_session = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(disk_session, dict) or disk_session.get("session_id") != session_id:
                continue
            with self._lock:
                current = self._sessions.get(session_id)
                if current is None:
                    continue
                current_ids = current.get("run_ids", []) if isinstance(current.get("run_ids", []), list) else []
                disk_ids = disk_session.get("run_ids", []) if isinstance(disk_session.get("run_ids", []), list) else []
                merged_ids = list(dict.fromkeys(
                    [item for item in current_ids + disk_ids if isinstance(item, str) and _RUN_ID_RE.fullmatch(item)]
                ))
                disk_history = disk_session.get("assistant_history", [])
                safe_history = [
                    {"role": turn["role"], "content": turn["content"][:4000]}
                    for turn in disk_history[-40:]
                    if isinstance(turn, dict)
                    and turn.get("role") in {"user", "assistant"}
                    and isinstance(turn.get("content"), str)
                ] if isinstance(disk_history, list) else current.get("assistant_history", [])
                disk_current = disk_session.get("current_run_id")
                current.update({
                    "title": str(disk_session.get("title") or current.get("title") or "Network investigation")[:120],
                    "run_ids": merged_ids,
                    "assistant_history": safe_history,
                    "current_run_id": disk_current if disk_current in merged_ids else current.get("current_run_id"),
                    "updated_at": max(
                        str(current.get("updated_at", "")),
                        str(disk_session.get("updated_at", "")),
                    ),
                })

    def list_sessions(self) -> list[SessionSummary]:
        self.refresh_external_state()
        with self._lock:
            sessions = list(self._sessions.values())
        return [self._session_summary(s) for s in sorted(sessions, key=lambda s: s["updated_at"], reverse=True)]

    def get_session(self, session_id: str) -> SessionDetail | None:
        self.refresh_external_state()
        with self._lock:
            session = self._sessions.get(session_id)
            run_ids = list(session.get("run_ids", [])) if session else []
        if not session:
            return None
        runs = [status for run_id in run_ids if (status := self.get_run(run_id)) is not None]
        summary = self._session_summary(session)
        return SessionDetail(**summary.model_dump(), runs=runs)

    def get_session_assistant_history(self, session_id: str) -> list[dict[str, str]] | None:
        self.refresh_external_state()
        with self._lock:
            session = self._sessions.get(session_id)
            return list(session.get("assistant_history", [])) if session else None

    def append_session_assistant_turns(self, session_id: str, question: str, answer: str) -> None:
        self.refresh_external_state()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            history = session.setdefault("assistant_history", [])
            history.extend([
                {"role": "user", "content": question[:2000]},
                {"role": "assistant", "content": answer[:4000]},
            ])
            session["assistant_history"] = history[-40:]
            session["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._persist_session(session)

    def clear_session_assistant_history(self, session_id: str) -> bool:
        self.refresh_external_state()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session["assistant_history"] = []
            session["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._persist_session(session)
        return True

    def _attach_run_to_session(self, session_id: str | None, run_id: str) -> str:
        if session_id is None:
            session_id = self.create_session().session_id
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Session '{session_id}' not found")
            run_ids = session.setdefault("run_ids", [])
            if run_id not in run_ids:
                run_ids.append(run_id)
            session["current_run_id"] = run_id
            session["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._persist_session(session)
        return session_id

    def _metadata_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.json"

    def _persist_run(self, rec: RunRecord) -> None:
        # Serialize writers and snapshot mutable run fields while holding the
        # manager lock. Without this, concurrent chat persistence and worker
        # completion can race on the same temporary metadata file.
        with self._persist_lock:
            with self._lock:
                metadata = {
                    "run_id": rec.run_id,
                    "incident_id": rec.incident_id,
                    "session_id": rec.session_id,
                    "scenario_id": rec.scenario_id,
                    "target_path": str(rec.target_path),
                    "repository_path": str(rec.repository_path),
                    "topology_path": str(rec.topology_path) if rec.topology_path else None,
                    "entity_aliases": rec.entity_aliases,
                    "status": rec.status,
                    "created_at": rec.created_at.isoformat(),
                    "started_at": rec.started_at.isoformat() if rec.started_at else None,
                    "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
                    "error": rec.error,
                    "assistant_history": list(rec.assistant_history),
                    "events": [event.model_dump(mode="json") for event in event_sink.get_events(rec.run_id)],
                }
            path = self._metadata_path(rec.run_id)
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(metadata), encoding="utf-8")
            temporary.replace(path)

    def _restore_runs(self, *, only_missing: bool = False) -> None:
        """Restore run reports and artifact references after a local server restart."""
        for metadata_path in sorted(self.runs_dir.glob("run-*.json")):
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("run metadata root must be an object")
                run_id = data.get("run_id")
                if (
                    not isinstance(run_id, str)
                    or not _RUN_ID_RE.fullmatch(run_id)
                    or metadata_path.stem != run_id
                ):
                    raise ValueError("run metadata contains an invalid run ID")
                if only_missing:
                    with self._lock:
                        if run_id in self._runs:
                            continue
                    if data.get("status") in {"queued", "running"}:
                        continue
                session_id = data.get("session_id")
                if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
                    session_id = self.create_session().session_id
                scenario_id = data.get("scenario_id")
                scenario_path = self._scenario_path(scenario_id) if isinstance(scenario_id, str) else None
                if scenario_path is not None:
                    target_path = scenario_path
                else:
                    if scenario_id is not None:
                        scenario_id = None
                    try:
                        target_path = Path(data["target_path"]).resolve()
                    except (KeyError, TypeError, ValueError):
                        target_path = self.uploads_dir / "missing-upload"
                    if not target_path.is_relative_to(self.uploads_dir):
                        target_path = self.uploads_dir / "missing-upload"
                repository_path = self.runs_dir / f"{run_id}.sqlite3"
                topology_raw = data.get("topology_path")
                try:
                    topology_path = Path(topology_raw).resolve() if isinstance(topology_raw, str) else None
                except (OSError, ValueError):
                    topology_path = None
                if topology_path:
                    allowed_topology_roots = [
                        self.uploads_dir,
                        Path(__file__).resolve().parents[2] / "config" / "sites",
                    ]
                    if not any(topology_path.is_relative_to(root.resolve()) for root in allowed_topology_roots):
                        topology_path = None
                rec = RunRecord(
                    run_id=run_id,
                    incident_id=data["incident_id"],
                    scenario_id=scenario_id,
                    target_path=target_path,
                    repository_path=repository_path,
                    session_id=session_id,
                    topology_path=topology_path,
                    entity_aliases={
                        key: value
                        for key, value in data.get("entity_aliases", {}).items()
                        if isinstance(key, str) and isinstance(value, str)
                    } if isinstance(data.get("entity_aliases", {}), dict) else {},
                )
                rec.status = data.get("status", "failed")
                rec.created_at = datetime.fromisoformat(data["created_at"])
                rec.started_at = datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None
                rec.completed_at = datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
                rec.error = data.get("error")
                history = data.get("assistant_history", [])
                rec.assistant_history = [
                    {"role": turn["role"], "content": turn["content"][:4000]}
                    for turn in history[-40:]
                    if isinstance(turn, dict)
                    and turn.get("role") in {"user", "assistant"}
                    and isinstance(turn.get("content"), str)
                ] if isinstance(history, list) else []

                if rec.status in {"queued", "running"}:
                    rec.status = "failed"
                    rec.completed_at = datetime.now(timezone.utc)
                    rec.error = "The API restarted before this run completed; start a new run to continue."

                if rec.repository_path.is_file():
                    try:
                        repo = SQLiteRepository(rec.repository_path)
                        rec.repository = repo
                        rec.observations = repo.get_observations(rec.incident_id)
                        if rec.observations:
                            rec.features = FeaturePipeline().extract_features(
                                rec.observations, incident_id=rec.incident_id
                            )
                        rec.report = repo.get_final_report(rec.incident_id)
                        rec.tower_reports = {
                            report.tower_id: report for report in repo.get_tower_reports(rec.incident_id)
                        }
                        rec.gate_result = repo.get_gate_result(rec.incident_id)
                    except Exception as exc:
                        logger.exception("Could not restore SQLite artifacts for run %s", rec.run_id)
                        rec.status = "failed"
                        rec.completed_at = rec.completed_at or datetime.now(timezone.utc)
                        rec.error = f"Saved run artifacts could not be restored: {exc}"
                if rec.status == "completed" and rec.report is None:
                    rec.status = "failed"
                    rec.error = "Saved report artifacts are missing; rerun this investigation."
                    rec.completed_at = rec.completed_at or datetime.now(timezone.utc)

                with self._lock:
                    self._runs[rec.run_id] = rec
                # Rehydration must not make an arbitrary filename-sorted run the
                # session's current run or make old sessions appear recently used.
                with self._lock:
                    session = self._sessions.get(rec.session_id)
                    if session is None:
                        session = {
                            "session_id": rec.session_id,
                            "title": "Network investigation",
                            "created_at": rec.created_at.isoformat(),
                            "updated_at": rec.created_at.isoformat(),
                            "current_run_id": None,
                            "run_ids": [rec.run_id],
                        }
                        self._sessions[rec.session_id] = session
                    else:
                        session.setdefault("run_ids", [])
                        if rec.run_id not in session["run_ids"]:
                            session["run_ids"].append(rec.run_id)
                        if not session.get("current_run_id"):
                            session["current_run_id"] = rec.run_id
                    self._persist_session(session)
                try:
                    events = [ExecutionEventModel.model_validate(event) for event in data.get("events", [])]
                except Exception as exc:
                    logger.exception("Could not restore execution events for run %s", rec.run_id)
                    events = []
                    rec.error = rec.error or f"Saved event history could not be restored: {exc}"
                event_sink.restore_run(
                    rec.run_id,
                    events,
                    closed=rec.status in {"completed", "failed"},
                    status=rec.status,
                )
                self._persist_run(rec)
            except Exception:
                logger.exception("Failed to restore API run metadata from %s", metadata_path)

        # Repair a stale current pointer only when its target is absent. Existing
        # pointers remain authoritative so restoring history is side-effect free.
        with self._lock:
            restored_runs = dict(self._runs)
            sessions = list(self._sessions.values())
        for session in sessions:
            with self._lock:
                session_id = session["session_id"]
                original_ids = session.get("run_ids", [])
                valid_ids = [
                    run_id for run_id in original_ids
                    if (
                        run_id in restored_runs and restored_runs[run_id].session_id == session_id
                    ) or (only_missing and self._metadata_path(run_id).is_file())
                ]
                changed = valid_ids != original_ids
                session["run_ids"] = valid_ids
                current_id = session.get("current_run_id")
                if current_id not in valid_ids:
                    candidates = [restored_runs[run_id] for run_id in valid_ids]
                    if candidates:
                        latest = max(candidates, key=lambda item: item.created_at)
                        session["current_run_id"] = latest.run_id
                    else:
                        session["current_run_id"] = None
                    changed = True
                if changed:
                    self._persist_session(session)

    def _scenario_path(self, scenario_id: str) -> Path | None:
        """Resolve a catalog scenario without permitting paths outside the catalog."""
        candidate = (self.scenarios_dir / scenario_id).resolve()
        if not candidate.is_relative_to(self.scenarios_dir):
            return None
        if not candidate.is_dir() or not (candidate / "telemetry.jsonl").is_file():
            return None
        return candidate

    def list_scenarios(self) -> list[ScenarioSummary]:
        results: list[ScenarioSummary] = []
        if not self.scenarios_dir.exists():
            return results

        for p in sorted(self.scenarios_dir.iterdir()):
            scenario_path = self._scenario_path(p.name)
            if scenario_path is not None:
                meta = SCENARIO_CATALOG_META.get(scenario_path.name, {
                    "name": scenario_path.name.replace("_", " ").title(),
                    "category": "Synthetic",
                    "description": f"Synthetic scenario for {scenario_path.name}",
                    "symptoms": "Network telemetry anomaly capture",
                })
                results.append(ScenarioSummary(
                    scenario_id=scenario_path.name,
                    name=meta["name"],
                    category=meta["category"],
                    description=meta["description"],
                    fixture_path=str(scenario_path),
                    symptoms_summary=meta["symptoms"],
                ))
        return results

    def get_scenario(self, scenario_id: str) -> ScenarioDetail | None:
        scenario_path = self._scenario_path(scenario_id)
        if scenario_path is None:
            return None

        meta = SCENARIO_CATALOG_META.get(scenario_id, {
            "name": scenario_id.replace("_", " ").title(),
            "category": "Synthetic",
            "description": f"Synthetic scenario for {scenario_id}",
            "symptoms": "Network telemetry anomaly capture",
        })

        node_count = 0
        link_count = 0
        topo_file = scenario_path / "topology.json"
        if topo_file.exists():
            try:
                topo_data = json.loads(topo_file.read_text(encoding="utf-8"))
                node_count = len(topo_data.get("nodes", []))
                link_count = len(topo_data.get("links", []))
            except Exception:
                pass

        has_ground_truth = (scenario_path / "evaluation" / "ground_truth.json").exists()

        return ScenarioDetail(
            scenario_id=scenario_id,
            name=meta["name"],
            category=meta["category"],
            description=meta["description"],
            fixture_path=str(scenario_path),
            symptoms_summary=meta["symptoms"],
            node_count=node_count,
            link_count=link_count,
            has_ground_truth=has_ground_truth,
        )

    def get_scenario_topology(self, scenario_id: str) -> TopologyGraph | None:
        scenario_path = self._scenario_path(scenario_id)
        if scenario_path is None:
            return None

        topo_file = scenario_path / "topology.json"
        if not topo_file.exists():
            return TopologyGraph(topology_id=scenario_id)

        try:
            data = json.loads(topo_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error(f"Failed to read topology file: {exc}")
            return None

        nodes = [
            TopologyNode(
                id=n.get("entity_id", ""),
                name=n.get("name", n.get("entity_id", "")),
                role=n.get("role", "device"),
                type=n.get("entity_type", "device"),
                status="nominal",
            )
            for n in data.get("nodes", [])
        ]

        links = [
            TopologyLink(
                id=lk.get("link_id", f"{lk.get('source_entity')}--{lk.get('target_entity')}"),
                source=lk.get("source_entity", ""),
                target=lk.get("target_entity", ""),
                relationship=lk.get("relationship_type", "connected_to"),
                status="nominal",
            )
            for lk in data.get("links", [])
        ]

        return TopologyGraph(
            topology_id=data.get("topology_id", scenario_id),
            nodes=nodes,
            links=links,
            metadata={"source": str(topo_file)},
        )

    def create_run(self, req: RunCreateRequest) -> RunStatusResponse:
        run_id = f"run-{uuid.uuid4().hex[:10]}"
        if not req.scenario_id:
            raise ValueError("scenario_id is required; use the upload endpoint for custom captures")
        scenario_path = self._scenario_path(req.scenario_id)
        if scenario_path is None:
            raise ValueError(f"Scenario '{req.scenario_id}' not found in {self.scenarios_dir}")
        incident_id = req.incident_id or f"INC-{req.scenario_id}-{uuid.uuid4().hex[:6]}"
        return self._start_run(
            run_id=run_id,
            target_path=scenario_path,
            scenario_id=req.scenario_id,
            incident_id=incident_id,
            llm=req.llm,
            symptom_chat=req.symptom_chat,
            site=req.site,
            session_id=req.session_id,
        )

    def create_uploaded_run(self, req: UploadRunRequest) -> RunStatusResponse:
        telemetry_suffix = Path(req.telemetry_filename).suffix.lower()
        if telemetry_suffix not in {".json", ".jsonl", ".csv", ".log"}:
            raise ValueError("Telemetry must be a .json, .jsonl, .csv, or .log file")
        if (req.topology_filename is None) != (req.topology_content is None):
            raise ValueError("topology_filename and topology_content must be provided together")
        if req.topology_filename and Path(req.topology_filename).suffix.lower() != ".json":
            raise ValueError("Topology must be a .json file")
        if req.topology_content is not None:
            try:
                topology = json.loads(req.topology_content)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Topology file is not valid JSON: {exc.msg}") from exc
            if not isinstance(topology, dict):
                raise ValueError("Topology JSON must contain an object")

        upload_id = uuid.uuid4().hex
        target_path = self.uploads_dir / upload_id
        target_path.mkdir(parents=True, exist_ok=False)
        telemetry_path = target_path / f"telemetry{telemetry_suffix}"
        try:
            telemetry_path.write_text(req.telemetry_content, encoding="utf-8")
            if req.topology_content is not None:
                (target_path / "topology.json").write_text(req.topology_content, encoding="utf-8")
        except Exception:
            import shutil

            shutil.rmtree(target_path, ignore_errors=True)
            raise

        run_id = f"run-{uuid.uuid4().hex[:10]}"
        incident_id = req.incident_id or f"INC-UPLOAD-{uuid.uuid4().hex[:6]}"
        try:
            return self._start_run(
                run_id=run_id,
                target_path=target_path,
                scenario_id=None,
                incident_id=incident_id,
                llm=req.llm,
                symptom_chat=req.symptom_chat,
                site=req.site,
                session_id=req.session_id,
            )
        except Exception:
            import shutil

            shutil.rmtree(target_path, ignore_errors=True)
            raise

    def create_cli_run(
        self,
        *,
        session_id: str,
        incident_id: str,
        input_path: Path,
        topology_path: Path | None = None,
        entity_aliases: dict[str, str] | None = None,
    ) -> RunRecord:
        """Reserve a session run for CLI diagnosis; persistence occurs after completion."""
        self.refresh_external_state()
        scenario_id = None
        candidate = self._scenario_path(input_path.name)
        if candidate is not None and candidate == input_path.resolve():
            scenario_id = input_path.name

        if scenario_id:
            stored_target = candidate
            stored_topology = None
        else:
            stored_target = self.uploads_dir / f"cli-{uuid.uuid4().hex}"
            stored_target.mkdir(parents=True, exist_ok=False)
            stored_topology = stored_target / "topology.json"
            source_topology = topology_path or (
                input_path / "topology.json" if input_path.is_dir() else None
            )
            if source_topology and source_topology.is_file():
                import shutil

                shutil.copyfile(source_topology, stored_topology)
            else:
                stored_topology = None

        run_id = f"run-{uuid.uuid4().hex[:10]}"
        session_id = self._attach_run_to_session(session_id, run_id)
        record = RunRecord(
            run_id=run_id,
            incident_id=incident_id,
            scenario_id=scenario_id,
            target_path=stored_target,
            repository_path=self.runs_dir / f"{run_id}.sqlite3",
            session_id=session_id,
            topology_path=stored_topology,
            entity_aliases=entity_aliases or {},
        )
        record.status = "running"
        record.started_at = record.created_at
        with self._lock:
            self._runs[run_id] = record
        self._persist_run(record)
        return record

    def complete_cli_run(
        self,
        run_id: str,
        *,
        report: FinalReport,
        observations: list[CanonicalObservation],
        source_repository: SQLiteRepository,
    ) -> None:
        """Publish a CLI diagnosis as a normal persisted session run for the dashboard."""
        with self._lock:
            record = self._runs.get(run_id)
        if record is None:
            raise ValueError(f"CLI run '{run_id}' was not registered")

        stored_repository = SQLiteRepository(record.repository_path)
        if source_repository.db_path != stored_repository.db_path:
            stored_repository.record_incident(record.incident_id, status="completed")
            for observation in observations:
                stored_repository.insert_observation(observation)
            for tower_report in source_repository.get_tower_reports(record.incident_id):
                stored_repository.insert_tower_report(tower_report)
            gate_result = source_repository.get_gate_result(record.incident_id)
            if gate_result is not None:
                stored_repository.insert_gate_result(record.incident_id, gate_result)
            for task in source_repository.get_tasks(record.incident_id):
                stored_repository.insert_task(task)
            for proposal in source_repository.get_supervisor_proposals(record.incident_id):
                stored_repository.insert_supervisor_proposal(proposal)

        stored_repository.insert_final_report(report)
        now = datetime.now(timezone.utc)
        with self._lock:
            record.repository = stored_repository
            record.observations = stored_repository.get_observations(record.incident_id)
            record.features = FeaturePipeline().extract_features(
                record.observations, incident_id=record.incident_id
            )
            record.report = report
            record.tower_reports = {
                item.tower_id: item
                for item in stored_repository.get_tower_reports(record.incident_id)
            }
            record.gate_result = stored_repository.get_gate_result(record.incident_id)
            record.status = "completed"
            record.completed_at = now

        event_sink.restore_run(
            run_id,
            [
                ExecutionEventModel(
                    event_id=str(uuid.uuid4()),
                    run_id=run_id,
                    incident_id=record.incident_id,
                    timestamp=record.started_at or record.created_at,
                    event_type="run.started",
                    source_component="cli",
                    status="completed",
                    payload={"source": "CLI"},
                ),
                ExecutionEventModel(
                    event_id=str(uuid.uuid4()),
                    run_id=run_id,
                    incident_id=record.incident_id,
                    timestamp=now,
                    event_type="run.completed",
                    source_component="cli",
                    status="completed",
                    payload={"source": "CLI", "report_status": report.status},
                ),
            ],
            closed=True,
            status="completed",
        )
        self._attach_run_to_session(record.session_id, run_id)
        self._persist_run(record)

    def fail_cli_run(self, run_id: str, error: str) -> None:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return
            record.status = "failed"
            record.error = error[:2000]
            record.completed_at = datetime.now(timezone.utc)
        event_sink.close_run(run_id, status="failed")
        self._persist_run(record)

    def _start_run(
        self,
        *,
        run_id: str,
        target_path: Path,
        scenario_id: str | None,
        incident_id: str,
        llm: str,
        symptom_chat: str | None,
        site: str | None,
        session_id: str | None,
    ) -> RunStatusResponse:

        session_id = self._attach_run_to_session(session_id, run_id)

        record = RunRecord(
            run_id=run_id,
            incident_id=incident_id,
            scenario_id=scenario_id,
            target_path=target_path,
            repository_path=self.runs_dir / f"{run_id}.sqlite3",
            session_id=session_id,
        )

        with self._lock:
            self._runs[run_id] = record
        self._persist_run(record)

        # Start execution in background thread
        thread = threading.Thread(
            target=self._execute_run_worker,
            args=(run_id, llm, symptom_chat, site),
            daemon=True,
        )
        thread.start()

        return RunStatusResponse(
            run_id=run_id,
            incident_id=incident_id,
            session_id=session_id,
            scenario_id=scenario_id,
            status="queued",
            created_at=record.created_at,
        )

    def get_run(self, run_id: str) -> RunStatusResponse | None:
        with self._lock:
            rec = self._runs.get(run_id)
            if not rec:
                return None
            return RunStatusResponse(
                run_id=rec.run_id,
                incident_id=rec.incident_id,
                session_id=rec.session_id,
                scenario_id=rec.scenario_id,
                status=rec.status,
                created_at=rec.created_at,
                started_at=rec.started_at,
                completed_at=rec.completed_at,
                error=rec.error,
            )

    def list_runs(self) -> list[RunStatusResponse]:
        with self._lock:
            run_ids = list(self._runs)
        runs = [status for run_id in run_ids if (status := self.get_run(run_id)) is not None]
        return sorted(runs, key=lambda status: status.created_at, reverse=True)

    def get_assistant_history(self, run_id: str) -> list[dict[str, str]] | None:
        with self._lock:
            rec = self._runs.get(run_id)
            return list(rec.assistant_history) if rec else None

    def append_assistant_turns(self, run_id: str, question: str, answer: str) -> None:
        with self._lock:
            rec = self._runs.get(run_id)
            if rec is None:
                return
            rec.assistant_history.extend([
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ])
            # Keep a bounded durable transcript; each model call also receives only its latest turns.
            rec.assistant_history = rec.assistant_history[-40:]
        self._persist_run(rec)

    def clear_assistant_history(self, run_id: str) -> bool:
        with self._lock:
            rec = self._runs.get(run_id)
            if rec is None:
                return False
            rec.assistant_history.clear()
        self._persist_run(rec)
        return True

    def get_run_telemetry(self, run_id: str) -> TelemetryResponse | None:
        with self._lock:
            rec = self._runs.get(run_id)
            if not rec:
                return None

        obs_models: list[TelemetryObservationModel] = []
        for o in rec.observations:
            if isinstance(o, MetricObservation):
                obs_models.append(TelemetryObservationModel(
                    observation_id=o.observation_id,
                    incident_id=o.incident_id,
                    entity_id=o.entity_id,
                    entity_type="device",
                    timestamp=o.timestamp,
                    metric_name=o.metric_name,
                    value=o.value,
                    unit=o.unit,
                    source=o.source,
                    observation_type="metric",
                ))
            elif isinstance(o, LogObservation):
                obs_models.append(TelemetryObservationModel(
                    observation_id=o.observation_id,
                    incident_id=o.incident_id,
                    entity_id=o.entity_id,
                    entity_type="device",
                    timestamp=o.timestamp,
                    metric_name=o.log_level,
                    source=o.source,
                    observation_type="log",
                    message=o.message,
                ))
            elif isinstance(o, TopologyObservation):
                obs_models.append(TelemetryObservationModel(
                    observation_id=o.observation_id,
                    incident_id=o.incident_id,
                    entity_id=o.entity_id,
                    entity_type="device",
                    timestamp=o.timestamp,
                    metric_name=o.relationship_type,
                    source=o.source,
                    observation_type="topology",
                ))
            elif isinstance(o, ConfigObservation):
                obs_models.append(TelemetryObservationModel(
                    observation_id=o.observation_id,
                    incident_id=o.incident_id,
                    entity_id=o.entity_id,
                    entity_type="device",
                    timestamp=o.timestamp,
                    metric_name=o.config_key,
                    source=o.source,
                    observation_type="config",
                    message=str(o.config_value),
                ))

        feat_models = [
            DerivedFeatureModel(
                feature_id=f.feature_id,
                incident_id=f.incident_id,
                entity_id=f.entity_id,
                feature_name=f.feature_name,
                value=f.value,
                unit=f.unit,
                time_window_start=f.time_window_start,
                time_window_end=f.time_window_end,
                source_observation_ids=f.source_observation_ids,
            )
            for f in rec.features
        ]

        return TelemetryResponse(
            observations=obs_models,
            features=feat_models,
            total_observations=len(obs_models),
            total_features=len(feat_models),
        )

    def get_run_topology(self, run_id: str) -> TopologyGraph | None:
        with self._lock:
            rec = self._runs.get(run_id)
            if not rec:
                return None

        # Build topology from scenario file or observations
        graph: TopologyGraph | None = None
        if rec.scenario_id:
            graph = self.get_scenario_topology(rec.scenario_id)

        if not graph:
            graph = TopologyGraph(
                topology_id=rec.incident_id,
            )

        # Keep telemetry entities visible even when a supplied map is partial,
        # and preserve explicitly declared isolated nodes that cannot be
        # represented as link observations.
        node_ids = {node.id for node in graph.nodes}
        link_ids = {link.id for link in graph.links}
        for obs in rec.observations:
            entity_id = getattr(obs, "entity_id", None)
            if entity_id and entity_id not in node_ids:
                graph.nodes.append(TopologyNode(id=entity_id, name=entity_id, role="device"))
                node_ids.add(entity_id)
            if isinstance(obs, TopologyObservation):
                for endpoint in (obs.source_entity, obs.target_entity):
                    if endpoint not in node_ids:
                        graph.nodes.append(TopologyNode(id=endpoint, name=endpoint, role="device"))
                        node_ids.add(endpoint)
                if obs.observation_id not in link_ids:
                    graph.links.append(TopologyLink(
                        id=obs.observation_id,
                        source=obs.source_entity,
                        target=obs.target_entity,
                        relationship=obs.relationship_type,
                    ))
                    link_ids.add(obs.observation_id)

        if rec.target_path.is_dir():
            topology_path = rec.topology_path or (rec.target_path / "topology.json")
            try:
                topology_data = json.loads(topology_path.read_text(encoding="utf-8"))
                for item in topology_data.get("nodes", []):
                    if not isinstance(item, dict):
                        continue
                    entity_id = item.get("entity_id") or item.get("id")
                    if not isinstance(entity_id, str) or not entity_id.strip():
                        continue
                    entity_id = rec.entity_aliases.get(entity_id.strip().upper(), entity_id.strip())
                    if entity_id in node_ids:
                        continue
                    name = item.get("name")
                    role = item.get("role")
                    node_type = item.get("entity_type") or item.get("type")
                    graph.nodes.append(TopologyNode(
                        id=entity_id,
                        name=name if isinstance(name, str) and name else entity_id,
                        role=role if isinstance(role, str) and role else "device",
                        type=node_type if isinstance(node_type, str) and node_type else "device",
                    ))
                    node_ids.add(entity_id)
            except (OSError, json.JSONDecodeError, AttributeError, TypeError):
                # The ingestion path reports malformed map data as a warning;
                # topology display should still show telemetry-derived nodes.
                pass

        # Annotate nodes based on final report if completed
        if rec.report:
            symptom_entities = set(rec.report.observed_symptom_entities)
            inferred_entities = set(rec.report.inferred_affected_entities)
            root_cause_text = rec.report.suspected_root_cause.upper()

            for node in graph.nodes:
                if node.id in symptom_entities:
                    node.status = "symptom"
                elif node.id in inferred_entities:
                    node.status = "impacted"
                escaped_id = re.escape(node.id.upper())
                if re.search(rf"(?<![A-Z0-9]){escaped_id}(?![A-Z0-9])", root_cause_text):
                    node.status = "probable_root_cause"

        return graph

    def get_run_findings(self, run_id: str) -> list[TowerReportSummary]:
        with self._lock:
            rec = self._runs.get(run_id)
            if not rec:
                return []

        summaries: list[TowerReportSummary] = []
        for tower_id, tr in rec.tower_reports.items():
            findings_data = [
                {
                    "finding_id": f.finding_id,
                    "finding_type": f.finding_type,
                    "severity": f.severity.value,
                    "confidence": f.confidence,
                    "description": f.description,
                    "entity_refs": f.entity_refs,
                    "evidence_refs": f.evidence_refs,
                }
                for f in tr.findings
            ]
            hypotheses_data = [
                {
                    "hypothesis_id": h.hypothesis_id,
                    "fault_code": h.fault_code,
                    "confidence": h.confidence_score,
                    "confidence_category": h.confidence_category.value,
                    "rationale": h.rationale,
                    "suspected_entities": h.suspected_entities,
                    "supporting_finding_refs": h.supporting_finding_refs,
                    "contradicting_finding_refs": h.contradicting_finding_refs,
                }
                for h in tr.hypotheses
            ]
            summaries.append(TowerReportSummary(
                tower_id=tower_id.value,
                findings_count=len(tr.findings),
                hypotheses_count=len(tr.hypotheses),
                findings=findings_data,
                hypotheses=hypotheses_data,
            ))
        return summaries

    def get_run_tasks(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rec = self._runs.get(run_id)
            if not rec or not rec.repository:
                return []

        tasks = rec.repository.get_tasks(rec.incident_id)
        return [
            {
                "task_id": t.task_id,
                "incident_id": t.incident_id,
                "assigned_tower": t.assigned_tower.value,
                "task_type": t.task_type,
                "status": t.status.value,
                "priority": t.priority,
                "created_at": t.created_at.isoformat(),
                "description": t.description,
            }
            for t in tasks
        ]

    def get_run_report(self, run_id: str) -> FinalReport | None:
        with self._lock:
            rec = self._runs.get(run_id)
            if not rec:
                return None
            return rec.report

    def get_run_gate(self, run_id: str) -> GateResultDetail | None:
        with self._lock:
            rec = self._runs.get(run_id)
            if not rec or not rec.gate_result:
                return None
        gr = rec.gate_result
        return GateResultDetail(
            incident_id=rec.incident_id,
            outcome=gr.outcome.value if hasattr(gr.outcome, "value") else str(gr.outcome),
            passed=gr.passed,
            checks=[
                GateCheckResultModel(
                    check_name=c.check_name,
                    passed=c.passed,
                    message=c.message,
                    severity=c.severity,
                )
                for c in gr.checks
            ],
            errors=gr.errors,
            warnings=gr.warnings,
            limitations=gr.limitations,
            evaluated_at=gr.evaluated_at.isoformat() if getattr(gr, "evaluated_at", None) else None,
        )

    def get_run_evaluation(self, run_id: str) -> EvaluationResponse:
        with self._lock:
            rec = self._runs.get(run_id)
            if not rec:
                raise ValueError(f"Run '{run_id}' not found")
            if rec.status != "completed" or not rec.report:
                raise ValueError("Evaluation is strictly available only after diagnosis completes")

        if not rec.scenario_id:
            raise ValueError("Run was not executed from a known benchmark scenario with ground truth")

        gt_file = self.scenarios_dir / rec.scenario_id / "evaluation" / "ground_truth.json"
        if not gt_file.exists():
            raise ValueError(f"Ground truth file not found for scenario '{rec.scenario_id}'")

        gt = json.loads(gt_file.read_text(encoding="utf-8"))
        actual_fault = gt.get("injected_fault_class", "").upper()
        target_entity = gt.get("target_entity")
        intended_affected = gt.get("intended_affected_entities", [])

        # Match check
        if rec.report.status == "insufficient_evidence":
            predicted = "ABSTAIN"
        else:
            candidates = [rec.report.suspected_root_cause, *rec.report.concurrent_causes]
            predicted = "OTHER"
            for cand in candidates:
                if actual_fault in cand.upper():
                    predicted = actual_fault
                    break
                if "ABSTAIN" in cand.upper():
                    predicted = "ABSTAIN"
                    break

        class_match = (predicted == actual_fault) if actual_fault != "HEALTHY" else (predicted == "ABSTAIN")
        reported_affected = rec.report.affected_devices

        target_match = False
        if actual_fault == "HEALTHY" or (target_entity and target_entity in reported_affected):
            target_match = True

        expected_set = set(intended_affected)
        reported_set = set(reported_affected)
        tp = len(expected_set & reported_set)
        fp = len(reported_set - expected_set)
        fn = len(expected_set - reported_set)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0 if not expected_set else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0 if not expected_set else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        return EvaluationResponse(
            run_id=run_id,
            incident_id=rec.incident_id,
            scenario_id=rec.scenario_id,
            injected_fault_class=actual_fault,
            diagnosed_root_cause=rec.report.suspected_root_cause,
            class_match=class_match,
            target_entity=target_entity,
            target_match=target_match,
            intended_affected_entities=intended_affected,
            reported_affected_entities=reported_affected,
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1=round(f1, 4),
        )

    def _execute_run_worker(
        self,
        run_id: str,
        llm_mode: str = "off",
        symptom_chat: str | None = None,
        site: str | None = None,
    ) -> None:
        """Background thread executing diagnosis and emitting structured events."""
        with self._lock:
            rec = self._runs[run_id]
            rec.status = "running"
            rec.started_at = datetime.now(timezone.utc)
        self._persist_run(rec)

        def emit(event_type: str, component: str, status: str = "info", payload: dict[str, Any] | None = None, entity_refs: list[str] | None = None, evidence_refs: list[str] | None = None):
            event = ExecutionEventModel(
                event_id=str(uuid.uuid4()),
                run_id=run_id,
                incident_id=rec.incident_id,
                timestamp=datetime.now(timezone.utc),
                event_type=event_type,
                source_component=component,
                status=status,
                entity_refs=entity_refs or [],
                evidence_refs=evidence_refs or [],
                payload=payload or {},
            )
            event_sink.emit(event)

        try:
            emit("run.started", "runner", "running", {"scenario_id": rec.scenario_id, "target_path": str(rec.target_path)})

            # 1. Ingestion
            data_quality_warnings: list[str] = []
            project_root = Path(__file__).resolve().parents[2]
            network_profile = None
            topology_path = None
            if site:
                profile_candidates = [
                    project_root / "config" / "profiles" / f"{site}.yaml",
                    project_root / "config" / "profiles" / f"{site}.yml",
                ]
                profile_file = next((path for path in profile_candidates if path.is_file()), None)
                if profile_file:
                    network_profile = NetworkProfile.load(profile_file)
                    rec.entity_aliases = network_profile.aliases()
                else:
                    data_quality_warnings.append(
                        f"No profile registered for site {site}; using generic mappings. "
                        "Create a matching config/profiles profile to apply site-specific mappings."
                    )
                site_topology = project_root / "config" / "sites" / site / "topology.json"
                if site_topology.is_file() and not (rec.target_path / "topology.json").is_file():
                    topology_path = site_topology
            rec.topology_path = topology_path
            self._persist_run(rec)

            inc_id, observations = _load_observations_from_target(
                rec.target_path,
                incident_id=rec.incident_id,
                data_quality_warnings=data_quality_warnings,
                profile=network_profile,
                topology_path=topology_path,
            )
            rec.incident_id = inc_id
            rec.observations = observations
            if network_profile and network_profile.topology_completeness != "complete":
                data_quality_warnings.append(
                    f"Profile {network_profile.profile_id} marks topology "
                    f"{network_profile.topology_completeness}; missing links are not treated as proof of an outage."
                )

            emit("ingestion.completed", "ingestion", "completed", {
                "observation_count": len(observations),
                "warnings_count": len(data_quality_warnings),
            })

            # 2. Features
            pipeline = FeaturePipeline()
            features = pipeline.extract_features(observations, incident_id=inc_id)
            rec.features = features
            emit("features.computed", "feature_pipeline", "completed", {"features_count": len(features)})

            # 3. Setup SQLite repository
            repo = SQLiteRepository(rec.repository_path)
            rec.repository = repo

            # 4. Supervisor Runtime
            rules = load_rules()
            if network_profile:
                rules = network_profile.apply_to_rules(rules)
            fabric = IntegrationFabric(repository=repo, rules=rules)
            gate = EvidenceReleaseGate(repository=repo)
            rca_agent = SupervisoryRCAAgent(llm_mode=llm_mode)

            def explain_callback(stage: str, message: str):
                emit(f"workflow.{stage.replace(' ', '_')}", "supervisor", "info", {"stage": stage, "message": message})

            runtime = SupervisorRuntime(
                fabric=fabric,
                repository=repo,
                rca_agent=rca_agent,
                gate=gate,
                network_profile=(
                    {"profile_id": network_profile.profile_id, "version": network_profile.version}
                    if network_profile else None
                ),
                explain=explain_callback,
            )

            emit("towers.started", "fabric", "running", {"towers": ["Performance", "Infrastructure", "Connectivity", "Services"]})

            # Run incident
            report = runtime.run_incident(
                inc_id,
                observations,
                data_quality_warnings=data_quality_warnings,
            )
            rec.tower_reports = {tr.tower_id: tr for tr in repo.get_tower_reports(inc_id)}
            rec.gate_result = repo.get_gate_result(inc_id)

            for tower_id, tower_report in rec.tower_reports.items():
                emit("tower.completed", tower_id.value, "completed", {
                    "findings_count": len(tower_report.findings),
                    "hypotheses_count": len(tower_report.hypotheses),
                }, entity_refs=[entity for finding in tower_report.findings for entity in finding.entity_refs])

            gate_outcome = rec.gate_result.outcome.value if rec.gate_result else "UNKNOWN"
            emit("gate.check.completed", "evidence_gate", "completed", {
                "gate_outcome": gate_outcome,
                "passed": "PASS" in gate_outcome,
            })

            if site is not None:
                report = report.model_copy(update={"site_id": site})
                repo.insert_final_report(report)
            if symptom_chat is not None:
                emit(
                    "symptom_review.started",
                    "symptom_agent",
                    "running",
                    {"decision_loop_participant": False},
                )
                symptom_addendum = SymptomReasoningAgent(llm_mode=llm_mode).analyze(
                    symptom=symptom_chat,
                    report=report,
                    observations=observations,
                    tower_reports=list(rec.tower_reports.values())
                    or repo.get_tower_reports(inc_id),
                )
                report = report.model_copy(update={"symptom_reasoning": symptom_addendum})
                repo.insert_final_report(report)
                emit(
                    "symptom_review.completed",
                    "symptom_agent",
                    "completed",
                    {"status": symptom_addendum.status, "agent_mode": symptom_addendum.agent_mode},
                )
            rec.report = report

            emit("report.published", "supervisor", "completed", {
                "status": report.status,
                "suspected_root_cause": report.suspected_root_cause,
                "confidence": report.confidence,
                "affected_devices": report.affected_devices,
            })

            with self._lock:
                rec.status = "completed"
                rec.completed_at = datetime.now(timezone.utc)

            emit("run.completed", "runner", "completed", {"run_id": run_id, "incident_id": inc_id})

        except Exception as exc:
            logger.exception(f"Run {run_id} failed: {exc}")
            with self._lock:
                rec.status = "failed"
                rec.completed_at = datetime.now(timezone.utc)
                rec.error = str(exc)
            emit("run.failed", "runner", "error", {"error": str(exc)})
        finally:
            event_sink.close_run(run_id, status=rec.status)
            self._persist_run(rec)


# Global singleton run manager
run_manager = RunManager()
