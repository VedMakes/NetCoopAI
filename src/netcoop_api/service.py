"""Application service coordinator managing scenarios, runs, and incident artifacts."""

from __future__ import annotations

import json
import logging
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
from netcoop_api.events import event_sink
from netcoop_api.schemas import (
    DerivedFeatureModel,
    EvaluationResponse,
    ExecutionEventModel,
    RunCreateRequest,
    RunStatusResponse,
    ScenarioDetail,
    ScenarioSummary,
    TelemetryObservationModel,
    TelemetryResponse,
    TopologyGraph,
    TopologyLink,
    TopologyNode,
    TowerReportSummary,
)

logger = logging.getLogger(__name__)

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
    def __init__(self, run_id: str, incident_id: str, scenario_id: str | None, target_path: Path):
        self.run_id = run_id
        self.incident_id = incident_id
        self.scenario_id = scenario_id
        self.target_path = target_path
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


class RunManager:
    """Coordinates benchmark scenarios, runs, and artifacts."""

    def __init__(self, scenarios_dir: Path | None = None):
        self.scenarios_dir = scenarios_dir or Path("fixtures/scenarios")
        self._runs: dict[str, RunRecord] = {}
        self._lock = threading.Lock()

    def list_scenarios(self) -> list[ScenarioSummary]:
        results: list[ScenarioSummary] = []
        if not self.scenarios_dir.exists():
            return results

        for p in sorted(self.scenarios_dir.iterdir()):
            if p.is_dir() and (p / "telemetry.jsonl").exists():
                meta = SCENARIO_CATALOG_META.get(p.name, {
                    "name": p.name.replace("_", " ").title(),
                    "category": "Synthetic",
                    "description": f"Synthetic scenario for {p.name}",
                    "symptoms": "Network telemetry anomaly capture",
                })
                results.append(ScenarioSummary(
                    scenario_id=p.name,
                    name=meta["name"],
                    category=meta["category"],
                    description=meta["description"],
                    fixture_path=str(p),
                    symptoms_summary=meta["symptoms"],
                ))
        return results

    def get_scenario(self, scenario_id: str) -> ScenarioDetail | None:
        scenario_path = self.scenarios_dir / scenario_id
        if not scenario_path.is_dir():
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
        scenario_path = self.scenarios_dir / scenario_id
        if not scenario_path.is_dir():
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

        if req.scenario_id:
            scenario_path = self.scenarios_dir / req.scenario_id
            if not scenario_path.is_dir():
                raise ValueError(f"Scenario '{req.scenario_id}' not found in {self.scenarios_dir}")
            target_path = scenario_path
        elif req.target_path:
            target_path = Path(req.target_path)
            if not target_path.exists():
                raise ValueError(f"Target path '{req.target_path}' does not exist")
        else:
            raise ValueError("Either scenario_id or target_path must be provided")

        incident_id = req.incident_id or f"INC-{req.scenario_id or 'CUSTOM'}-{uuid.uuid4().hex[:6]}"

        record = RunRecord(
            run_id=run_id,
            incident_id=incident_id,
            scenario_id=req.scenario_id,
            target_path=target_path,
        )

        with self._lock:
            self._runs[run_id] = record

        # Start execution in background thread
        thread = threading.Thread(
            target=self._execute_run_worker,
            args=(run_id, req.llm, req.symptom, req.site),
            daemon=True,
        )
        thread.start()

        return RunStatusResponse(
            run_id=run_id,
            incident_id=incident_id,
            scenario_id=req.scenario_id,
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
                scenario_id=rec.scenario_id,
                status=rec.status,
                created_at=rec.created_at,
                started_at=rec.started_at,
                completed_at=rec.completed_at,
                error=rec.error,
            )

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
            # Fallback: extract from topology observations
            nodes_dict: dict[str, TopologyNode] = {}
            links_list: list[TopologyLink] = []
            for obs in rec.observations:
                if isinstance(obs, TopologyObservation):
                    if obs.source_entity not in nodes_dict:
                        nodes_dict[obs.source_entity] = TopologyNode(
                            id=obs.source_entity, name=obs.source_entity, role="device"
                        )
                    if obs.target_entity not in nodes_dict:
                        nodes_dict[obs.target_entity] = TopologyNode(
                            id=obs.target_entity, name=obs.target_entity, role="device"
                        )
                    links_list.append(TopologyLink(
                        id=obs.observation_id,
                        source=obs.source_entity,
                        target=obs.target_entity,
                        relationship=obs.relationship_type,
                    ))
            graph = TopologyGraph(
                topology_id=rec.incident_id,
                nodes=list(nodes_dict.values()),
                links=links_list,
            )

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
                if node.id.upper() in root_cause_text:
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
        symptom: str | None = None,
        site: str | None = None,
    ) -> None:
        """Background thread executing diagnosis and emitting structured events."""
        with self._lock:
            rec = self._runs[run_id]
            rec.status = "running"
            rec.started_at = datetime.now(timezone.utc)

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
            inc_id, observations = _load_observations_from_target(
                rec.target_path,
                incident_id=rec.incident_id,
                data_quality_warnings=data_quality_warnings,
            )
            rec.observations = observations

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
            repo = SQLiteRepository(":memory:")
            rec.repository = repo

            # 4. Supervisor Runtime
            fabric = IntegrationFabric(repository=repo, rules=load_rules())
            gate = EvidenceReleaseGate(repository=repo)
            rca_agent = SupervisoryRCAAgent(llm_mode=llm_mode)

            def explain_callback(stage: str, message: str):
                emit(f"workflow.{stage.replace(' ', '_')}", "supervisor", "info", {"stage": stage, "message": message})

            runtime = SupervisorRuntime(
                fabric=fabric,
                repository=repo,
                rca_agent=rca_agent,
                gate=gate,
                explain=explain_callback,
            )

            emit("towers.started", "fabric", "running", {"towers": ["Performance", "Infrastructure", "Connectivity", "Services"]})

            # Run incident
            report = runtime.run_incident(
                inc_id,
                observations,
                symptom=symptom or "",
                data_quality_warnings=data_quality_warnings,
            )
            rec.report = report
            rec.tower_reports = {tr.tower_id: tr for tr in repo.get_tower_reports(inc_id)}
            rec.gate_result = repo.get_gate_result(inc_id)

            # Emit tower completion events
            for tower_id, tr in rec.tower_reports.items():
                emit("tower.completed", tower_id.value, "completed", {
                    "findings_count": len(tr.findings),
                    "hypotheses_count": len(tr.hypotheses),
                }, entity_refs=[e for f in tr.findings for e in f.entity_refs])

            gate_outcome = rec.gate_result.outcome.value if rec.gate_result else "UNKNOWN"
            emit("gate.check.completed", "evidence_gate", "completed", {
                "gate_outcome": gate_outcome,
                "passed": "PASS" in gate_outcome,
            })

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
            event_sink.close_run(run_id)


# Global singleton run manager
run_manager = RunManager()
