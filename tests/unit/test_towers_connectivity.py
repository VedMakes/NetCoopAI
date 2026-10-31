"""Unit tests for the Connectivity Tower and in-memory NetworkX Topology Graph."""

from datetime import datetime, timezone

from netcoop.communication.queries import PeerQuery
from netcoop.communication.tasks import InvestigationTask
from netcoop.models.enums import QueryStatus, TaskStatus, TowerId
from netcoop.models.observations import MetricObservation, TopologyObservation
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.towers.connectivity import (
    ConnectivityEngine,
    ConnectivityTower,
    TopologyGraph,
)


def _make_sample_topology() -> list[TopologyObservation]:
    now = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    # GW_EDGE_01 <-> SW_CORE_01 <-> SW_DIST_HOSTEL <-> AP_HOSTEL_A
    #                                              <-> AP_HOSTEL_B
    return [
        TopologyObservation(
            observation_id="TOPO-1",
            incident_id="INC-CONN-1",
            source="lldp",
            entity_id="GW_EDGE_01",
            source_entity="GW_EDGE_01",
            target_entity="SW_CORE_01",
            relationship_type="connected_to",
            link_speed_mbps=10000.0,
            interface_name="Te1/1/1",
            timestamp=now,
        ),
        TopologyObservation(
            observation_id="TOPO-2",
            incident_id="INC-CONN-1",
            source="lldp",
            entity_id="SW_CORE_01",
            source_entity="SW_CORE_01",
            target_entity="SW_DIST_HOSTEL",
            relationship_type="connected_to",
            link_speed_mbps=10000.0,
            interface_name="Te1/1/2",
            timestamp=now,
        ),
        TopologyObservation(
            observation_id="TOPO-3",
            incident_id="INC-CONN-1",
            source="lldp",
            entity_id="SW_DIST_HOSTEL",
            source_entity="SW_DIST_HOSTEL",
            target_entity="AP_HOSTEL_A",
            relationship_type="connected_to",
            link_speed_mbps=1000.0,
            interface_name="Gi1/0/1",
            timestamp=now,
        ),
        TopologyObservation(
            observation_id="TOPO-4",
            incident_id="INC-CONN-1",
            source="lldp",
            entity_id="SW_DIST_HOSTEL",
            source_entity="SW_DIST_HOSTEL",
            target_entity="AP_HOSTEL_B",
            relationship_type="connected_to",
            link_speed_mbps=1000.0,
            interface_name="Gi1/0/2",
            timestamp=now,
        ),
    ]


def test_service_dependency_does_not_fabricate_a_physical_path():
    dependency = TopologyObservation(
        observation_id="DEP-DNS-1", incident_id="INC-DEP", source="topology_json",
        entity_id="HOSTEL_ZONE_A", source_entity="HOSTEL_ZONE_A", target_entity="SRV_DNS_01",
        relationship_type="dns", timestamp=datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc),
    )
    graph = TopologyGraph()
    graph.build_from_observations([dependency])

    assert graph.trace_path("HOSTEL_ZONE_A", "SRV_DNS_01")["reachable"] is False


def test_topology_graph_construction_and_path():
    topo = TopologyGraph()
    topo.build_from_observations(_make_sample_topology())

    assert topo.graph.number_of_nodes() == 5
    assert topo.graph.number_of_edges() == 4

    res = topo.trace_path("AP_HOSTEL_A", "GW_EDGE_01")
    assert res["reachable"] is True
    assert res["path"] == ["AP_HOSTEL_A", "SW_DIST_HOSTEL", "SW_CORE_01", "GW_EDGE_01"]
    assert res["hops"] == 3
    assert len(res["link_details"]) == 3
    assert "TOPO-3" in res["evidence_refs"]
    assert "TOPO-2" in res["evidence_refs"]
    assert "TOPO-1" in res["evidence_refs"]


def test_topology_graph_refuses_to_invent_missing_path():
    topo = TopologyGraph()
    topo.build_from_observations(_make_sample_topology())
    topo.add_node("ISOLATED_DEV")

    # Path between ISOLATED_DEV and SW_CORE_01
    res = topo.trace_path("ISOLATED_DEV", "SW_CORE_01")
    assert res["reachable"] is False
    assert res["path"] == []
    assert "No topological path" in res["warning"]

    # Unknown entity
    res_unk = topo.trace_path("NON_EXISTENT_DEV", "SW_CORE_01")
    assert res_unk["reachable"] is False
    assert "Refusing to fabricate path" in res_unk["warning"]


def test_topology_graph_preserves_parallel_links_and_both_evidence_refs():
    topo = TopologyGraph()
    links = _make_sample_topology()[:1]
    parallel = links[0].model_copy(update={
        "observation_id": "TOPO-PARALLEL",
        "interface_name": "SW_CORE_01:Gi0/9",
        "link_speed_mbps": 40000.0,
    })
    topo.build_from_observations([*links, parallel])

    result = topo.trace_path("SW_CORE_01", "GW_EDGE_01")

    assert topo.graph.number_of_edges("SW_CORE_01", "GW_EDGE_01") == 2
    assert result["link_details"][0]["parallel_link_count"] == 2
    assert set(result["evidence_refs"]) == {links[0].observation_id, "TOPO-PARALLEL"}


def test_common_upstream_dependency_identification():
    topo = TopologyGraph()
    topo.build_from_observations(_make_sample_topology())

    # Both AP_HOSTEL_A and AP_HOSTEL_B share SW_DIST_HOSTEL as closest uplink
    res = topo.find_common_uplink(["AP_HOSTEL_A", "AP_HOSTEL_B"])
    assert res["common_uplink"] == "SW_DIST_HOSTEL"
    assert "SW_CORE_01" in res["all_common_nodes"]


def test_neighbors_and_blast_radius():
    topo = TopologyGraph()
    topo.build_from_observations(_make_sample_topology())

    neighbors = topo.query_neighbors("SW_DIST_HOSTEL")
    neighbor_ids = {n["neighbor_id"] for n in neighbors}
    assert neighbor_ids == {"SW_CORE_01", "AP_HOSTEL_A", "AP_HOSTEL_B"}

    # If SW_DIST_HOSTEL fails, both AP_HOSTEL_A and AP_HOSTEL_B become isolated from SW_CORE_01
    blast = topo.analyze_blast_radius("SW_DIST_HOSTEL", backbone_entity="SW_CORE_01")
    assert blast["failed_entity"] == "SW_DIST_HOSTEL"
    assert set(blast["isolated_entities"]) == {"AP_HOSTEL_A", "AP_HOSTEL_B"}
    assert blast["total_isolated"] == 2


def test_connectivity_engine_partition_detection():
    now = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    # Two disconnected segments
    obs = [
        TopologyObservation(
            observation_id="TOPO-SEG1",
            incident_id="INC-PART",
            source="lldp",
            entity_id="SW_A1",
            source_entity="SW_A1",
            target_entity="SW_A2",
            relationship_type="connected_to",
            timestamp=now,
        ),
        TopologyObservation(
            observation_id="TOPO-SEG2",
            incident_id="INC-PART",
            source="lldp",
            entity_id="SW_B1",
            source_entity="SW_B1",
            target_entity="SW_B2",
            relationship_type="connected_to",
            timestamp=now,
        ),
    ]

    engine = ConnectivityEngine()
    findings, hypotheses, _ = engine.analyze("INC-PART", obs)

    assert len(findings) == 1
    assert findings[0].finding_type == "path_interruption"
    assert len(hypotheses) == 1
    assert hypotheses[0].fault_code == "ROUTING_FAILURE"
    assert "partitioned into 2 disconnected components" in findings[0].description


def test_connectivity_engine_common_uplink_correlation():
    now = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    obs: list[TopologyObservation | MetricObservation] = _make_sample_topology()
    # Add packet loss on both AP_HOSTEL_A and AP_HOSTEL_B
    obs.append(
        MetricObservation(
            observation_id="OBS-LOSS-A",
            incident_id="INC-CORR",
            source="snmp",
            entity_id="AP_HOSTEL_A",
            metric_name="packet_loss_pct",
            value=12.5,
            unit="percent",
            timestamp=now,
        )
    )
    obs.append(
        MetricObservation(
            observation_id="OBS-LOSS-B",
            incident_id="INC-CORR",
            source="snmp",
            entity_id="AP_HOSTEL_B",
            metric_name="packet_loss_pct",
            value=14.0,
            unit="percent",
            timestamp=now,
        )
    )

    engine = ConnectivityEngine()
    findings, _, _ = engine.analyze("INC-CORR", obs)

    # Identifies shared uplink SW_DIST_HOSTEL
    uplink_finding = next((f for f in findings if f.finding_type == "uplink_saturation"), None)
    assert uplink_finding is not None
    assert "SW_DIST_HOSTEL" in uplink_finding.entity_refs
    assert "OBS-LOSS-A" in uplink_finding.evidence_refs
    assert "OBS-LOSS-B" in uplink_finding.evidence_refs


def test_connectivity_tower_controller_and_sqlite():
    repo = SQLiteRepository(":memory:")
    tower = ConnectivityTower(repository=repo)
    sample_obs = _make_sample_topology()

    report = tower.analyze_incident("INC-CONN-SQLITE", sample_obs)
    assert report.tower_id == TowerId.CONNECTIVITY
    assert report.status == "completed"

    stored_reports = repo.get_tower_reports("INC-CONN-SQLITE")
    assert len(stored_reports) == 1
    assert stored_reports[0].tower_id == TowerId.CONNECTIVITY


def test_connectivity_peer_queries_and_tasks():
    tower = ConnectivityTower()
    tower.topology.build_from_observations(_make_sample_topology())
    now = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Trace path query
    q_path = PeerQuery(
        query_id="Q-PATH-1",
        incident_id="INC-1",
        requester="performance",
        recipient="connectivity",
        capability="connectivity.trace_path",
        scope=["AP_HOSTEL_A", "GW_EDGE_01"],
        expected_schema="path_output",
        created_at=now,
    )
    res_path = tower.handle_query(q_path)
    assert res_path.status == QueryStatus.COMPLETED
    assert res_path.result["reachable"] is True
    assert res_path.result["hops"] == 3

    # 2. Find common uplink query
    q_uplink = PeerQuery(
        query_id="Q-UPLINK-1",
        incident_id="INC-1",
        requester="performance",
        recipient="connectivity",
        capability="connectivity.find_common_uplink",
        scope=["AP_HOSTEL_A", "AP_HOSTEL_B"],
        expected_schema="uplink_output",
        created_at=now,
    )
    res_uplink = tower.handle_query(q_uplink)
    assert res_uplink.status == QueryStatus.COMPLETED
    assert res_uplink.result["common_uplink"] == "SW_DIST_HOSTEL"

    # 3. Investigation task
    task = InvestigationTask(
        task_id="TASK-CONN-01",
        incident_id="INC-1",
        requester="supervisor",
        assignee=TowerId.CONNECTIVITY,
        capability="INVESTIGATE_TOPOLOGY",
        objective={"scope": ["AP_HOSTEL_A", "GW_EDGE_01"]},
        constraints={"scope": ["AP_HOSTEL_A", "GW_EDGE_01"]},
        expected_result_schema="reachability_result",
        created_at=now,
        updated_at=now,
    )
    t_res = tower.handle_task(task)
    assert t_res.status == TaskStatus.COMPLETED
    assert t_res.assignee == TowerId.CONNECTIVITY
    assert t_res.result["analysis"]["reachable"] is True
