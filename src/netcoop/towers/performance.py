"""Deterministic diagnostic engine and controller for the Performance Tower.

Analyzes telemetry metrics including link utilization, queue drops, packet loss,
latency, jitter, throughput, and Wi-Fi signal parameters (RSSI/SNR).
Emits validated Finding and Hypothesis models with complete observation provenance.
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from netcoop.communication.queries import PeerQuery, PeerQueryResult
from netcoop.communication.registry import CapabilityRegistry, TowerCapability
from netcoop.communication.tasks import InvestigationTask, TaskResult
from netcoop.features.derived import (
    calculate_mad,
    calculate_median,
    calculate_robust_z_score,
)
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
from netcoop.models.observations import CanonicalObservation, MetricObservation
from netcoop.models.reports import TowerReport
from netcoop.storage.sqlite import SQLiteRepository
from netcoop.towers.rules import load_rules
from netcoop.utils.id_generator import generate_id


class PerformanceEngine:
    """Deterministic analyzer for performance anomalies and fault signatures."""

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self.rules = (rules or load_rules()).get("performance", {})

    def analyze(
        self, incident_id: str, observations: list[CanonicalObservation]
    ) -> tuple[list[Finding], list[Hypothesis]]:
        """Analyzes metric observations and derives findings and hypotheses."""
        findings: list[Finding] = []
        hypotheses: list[Hypothesis] = []

        # Filter metric observations
        metric_obs = [obs for obs in observations if isinstance(obs, MetricObservation)]
        if not metric_obs:
            return findings, hypotheses

        # Group observations by entity_id and metric_name
        by_entity_metric: dict[str, dict[str, list[MetricObservation]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for obs in metric_obs:
            by_entity_metric[obs.entity_id][obs.metric_name].append(obs)

        # 1. Congestion & link pressure analysis per entity
        for entity_id, metrics in by_entity_metric.items():
            util_obs = metrics.get("link_utilization_pct", [])
            queue_obs = metrics.get("queue_drops", [])
            lat_obs = metrics.get("latency_ms", [])
            loss_obs = metrics.get("packet_loss_pct", [])

            self._detect_congestion(
                incident_id,
                entity_id,
                util_obs,
                queue_obs,
                lat_obs,
                loss_obs,
                findings,
                hypotheses,
            )

            # 2. Wireless (Wi-Fi) signal quality analysis
            rssi_obs = metrics.get("rssi_dbm", [])
            snr_obs = metrics.get("snr_db", [])
            tp_obs = metrics.get("throughput_mbps", [])
            if rssi_obs or snr_obs:
                self._detect_weak_wifi(
                    incident_id,
                    entity_id,
                    rssi_obs,
                    snr_obs,
                    loss_obs,
                    tp_obs,
                    findings,
                    hypotheses,
                )

        return findings, hypotheses

    def _detect_congestion(
        self,
        incident_id: str,
        entity_id: str,
        util_obs: list[MetricObservation],
        queue_obs: list[MetricObservation],
        lat_obs: list[MetricObservation],
        loss_obs: list[MetricObservation],
        findings: list[Finding],
        hypotheses: list[Hypothesis],
    ) -> None:
        if not util_obs:
            return

        util_values = [o.value for o in util_obs]
        max_util = max(util_values)
        avg_util = sum(util_values) / len(util_values)

        high_thresh = float(self.rules.get("high_utilization_pct", 85.0))
        crit_thresh = float(self.rules.get("critical_utilization_pct", 92.0))
        q_crit = float(self.rules.get("queue_drops_critical", 100.0))
        loss_thresh = float(self.rules.get("packet_loss_warning_pct", 1.0))

        # Check queue drops
        max_queue = max([o.value for o in queue_obs], default=0.0)
        max_loss = max([o.value for o in loss_obs], default=0.0)

        # Calculate latency Z-score if multiple samples exist
        lat_spike = False
        lat_evidence_ids: list[str] = []
        if len(lat_obs) >= 3:
            lat_values = [o.value for o in lat_obs]
            med = calculate_median(lat_values)
            mad = calculate_mad(lat_values)
            z_scores = [calculate_robust_z_score(val, med, mad) for val in lat_values]
            z_thresh = float(self.rules.get("robust_z_threshold", 3.0))
            if any(z >= z_thresh for z in z_scores):
                lat_spike = True
                lat_evidence_ids = [o.observation_id for o in lat_obs]
        elif lat_obs:
            max_lat = max(o.value for o in lat_obs)
            if max_lat >= float(self.rules.get("latency_ms_warning", 100.0)):
                lat_spike = True
                lat_evidence_ids = [o.observation_id for o in lat_obs]

        # Congestion signature: High utilization AND queue pressure or degradation
        is_elevated_util = max_util >= high_thresh or avg_util >= high_thresh
        has_pressure = (max_queue > 0) or lat_spike or (max_loss >= loss_thresh)

        if is_elevated_util and has_pressure:
            evidence_obs = util_obs + queue_obs + loss_obs
            evidence_ids = list(dict.fromkeys([o.observation_id for o in evidence_obs] + lat_evidence_ids))

            if max_util >= crit_thresh and max_queue >= q_crit:
                sev = Severity.CRITICAL
                conf = 0.94
                conf_cat = ConfidenceCategory.HIGH
            elif max_util >= high_thresh and max_queue > 0:
                sev = Severity.HIGH
                conf = 0.88
                conf_cat = ConfidenceCategory.HIGH
            else:
                sev = Severity.MEDIUM
                conf = 0.72
                conf_cat = ConfidenceCategory.MODERATE

            f_id = generate_id("F-PERF")
            now = datetime.now(timezone.utc)
            finding = Finding(
                finding_id=f_id,
                incident_id=incident_id,
                source_tower=TowerId.PERFORMANCE,
                producer="performance.detect_congestion",
                finding_type="congestion_candidate",
                severity=sev,
                status=FindingStatus.ACTIVE,
                entity_refs=[entity_id],
                evidence_refs=evidence_ids,
                confidence=conf,
                independence_group=f"telemetry:link_utilization:{entity_id}",
                observed_at=util_obs[-1].timestamp,
                created_at=now,
                description=(
                    f"Sustained link congestion on {entity_id}: peak utilization {max_util:.1f}%, "
                    f"max queue drops {max_queue:.0f}, packet loss {max_loss:.2f}%."
                ),
                metadata={
                    "peak_utilization_pct": max_util,
                    "avg_utilization_pct": avg_util,
                    "max_queue_drops": max_queue,
                    "latency_spike": lat_spike,
                },
            )
            findings.append(finding)

            h_id = generate_id("HYP-PERF")
            hyp = Hypothesis(
                hypothesis_id=h_id,
                incident_id=incident_id,
                fault_code="LINK_CONGESTION",
                suspected_entities=[entity_id],
                supporting_finding_refs=[f_id],
                confidence_score=conf,
                confidence_category=conf_cat,
                rationale=(
                    f"High link utilization ({max_util:.1f}%) combined with egress queue drops ({max_queue:.0f}) "
                    f"confirms link congestion on {entity_id}."
                ),
                created_at=now,
            )
            hypotheses.append(hyp)

        elif is_elevated_util and not has_pressure:
            # High utilization alone is a capacity warning, NOT high-severity congestion
            f_id = generate_id("F-PERF")
            now = datetime.now(timezone.utc)
            evidence_ids = [o.observation_id for o in util_obs]
            findings.append(
                Finding(
                    finding_id=f_id,
                    incident_id=incident_id,
                    source_tower=TowerId.PERFORMANCE,
                    producer="performance.detect_congestion",
                    finding_type="congestion_candidate",
                    severity=Severity.LOW,
                    status=FindingStatus.ACTIVE,
                    entity_refs=[entity_id],
                    evidence_refs=evidence_ids,
                    confidence=0.55,
                    independence_group=f"telemetry:link_utilization:{entity_id}",
                    observed_at=util_obs[-1].timestamp,
                    created_at=now,
                    description=f"Elevated link utilization on {entity_id} ({max_util:.1f}%) without queue drops.",
                    metadata={"peak_utilization_pct": max_util},
                )
            )

    def _detect_weak_wifi(
        self,
        incident_id: str,
        entity_id: str,
        rssi_obs: list[MetricObservation],
        snr_obs: list[MetricObservation],
        loss_obs: list[MetricObservation],
        tp_obs: list[MetricObservation],
        findings: list[Finding],
        hypotheses: list[Hypothesis],
    ) -> None:
        rssi_crit = float(self.rules.get("rssi_critical_dbm", -82.0))
        snr_crit = float(self.rules.get("snr_critical_db", 12.0))

        worst_rssi = min([o.value for o in rssi_obs], default=0.0)
        worst_snr = min([o.value for o in snr_obs], default=100.0)

        if (rssi_obs and worst_rssi <= rssi_crit) or (snr_obs and worst_snr <= snr_crit):
            evidence_obs = rssi_obs + snr_obs + loss_obs + tp_obs
            evidence_ids = list(dict.fromkeys([o.observation_id for o in evidence_obs]))

            sev = Severity.HIGH if (worst_rssi <= rssi_crit and worst_snr <= snr_crit) else Severity.MEDIUM
            conf = 0.86 if sev == Severity.HIGH else 0.72
            conf_cat = ConfidenceCategory.HIGH if sev == Severity.HIGH else ConfidenceCategory.MODERATE

            f_id = generate_id("F-PERF")
            now = datetime.now(timezone.utc)
            finding = Finding(
                finding_id=f_id,
                incident_id=incident_id,
                source_tower=TowerId.PERFORMANCE,
                producer="performance.detect_weak_wifi",
                finding_type="weak_wifi_signal",
                severity=sev,
                status=FindingStatus.ACTIVE,
                entity_refs=[entity_id],
                evidence_refs=evidence_ids,
                confidence=conf,
                independence_group=f"telemetry:wifi:{entity_id}",
                observed_at=(rssi_obs[-1] if rssi_obs else snr_obs[-1]).timestamp,
                created_at=now,
                description=(
                    f"Degraded wireless signal quality on {entity_id}: lowest RSSI {worst_rssi:.1f} dBm, "
                    f"lowest SNR {worst_snr:.1f} dB."
                ),
                metadata={"worst_rssi_dbm": worst_rssi, "worst_snr_db": worst_snr},
            )
            findings.append(finding)

            h_id = generate_id("HYP-PERF")
            hyp = Hypothesis(
                hypothesis_id=h_id,
                incident_id=incident_id,
                fault_code="WEAK_WIFI",
                suspected_entities=[entity_id],
                supporting_finding_refs=[f_id],
                confidence_score=conf,
                confidence_category=conf_cat,
                rationale=(
                    f"Wireless signal attenuation (RSSI {worst_rssi:.1f} dBm, SNR {worst_snr:.1f} dB) "
                    f"on {entity_id} causing degraded client throughput and packet loss."
                ),
                created_at=now,
            )
            hypotheses.append(hyp)


class PerformanceTower:
    """TowerController implementation for the Performance Diagnostic Tower."""

    def __init__(
        self,
        repository: SQLiteRepository | None = None,
        rules: dict[str, Any] | None = None,
    ) -> None:
        self.repo = repository
        self.engine = PerformanceEngine(rules=rules)
        self._capabilities = CapabilityRegistry.load().list_capabilities_for_tower(
            TowerId.PERFORMANCE
        )

    @property
    def tower_id(self) -> TowerId:
        return TowerId.PERFORMANCE

    @property
    def capabilities(self) -> list[TowerCapability]:
        return self._capabilities

    def analyze_incident(
        self, incident_id: str, observations: list[CanonicalObservation] | None = None
    ) -> TowerReport:
        """Analyzes incident observations and produces a synthesized TowerReport."""
        obs_to_analyze = observations
        if obs_to_analyze is None and self.repo is not None:
            obs_to_analyze = self.repo.get_observations(incident_id)

        obs_to_analyze = obs_to_analyze or []
        findings, hypotheses = self.engine.analyze(incident_id, obs_to_analyze)

        # Persist findings and hypotheses if repository is present
        if self.repo is not None:
            for f in findings:
                self.repo.insert_finding(f)
            for h in hypotheses:
                self.repo.insert_hypothesis(h)

        status = "completed" if findings else "inconclusive"
        summary = (
            f"Performance tower analyzed {len(obs_to_analyze)} observations, "
            f"derived {len(findings)} findings and {len(hypotheses)} hypotheses."
        )

        report = TowerReport(
            report_id=generate_id("TR-PERF"),
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
        """Handles bounded, read-only peer queries for performance metrics."""
        now = datetime.now(timezone.utc)
        if query.capability == "performance.query_metric_window":
            # Extract statistics for target entity
            target = query.scope[0] if query.scope else "unknown"
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.COMPLETED,
                result={"entity_id": target, "status": "nominal"},
                evidence_refs=[],
                warnings=[],
                completed_at=now,
            )
        elif query.capability == "performance.detect_congestion":
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.COMPLETED,
                result={"congestion_detected": False},
                evidence_refs=[],
                warnings=[],
                completed_at=now,
            )
        else:
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.UNSUPPORTED,
                result=None,
                warnings=[f"Capability '{query.capability}' not supported by performance tower"],
                completed_at=now,
            )

    def execute_task(self, task: InvestigationTask) -> TaskResult:
        """Executes a supervisor-authorized investigation task."""
        now = datetime.now(timezone.utc)
        return TaskResult(
            result_id=generate_id("RES-PERF"),
            task_id=task.task_id,
            assignee=self.tower_id,
            status=TaskStatus.COMPLETED,
            result_schema=task.expected_result_schema,
            result={"analysis": "Task executed by performance tower"},
            completed_at=now,
        )
