"""Unit tests verifying serialization, deserialization, and strict schema validation for all contracts."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from netcoop.communication.events import EventEnvelope
from netcoop.communication.queries import PeerQuery, PeerQueryResult
from netcoop.communication.registry import CapabilityRegistry
from netcoop.models.enums import (
    ConfidenceCategory,
    FindingStatus,
    ProposalDecision,
    QueryStatus,
    Severity,
    TowerId,
)
from netcoop.models.findings import Finding
from netcoop.models.hypotheses import Hypothesis
from netcoop.models.observations import (
    ConfigObservation,
    LogObservation,
    MetricObservation,
    TopologyObservation,
)
from netcoop.models.reports import (
    FinalReport,
    SupervisorProposal,
    SupportingEvidenceItem,
)


def test_metric_observation_valid(sample_utc_time):
    obs = MetricObservation(
        observation_id="OBS-01",
        incident_id="INC-01",
        source="test",
        entity_id="SW_1",
        metric_name="link_utilization_pct",
        value=92.5,
        unit="percent",
        timestamp=sample_utc_time,
    )
    assert obs.value == 92.5
    # Round-trip JSON test
    json_str = obs.model_dump_json()
    restored = MetricObservation.model_validate_json(json_str)
    assert restored.observation_id == obs.observation_id
    assert restored.timestamp == obs.timestamp


def test_metric_observation_rejects_naive_datetime():
    naive_dt = datetime(2026, 10, 31, 12, 0, 0)
    with pytest.raises(ValidationError, match="timezone-aware"):
        MetricObservation(
            observation_id="OBS-01",
            incident_id="INC-01",
            source="test",
            entity_id="SW_1",
            metric_name="latency_ms",
            value=25.0,
            unit="milliseconds",
            timestamp=naive_dt,
        )


def test_metric_observation_rejects_invalid_unit(sample_utc_time):
    with pytest.raises(ValidationError, match="Invalid unit 'gigabytes'"):
        MetricObservation(
            observation_id="OBS-01",
            incident_id="INC-01",
            source="test",
            entity_id="SW_1",
            metric_name="latency_ms",
            value=25.0,
            unit="gigabytes",
            timestamp=sample_utc_time,
        )


def test_metric_observation_rejects_out_of_bounds_value(sample_utc_time):
    with pytest.raises(ValidationError, match="above maximum"):
        MetricObservation(
            observation_id="OBS-01",
            incident_id="INC-01",
            source="test",
            entity_id="SW_1",
            metric_name="link_utilization_pct",
            value=125.0,  # Max allowed is 100.0
            unit="percent",
            timestamp=sample_utc_time,
        )


def test_metric_observation_rejects_extra_fields(sample_utc_time):
    with pytest.raises(ValidationError):
        MetricObservation(
            observation_id="OBS-01",
            incident_id="INC-01",
            source="test",
            entity_id="SW_1",
            metric_name="latency_ms",
            value=25.0,
            unit="milliseconds",
            timestamp=sample_utc_time,
            unauthorized_field="malicious_payload",  # Extra fields forbidden
        )


def test_log_and_topology_observations(sample_utc_time):
    log_obs = LogObservation(
        observation_id="LOG-01",
        incident_id="INC-01",
        source="syslog",
        entity_id="SW_1",
        log_level="ERROR",
        message="Interface flapping",
        timestamp=sample_utc_time,
    )
    assert log_obs.observation_type == "log"

    topo_obs = TopologyObservation(
        observation_id="TOPO-01",
        incident_id="INC-01",
        source="cdp",
        entity_id="SW_1",
        source_entity="SW_1",
        target_entity="RTR_CORE",
        relationship_type="connected_to",
        link_speed_mbps=1000.0,
        timestamp=sample_utc_time,
    )
    assert topo_obs.observation_type == "topology"

    cfg_obs = ConfigObservation(
        observation_id="CFG-01",
        incident_id="INC-01",
        source="git",
        entity_id="SW_1",
        config_key="interface.Gi0/1.mtu",
        config_value="1500",
        timestamp=sample_utc_time,
    )
    assert cfg_obs.observation_type == "config"


def test_finding_contract_immutability_and_validation(sample_utc_time):
    finding = Finding(
        finding_id="F-101",
        incident_id="INC-101",
        source_tower=TowerId.INFRASTRUCTURE,
        producer="device_analyzer",
        finding_type="interface_degradation",
        severity=Severity.HIGH,
        status=FindingStatus.ACTIVE,
        entity_refs=["SW_1:Gi0/1"],
        evidence_refs=["OBS-01"],
        confidence=0.91,
        independence_group="group_hw",
        observed_at=sample_utc_time,
        created_at=sample_utc_time,
        description="CRC error rate elevated above threshold.",
    )
    assert finding.finding_id == "F-101"

    # Verify frozen immutability
    with pytest.raises(ValidationError):
        finding.confidence = 0.5  # Mutation forbidden

    # Verify invalid finding type rejection
    with pytest.raises(ValidationError, match="Invalid finding_type"):
        Finding(
            finding_id="F-102",
            incident_id="INC-101",
            source_tower=TowerId.INFRASTRUCTURE,
            producer="test",
            finding_type="invalid_unknown_type",
            severity=Severity.LOW,
            status=FindingStatus.ACTIVE,
            entity_refs=["SW_1"],
            evidence_refs=["OBS-01"],
            confidence=0.5,
            independence_group="grp",
            observed_at=sample_utc_time,
            created_at=sample_utc_time,
            description="test",
        )


def test_hypothesis_contract(sample_utc_time):
    hyp = Hypothesis(
        hypothesis_id="HYP-01",
        incident_id="INC-01",
        fault_code="LINK_CONGESTION",
        suspected_entities=["SW_1:Gi0/1"],
        supporting_finding_refs=["F-101"],
        confidence_score=0.85,
        confidence_category=ConfidenceCategory.HIGH,
        rationale="Egress drops correlated with 95% utilization.",
        created_at=sample_utc_time,
    )
    assert hyp.fault_code == "LINK_CONGESTION"

    # Reject invalid fault code
    with pytest.raises(ValidationError, match="Invalid fault_code"):
        Hypothesis(
            hypothesis_id="HYP-02",
            incident_id="INC-01",
            fault_code="UNKNOWN_ALIEN_INTERFERENCE",
            suspected_entities=["SW_1"],
            confidence_score=0.1,
            confidence_category=ConfidenceCategory.LOW,
            rationale="test",
            created_at=sample_utc_time,
        )


def test_event_envelope_validation(sample_utc_time):
    event = EventEnvelope(
        specversion="1.0",
        id="EVT-000001",
        source="netcoop/performance",
        type="performance.congestion_candidate",
        subject="SW_1:Gi0/1",
        time=sample_utc_time,
        datacontenttype="application/json",
        dataschema="netcoop://schemas/events/congestion-candidate/1.0",
        correlationid="INC-101",
        causationid=None,
        data={
            "incident_id": "INC-101",
            "source_tower": "performance",
            "finding_refs": ["F-101"],
            "severity": "high",
        },
    )
    dumped = event.model_dump_json()
    loaded = EventEnvelope.model_validate_json(dumped)
    assert loaded.id == "EVT-000001"
    assert loaded.data["severity"] == "high"


def test_peer_query_and_result(sample_utc_time):
    query = PeerQuery(
        query_id="QRY-001",
        incident_id="INC-101",
        requester="performance",
        recipient="connectivity",
        capability="connectivity.query_neighbors",
        scope=["SW_1"],
        constraints={"timeout_ms": 200},
        expected_schema="netcoop://schemas/capabilities/connectivity-query-neighbors-output/1.0",
        created_at=sample_utc_time,
    )
    assert query.capability == "connectivity.query_neighbors"

    result = PeerQueryResult(
        query_id="QRY-001",
        status=QueryStatus.COMPLETED,
        result={"neighbors": ["RTR_1", "SW_2"]},
        evidence_refs=["OBS-01"],
        completed_at=sample_utc_time,
    )
    assert result.status == QueryStatus.COMPLETED
    assert result.result["neighbors"] == ["RTR_1", "SW_2"]


def test_supervisor_proposal_and_final_report(sample_utc_time):
    proposal = SupervisorProposal(
        proposal_id="PROP-01",
        incident_id="INC-101",
        decision=ProposalDecision.PROPOSE_DIAGNOSIS,
        suspected_root_cause="Link congestion causing egress queue drops",
        affected_entities=["SW_1:Gi0/1"],
        supporting_finding_refs=["F-101"],
        confidence_category=ConfidenceCategory.HIGH,
        alternative_causes=["Upstream policer drop"],
        recommended_actions=["Review queue scheduling"],
        created_at=sample_utc_time,
    )
    assert proposal.decision == ProposalDecision.PROPOSE_DIAGNOSIS

    final_report = FinalReport(
        incident_id="INC-101",
        status="diagnosed",
        suspected_root_cause="Likely link congestion causing egress queue drops",
        confidence=0.86,
        confidence_category=ConfidenceCategory.HIGH,
        affected_devices=["SW_CAMPUS_1"],
        supporting_evidence=[
            SupportingEvidenceItem(
                metric="link_utilization_pct",
                value=94.2,
                interpretation="High link utilization",
            ),
            SupportingEvidenceItem(
                metric="queue_drops",
                value=160,
                interpretation="Elevated packet drops",
            ),
        ],
        alternative_causes=["Upstream link congestion"],
        recommended_actions=["Inspect upstream link", "Review queue config"],
        evidence_sources=["performance", "infrastructure"],
        limitations=["Further verification recommended"],
        generated_at=sample_utc_time,
    )
    assert final_report.confidence == 0.86
    assert len(final_report.supporting_evidence) == 2


def test_capability_registry_query_validation():
    registry = CapabilityRegistry.load()
    # Performance tower querying connectivity.query_neighbors -> Valid
    is_valid, msg = registry.validate_query(TowerId.CONNECTIVITY, "connectivity.query_neighbors")
    assert is_valid, msg

    # Asking wrong tower for capability -> Invalid
    is_valid, msg = registry.validate_query(TowerId.PERFORMANCE, "connectivity.query_neighbors")
    assert not is_valid
    assert "owned by 'connectivity'" in msg

    # Non-existent capability -> Invalid
    is_valid, msg = registry.validate_query(TowerId.PERFORMANCE, "performance.non_existent")
    assert not is_valid
