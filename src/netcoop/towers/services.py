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
from netcoop.towers.base import investigate_with_engine, query_incident_observations
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
        role_config = self.rules.get("entity_roles", {})
        dns_entities = set(role_config.get("dns_resolver", []))
        dns_target_entity = next(iter(sorted(dns_entities)), "SRV_DNS_01")
        profile_roles_configured = bool(dns_entities)

        for obs in observations:
            # Check metrics on DNS servers or dns latency metrics
            if isinstance(obs, MetricObservation):
                is_dns_entity = obs.entity_id in dns_entities or (
                    not profile_roles_configured and "DNS" in obs.entity_id.upper()
                )
                if is_dns_entity and obs.metric_name == "latency_ms":
                    dns_obs.append(obs)
                    dns_target_entity = obs.entity_id
                    if obs.value > max_dns_latency:
                        max_dns_latency = obs.value
            elif isinstance(obs, LogObservation):
                msg_upper = obs.message.upper()
                is_dns_entity = obs.entity_id in dns_entities or (
                    not profile_roles_configured and "DNS" in obs.entity_id.upper()
                )
                if is_dns_entity or any(k in msg_upper for k in dns_keywords):
                    if any(k in msg_upper for k in dns_keywords) or obs.log_level in ("ERROR", "CRITICAL"):
                        dns_obs.append(obs)
                        dns_target_entity = obs.entity_id
                        has_severe_error = True

        if not dns_obs:
            return

        evidence_ids = [
            o.observation_id for o in dns_obs
            if (isinstance(o, MetricObservation) and o.metric_name == "latency_ms" and o.value >= dns_lat_warn)
            or (isinstance(o, LogObservation) and any(k in o.message.upper() for k in dns_keywords))
        ]

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
                "dhcp_error_keywords", ["EXHAUSTED", "NAK", "POOL_FULL", "DHCP_FAILURE", "DHCP"]
            )
        ]

        dhcp_obs: list[CanonicalObservation] = []
        role_config = self.rules.get("entity_roles", {})
        dhcp_entities = set(role_config.get("dhcp_server", []))
        target_entity = next(iter(sorted(dhcp_entities)), "SRV_DHCP_01")
        profile_roles_configured = bool(dhcp_entities)

        for obs in observations:
            if isinstance(obs, LogObservation):
                msg_upper = obs.message.upper()
                is_dhcp_entity = obs.entity_id in dhcp_entities or (
                    not profile_roles_configured and "DHCP" in obs.entity_id.upper()
                )
                has_dhcp_signal = any(k in msg_upper for k in dhcp_keywords)
                if has_dhcp_signal or (
                    is_dhcp_entity and obs.log_level in ("ERROR", "CRITICAL")
                ):
                    dhcp_obs.append(obs)
                    target_entity = obs.entity_id
            elif isinstance(obs, MetricObservation) and (
                obs.entity_id in dhcp_entities
                or (not profile_roles_configured and "DHCP" in obs.entity_id.upper())
            ):
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
            fault_code = "DNS_FAILURE"

        elif cap == "services.check_dhcp":
            fault_code = "DHCP_FAILURE"

        elif cap == "services.query_config_drift":
            fault_code = "CONFIG_DRIFT"
        else:
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.UNSUPPORTED,
                warnings=[f"Capability '{cap}' not supported by ServicesTower"],
                completed_at=now,
            )

        if not query.scope:
            return PeerQueryResult(
                query_id=query.query_id, status=QueryStatus.INVALID_SCOPE,
                warnings=[f"{cap} requires an entity scope."], completed_at=now,
            )
        scoped = query_incident_observations(self.repository, query)
        findings, hypotheses = self.engine.analyze(query.incident_id, scoped)
        relevant_findings = [finding for finding in findings if any(
            entity in query.scope or any(entity.startswith(f"{target}:") for target in query.scope)
            for entity in finding.entity_refs
        ) and finding.finding_type in {
            "dns_resolution_failure" if fault_code == "DNS_FAILURE" else
            "dhcp_lease_exhaustion" if fault_code == "DHCP_FAILURE" else
            "config_drift_detected"
        }]
        relevant_hypotheses = [hyp for hyp in hypotheses if hyp.fault_code == fault_code]
        refs = list(dict.fromkeys(ref for finding in relevant_findings for ref in finding.evidence_refs))
        if fault_code == "DNS_FAILURE":
            has_relevant_inputs = any(
                isinstance(item, LogObservation)
                or isinstance(item, MetricObservation) and item.metric_name == "latency_ms"
                for item in scoped
            )
        elif fault_code == "DHCP_FAILURE":
            has_relevant_inputs = any(
                isinstance(item, LogObservation)
                or isinstance(item, MetricObservation) and item.metric_name in {"latency_ms", "packet_loss_pct"}
                for item in scoped
            )
        else:
            has_relevant_inputs = any(isinstance(item, ConfigObservation) for item in scoped)
        return PeerQueryResult(
            query_id=query.query_id,
            status=QueryStatus.COMPLETED,
            result={
                "entities": query.scope,
                "fault_code": fault_code,
                "status": "failure_signal_observed" if relevant_hypotheses else "no_failure_signal_observed" if has_relevant_inputs else "unknown",
                "findings": [finding.model_dump(mode="json") for finding in relevant_findings],
                "hypotheses": [hyp.model_dump(mode="json") for hyp in relevant_hypotheses],
            },
            evidence_refs=refs,
            warnings=[] if has_relevant_inputs else ["No matching incident evidence was available; no live service query was made."],
            completed_at=now,
        )

    def handle_task(self, task: InvestigationTask) -> TaskResult:
        """Handles supervisor-authorized persistent investigation tasks."""
        now = datetime.now(timezone.utc)
        result, finding_refs, evidence_refs, warnings = investigate_with_engine(
            self.engine, self.repository, task
        )
        return TaskResult(
            result_id=generate_id("RES-SERV"),
            task_id=task.task_id,
            assignee=self.tower_id,
            status=TaskStatus.COMPLETED,
            result_schema=task.expected_result_schema,
            result=result,
            finding_refs=finding_refs,
            evidence_refs=evidence_refs,
            warnings=warnings,
            completed_at=now,
        )

    execute_task = handle_task
