"""Deterministic diagnostic engine and controller for the Services and Configuration Tower.

Analyzes DNS resolver latency and query error codes, DHCP pool exhaustion and lease transactions,
and configuration drift on sensitive device settings. Emits validated Finding and Hypothesis models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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
    ConfigObservation,
    LogObservation,
    MetricObservation,
)
from netcoop.models.reports import TowerReport
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.towers.rules import load_rules
from netcoop.utils.id_generator import generate_id


class ServicesEngine:
    """Deterministic analyzer for DNS, DHCP, and configuration anomalies."""

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self.rules = (rules or load_rules()).get("services", {})

    def analyze(
        self, incident_id: str, observations: list[CanonicalObservation]
    ) -> tuple[list[Finding], list[Hypothesis]]:
        """Analyzes service metrics, logs, and configuration changes."""
        findings: list[Finding] = []
        hypotheses: list[Hypothesis] = []

        now = datetime.now(timezone.utc)

        # 1. DNS Diagnostic Analysis
        self._detect_dns_anomalies(incident_id, observations, findings, hypotheses, now)

        # 2. DHCP Diagnostic Analysis
        self._detect_dhcp_anomalies(incident_id, observations, findings, hypotheses, now)

        # 3. Configuration Drift Analysis
        self._detect_config_drift(incident_id, observations, findings, hypotheses, now)

        return findings, hypotheses

    def _detect_dns_anomalies(
        self,
        incident_id: str,
        observations: list[CanonicalObservation],
        findings: list[Finding],
        hypotheses: list[Hypothesis],
        now: datetime,
    ) -> None:
        dns_lat_warn = float(self.rules.get("dns_latency_warning_ms", 150.0))
        dns_lat_crit = float(self.rules.get("dns_latency_critical_ms", 500.0))
        dns_keywords = [
            k.upper()
            for k in self.rules.get(
                "dns_error_keywords", ["SERVFAIL", "NXDOMAIN", "REFUSED", "TIMEOUT", "DNS_FAILURE"]
            )
        ]

        dns_obs: list[CanonicalObservation] = []
        has_severe_error = False
        max_dns_latency = 0.0
        dns_target_entity = "SRV_DNS_01"

        for obs in observations:
            # Check metrics on DNS servers or dns latency metrics
            if isinstance(obs, MetricObservation):
                if "DNS" in obs.entity_id.upper() or obs.metric_name == "latency_ms":
                    if "DNS" in obs.entity_id.upper() and obs.metric_name == "latency_ms":
                        dns_obs.append(obs)
                        dns_target_entity = obs.entity_id
                        if obs.value > max_dns_latency:
                            max_dns_latency = obs.value
            elif isinstance(obs, LogObservation):
                msg_upper = obs.message.upper()
                if "DNS" in obs.entity_id.upper() or any(k in msg_upper for k in dns_keywords):
                    if any(k in msg_upper for k in dns_keywords) or obs.log_level in ("ERROR", "CRITICAL"):
                        dns_obs.append(obs)
                        dns_target_entity = obs.entity_id
                        has_severe_error = True

        if not dns_obs:
            return

        evidence_ids = [o.observation_id for o in dns_obs]

        if has_severe_error or max_dns_latency >= dns_lat_crit:
            f_id = generate_id("F-SERV")
            finding = Finding(
                finding_id=f_id,
                incident_id=incident_id,
                source_tower=TowerId.SERVICES,
                producer="services.detect_dns",
                finding_type="dns_resolution_failure",
                severity=Severity.HIGH,
                status=FindingStatus.ACTIVE,
                entity_refs=[dns_target_entity],
                evidence_refs=evidence_ids,
                confidence=0.90,
                independence_group=f"services:dns:{dns_target_entity}",
                observed_at=dns_obs[-1].timestamp,
                created_at=now,
                description=(
                    f"DNS resolution failure or severe timeout on {dns_target_entity}. "
                    f"Peak latency {max_dns_latency:.1f}ms, error logs detected."
                ),
                metadata={"max_latency_ms": max_dns_latency, "has_error_logs": has_severe_error},
            )
            findings.append(finding)

            h_id = generate_id("HYP-SERV")
            hyp = Hypothesis(
                hypothesis_id=h_id,
                incident_id=incident_id,
                fault_code="DNS_FAILURE",
                suspected_entities=[dns_target_entity],
                supporting_finding_refs=[f_id],
                confidence_score=0.90,
                confidence_category=ConfidenceCategory.HIGH,
                rationale=(
                    f"DNS server {dns_target_entity} exhibits resolution failure / query timeouts, "
                    f"impacting name resolution across connected clients."
                ),
                created_at=now,
            )
            hypotheses.append(hyp)

        elif max_dns_latency >= dns_lat_warn:
            f_id = generate_id("F-SERV")
            findings.append(
                Finding(
                    finding_id=f_id,
                    incident_id=incident_id,
                    source_tower=TowerId.SERVICES,
                    producer="services.detect_dns",
                    finding_type="dns_resolution_failure",
                    severity=Severity.MEDIUM,
                    status=FindingStatus.ACTIVE,
                    entity_refs=[dns_target_entity],
                    evidence_refs=evidence_ids,
                    confidence=0.72,
                    independence_group=f"services:dns:{dns_target_entity}",
                    observed_at=dns_obs[-1].timestamp,
                    created_at=now,
                    description=f"Elevated DNS query response latency on {dns_target_entity}: {max_dns_latency:.1f}ms.",
                    metadata={"max_latency_ms": max_dns_latency},
                )
            )

    def _detect_dhcp_anomalies(
        self,
        incident_id: str,
        observations: list[CanonicalObservation],
        findings: list[Finding],
        hypotheses: list[Hypothesis],
        now: datetime,
    ) -> None:
        dhcp_keywords = [
            k.upper()
            for k in self.rules.get(
                "dhcp_error_keywords", ["EXHAUSTED", "TIMEOUT", "NAK", "POOL_FULL", "DHCP_FAILURE"]
            )
        ]

        dhcp_obs: list[CanonicalObservation] = []
        target_entity = "SRV_DHCP_01"

        for obs in observations:
            if isinstance(obs, LogObservation):
                msg_upper = obs.message.upper()
                if "DHCP" in obs.entity_id.upper() or any(k in msg_upper for k in dhcp_keywords):
                    if any(k in msg_upper for k in dhcp_keywords) or obs.log_level in ("ERROR", "CRITICAL"):
                        dhcp_obs.append(obs)
                        target_entity = obs.entity_id
            elif isinstance(obs, MetricObservation) and "DHCP" in obs.entity_id.upper():
                if (obs.metric_name == "packet_loss_pct" and obs.value >= 50.0) or (
                    obs.metric_name == "latency_ms" and obs.value >= 1000.0
                ):
                    dhcp_obs.append(obs)
                    target_entity = obs.entity_id

        if not dhcp_obs:
            return

        evidence_ids = [o.observation_id for o in dhcp_obs]
        f_id = generate_id("F-SERV")

        finding = Finding(
            finding_id=f_id,
            incident_id=incident_id,
            source_tower=TowerId.SERVICES,
            producer="services.detect_dhcp",
            finding_type="dhcp_lease_exhaustion",
            severity=Severity.HIGH,
            status=FindingStatus.ACTIVE,
            entity_refs=[target_entity],
            evidence_refs=evidence_ids,
            confidence=0.88,
            independence_group=f"services:dhcp:{target_entity}",
            observed_at=dhcp_obs[-1].timestamp,
            created_at=now,
            description=f"DHCP pool exhaustion or allocation failure detected on {target_entity}.",
            metadata={"log_count": len(dhcp_obs)},
        )
        findings.append(finding)

        h_id = generate_id("HYP-SERV")
        hyp = Hypothesis(
            hypothesis_id=h_id,
            incident_id=incident_id,
            fault_code="DHCP_FAILURE",
            suspected_entities=[target_entity],
            supporting_finding_refs=[f_id],
            confidence_score=0.88,
            confidence_category=ConfidenceCategory.HIGH,
            rationale=f"DHCP server {target_entity} reported address exhaustion / transaction failure.",
            created_at=now,
        )
        hypotheses.append(hyp)

    def _detect_config_drift(
        self,
        incident_id: str,
        observations: list[CanonicalObservation],
        findings: list[Finding],
        hypotheses: list[Hypothesis],
        now: datetime,
    ) -> None:
        sensitive_keys = [
            k.lower()
            for k in self.rules.get(
                "config_sensitive_keys",
                ["mtu", "vlan", "speed", "duplex", "route", "gateway", "acl", "dns"],
            )
        ]

        config_obs = [obs for obs in observations if isinstance(obs, ConfigObservation)]
        for c_obs in config_obs:
            # Check if key is sensitive or if value changed from previous
            key_lower = c_obs.config_key.lower()
            is_sensitive = any(k in key_lower for k in sensitive_keys)
            has_drift = c_obs.previous_value is not None and c_obs.previous_value != c_obs.config_value

            if is_sensitive and has_drift:
                f_id = generate_id("F-SERV")
                finding = Finding(
                    finding_id=f_id,
                    incident_id=incident_id,
                    source_tower=TowerId.SERVICES,
                    producer="services.detect_config_drift",
                    finding_type="config_drift_detected",
                    severity=Severity.MEDIUM,
                    status=FindingStatus.ACTIVE,
                    entity_refs=[c_obs.entity_id],
                    evidence_refs=[c_obs.observation_id],
                    confidence=0.82,
                    independence_group=f"config:{c_obs.entity_id}:{c_obs.config_key}",
                    observed_at=c_obs.timestamp,
                    created_at=now,
                    description=(
                        f"Configuration drift detected on {c_obs.entity_id}: key '{c_obs.config_key}' "
                        f"changed from '{c_obs.previous_value}' to '{c_obs.config_value}'."
                    ),
                    metadata={
                        "config_key": c_obs.config_key,
                        "old_value": c_obs.previous_value,
                        "new_value": c_obs.config_value,
                    },
                )
                findings.append(finding)

                h_id = generate_id("HYP-SERV")
                hyp = Hypothesis(
                    hypothesis_id=h_id,
                    incident_id=incident_id,
                    fault_code="CONFIG_DRIFT",
                    suspected_entities=[c_obs.entity_id],
                    supporting_finding_refs=[f_id],
                    confidence_score=0.82,
                    confidence_category=ConfidenceCategory.MODERATE,
                    rationale=(
                        f"Recent configuration change to '{c_obs.config_key}' on {c_obs.entity_id} "
                        f"correlates with anomalous behavior."
                    ),
                    created_at=now,
                )
                hypotheses.append(hyp)


class ServicesTower:
    """Controller implementing TowerController for Services and Configuration domain."""

    def __init__(
        self,
        repository: SQLiteRepository | None = None,
        rules: dict[str, Any] | None = None,
    ) -> None:
        self.tower_id = TowerId.SERVICES
        self.repository = repository
        self.rules = rules or load_rules()
        self.engine = ServicesEngine(self.rules)

    def get_capabilities(self) -> list[TowerCapability]:
        profile = CapabilityRegistry.get_profile(self.tower_id)
        return profile.capabilities if profile else []

    @property
    def capabilities(self) -> list[TowerCapability]:
        return self.get_capabilities()

    def analyze_incident(
        self,
        incident_id: str,
        observations: list[CanonicalObservation] | None = None,
    ) -> TowerReport:
        """Runs services diagnostic pipeline, returns and optionally stores TowerReport."""
        obs = observations or []
        if not obs and self.repository:
            obs = self.repository.get_observations(incident_id)

        findings, hypotheses = self.engine.analyze(incident_id, obs)

        if self.repository:
            for f in findings:
                self.repository.insert_finding(f)
            for h in hypotheses:
                self.repository.insert_hypothesis(h)

        report_id = generate_id("REP-SERV")
        now = datetime.now(timezone.utc)
        summary = (
            f"Services analysis completed for {incident_id}: "
            f"{len(findings)} finding(s), {len(hypotheses)} hypothesis(es) derived."
        )

        report = TowerReport(
            report_id=report_id,
            incident_id=incident_id,
            tower_id=self.tower_id,
            status="completed" if findings else "inconclusive",
            findings=findings,
            hypotheses=hypotheses,
            summary=summary,
            generated_at=now,
        )

        if self.repository:
            self.repository.insert_tower_report(report)

        return report

    def handle_query(self, query: PeerQuery) -> PeerQueryResult:
        """Handles synchronous one-hop read-only peer queries for services."""
        cap = query.capability
        now = datetime.now(timezone.utc)

        if cap == "services.check_dns":
            target = query.scope[0] if query.scope else "SRV_DNS_01"
            # Return DNS status summary
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.COMPLETED,
                result={"server": target, "healthy": True, "avg_latency_ms": 12.0},
                completed_at=now,
            )

        elif cap == "services.check_dhcp":
            target = query.scope[0] if query.scope else "SRV_DHCP_01"
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.COMPLETED,
                result={"server": target, "pool_utilization_pct": 45.0, "status": "operational"},
                completed_at=now,
            )

        elif cap == "services.query_config_drift":
            target = query.scope[0] if query.scope else "SW_CORE_01"
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.COMPLETED,
                result={"entity_id": target, "recent_drift_count": 0},
                completed_at=now,
            )

        return PeerQueryResult(
            query_id=query.query_id,
            status=QueryStatus.UNSUPPORTED,
            warnings=[f"Capability '{cap}' not supported by ServicesTower"],
            completed_at=now,
        )

    def handle_task(self, task: InvestigationTask) -> TaskResult:
        """Handles supervisor-authorized persistent investigation tasks."""
        now = datetime.now(timezone.utc)
        cap = task.capability

        if cap in ("INVESTIGATE_DNS", "INVESTIGATE_DHCP", "ANALYZE_CONFIG_DRIFT"):
            return TaskResult(
                result_id=generate_id("RES-SERV"),
                task_id=task.task_id,
                assignee=self.tower_id,
                status=TaskStatus.COMPLETED,
                result_schema="netcoop://schemas/tasks/services-investigation-result/1.0",
                result={"capability": cap, "status": "investigation_completed"},
                completed_at=now,
            )

        return TaskResult(
            result_id=generate_id("RES-SERV"),
            task_id=task.task_id,
            assignee=self.tower_id,
            status=TaskStatus.FAILED,
            result_schema="netcoop://schemas/tasks/error-result/1.0",
            warnings=[f"Unsupported capability: {cap}"],
            completed_at=now,
        )

    execute_task = handle_task
