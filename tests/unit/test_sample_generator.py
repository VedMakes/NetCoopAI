"""Unit tests for the NetCoop AI synthetic network data generator."""

import json
from pathlib import Path

import pytest

from reference.sample_generator import (
    SCENARIO_PRESETS,
    build_default_campus_topology,
    generate_scenario,
    generate_telemetry,
)


def test_topology_structure():
    topo = build_default_campus_topology()
    assert 8 <= len(topo.nodes) <= 12
    assert len(topo.interfaces) > 0
    assert len(topo.links) > 0
    assert len(topo.service_dependencies) > 0

    node_ids = {n.entity_id for n in topo.nodes}
    assert "GW_EDGE_01" in node_ids
    assert "SW_CORE_01" in node_ids
    assert "SW_DIST_HOSTEL" in node_ids
    assert "AP_HOSTEL_A" in node_ids
    assert "SRV_DNS_01" in node_ids
    assert "SRV_DHCP_01" in node_ids

    # All interfaces belong to existing nodes
    for iface in topo.interfaces:
        assert iface.device_id in node_ids


@pytest.mark.parametrize("scenario_name", list(SCENARIO_PRESETS.keys()))
def test_all_scenarios_generate_successfully(tmp_path: Path, scenario_name: str):
    out_dir = tmp_path / scenario_name
    paths = generate_scenario(
        scenario_name=scenario_name,
        output_dir=out_dir,
        seed=100,
        num_steps=10,
    )

    assert paths["telemetry"].exists()
    assert paths["topology"].exists()
    assert paths["ground_truth"].exists()

    # Ground truth is isolated in an evaluation directory
    assert "evaluation" in str(paths["ground_truth"].parent)


def test_strict_reproducibility(tmp_path: Path):
    dir_run1 = tmp_path / "run1"
    dir_run2 = tmp_path / "run2"

    paths1 = generate_scenario("link_congestion", dir_run1, seed=999, num_steps=12)
    paths2 = generate_scenario("link_congestion", dir_run2, seed=999, num_steps=12)

    # Telemetry exact match
    content1 = paths1["telemetry"].read_text(encoding="utf-8")
    content2 = paths2["telemetry"].read_text(encoding="utf-8")
    assert content1 == content2

    # Topology exact match
    assert paths1["topology"].read_text(encoding="utf-8") == paths2["topology"].read_text(encoding="utf-8")

    # Ground truth exact match
    assert paths1["ground_truth"].read_text(encoding="utf-8") == paths2["ground_truth"].read_text(encoding="utf-8")


def test_telemetry_no_leakage_and_valid_references(tmp_path: Path):
    out_dir = tmp_path / "test_leakage"
    paths = generate_scenario("device_overload", out_dir, seed=42, num_steps=10)

    # Read topology entity IDs
    with open(paths["topology"], "r", encoding="utf-8") as f:
        topo_data = json.load(f)
    valid_entities = {n["entity_id"] for n in topo_data["nodes"]}
    valid_interfaces = {i["interface_id"] for i in topo_data["interfaces"]}
    all_valid_entities = valid_entities | valid_interfaces

    # Read and inspect telemetry records
    forbidden_keys = {
        "fault_type",
        "injected_fault",
        "expected_root_cause",
        "ground_truth",
        "answer",
        "status",  # Should not have 'status: Healthy/Critical'
    }

    record_count = 0
    with open(paths["telemetry"], "r", encoding="utf-8") as f:
        for line in f:
            record_count += 1
            record = json.loads(line)

            # Check no forbidden keys exist
            for forbidden in forbidden_keys:
                assert forbidden not in record, f"Leaked '{forbidden}' found in telemetry: {record}"

            # Verify entity reference matches topology
            assert record["entity_id"] in all_valid_entities, (
                f"Unknown entity '{record['entity_id']}' in telemetry."
            )

            # Check time format is timezone-aware ISO string
            assert "+00:00" in record["event_time"] or record["event_time"].endswith("Z")

            # Check schema version
            assert record["schema_version"] == "1.0"

    assert record_count > 0


def test_ground_truth_isolation_and_content(tmp_path: Path):
    out_dir = tmp_path / "test_gt"
    paths = generate_scenario("dns_failure", out_dir, seed=42, num_steps=10)

    with open(paths["ground_truth"], "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    assert gt_data["injected_fault_class"] == "dns_failure"
    assert gt_data["target_entity"] == "SRV_DNS_01"
    assert "intended_affected_entities" in gt_data
    assert gt_data["fault_start_step"] == 4
    assert gt_data["severity"] == "high"
    assert gt_data["simulator_metadata"]["seed"] == 42


def test_backward_compatibility_shim():
    record = generate_telemetry("latency_spike", seed=42)
    assert isinstance(record, dict)
    assert "entity_id" in record
    assert "metric" in record
    assert "value" in record
