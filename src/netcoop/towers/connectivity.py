"""Deterministic diagnostic engine and controller for the Connectivity Tower.

Builds and manages an in-memory NetworkX network topology graph.
Performs reachability pathing, common upstream dependency analysis, neighbor discovery,
and blast radius assessment. Emits validated Finding and Hypothesis models with provenance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import networkx as nx

from netcoop.communication.queries import PeerQuery, PeerQueryResult
from netcoop.communication.registry import CapabilityRegistry, TowerCapability
from netcoop.communication.tasks import InvestigationTask, TaskResult
from netcoop.models.enums import (
    ConfidenceCategory,
    FindingStatus,
    QueryStatus,
    Severity,
    TaskStatus,
    TowerId,
)
from netcoop.models.findings import Finding
from netcoop.models.hypotheses import Hypothesis
from netcoop.models.observations import (
    CanonicalObservation,
    MetricObservation,
    TopologyObservation,
)
from netcoop.models.reports import TowerReport
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.towers.rules import load_rules
from netcoop.utils.id_generator import generate_id


class TopologyGraph:
    """Manages an in-memory NetworkX topology graph for campus connectivity."""

    def __init__(self) -> None:
        self.graph: nx.Graph = nx.Graph()
        self.observation_map: dict[tuple[str, str], str] = {}  # (u, v) -> observation_id

    def add_node(self, node_id: str, **attrs: Any) -> None:
        self.graph.add_node(node_id, **attrs)

    def add_link(
        self,
        source: str,
        target: str,
        relationship: str = "connected_to",
        speed_mbps: float | None = None,
        interface_name: str | None = None,
        observation_id: str | None = None,
        **extra: Any,
    ) -> None:
        self.graph.add_edge(
            source,
            target,
            relationship=relationship,
            link_speed_mbps=speed_mbps,
            interface_name=interface_name,
            observation_id=observation_id,
            **extra,
        )
        if observation_id:
            self.observation_map[(source, target)] = observation_id
            self.observation_map[(target, source)] = observation_id

    def build_from_observations(self, observations: list[CanonicalObservation]) -> None:
        """Constructs graph from canonical TopologyObservations."""
        for obs in observations:
            if isinstance(obs, TopologyObservation):
                self.add_node(obs.source_entity)
                self.add_node(obs.target_entity)
                self.add_link(
                    source=obs.source_entity,
                    target=obs.target_entity,
                    relationship=obs.relationship_type,
                    speed_mbps=obs.link_speed_mbps,
                    interface_name=obs.interface_name,
                    observation_id=obs.observation_id,
                )

    def trace_path(self, source: str, target: str) -> dict[str, Any]:
        """Calculates topological path between two entities without fabricating missing links."""
        if source not in self.graph or target not in self.graph:
            missing = [e for e in (source, target) if e not in self.graph]
            return {
                "reachable": False,
                "path": [],
                "hops": -1,
                "warning": f"Entity/entities not found in topology graph: {missing}. Refusing to fabricate path.",
            }

        if nx.has_path(self.graph, source, target):
            path = nx.shortest_path(self.graph, source, target)
            links = []
            obs_ids = []
            for i in range(len(path) - 1):
                edge_data = self.graph.get_edge_data(path[i], path[i + 1]) or {}
                links.append({
                    "from": path[i],
                    "to": path[i + 1],
                    "interface": edge_data.get("interface_name"),
                    "speed_mbps": edge_data.get("link_speed_mbps"),
                })
                obs_id = edge_data.get("observation_id")
                if obs_id:
                    obs_ids.append(obs_id)

            return {
                "reachable": True,
                "path": path,
                "hops": len(path) - 1,
                "link_details": links,
                "evidence_refs": obs_ids,
            }

        return {
            "reachable": False,
            "path": [],
            "hops": -1,
            "warning": f"No topological path connects '{source}' and '{target}'.",
        }

    def query_neighbors(self, entity_id: str) -> list[dict[str, Any]]:
        """Returns adjacent entities and link parameters."""
        if entity_id not in self.graph:
            return []

        neighbors: list[dict[str, Any]] = []
        for nbr in self.graph.neighbors(entity_id):
            edge_data = self.graph.get_edge_data(entity_id, nbr) or {}
            neighbors.append({
                "neighbor_id": nbr,
                "relationship": edge_data.get("relationship", "connected_to"),
                "speed_mbps": edge_data.get("link_speed_mbps"),
                "interface_name": edge_data.get("interface_name"),
                "observation_id": edge_data.get("observation_id"),
            })
        return neighbors

    def find_common_uplink(
        self,
        entities: list[str],
        core_targets: tuple[str, ...] = ("GW_EDGE_01", "SW_CORE_01"),
    ) -> dict[str, Any]:
        """Finds shared upstream dependency (e.g. common distribution or core switch) for affected entities."""
        valid_entities = [e for e in entities if e in self.graph]
        if len(valid_entities) < 2:
            return {
                "common_uplink": None,
                "uplinks": [],
                "reason": "At least two valid entities are required to determine a common upstream dependency.",
            }

        target = next((c for c in core_targets if c in self.graph), None)
        if not target:
            # Fallback to node with highest degree
            target = max(self.graph.nodes, key=lambda n: self.graph.degree(n))

        upstream_paths: dict[str, list[str]] = {}
        for entity in valid_entities:
            if entity == target:
                continue
            if nx.has_path(self.graph, entity, target):
                upstream_paths[entity] = nx.shortest_path(self.graph, entity, target)

        if len(upstream_paths) < 2:
            return {
                "common_uplink": None,
                "uplinks": [],
                "reason": "Not enough entities have reachability to upstream backbone.",
            }

        # Intersect all nodes in the upstream paths except the entities themselves
        common_nodes = set.intersection(
            *[set(p) for p in upstream_paths.values()]
        )

        if not common_nodes:
            return {"common_uplink": None, "uplinks": [], "reason": "No common upstream node found."}

        # Sort common nodes by topological distance to entities (closest first)
        def min_distance(node: str) -> int:
            return min(p.index(node) for p in upstream_paths.values() if node in p)

        ordered_common = sorted(common_nodes, key=min_distance)
        closest_uplink = ordered_common[0]

        return {
            "common_uplink": closest_uplink,
            "all_common_nodes": ordered_common,
            "upstream_paths": upstream_paths,
        }

    def analyze_blast_radius(
        self, failed_entity: str, backbone_entity: str = "SW_CORE_01"
    ) -> dict[str, Any]:
        """Calculates which entities lose reachability to the backbone if failed_entity is disconnected."""
        if failed_entity not in self.graph:
            return {
                "failed_entity": failed_entity,
                "isolated_entities": [],
                "total_isolated": 0,
                "warning": f"Entity '{failed_entity}' not in topology graph.",
            }

        target = backbone_entity if backbone_entity in self.graph else None
        if not target:
            # Pick highest degree node as representative backbone
            target = max(self.graph.nodes, key=lambda n: self.graph.degree(n))

        if failed_entity == target:
            isolated = [n for n in self.graph.nodes if n != target]
            return {
                "failed_entity": failed_entity,
                "isolated_entities": isolated,
                "total_isolated": len(isolated),
                "is_backbone_failure": True,
            }

        # Create simulated subgraph without failed_entity
        subgraph = self.graph.copy()
        subgraph.remove_node(failed_entity)

        isolated = []
        for node in subgraph.nodes:
            if not nx.has_path(subgraph, node, target):
                isolated.append(node)

        return {
            "failed_entity": failed_entity,
            "isolated_entities": isolated,
            "total_isolated": len(isolated),
            "is_backbone_failure": False,
        }


class ConnectivityEngine:
    """Deterministic analyzer for network topology, reachability, and shared dependency correlation."""

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self.rules = (rules or load_rules()).get("connectivity", {})

    def analyze(
        self,
        incident_id: str,
        observations: list[CanonicalObservation],
        topology: TopologyGraph | None = None,
    ) -> tuple[list[Finding], list[Hypothesis], TopologyGraph]:
        """Analyzes topology observations and correlates affected entities."""
        findings: list[Finding] = []
        hypotheses: list[Hypothesis] = []

        topo = topology or TopologyGraph()
        topo.build_from_observations(observations)

        if topo.graph.number_of_nodes() == 0:
            return findings, hypotheses, topo

        now = datetime.now(timezone.utc)

        # 1. Check for disconnected components in topology
        connected_components = list(nx.connected_components(topo.graph))
        if len(connected_components) > 1:
            # Partitioned network topology detected
            evidence_obs = [
                o.observation_id
                for o in observations
                if isinstance(o, TopologyObservation)
            ]
            f_id = generate_id("F-CONN")
            part_entities = [item for comp in connected_components for item in comp]

            findings.append(
                Finding(
                    finding_id=f_id,
                    incident_id=incident_id,
                    source_tower=TowerId.CONNECTIVITY,
                    producer="connectivity.analyze_partitions",
                    finding_type="path_interruption",
                    severity=Severity.HIGH,
                    status=FindingStatus.ACTIVE,
                    entity_refs=part_entities[:5],
                    evidence_refs=evidence_obs if evidence_obs else ["TOPO-DEFAULT"],
                    confidence=0.85,
                    independence_group="topology:reachability:partition",
                    observed_at=now,
                    created_at=now,
                    description=(
                        f"Network topology is partitioned into {len(connected_components)} disconnected components. "
                        f"Isolated segments: {[list(c)[:3] for c in connected_components]}"
                    ),
                    metadata={"component_count": len(connected_components)},
                )
            )

            h_id = generate_id("HYP-CONN")
            hypotheses.append(
                Hypothesis(
                    hypothesis_id=h_id,
                    incident_id=incident_id,
                    fault_code="ROUTING_FAILURE",
                    suspected_entities=part_entities[:5],
                    supporting_finding_refs=[f_id],
                    confidence_score=0.85,
                    confidence_category=ConfidenceCategory.HIGH,
                    rationale=f"Topology analysis detected {len(connected_components)} partitioned segments without transit paths.",
                    created_at=now,
                )
            )

        # 2. Check for affected devices with high packet loss or errors and analyze common upstream dependency
        degraded_entities: list[str] = []
        degraded_obs_ids: list[str] = []
        for o in observations:
            if isinstance(o, MetricObservation):
                if o.metric_name == "packet_loss_pct" and o.value >= 5.0:
                    degraded_entities.append(o.entity_id)
                    degraded_obs_ids.append(o.observation_id)

        degraded_entities = list(dict.fromkeys(degraded_entities))
        if len(degraded_entities) >= 2:
            uplink_info = topo.find_common_uplink(degraded_entities)
            common_uplink = uplink_info.get("common_uplink")
            if common_uplink:
                f_id = generate_id("F-CONN")
                findings.append(
                    Finding(
                        finding_id=f_id,
                        incident_id=incident_id,
                        source_tower=TowerId.CONNECTIVITY,
                        producer="connectivity.find_common_uplink",
                        finding_type="uplink_saturation",
                        severity=Severity.MEDIUM,
                        status=FindingStatus.ACTIVE,
                        entity_refs=[common_uplink] + degraded_entities,
                        evidence_refs=degraded_obs_ids if degraded_obs_ids else ["OBS-CONN-MULTI"],
                        confidence=0.78,
                        independence_group=f"topology:common_uplink:{common_uplink}",
                        observed_at=now,
                        created_at=now,
                        description=(
                            f"Identified shared upstream dependency '{common_uplink}' for affected endpoints "
                            f"{degraded_entities}. Indicates potential shared choke point or transit degradation."
                        ),
                        metadata={"common_uplink": common_uplink, "affected_endpoints": degraded_entities},
                    )
                )

        return findings, hypotheses, topo


class ConnectivityTower:
    """Controller implementing TowerController for Connectivity and Topology domain."""

    def __init__(
        self,
        repository: SQLiteRepository | None = None,
        rules: dict[str, Any] | None = None,
        topology_graph: TopologyGraph | None = None,
    ) -> None:
        self.tower_id = TowerId.CONNECTIVITY
        self.repository = repository
        self.rules = rules or load_rules()
        self.engine = ConnectivityEngine(self.rules)
        self.topology = topology_graph or TopologyGraph()

    def get_capabilities(self) -> list[TowerCapability]:
        profile = CapabilityRegistry.get_profile(self.tower_id)
        return profile.capabilities if profile else []

    def analyze_incident(
        self,
        incident_id: str,
        observations: list[CanonicalObservation] | None = None,
    ) -> TowerReport:
        """Runs connectivity diagnostic pipeline, returns and optionally stores TowerReport."""
        obs = observations or []
        if not obs and self.repository:
            obs = self.repository.get_observations(incident_id)

        findings, hypotheses, self.topology = self.engine.analyze(incident_id, obs, self.topology)

        if self.repository:
            for f in findings:
                self.repository.insert_finding(f)
            for h in hypotheses:
                self.repository.insert_hypothesis(h)

        report_id = generate_id("REP-CONN")
        now = datetime.now(timezone.utc)
        summary = (
            f"Connectivity analysis completed for {incident_id}: "
            f"{len(findings)} finding(s), {len(hypotheses)} hypothesis(es) derived from "
            f"{self.topology.graph.number_of_nodes()} topology nodes and {self.topology.graph.number_of_edges()} links."
        )

        report = TowerReport(
            report_id=report_id,
            incident_id=incident_id,
            tower_id=self.tower_id,
            status="completed" if findings or self.topology.graph.number_of_nodes() > 0 else "inconclusive",
            findings=findings,
            hypotheses=hypotheses,
            summary=summary,
            generated_at=now,
        )

        if self.repository:
            self.repository.insert_tower_report(report)

        return report

    def handle_query(self, query: PeerQuery) -> PeerQueryResult:
        """Handles synchronous one-hop read-only peer queries for topology inspection."""
        cap = query.capability
        now = datetime.now(timezone.utc)

        if cap == "connectivity.trace_path":
            if len(query.scope) < 2:
                return PeerQueryResult(
                    query_id=query.query_id,
                    status=QueryStatus.INVALID_SCOPE,
                    warnings=["connectivity.trace_path requires at least 2 entities [source, target]"],
                    completed_at=now,
                )
            src, dst = query.scope[0], query.scope[1]
            res = self.topology.trace_path(src, dst)
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.COMPLETED,
                result=res,
                evidence_refs=res.get("evidence_refs", []),
                completed_at=now,
            )

        elif cap == "connectivity.find_common_uplink":
            if len(query.scope) < 2:
                return PeerQueryResult(
                    query_id=query.query_id,
                    status=QueryStatus.INVALID_SCOPE,
                    warnings=["connectivity.find_common_uplink requires at least 2 entities in scope"],
                    completed_at=now,
                )
            res = self.topology.find_common_uplink(query.scope)
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.COMPLETED,
                result=res,
                completed_at=now,
            )

        elif cap == "connectivity.query_neighbors":
            entity = query.scope[0] if query.scope else ""
            res = self.topology.query_neighbors(entity)
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.COMPLETED,
                result={"entity_id": entity, "neighbors": res},
                completed_at=now,
            )

        elif cap == "connectivity.analyze_blast_radius":
            entity = query.scope[0] if query.scope else ""
            res = self.topology.analyze_blast_radius(entity)
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.COMPLETED,
                result=res,
                completed_at=now,
            )

        return PeerQueryResult(
            query_id=query.query_id,
            status=QueryStatus.UNSUPPORTED,
            warnings=[f"Capability '{cap}' not supported by ConnectivityTower"],
            completed_at=now,
        )

    def handle_task(self, task: InvestigationTask) -> TaskResult:
        """Handles supervisor-authorized persistent investigation tasks."""
        now = datetime.now(timezone.utc)
        cap = task.capability

        if cap in ("INVESTIGATE_TOPOLOGY", "ANALYZE_REACHABILITY"):
            scope = task.constraints.get("scope", [])
            src = scope[0] if len(scope) > 0 else "SW_CORE_01"
            dst = scope[1] if len(scope) > 1 else "GW_EDGE_01"
            res = self.topology.trace_path(src, dst)

            return TaskResult(
                result_id=generate_id("RES-CONN"),
                task_id=task.task_id,
                assignee=self.tower_id,
                status=TaskStatus.COMPLETED,
                result_schema="netcoop://schemas/tasks/connectivity-reachability-result/1.0",
                result=res,
                evidence_refs=res.get("evidence_refs", []),
                completed_at=now,
            )

        return TaskResult(
            result_id=generate_id("RES-CONN"),
            task_id=task.task_id,
            assignee=self.tower_id,
            status=TaskStatus.FAILED,
            result_schema="netcoop://schemas/tasks/error-result/1.0",
            warnings=[f"Unsupported capability: {cap}"],
            completed_at=now,
        )
