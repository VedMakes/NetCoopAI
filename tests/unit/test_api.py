"""Integration tests for NetCoop AI FastAPI backend."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from netcoop_api.app import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_root_endpoint(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "NetCoop AI API"
    assert data["status"] == "online"


def test_health_endpoint(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert "runtime" in data["components"]
    assert "towers" in data["components"]
    assert "supervisor_gate" in data["components"]


def test_list_scenarios(client: TestClient):
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    scenarios = response.json()
    assert len(scenarios) >= 5
    ids = [s["scenario_id"] for s in scenarios]
    assert "healthy" in ids
    assert "link_congestion" in ids
    assert "weak_wifi" in ids


def test_scenario_detail_and_topology(client: TestClient):
    # Valid scenario
    res = client.get("/api/scenarios/link_congestion")
    assert res.status_code == 200
    detail = res.json()
    assert detail["scenario_id"] == "link_congestion"
    assert detail["node_count"] > 0
    assert detail["link_count"] > 0
    assert "ground_truth" not in detail["description"].lower()

    # Topology
    topo_res = client.get("/api/scenarios/link_congestion/topology")
    assert topo_res.status_code == 200
    topo = topo_res.json()
    assert len(topo["nodes"]) > 0
    assert len(topo["links"]) > 0

    # Non-existent scenario
    err_res = client.get("/api/scenarios/nonexistent_scenario")
    assert err_res.status_code == 404


def test_run_lifecycle_and_artifacts(client: TestClient):
    # 1. Start run on link_congestion
    create_res = client.post("/api/runs", json={"scenario_id": "link_congestion", "llm": "off"})
    assert create_res.status_code == 201
    run_info = create_res.json()
    run_id = run_info["run_id"]
    assert run_id.startswith("run-")
    assert run_info["status"] in ("queued", "running", "completed")

    # 2. Poll until completed (timeout 15s)
    max_wait = 15.0
    start_time = time.time()
    completed = False
    while time.time() - start_time < max_wait:
        st_res = client.get(f"/api/runs/{run_id}")
        assert st_res.status_code == 200
        st_data = st_res.json()
        if st_data["status"] == "completed":
            completed = True
            break
        elif st_data["status"] == "failed":
            pytest.fail(f"Run failed: {st_data.get('error')}")
        time.sleep(0.3)

    assert completed, "Run did not complete within timeout"

    # 3. Telemetry
    telem_res = client.get(f"/api/runs/{run_id}/telemetry")
    assert telem_res.status_code == 200
    telem = telem_res.json()
    assert telem["total_observations"] > 0
    assert telem["total_features"] > 0

    # 4. Topology annotated
    topo_res = client.get(f"/api/runs/{run_id}/topology")
    assert topo_res.status_code == 200
    topo = topo_res.json()
    assert len(topo["nodes"]) > 0

    # 5. Events
    events_res = client.get(f"/api/runs/{run_id}/events")
    assert events_res.status_code == 200
    events = events_res.json()
    event_types = [e["event_type"] for e in events]
    assert "run.started" in event_types
    assert "ingestion.completed" in event_types
    assert "tower.completed" in event_types
    assert "gate.check.completed" in event_types
    assert "report.published" in event_types
    assert "run.completed" in event_types

    # 6. Findings
    findings_res = client.get(f"/api/runs/{run_id}/findings")
    assert findings_res.status_code == 200
    findings = findings_res.json()
    assert len(findings) == 4  # Performance, Infra, Conn, Services

    # 7. Final Report
    report_res = client.get(f"/api/runs/{run_id}/report")
    assert report_res.status_code == 200
    report = report_res.json()
    assert "LINK_CONGESTION" in report["suspected_root_cause"]
    assert len(report["supporting_evidence"]) > 0

    # 8. Post-diagnosis evaluation against ground truth
    eval_res = client.get(f"/api/runs/{run_id}/evaluation")
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert eval_data["injected_fault_class"] == "LINK_CONGESTION"
    assert eval_data["class_match"] is True
    assert eval_data["target_match"] is True

    # 8b. Tasks retrieval
    tasks_res = client.get(f"/api/runs/{run_id}/tasks")
    assert tasks_res.status_code == 200

    # 8c. Stream past events
    stream_res = client.get(f"/api/runs/{run_id}/events/stream")
    assert stream_res.status_code == 200
    assert "data:" in stream_res.text

    # 9. Explanation Assistant Q&A
    asst_res = client.post(
        f"/api/runs/{run_id}/assistant",
        json={"question": "Why did Performance tower suspect link congestion?", "llm": "off"},
    )
    assert asst_res.status_code == 200
    asst_data = asst_res.json()
    assert "LINK_CONGESTION" in asst_data["answer"].upper() or "PERFORMANCE" in asst_data["answer"].upper()
    assert len(asst_data["cited_evidence_ids"]) > 0
    assert asst_data["provider_used"] == "deterministic"


def test_evaluation_quarantine_before_completion(client: TestClient):
    # Non-existent run
    err_res = client.get("/api/runs/run-nonexistent/evaluation")
    assert err_res.status_code == 400
