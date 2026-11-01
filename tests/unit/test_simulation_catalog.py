"""Regression checks for the dashboard's runnable simulation catalog."""

import time
from pathlib import Path

from netcoop_api.schemas import RunCreateRequest
from netcoop_api.service import RunManager


def test_catalog_keeps_challenge_regression_and_edge_case_suites(tmp_path: Path) -> None:
    manager = RunManager(scenarios_dir=Path("fixtures/scenarios"), storage_dir=tmp_path)
    scenarios = manager.list_scenarios()
    by_suite = {
        suite: [scenario for scenario in scenarios if scenario.suite == suite]
        for suite in ("challenge", "netcoop", "edge")
    }

    assert len(by_suite["challenge"]) == 7
    assert len(by_suite["netcoop"]) == 21
    assert len(by_suite["edge"]) == 5
    assert len(scenarios) == 33
    assert all(manager.get_scenario(item.scenario_id).has_ground_truth for item in by_suite["challenge"])
    assert all(manager.get_scenario(item.scenario_id).has_ground_truth for item in by_suite["netcoop"])
    assert all(not manager.get_scenario(item.scenario_id).has_ground_truth for item in by_suite["edge"])


def test_seeded_regression_metadata_and_map_are_available(tmp_path: Path) -> None:
    manager = RunManager(scenarios_dir=Path("fixtures/scenarios"), storage_dir=tmp_path)
    scenario = manager.get_scenario("netcoop_dns_failure_seed_42")
    topology = manager.get_scenario_topology("netcoop_dns_failure_seed_42")

    assert scenario is not None
    assert scenario.suite == "netcoop"
    assert scenario.name == "Campus DNS Resolver Timeout · seed 42"
    assert scenario.has_ground_truth
    assert topology is not None
    assert topology.nodes
    assert topology.links


def test_seeded_regression_case_runs_and_keeps_its_evaluation_target(tmp_path: Path) -> None:
    manager = RunManager(scenarios_dir=Path("fixtures/scenarios"), storage_dir=tmp_path)
    session = manager.create_session("Regression simulation")
    run = manager.create_run(RunCreateRequest(
        scenario_id="netcoop_dns_failure_seed_42",
        session_id=session.session_id,
    ))
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        status = manager.get_run(run.run_id)
        assert status is not None
        if status.status in {"completed", "failed"}:
            break
        time.sleep(0.1)

    assert status.status == "completed", status.error
    evaluation = manager.get_run_evaluation(run.run_id)
    assert evaluation.injected_fault_class == "DNS_FAILURE"
    assert evaluation.class_match
