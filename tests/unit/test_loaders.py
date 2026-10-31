"""Unit tests for telemetry loaders across JSON, CSV, and JSONL formats."""

import json
from pathlib import Path

from netcoop.ingestion.loaders import TelemetryLoader
from netcoop.models.observations import MetricObservation


def test_load_canonical_fixture(tmp_path: Path):
    loader = TelemetryLoader()
    # Use existing sample fixture
    fixture_path = Path("fixtures/sample_incident.json")
    assert fixture_path.exists()

    batch = loader.load_file(fixture_path, incident_id="INC-TEST")
    assert batch.incident_id == "INC-2026-001"
    assert batch.total_count == 9
    assert batch.metric_count == 5
    assert batch.log_count == 1
    assert batch.topology_count == 2
    assert batch.config_count == 1
    assert len(batch.quarantined_records) == 0


def test_load_organizer_json_record(tmp_path: Path):
    loader = TelemetryLoader()
    sample_record = {
        "timestamp": "2026-10-31T12:00:00Z",
        "device_id": "SW_CAMPUS_1",
        "metrics": {
            "cpu_utilization_pct": 72.5,
            "link_utilization_pct": 89.0,
            "packet_loss_pct": 1.2,
            "latency_ms": 210.5,
            "jitter_ms": 15.0,
            "queue_drops": 45,
            "interface_errors": 12,
        },
        "status": "Warning",
    }
    file_p = tmp_path / "organizer_sample.json"
    file_p.write_text(json.dumps(sample_record), encoding="utf-8")

    batch = loader.load_file(file_p, incident_id="INC-ORG-01")
    assert batch.incident_id == "INC-ORG-01"
    assert batch.metric_count == 7
    # SW_CAMPUS_1 resolves to SW_CORE_01
    for obs in batch.observations:
        assert isinstance(obs, MetricObservation)
        assert obs.entity_id == "SW_CORE_01"
        assert obs.timestamp.tzinfo is not None


def test_load_organizer_missing_values_never_coerced_to_zero(tmp_path: Path):
    loader = TelemetryLoader()
    record_with_missing = {
        "timestamp": "2026-10-31T12:00:00Z",
        "device_id": "SW_CORE_01",
        "metrics": {
            "cpu_utilization_pct": 55.0,
            "queue_drops": None,  # Explicitly null
        },
    }
    file_p = tmp_path / "missing_test.json"
    file_p.write_text(json.dumps(record_with_missing), encoding="utf-8")

    batch = loader.load_file(file_p)
    # Only cpu should be loaded as metric observation
    assert batch.metric_count == 1
    assert batch.observations[0].metric_name == "cpu_utilization_pct"
    # Warning emitted for queue_drops
    assert any("will not be coerced to zero" in w.message for w in batch.warnings)


def test_load_wide_csv(tmp_path: Path):
    loader = TelemetryLoader()
    csv_content = """timestamp,device_id,cpu_utilization_pct,link_utilization_pct,latency_ms
2026-10-31T12:00:00Z,SW_CORE_01,45.2,60.1,12.5
2026-10-31T12:01:00Z,SW_CORE_01,48.0,,14.2
"""
    file_p = tmp_path / "metrics_wide.csv"
    file_p.write_text(csv_content, encoding="utf-8")

    batch = loader.load_file(file_p, incident_id="INC-CSV-WIDE")
    assert batch.incident_id == "INC-CSV-WIDE"
    # Row 1 has 3 metrics, Row 2 has 2 metrics (link_utilization_pct is empty)
    assert batch.metric_count == 5
    assert any("Not coerced to zero" in w.message for w in batch.warnings)


def test_load_narrow_csv(tmp_path: Path):
    loader = TelemetryLoader()
    csv_content = """timestamp,device_id,metric_name,value,unit
2026-10-31T12:00:00Z,SW_CORE_01,cpu,50.0,%
2026-10-31T12:00:00Z,SW_CORE_01,rtt,20.0,ms
"""
    file_p = tmp_path / "metrics_narrow.csv"
    file_p.write_text(csv_content, encoding="utf-8")

    batch = loader.load_file(file_p, incident_id="INC-CSV-NARROW")
    assert batch.metric_count == 2
    metrics = {o.metric_name: o.value for o in batch.observations if isinstance(o, MetricObservation)}
    assert metrics["cpu_utilization_pct"] == 50.0
    assert metrics["latency_ms"] == 20.0


def test_load_jsonl_logs(tmp_path: Path):
    loader = TelemetryLoader()
    jsonl_content = """{"timestamp": "2026-10-31T12:00:00Z", "device_id": "SW_CORE_01", "log_level": "WARNING", "message": "Queue threshold exceeded on Gi0/1"}
{"timestamp": "2026-10-31T12:01:00Z", "device_id": "SW_CORE_01", "log_level": "ERROR", "message": "Interface Gi0/1 link down"}
"""
    file_p = tmp_path / "logs.jsonl"
    file_p.write_text(jsonl_content, encoding="utf-8")

    batch = loader.load_file(file_p, incident_id="INC-JSONL")
    assert batch.log_count == 2
    assert batch.observations[0].log_level == "WARNING"
    assert batch.observations[1].log_level == "ERROR"


def test_malformed_input_quarantined_without_crash(tmp_path: Path):
    loader = TelemetryLoader()
    # Corrupted CSV row
    csv_content = """timestamp,device_id,metric_name,value,unit
2026-10-31T12:00:00Z,SW_CORE_01,cpu_utilization_pct,50.0,percent
NOT_A_DATE,SW_CORE_01,cpu_utilization_pct,55.0,percent
2026-10-31T12:02:00Z,SW_CORE_01,cpu_utilization_pct,60.0,percent
"""
    file_p = tmp_path / "corrupted.csv"
    file_p.write_text(csv_content, encoding="utf-8")

    batch = loader.load_file(file_p)
    # The valid 2 rows loaded, 1 quarantined
    assert batch.metric_count == 2
    assert len(batch.quarantined_records) == 1
    assert "Missing timestamp" in batch.quarantined_records[0]["error"] or "timestamp" in str(batch.quarantined_records[0]["error"]).lower()


def test_unknown_units_are_quarantined_instead_of_silently_relabelled(tmp_path: Path):
    file_path = tmp_path / "unknown_unit.csv"
    file_path.write_text(
        "timestamp,device_id,metric_name,value,unit\n"
        "2026-10-31T12:00:00Z,SW_CORE_01,latency_ms,5,minutes\n",
        encoding="utf-8",
    )

    batch = TelemetryLoader().load_file(file_path)

    assert batch.metric_count == 0
    assert any("Unrecognized unit 'minutes'" in warning.message for warning in batch.warnings)


def test_unsupported_canonical_schema_version_is_explicitly_warned():
    record = {
        "observation_type": "metric", "observation_id": "OBS-V2", "incident_id": "INC-V2",
        "source": "test", "entity_id": "SW_CORE_01", "timestamp": "2026-10-31T12:00:00Z",
        "schema_version": "2.0", "metric_name": "latency_ms", "value": 10, "unit": "milliseconds",
    }
    batch = TelemetryLoader().load_json_data({"observations": [record]})

    assert batch.metric_count == 1
    assert any(w.warning_type == "schema_version_warning" for w in batch.warnings)
