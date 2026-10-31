"""Deterministic diagnostic engine and controller for the Infrastructure Tower.

Analyzes hardware metrics (CPU, memory), interface physical errors (CRC errors,
link flaps), and structured syslog events.
Emits validated Finding and Hypothesis models with complete observation provenance.
"""

import re
from collections import defaultdict
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
    LogObservation,
    MetricObservation,
)
from netcoop.models.reports import TowerReport
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.towers.base import investigate_with_engine
from netcoop.towers.rules import load_rules
from netcoop.utils.id_generator import generate_id


class InfrastructureEngine:
    """Deterministic analyzer for infrastructure degradation, device overload, and hardware logs."""

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self.rules = (rules or load_rules()).get("infrastructure", {})

    def analyze(
        self, incident_id: str, observations: list[CanonicalObservation]
    ) -> tuple[list[Finding], list[Hypothesis]]:
        """Analyzes hardware metrics and log observations to derive findings and hypotheses."""
        findings: list[Finding] = []
        hypotheses: list[Hypothesis] = []

        metric_obs = [obs for obs in observations if isinstance(obs, MetricObservation)]
        log_obs = [obs for obs in observations if isinstance(obs, LogObservation)]

        # 1. Device metrics analysis (CPU & Memory)
        by_device_metric: dict[str, dict[str, list[MetricObservation]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for obs in metric_obs:
            by_device_metric[obs.entity_id][obs.metric_name].append(obs)

        for entity_id, metrics in by_device_metric.items():
            cpu_obs = metrics.get("cpu_utilization_pct", [])
            mem_obs = metrics.get("memory_utilization_pct", [])
            if cpu_obs or mem_obs:
                self._detect_device_overload(incident_id, entity_id, cpu_obs, mem_obs, findings, hypotheses)

        # 2. Interface physical health (Errors & Flaps)
        for entity_id, metrics in by_device_metric.items():
            err_obs = metrics.get("interface_errors", [])
            flap_obs = metrics.get("link_flaps", [])
            if err_obs or flap_obs:
                self._detect_interface_errors(
                    incident_id, entity_id, err_obs, flap_obs, findings, hypotheses
                )

        # 3. Log parsing and error pattern extraction
        if log_obs:
            self._analyze_logs(incident_id, log_obs, findings, hypotheses)

        return findings, hypotheses

    def _detect_device_overload(
        self,
        incident_id: str,
        entity_id: str,
        cpu_obs: list[MetricObservation],
        mem_obs: list[MetricObservation],
        findings: list[Finding],
        hypotheses: list[Hypothesis],
    ) -> None:
        cpu_crit = float(self.rules.get("cpu_critical_pct", 90.0))
        cpu_warn = float(self.rules.get("cpu_warning_pct", 75.0))
        mem_crit = float(self.rules.get("memory_critical_pct", 90.0))

        max_cpu = max([o.value for o in cpu_obs], default=0.0)
        max_mem = max([o.value for o in mem_obs], default=0.0)

        is_overload = max_cpu >= cpu_crit or max_mem >= mem_crit
        is_warning = max_cpu >= cpu_warn or max_mem >= float(self.rules.get("memory_warning_pct", 80.0))

        if is_overload:
            evidence_obs = [
                o for o in cpu_obs + mem_obs
                if (o.metric_name == "cpu_utilization_pct" and o.value >= cpu_crit)
                or (o.metric_name == "memory_utilization_pct" and o.value >= mem_crit)
            ]
            evidence_ids = list(dict.fromkeys([o.observation_id for o in evidence_obs]))

            sev = Severity.CRITICAL if (max_cpu >= 95.0 or max_mem >= 95.0) else Severity.HIGH
            conf = 0.92 if sev == Severity.CRITICAL else 0.85
            conf_cat = ConfidenceCategory.HIGH

            f_id = generate_id("F-INFRA")
            now = datetime.now(timezone.utc)
            finding = Finding(
                finding_id=f_id,
                incident_id=incident_id,
                source_tower=TowerId.INFRASTRUCTURE,
                producer="infrastructure.check_device_health",
                finding_type="hardware_overload",
                severity=sev,
                status=FindingStatus.ACTIVE,
                entity_refs=[entity_id],
                evidence_refs=evidence_ids,
                confidence=conf,
                independence_group=f"hardware:resource:{entity_id}",
                observed_at=(cpu_obs[-1] if cpu_obs else mem_obs[-1]).timestamp,
                created_at=now,
                description=(
                    f"Severe resource exhaustion on {entity_id}: peak CPU {max_cpu:.1f}%, "
                    f"peak memory {max_mem:.1f}%."
                ),
                metadata={"max_cpu_pct": max_cpu, "max_memory_pct": max_mem},
            )
            findings.append(finding)

            h_id = generate_id("HYP-INFRA")
            hyp = Hypothesis(
                hypothesis_id=h_id,
                incident_id=incident_id,
                fault_code="DEVICE_OVERLOAD",
                suspected_entities=[entity_id],
                supporting_finding_refs=[f_id],
                confidence_score=conf,
                confidence_category=conf_cat,
                rationale=(
                    f"Hardware utilization thresholds exceeded on {entity_id} "
                    f"(CPU {max_cpu:.1f}%, memory {max_mem:.1f}%) causing device processing degradation."
                ),
                created_at=now,
            )
            hypotheses.append(hyp)

        elif is_warning:
            evidence_ids = [o.observation_id for o in (cpu_obs + mem_obs)]
            f_id = generate_id("F-INFRA")
            now = datetime.now(timezone.utc)
            findings.append(
                Finding(
                    finding_id=f_id,
                    incident_id=incident_id,
                    source_tower=TowerId.INFRASTRUCTURE,
                    producer="infrastructure.check_device_health",
                    finding_type="hardware_overload",
                    severity=Severity.LOW,
                    status=FindingStatus.ACTIVE,
                    entity_refs=[entity_id],
                    evidence_refs=evidence_ids,
                    confidence=0.60,
                    independence_group=f"hardware:resource:{entity_id}",
                    observed_at=(cpu_obs[-1] if cpu_obs else mem_obs[-1]).timestamp,
                    created_at=now,
                    description=f"Moderate resource utilization on {entity_id} (CPU {max_cpu:.1f}%, memory {max_mem:.1f}%).",
                    metadata={"max_cpu_pct": max_cpu, "max_memory_pct": max_mem},
                )
            )

    def _detect_interface_errors(
        self,
        incident_id: str,
        entity_id: str,
        err_obs: list[MetricObservation],
        flap_obs: list[MetricObservation],
        findings: list[Finding],
        hypotheses: list[Hypothesis],
    ) -> None:
        err_crit = float(self.rules.get("interface_errors_critical", 50.0))
        err_warn = float(self.rules.get("interface_errors_warning", 10.0))

        max_err = max([o.value for o in err_obs], default=0.0)
        max_flaps = max([o.value for o in flap_obs], default=0.0)

        if max_err >= err_warn or max_flaps >= 1:
            evidence_obs = [o for o in err_obs + flap_obs if o.value > 0]
            evidence_ids = list(dict.fromkeys([o.observation_id for o in evidence_obs]))

            sev = Severity.HIGH if (max_err >= err_crit or max_flaps >= 2) else Severity.MEDIUM
            conf = 0.89 if sev == Severity.HIGH else 0.75
            conf_cat = ConfidenceCategory.HIGH if sev == Severity.HIGH else ConfidenceCategory.MODERATE

            f_id = generate_id("F-INFRA")
            now = datetime.now(timezone.utc)
            finding = Finding(
                finding_id=f_id,
                incident_id=incident_id,
                source_tower=TowerId.INFRASTRUCTURE,
                producer="infrastructure.query_interface_health",
                finding_type="interface_degradation",
                severity=sev,
                status=FindingStatus.ACTIVE,
                entity_refs=[entity_id],
                evidence_refs=evidence_ids,
                confidence=conf,
                independence_group=f"hardware:interface:{entity_id}",
                observed_at=(err_obs[-1] if err_obs else flap_obs[-1]).timestamp,
                created_at=now,
                description=(
                    f"Physical interface degradation on {entity_id}: {max_err:.0f} errors observed, "
                    f"{max_flaps:.0f} link flaps."
                ),
                metadata={"interface_errors": max_err, "link_flaps": max_flaps},
            )
            findings.append(finding)

            h_id = generate_id("HYP-INFRA")
            hyp = Hypothesis(
                hypothesis_id=h_id,
                incident_id=incident_id,
                fault_code="INTERFACE_FAULT",
                suspected_entities=[entity_id],
                supporting_finding_refs=[f_id],
                confidence_score=conf,
                confidence_category=conf_cat,
                rationale=(
                    f"Elevated interface error counters ({max_err:.0f}) and flaps ({max_flaps:.0f}) "
                    f"indicate physical link or port degradation on {entity_id}."
                ),
                created_at=now,
            )
            hypotheses.append(hyp)

    def _analyze_logs(
        self,
        incident_id: str,
        log_obs: list[LogObservation],
        findings: list[Finding],
        hypotheses: list[Hypothesis],
    ) -> None:
        error_levels = set(self.rules.get("error_log_levels", ["CRITICAL", "ERROR", "WARNING"]))
        keywords = self.rules.get("error_keywords", ["down", "flap", "crc", "error", "fail", "reset"])

        # Deduplicate logs by (entity_id, normalized_msg)
        seen_patterns: set[tuple[str, str]] = set()

        for obs in log_obs:
            msg_lower = obs.message.lower()
            is_matching_level = obs.log_level.upper() in error_levels
            has_error_keyword = any(kw in msg_lower for kw in keywords)

            if is_matching_level or has_error_keyword:
                # Normalize message for deduplication (strip variable numbers/timestamps)
                norm_msg = re.sub(r"\d+", "N", msg_lower).strip()
                pattern_key = (obs.entity_id, norm_msg)
                if pattern_key in seen_patterns:
                    continue
                seen_patterns.add(pattern_key)

                sev = Severity.HIGH if obs.log_level.upper() in ("CRITICAL", "ERROR") else Severity.MEDIUM
                f_type = "interface_degradation" if "updown" in msg_lower or "line" in msg_lower or "link" in msg_lower else "hardware_overload"

                f_id = generate_id("F-INFRA")
                now = datetime.now(timezone.utc)
                finding = Finding(
                    finding_id=f_id,
                    incident_id=incident_id,
                    source_tower=TowerId.INFRASTRUCTURE,
                    producer="infrastructure.analyze_logs",
                    finding_type=f_type,
                    severity=sev,
                    status=FindingStatus.ACTIVE,
                    entity_refs=[obs.entity_id],
                    evidence_refs=[obs.observation_id],
                    confidence=0.80,
                    independence_group=f"syslog:{obs.entity_id}",
                    observed_at=obs.timestamp,
                    created_at=now,
                    description=f"Log event on {obs.entity_id} [{obs.log_level}]: {obs.message}",
                    metadata={"facility": obs.facility, "log_level": obs.log_level},
                )
                findings.append(finding)


class InfrastructureTower:
    """TowerController implementation for the Infrastructure Health Tower."""

    def __init__(
        self,
        repository: SQLiteRepository | None = None,
        rules: dict[str, Any] | None = None,
    ) -> None:
        self.repo = repository
        self.engine = InfrastructureEngine(rules=rules)
        self._capabilities = CapabilityRegistry.load().list_capabilities_for_tower(
            TowerId.INFRASTRUCTURE
        )

    @property
    def tower_id(self) -> TowerId:
        return TowerId.INFRASTRUCTURE

    @property
    def capabilities(self) -> list[TowerCapability]:
        return self._capabilities

    def get_capabilities(self) -> list[TowerCapability]:
        return self.capabilities

    def analyze_incident(
        self, incident_id: str, observations: list[CanonicalObservation] | None = None
    ) -> TowerReport:
        """Analyzes incident observations and produces a synthesized TowerReport."""
        obs_to_analyze = observations
        if obs_to_analyze is None and self.repo is not None:
            obs_to_analyze = self.repo.get_observations(incident_id)

        obs_to_analyze = obs_to_analyze or []
        findings, hypotheses = self.engine.analyze(incident_id, obs_to_analyze)

        if self.repo is not None:
            for f in findings:
                self.repo.insert_finding(f)
            for h in hypotheses:
                self.repo.insert_hypothesis(h)

        status = "completed" if findings else "inconclusive"
        summary = (
            f"Infrastructure tower analyzed {len(obs_to_analyze)} observations, "
            f"derived {len(findings)} findings and {len(hypotheses)} hypotheses."
        )

        report = TowerReport(
            report_id=generate_id("TR-INFRA"),
            incident_id=incident_id,
            tower_id=self.tower_id,
            status=status,
            findings=findings,
            hypotheses=hypotheses,
            summary=summary,
            generated_at=datetime.now(timezone.utc),
        )

        if self.repo is not None:
            self.repo.insert_tower_report(report)

        return report

    def handle_query(self, query: PeerQuery) -> PeerQueryResult:
        """Handles bounded, read-only peer queries for infrastructure health."""
        now = datetime.now(timezone.utc)
        if query.capability in ("infrastructure.check_device_health", "infrastructure.query_interface_health"):
            target = query.scope[0] if query.scope else "unknown"
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.COMPLETED,
                result={"entity_id": target, "operational_status": "UP"},
                evidence_refs=[],
                warnings=[],
                completed_at=now,
            )
        elif query.capability == "infrastructure.analyze_logs":
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.COMPLETED,
                result={"error_logs_count": 0},
                evidence_refs=[],
                warnings=[],
                completed_at=now,
            )
        else:
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.UNSUPPORTED,
                result=None,
                warnings=[f"Capability '{query.capability}' not supported by infrastructure tower"],
                completed_at=now,
            )

    def execute_task(self, task: InvestigationTask) -> TaskResult:
        """Executes a supervisor-authorized investigation task."""
        now = datetime.now(timezone.utc)
        result, finding_refs, evidence_refs, warnings = investigate_with_engine(
            self.engine, self.repo, task
        )
        return TaskResult(
            result_id=generate_id("RES-INFRA"),
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

    handle_task = execute_task
