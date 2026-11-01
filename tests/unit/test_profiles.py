"""Network profile validation and cross-network adaptation tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from netcoop.cli.main import _load_observations_from_target
from netcoop.communication.fabric import IntegrationFabric
from netcoop.configuration.profile import NetworkProfile
from netcoop.models.observations import MetricObservation
from netcoop.supervisor.runtime import SupervisorRuntime
from netcoop.towers.rules import load_rules
from reference.sample_generator import generate_scenario


def test_profile_loads_and_merges_thresholds_roles_and_topology_settings():
    profile = NetworkProfile.load("config/profiles/branch-office-example.yaml")
    rules = profile.apply_to_rules(load_rules())

    assert rules["performance"]["high_utilization_pct"] == 90.0
    assert rules["connectivity"]["topology_anchors"] == ["BR-EDGE-01", "BR-CORE-01"]
    assert rules["services"]["entity_roles"]["dns_resolver"] == ["BR-DNS-01"]


def test_profile_rejects_ambiguous_entity_aliases():
    try:
        NetworkProfile.model_validate({
            "profile_id": "bad", "display_name": "bad",
            "entity_aliases": {"router-a": "R1", "ROUTER-A": "R2"},
        })
    except ValueError as exc:
        assert "Ambiguous entity alias" in str(exc)
    else:
        raise AssertionError("ambiguous aliases must fail profile validation")


def test_profile_rejects_counter_semantics_for_non_count_metric():
    try:
        NetworkProfile.model_validate({
            "profile_id": "bad-counter", "display_name": "bad",
            "metric_mappings": {
                "ifInErrors": {
                    "canonical_name": "latency_ms",
                    "counter_semantics": "cumulative_counter",
                }
            },
        })
    except ValueError as exc:
        assert "non-count metric" in str(exc)
    else:
        raise AssertionError("counter semantics require a count metric")


def test_profile_maps_vendor_record_field_names_and_metric_units(tmp_path: Path):
    profile = NetworkProfile.model_validate({
        "profile_id": "vendor-jsonl", "display_name": "Vendor JSONL",
        "source_fields": {
            "entity_id": "node", "timestamp": "observed_at", "metric": "measurement",
            "value": "reading", "unit": "units", "source_id": "collector",
        },
        "entity_aliases": {"router-west": "BR-EDGE-01"},
        "metric_mappings": {
            "processor_load": {"canonical_name": "cpu_utilization_pct", "source_unit": "percentage"}
        },
    })
    path = tmp_path / "vendor.jsonl"
    path.write_text(json.dumps({
        "observed_at": "2026-01-01T00:00:00Z", "node": "router-west",
        "measurement": "processor_load", "reading": 91, "units": "percentage",
        "collector": "vendor-agent",
    }) + "\n", encoding="utf-8")

    _, observations = _load_observations_from_target(path, profile=profile)

    assert len(observations) == 1
    observation = observations[0]
    assert isinstance(observation, MetricObservation)
    assert observation.entity_id == "BR-EDGE-01"
    assert observation.metric_name == "cpu_utilization_pct"
    assert observation.value == 91
    assert observation.unit == "percent"


def test_cumulative_counters_become_deltas_and_reset_intervals_are_skipped(tmp_path: Path):
    profile = NetworkProfile.model_validate({
        "profile_id": "snmp-branch", "display_name": "SNMP branch",
        "metric_mappings": {
            "ifInErrors": {
                "canonical_name": "interface_errors", "source_unit": "count",
                "counter_semantics": "cumulative_counter",
            }
        },
    })
    path = tmp_path / "counter.jsonl"
    records = [
        {"timestamp": f"2026-01-01T00:00:0{second}Z", "entity_id": "RTR-1",
         "metric": "ifInErrors", "value": value, "unit": "count"}
        for second, value in [(0, 100), (1, 110), (2, 112), (3, 2), (4, 5)]
    ]
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    warnings: list[str] = []

    _, observations = _load_observations_from_target(path, profile=profile, data_quality_warnings=warnings)

    assert [obs.value for obs in observations if isinstance(obs, MetricObservation)] == [10, 2, 3]
    intervals = [obs.raw_reference["counter_interval"] for obs in observations]
    assert [item["interval_seconds"] for item in intervals] == [1, 1, 1]
    assert any("baseline" in warning for warning in warnings)
    assert any("reset/decrease" in warning for warning in warnings)


def test_branch_profile_adapts_vendor_names_and_units_without_code_changes(tmp_path: Path):
    source = tmp_path / "generated-campus"
    generate_scenario("dns_failure", source, seed=51, num_steps=15)
    id_map = {
        "GW_EDGE_01": "edge-fw-a",
        "SW_CORE_01": "core-sw-a",
        "SW_DIST_HOSTEL": "dist-sw-west",
        "SRV_DNS_01": "resolver-prod",
        "SRV_DHCP_01": "relay-prod",
    }
    telemetry_path = source / "telemetry.jsonl"
    adapted_records = []
    for line in telemetry_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("entity_id") in id_map:
            record["entity_id"] = id_map[record["entity_id"]]
        if record.get("metric") == "latency_ms":
            record["metric"] = "round_trip_time"
            record["value"] = record["value"] / 1000.0
            record.pop("unit", None)
        elif record.get("metric") == "link_utilization_pct":
            record["metric"] = "tx_utilization"
        adapted_records.append(json.dumps(record))
    telemetry_path.write_text("\n".join(adapted_records) + "\n", encoding="utf-8")

    topology_path = source / "topology.json"
    topology = json.loads(topology_path.read_text(encoding="utf-8"))
    topology["links"] = [
        {
            "id": link["link_id"],
            "src_node": id_map.get(link["source_entity"], link["source_entity"]),
            "dst_node": id_map.get(link["target_entity"], link["target_entity"]),
            "kind": link["link_type"],
            "capacity": link["capacity_mbps"],
            "iface": link["source_interface"],
        }
        for link in topology["links"]
    ]
    topology["service_dependencies"] = [
        {
            "client": id_map.get(dep["consumer_entity"], dep["consumer_entity"]),
            "server": id_map.get(dep["provider_entity"], dep["provider_entity"]),
            "kind": dep["dependency_type"],
        }
        for dep in topology["service_dependencies"]
    ]
    topology_path.write_text(json.dumps(topology), encoding="utf-8")

    profile = NetworkProfile.load("config/profiles/branch-office-example.yaml")
    incident_id, observations = _load_observations_from_target(source, profile=profile)
    report = SupervisorRuntime(
        fabric=IntegrationFabric(rules=profile.apply_to_rules(load_rules())),
        network_profile={"profile_id": profile.profile_id, "version": profile.version},
    ).run_incident(incident_id, observations)

    assert report.status == "diagnosed"
    assert "DNS_FAILURE" in report.suspected_root_cause
    assert "BR-DNS-01" in report.affected_devices
    assert report.network_profile == {"profile_id": "branch-office-example", "version": "1.0"}
    latencies = [o for o in observations if isinstance(o, MetricObservation) and o.entity_id == "BR-DNS-01"]
    assert latencies and max(o.value for o in latencies) > 1000.0
    assert report.peer_interactions[0]["result"]["reachable"] is True


def test_incomplete_topology_does_not_turn_missing_link_into_routing_failure(tmp_path: Path):
    from netcoop.models.observations import TopologyObservation
    from netcoop.towers.connectivity import ConnectivityEngine, TopologyGraph

    observations = [
        TopologyObservation(
            observation_id="L-AB", incident_id="INC-PARTIAL", source="test", entity_id="A",
            source_entity="A", target_entity="B", relationship_type="connected_to",
            timestamp=datetime.now(timezone.utc),
        ),
        TopologyObservation(
            observation_id="L-CD", incident_id="INC-PARTIAL", source="test", entity_id="C",
            source_entity="C", target_entity="D", relationship_type="connected_to",
            timestamp=datetime.now(timezone.utc),
        ),
    ]
    graph = TopologyGraph(anchor_entities=["A"], logical_relationships=[], topology_completeness="partial")
    _, hypotheses, graph = ConnectivityEngine({
        "connectivity": {
            "topology_anchors": ["A"], "logical_relationships": [],
            "topology_completeness": "partial",
        }
    }).analyze("INC-PARTIAL", observations, graph)

    assert not any(h.fault_code == "ROUTING_FAILURE" for h in hypotheses)
    assert graph.trace_path("A", "D")["reachable"] is None
    assert "unknown" in graph.trace_path("A", "D")["warning"]
