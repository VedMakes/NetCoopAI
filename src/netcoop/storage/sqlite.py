"""SQLite persistence repository for NetCoop AI.

Provides single-database storage for incidents, canonical observations, findings,
hypotheses, tower reports, events (with outbox tracking), peer queries, tasks,
task results, and final reports.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from netcoop.communication.events import EventEnvelope
from netcoop.communication.queries import PeerQuery, PeerQueryResult
from netcoop.communication.tasks import InvestigationTask, TaskResult
from netcoop.models.enums import TaskStatus, TowerId
from netcoop.models.findings import Finding
from netcoop.models.hypotheses import Hypothesis
from netcoop.models.observations import (
    CanonicalObservation,
    ConfigObservation,
    LogObservation,
    MetricObservation,
    TopologyObservation,
)
from netcoop.models.reports import FinalReport, TowerReport

SCHEMA_VERSION = 1

INIT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    observation_type TEXT NOT NULL,
    source TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_incident ON observations(incident_id);
CREATE INDEX IF NOT EXISTS idx_obs_entity ON observations(entity_id);

CREATE TABLE IF NOT EXISTS findings (
    finding_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    source_tower TEXT NOT NULL,
    producer TEXT NOT NULL,
    finding_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL NOT NULL,
    observed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    supersedes_finding_id TEXT,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_incident ON findings(incident_id);
CREATE INDEX IF NOT EXISTS idx_findings_tower ON findings(source_tower);

CREATE TABLE IF NOT EXISTS hypotheses (
    hypothesis_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    fault_code TEXT NOT NULL,
    confidence_score REAL NOT NULL,
    confidence_category TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hypotheses_incident ON hypotheses(incident_id);

CREATE TABLE IF NOT EXISTS tower_reports (
    report_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    tower_id TEXT NOT NULL,
    status TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tower_reports_incident ON tower_reports(incident_id);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    specversion TEXT NOT NULL,
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    subject TEXT,
    time TEXT NOT NULL,
    correlationid TEXT NOT NULL,
    causationid TEXT,
    dataschema TEXT NOT NULL,
    data_json TEXT NOT NULL,
    outbox_dispatched INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_corr ON events(correlationid);
CREATE INDEX IF NOT EXISTS idx_events_outbox ON events(outbox_dispatched);

CREATE TABLE IF NOT EXISTS peer_queries (
    query_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    requester TEXT NOT NULL,
    recipient TEXT NOT NULL,
    capability TEXT NOT NULL,
    status TEXT NOT NULL,
    query_json TEXT NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_queries_incident ON peer_queries(incident_id);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    parent_task_id TEXT,
    requester TEXT NOT NULL,
    assignee TEXT NOT NULL,
    capability TEXT NOT NULL,
    status TEXT NOT NULL,
    counter_proposal_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    task_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_incident ON tasks(incident_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

CREATE TABLE IF NOT EXISTS task_results (
    result_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    assignee TEXT NOT NULL,
    status TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_results_task ON task_results(task_id);

CREATE TABLE IF NOT EXISTS final_reports (
    incident_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    suspected_root_cause TEXT NOT NULL,
    confidence REAL NOT NULL,
    generated_at TEXT NOT NULL,
    report_json TEXT NOT NULL
);
"""


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteRepository:
    """Manages transactional SQLite storage for NetCoop AI."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self._is_memory = (self.db_path == ":memory:")
        # For in-memory database, hold one persistent connection so tables survive between calls
        self._mem_conn: sqlite3.Connection | None = None
        if self._is_memory:
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
            self._mem_conn.execute("PRAGMA foreign_keys = ON;")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_memory and self._mem_conn is not None:
            return self._mem_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Enable foreign keys and WAL mode if on disk
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if not self._is_memory:
                conn.close()

    def _init_db(self) -> None:
        with self.transaction() as conn:
            conn.executescript(INIT_SCHEMA_SQL)
            cur = conn.cursor()
            cur.execute("SELECT version FROM schema_version WHERE version = ?", (SCHEMA_VERSION,))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, _iso_now()),
                )

    def get_schema_version(self) -> int:
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT MAX(version) as ver FROM schema_version")
            row = cur.fetchone()
            return int(row["ver"]) if row and row["ver"] is not None else 0

    # ---------------- Incidents ----------------
    def record_incident(self, incident_id: str, status: str = "active", description: str = "") -> None:
        now = _iso_now()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO incidents (incident_id, status, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    status=excluded.status,
                    description=excluded.description,
                    updated_at=excluded.updated_at
                """,
                (incident_id, status, description, now, now),
            )

    # ---------------- Observations ----------------
    def insert_observation(self, observation: CanonicalObservation) -> None:
        obs_dict = observation.model_dump(mode="json")
        now = _iso_now()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO observations
                (observation_id, incident_id, observation_type, source, entity_id, timestamp, data_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.observation_id,
                    observation.incident_id,
                    observation.observation_type,
                    observation.source,
                    observation.entity_id,
                    observation.timestamp.isoformat(),
                    json.dumps(obs_dict),
                    now,
                ),
            )

    def get_observations(self, incident_id: str) -> list[CanonicalObservation]:
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT observation_type, data_json FROM observations WHERE incident_id = ? ORDER BY timestamp ASC",
                (incident_id,),
            )
            rows = cur.fetchall()

        results: list[CanonicalObservation] = []
        for row in rows:
            obs_type = row["observation_type"]
            data = json.loads(row["data_json"])
            if obs_type == "metric":
                results.append(MetricObservation.model_validate(data))
            elif obs_type == "log":
                results.append(LogObservation.model_validate(data))
            elif obs_type == "topology":
                results.append(TopologyObservation.model_validate(data))
            elif obs_type == "config":
                results.append(ConfigObservation.model_validate(data))
        return results

    # ---------------- Findings ----------------
    def insert_finding(self, finding: Finding) -> None:
        data = finding.model_dump(mode="json")
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO findings
                (finding_id, incident_id, source_tower, producer, finding_type, severity,
                 status, confidence, observed_at, created_at, supersedes_finding_id, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    finding.finding_id,
                    finding.incident_id,
                    finding.source_tower.value,
                    finding.producer,
                    finding.finding_type,
                    finding.severity.value,
                    finding.status.value,
                    finding.confidence,
                    finding.observed_at.isoformat(),
                    finding.created_at.isoformat(),
                    finding.supersedes_finding_id,
                    json.dumps(data),
                ),
            )

    def get_findings(self, incident_id: str, tower_id: TowerId | None = None) -> list[Finding]:
        query = "SELECT payload_json FROM findings WHERE incident_id = ?"
        params: list[Any] = [incident_id]
        if tower_id is not None:
            query += " AND source_tower = ?"
            params.append(tower_id.value)
        query += " ORDER BY created_at ASC"

        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()

        return [Finding.model_validate(json.loads(r["payload_json"])) for r in rows]

    def get_finding_by_id(self, finding_id: str) -> Finding | None:
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT payload_json FROM findings WHERE finding_id = ?", (finding_id,))
            row = cur.fetchone()
            if row:
                return Finding.model_validate(json.loads(row["payload_json"]))
        return None

    # ---------------- Hypotheses ----------------
    def insert_hypothesis(self, hypothesis: Hypothesis) -> None:
        data = hypothesis.model_dump(mode="json")
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO hypotheses
                (hypothesis_id, incident_id, fault_code, confidence_score, confidence_category,
                 status, created_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hypothesis.hypothesis_id,
                    hypothesis.incident_id,
                    hypothesis.fault_code,
                    hypothesis.confidence_score,
                    hypothesis.confidence_category.value,
                    hypothesis.status,
                    hypothesis.created_at.isoformat(),
                    json.dumps(data),
                ),
            )

    def get_hypotheses(self, incident_id: str) -> list[Hypothesis]:
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT payload_json FROM hypotheses WHERE incident_id = ? ORDER BY confidence_score DESC",
                (incident_id,),
            )
            rows = cur.fetchall()
        return [Hypothesis.model_validate(json.loads(r["payload_json"])) for r in rows]

    # ---------------- Tower Reports ----------------
    def insert_tower_report(self, report: TowerReport) -> None:
        data = report.model_dump(mode="json")
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO tower_reports (report_id, incident_id, tower_id, status, generated_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_id) DO UPDATE SET
                    status=excluded.status,
                    payload_json=excluded.payload_json
                """,
                (
                    report.report_id,
                    report.incident_id,
                    report.tower_id.value,
                    report.status,
                    report.generated_at.isoformat(),
                    json.dumps(data),
                ),
            )

    def get_tower_reports(self, incident_id: str) -> list[TowerReport]:
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT payload_json FROM tower_reports WHERE incident_id = ? ORDER BY generated_at ASC",
                (incident_id,),
            )
            rows = cur.fetchall()
        return [TowerReport.model_validate(json.loads(r["payload_json"])) for r in rows]

    # ---------------- Events & Outbox ----------------
    def insert_event(self, event: EventEnvelope, dispatched: bool = False) -> None:
        now = _iso_now()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO events
                (id, specversion, source, type, subject, time, correlationid,
                 causationid, dataschema, data_json, outbox_dispatched, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.specversion,
                    event.source,
                    event.type,
                    event.subject,
                    event.time.isoformat(),
                    event.correlationid,
                    event.causationid,
                    event.dataschema,
                    json.dumps(event.data),
                    1 if dispatched else 0,
                    now,
                ),
            )

    def get_events(self, correlationid: str) -> list[EventEnvelope]:
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, specversion, source, type, subject, time,
                       correlationid, causationid, dataschema, data_json
                FROM events WHERE correlationid = ? ORDER BY time ASC
                """,
                (correlationid,),
            )
            rows = cur.fetchall()

        events: list[EventEnvelope] = []
        for r in rows:
            events.append(
                EventEnvelope(
                    specversion=r["specversion"],
                    id=r["id"],
                    source=r["source"],
                    type=r["type"],
                    subject=r["subject"],
                    time=datetime.fromisoformat(r["time"]),
                    correlationid=r["correlationid"],
                    causationid=r["causationid"],
                    dataschema=r["dataschema"],
                    data=json.loads(r["data_json"]),
                )
            )
        return events

    def get_pending_outbox_events(self, limit: int = 100) -> list[EventEnvelope]:
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, specversion, source, type, subject, time,
                       correlationid, causationid, dataschema, data_json
                FROM events WHERE outbox_dispatched = 0 ORDER BY time ASC LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()

        return [
            EventEnvelope(
                specversion=r["specversion"],
                id=r["id"],
                source=r["source"],
                type=r["type"],
                subject=r["subject"],
                time=datetime.fromisoformat(r["time"]),
                correlationid=r["correlationid"],
                causationid=r["causationid"],
                dataschema=r["dataschema"],
                data=json.loads(r["data_json"]),
            )
            for r in rows
        ]

    def mark_event_dispatched(self, event_id: str) -> None:
        with self.transaction() as conn:
            conn.execute("UPDATE events SET outbox_dispatched = 1 WHERE id = ?", (event_id,))

    # ---------------- Peer Queries ----------------
    def insert_peer_query(self, query: PeerQuery) -> None:
        data = query.model_dump(mode="json")
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO peer_queries
                (query_id, incident_id, requester, recipient, capability, status, query_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    query.query_id,
                    query.incident_id,
                    query.requester,
                    query.recipient,
                    query.capability,
                    "pending",
                    json.dumps(data),
                    query.created_at.isoformat(),
                ),
            )

    def update_peer_query_result(self, result: PeerQueryResult) -> None:
        data = result.model_dump(mode="json")
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE peer_queries
                SET status = ?, result_json = ?, completed_at = ?
                WHERE query_id = ?
                """,
                (
                    result.status.value,
                    json.dumps(data),
                    result.completed_at.isoformat(),
                    result.query_id,
                ),
            )

    # ---------------- Tasks ----------------
    def insert_task(self, task: InvestigationTask) -> None:
        data = task.model_dump(mode="json")
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO tasks
                (task_id, incident_id, parent_task_id, requester, assignee, capability,
                 status, counter_proposal_count, created_at, updated_at, task_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.incident_id,
                    task.parent_task_id,
                    task.requester,
                    task.assignee.value,
                    task.capability,
                    task.status.value,
                    task.counter_proposal_count,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                    json.dumps(data),
                ),
            )

    def update_task_status(
        self,
        task_id: str,
        new_status: TaskStatus,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> InvestigationTask:
        task = self.get_task_by_id(task_id)
        if not task:
            raise ValueError(f"Task with ID '{task_id}' not found.")

        updated_task = task.transition_to(new_status)
        if error_code or error_detail:
            updated_task = updated_task.model_copy(
                update={"error_code": error_code, "error_detail": error_detail}
            )

        data = updated_task.model_dump(mode="json")
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, counter_proposal_count = ?, updated_at = ?, task_json = ?
                WHERE task_id = ?
                """,
                (
                    updated_task.status.value,
                    updated_task.counter_proposal_count,
                    updated_task.updated_at.isoformat(),
                    json.dumps(data),
                    task_id,
                ),
            )
        return updated_task

    def get_task_by_id(self, task_id: str) -> InvestigationTask | None:
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT task_json FROM tasks WHERE task_id = ?", (task_id,))
            row = cur.fetchone()
            if row:
                return InvestigationTask.model_validate(json.loads(row["task_json"]))
        return None

    def get_tasks(self, incident_id: str) -> list[InvestigationTask]:
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT task_json FROM tasks WHERE incident_id = ? ORDER BY created_at ASC",
                (incident_id,),
            )
            rows = cur.fetchall()
        return [InvestigationTask.model_validate(json.loads(r["task_json"])) for r in rows]

    # ---------------- Task Results ----------------
    def insert_task_result(self, result: TaskResult) -> None:
        data = result.model_dump(mode="json")
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO task_results (result_id, task_id, assignee, status, completed_at, result_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    result.result_id,
                    result.task_id,
                    result.assignee.value,
                    result.status.value,
                    result.completed_at.isoformat(),
                    json.dumps(data),
                ),
            )

    def get_task_result(self, task_id: str) -> TaskResult | None:
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT result_json FROM task_results WHERE task_id = ?", (task_id,))
            row = cur.fetchone()
            if row:
                return TaskResult.model_validate(json.loads(row["result_json"]))
        return None

    # ---------------- Final Reports ----------------
    def insert_final_report(self, report: FinalReport) -> None:
        data = report.model_dump(mode="json")
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO final_reports
                (incident_id, status, suspected_root_cause, confidence, generated_at, report_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    status=excluded.status,
                    suspected_root_cause=excluded.suspected_root_cause,
                    confidence=excluded.confidence,
                    generated_at=excluded.generated_at,
                    report_json=excluded.report_json
                """,
                (
                    report.incident_id,
                    report.status,
                    report.suspected_root_cause,
                    report.confidence,
                    report.generated_at.isoformat(),
                    json.dumps(data),
                ),
            )

    def get_final_report(self, incident_id: str) -> FinalReport | None:
        with self.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT report_json FROM final_reports WHERE incident_id = ?", (incident_id,)
            )
            row = cur.fetchone()
            if row:
                return FinalReport.model_validate(json.loads(row["report_json"]))
        return None
