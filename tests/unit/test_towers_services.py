"""Unit tests for the Services and Configuration Tower."""

from datetime import datetime, timezone

from netcoop.communication.queries import PeerQuery
from netcoop.communication.tasks import InvestigationTask
from netcoop.models.enums import QueryStatus, TaskStatus, TowerId
from netcoop.models.observations import (
    ConfigObservation,
    LogObservation,
    MetricObservation,
)
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.towers.services import ServicesEngine, ServicesTower


def test_dns_resolution_failure_detected():
    now = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    obs = [
        MetricObservation(
            observation_id="OBS-DNS-LAT",
            incident_id="INC-DNS",
            source="probe",
            entity_id="SRV_DNS_01",
            metric_name="latency_ms",
            value=850.0,  # Critical > 500ms
            unit="milliseconds",
            timestamp=now,
        ),
        LogObservation(
            observation_id="OBS-DNS-LOG",
            incident_id="INC-DNS",
            source="bind9",
            entity_id="SRV_DNS_01",
            log_level="ERROR",
            message="named[1024]: query failed (SERVFAIL) for campus.edu",
            timestamp=now,
        ),
    ]

    engine = ServicesEngine()
    findings, hypotheses = engine.analyze("INC-DNS", obs)

    assert len(findings) == 1
    assert findings[0].finding_type == "dns_resolution_failure"
    assert "OBS-DNS-LAT" in findings[0].evidence_refs
    assert "OBS-DNS-LOG" in findings[0].evidence_refs

    assert len(hypotheses) == 1
    assert hypotheses[0].fault_code == "DNS_FAILURE"
    assert "SRV_DNS_01" in hypotheses[0].suspected_entities


def test_dhcp_pool_exhaustion_detected():
    now = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    obs = [
        LogObservation(
            observation_id="OBS-DHCP-LOG",
            incident_id="INC-DHCP",
            source="kea-dhcp",
            entity_id="SRV_DHCP_01",
            log_level="ERROR",
            message="DHCP4_POOL_EXHAUSTED: all 500 addresses in subnet 10.10.0.0/24 exhausted",
            timestamp=now,
        ),
    ]

    engine = ServicesEngine()
    findings, hypotheses = engine.analyze("INC-DHCP", obs)

    assert len(findings) == 1
    assert findings[0].finding_type == "dhcp_lease_exhaustion"
    assert "OBS-DHCP-LOG" in findings[0].evidence_refs

    assert len(hypotheses) == 1
    assert hypotheses[0].fault_code == "DHCP_FAILURE"
    assert "SRV_DHCP_01" in hypotheses[0].suspected_entities


def test_config_drift_detected():
    now = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    obs = [
        ConfigObservation(
            observation_id="OBS-CFG-1",
            incident_id="INC-CFG",
            source="oxidized",
            entity_id="SW_CORE_01",
            config_key="interfaces.Te1/1/1.mtu",
            config_value="1500",
            previous_value="9000",
            timestamp=now,
        )
    ]

    engine = ServicesEngine()
    findings, hypotheses = engine.analyze("INC-CFG", obs)

    assert len(findings) == 1
    assert findings[0].finding_type == "config_drift_detected"
    assert "interfaces.Te1/1/1.mtu" in findings[0].description
    assert "OBS-CFG-1" in findings[0].evidence_refs

    assert len(hypotheses) == 1
    assert hypotheses[0].fault_code == "CONFIG_DRIFT"


def test_normal_services_telemetry_causes_no_faults():
    now = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    obs = [
        MetricObservation(
            observation_id="OBS-DNS-OK",
            incident_id="INC-OK",
            source="probe",
            entity_id="SRV_DNS_01",
            metric_name="latency_ms",
            value=12.0,  # Healthy < 150ms
            unit="milliseconds",
            timestamp=now,
        ),
        LogObservation(
            observation_id="OBS-LOG-OK",
            incident_id="INC-OK",
            source="bind9",
            entity_id="SRV_DNS_01",
            log_level="INFO",
            message="zone campus.edu/IN: loaded serial 2026103101",
            timestamp=now,
        ),
    ]

    engine = ServicesEngine()
    findings, hypotheses = engine.analyze("INC-OK", obs)
    assert len(findings) == 0
    assert len(hypotheses) == 0


def test_services_tower_controller_and_sqlite():
    repo = SQLiteRepository(":memory:")
    tower = ServicesTower(repository=repo)
    now = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)

    obs = [
        LogObservation(
            observation_id="OBS-DHCP-ERR",
            incident_id="INC-SERV-SQLITE",
            source="dhcp",
            entity_id="SRV_DHCP_01",
            log_level="CRITICAL",
            message="DHCP scope pool_full no leases remaining",
            timestamp=now,
        )
    ]

    report = tower.analyze_incident("INC-SERV-SQLITE", obs)
    assert report.tower_id == TowerId.SERVICES
    assert report.status == "completed"
    assert len(report.findings) == 1

    stored_reports = repo.get_tower_reports("INC-SERV-SQLITE")
    assert len(stored_reports) == 1
    assert stored_reports[0].tower_id == TowerId.SERVICES


def test_services_peer_queries_and_tasks():
    tower = ServicesTower()
    now = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)

    # 1. DNS check query
    q_dns = PeerQuery(
        query_id="Q-DNS-1",
        incident_id="INC-1",
        requester="performance",
        recipient="services",
        capability="services.check_dns",
        scope=["SRV_DNS_01"],
        expected_schema="dns_output",
        created_at=now,
    )
    res_dns = tower.handle_query(q_dns)
    assert res_dns.status == QueryStatus.COMPLETED
    assert res_dns.result["healthy"] is True

    # 2. DHCP check query
    q_dhcp = PeerQuery(
        query_id="Q-DHCP-1",
        incident_id="INC-1",
        requester="performance",
        recipient="services",
        capability="services.check_dhcp",
        scope=["SRV_DHCP_01"],
        expected_schema="dhcp_output",
        created_at=now,
    )
    res_dhcp = tower.handle_query(q_dhcp)
    assert res_dhcp.status == QueryStatus.COMPLETED
    assert "pool_utilization_pct" in res_dhcp.result

    # 3. Investigation task
    task = InvestigationTask(
        task_id="TASK-SERV-01",
        incident_id="INC-1",
        requester="supervisor",
        assignee=TowerId.SERVICES,
        capability="INVESTIGATE_DNS",
        objective={"target": "SRV_DNS_01"},
        constraints={},
        expected_result_schema="dns_task_result",
        created_at=now,
        updated_at=now,
    )
    t_res = tower.handle_task(task)
    assert t_res.status == TaskStatus.COMPLETED
    assert t_res.assignee == TowerId.SERVICES
