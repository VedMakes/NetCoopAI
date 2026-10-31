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
from netcoop.towers.base import investigate_with_engine, query_incident_observations
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
        if len(lat_obs) >= 3:
            lat_values = [o.value for o in lat_obs]
            med = calculate_median(lat_values)
            mad = calculate_mad(lat_values)
            z_scores = [calculate_robust_z_score(val, med, mad) for val in lat_values]
            z_thresh = float(self.rules.get("robust_z_threshold", 3.0))
            if any(z >= z_thresh for z in z_scores):
                lat_spike = True
        elif lat_obs:
            max_lat = max(o.value for o in lat_obs)
            if max_lat >= float(self.rules.get("latency_ms_warning", 100.0)):
                lat_spike = True

        # Congestion signature: High utilization AND queue pressure or degradation
        is_elevated_util = max_util >= high_thresh or avg_util >= high_thresh
        has_pressure = (max_queue > 0) or lat_spike or (max_loss >= loss_thresh)
        # Collectors can timestamp metrics from one poll a few milliseconds apart.
        # Correlate within a five-second bucket, while keeping distinct 30-second
        # generator samples separate.
        def sample_bucket(obs: MetricObservation) -> int:
            return int(obs.timestamp.timestamp() // 5)

        def max_by_sample(observations: list[MetricObservation]) -> dict[int, float]:
            values: dict[int, float] = {}
            for observation in observations:
                bucket = sample_bucket(observation)
                values[bucket] = max(values.get(bucket, float("-inf")), observation.value)
            return values

        queue_by_time = max_by_sample(queue_obs)
        loss_by_time = max_by_sample(loss_obs)
        latency_by_time = max_by_sample(lat_obs)
        qualifying_times = {
            sample_bucket(o) for o in util_obs
            if o.value >= high_thresh and (
                queue_by_time.get(sample_bucket(o), 0.0) > 0
                or loss_by_time.get(sample_bucket(o), 0.0) >= loss_thresh
                or latency_by_time.get(sample_bucket(o), 0.0)
                >= float(self.rules.get("latency_ms_warning", 100.0))
            )
        }
        min_persistent_samples = int(self.rules.get("min_persistent_samples", 2))
        single_snapshot = len({sample_bucket(o) for o in util_obs}) == 1

        if is_elevated_util and has_pressure and (
            len(qualifying_times) >= min_persistent_samples
            or (single_snapshot and bool(qualifying_times))
        ):
            evidence_obs = [
                o for o in util_obs + queue_obs + loss_obs + lat_obs
                if sample_bucket(o) in qualifying_times and (
                    (o.metric_name == "link_utilization_pct" and o.value >= high_thresh)
                    or (o.metric_name == "queue_drops" and o.value > 0)
                    or (o.metric_name == "packet_loss_pct" and o.value >= loss_thresh)
                    or (o.metric_name == "latency_ms" and o.value >= float(self.rules.get("latency_ms_warning", 100.0)))
                )
            ]
            evidence_ids = list(dict.fromkeys(o.observation_id for o in evidence_obs))

            if max_util >= crit_thresh and max_queue >= q_crit and len(qualifying_times) >= 3:
                sev = Severity.CRITICAL
                conf = 0.94
                conf_cat = ConfidenceCategory.HIGH
            elif max_util >= high_thresh and max_queue > 0 and len(qualifying_times) >= 3:
                sev = Severity.HIGH
                conf = 0.88
                conf_cat = ConfidenceCategory.HIGH
            else:
                sev = Severity.MEDIUM
                conf = 0.55
                conf_cat = ConfidenceCategory.LOW
            if single_snapshot:
                # A complete high-pressure snapshot is actionable, but cannot
                # establish persistence without a time series.
                if max_util >= crit_thresh and max_queue >= q_crit:
                    sev = Severity.HIGH
                conf = 0.45
                conf_cat = ConfidenceCategory.LOW

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
                    f"Link congestion candidate on {entity_id}: pressure in {len(qualifying_times)} "
                    f"of {len(util_obs)} samples; peak utilization {max_util:.1f}%, "
                    f"max queue drops {max_queue:.0f}, packet loss {max_loss:.2f}%."
                ),
                metadata={
                    "peak_utilization_pct": max_util,
                    "avg_utilization_pct": avg_util,
                    "max_queue_drops": max_queue,
                    "latency_spike": lat_spike,
                    "qualifying_samples": len(qualifying_times),
                    "observed_samples": len(util_obs),
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
                    f"Repeated high utilization and link pressure support congestion on {entity_id} "
                    f"({len(qualifying_times)} correlated samples)."
                ),
                created_at=now,
            )
            hypotheses.append(hyp)

        elif is_elevated_util and has_pressure:
            transient_evidence = [
                o for o in util_obs + queue_obs + loss_obs + lat_obs
                if (o.metric_name == "link_utilization_pct" and o.value >= high_thresh)
                or (o.metric_name == "queue_drops" and o.value > 0)
                or (o.metric_name == "packet_loss_pct" and o.value >= loss_thresh)
                or (o.metric_name == "latency_ms" and o.value >= float(self.rules.get("latency_ms_warning", 100.0)))
            ]
            evidence_ids = list(dict.fromkeys(o.observation_id for o in transient_evidence))
            if not evidence_ids:
                return
            findings.append(
                Finding(
                    finding_id=generate_id("F-PERF"), incident_id=incident_id,
                    source_tower=TowerId.PERFORMANCE, producer="performance.detect_congestion",
                    finding_type="congestion_candidate", severity=Severity.LOW,
                    status=FindingStatus.ACTIVE, entity_refs=[entity_id], evidence_refs=evidence_ids,
                    confidence=0.35, independence_group=f"telemetry:link_utilization:{entity_id}",
                    observed_at=util_obs[-1].timestamp, created_at=datetime.now(timezone.utc),
                    description=(f"Transient congestion-like spike on {entity_id}: "
                                 f"{len(qualifying_times)} correlated sample(s); "
                                 f"{min_persistent_samples} required for diagnosis."),
                    metadata={"qualifying_samples": len(qualifying_times), "observed_samples": len(util_obs)},
                )
            )

        elif is_elevated_util and not has_pressure:
            f_id = generate_id("F-PERF")
            now = datetime.now(timezone.utc)
            evidence_ids = [o.observation_id for o in util_obs]
            missing_signals = []
            if not queue_obs:
                missing_signals.append("queue_drops")
            if not loss_obs:
                missing_signals.append("packet_loss_pct")

            if missing_signals:
                desc = (
                    f"Elevated link utilization on {entity_id} ({max_util:.1f}%), but corroborating "
                    f"buffer pressure observations ({', '.join(missing_signals)}) are missing or unavailable."
                )
            else:
                desc = f"Elevated link utilization on {entity_id} ({max_util:.1f}%) without queue drops."
            finding_type = "congestion_candidate"

            findings.append(
                Finding(
                    finding_id=f_id,
                    incident_id=incident_id,
                    source_tower=TowerId.PERFORMANCE,
                    producer="performance.detect_congestion",
                    finding_type=finding_type,
                    severity=Severity.LOW,
                    status=FindingStatus.ACTIVE,
                    entity_refs=[entity_id],
                    evidence_refs=evidence_ids,
                    confidence=0.35 if missing_signals else 0.55,
                    independence_group=f"telemetry:link_utilization:{entity_id}",
                    observed_at=util_obs[-1].timestamp,
                    created_at=now,
                    description=desc,
                    metadata={
                        "peak_utilization_pct": max_util,
                        "missing_signals": missing_signals,
                        "has_missing_pressure": bool(missing_signals),
                        "disposition": "insufficient_evidence" if missing_signals else "no_pressure",
                    },
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
            bad_times = {
                o.timestamp for o in rssi_obs if o.value <= rssi_crit
            } | {o.timestamp for o in snr_obs if o.value <= snr_crit}
            evidence_obs = [
                o for o in rssi_obs + snr_obs + loss_obs + tp_obs
                if o.timestamp in bad_times
                and ((o.metric_name == "rssi_dbm" and o.value <= rssi_crit)
                     or (o.metric_name == "snr_db" and o.value <= snr_crit)
                     or (o.metric_name not in ("rssi_dbm", "snr_db") and o.value > 0))
            ]
            evidence_ids = list(dict.fromkeys(o.observation_id for o in evidence_obs))

            min_persistent_samples = int(self.rules.get("min_persistent_samples", 2))
            single_snapshot = len({o.timestamp for o in rssi_obs + snr_obs}) == 1
            if len(bad_times) < min_persistent_samples and not single_snapshot:
                findings.append(
                    Finding(
                        finding_id=generate_id("F-PERF"), incident_id=incident_id,
                        source_tower=TowerId.PERFORMANCE, producer="performance.detect_weak_wifi",
                        finding_type="weak_wifi_signal", severity=Severity.LOW,
                        status=FindingStatus.ACTIVE, entity_refs=[entity_id], evidence_refs=evidence_ids,
                        confidence=0.35, independence_group=f"telemetry:wifi:{entity_id}",
                        observed_at=(rssi_obs[-1] if rssi_obs else snr_obs[-1]).timestamp,
                        created_at=datetime.now(timezone.utc),
                        description=f"Transient poor signal reading on {entity_id}; persistence not established.",
                        metadata={"qualifying_samples": len(bad_times)},
                    )
                )
                return

            sev = Severity.HIGH if (worst_rssi <= rssi_crit and worst_snr <= snr_crit) else Severity.MEDIUM
            conf = 0.86 if sev == Severity.HIGH and len(bad_times) >= 3 else 0.45
            conf_cat = ConfidenceCategory.HIGH if conf >= 0.8 else ConfidenceCategory.LOW

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
                metadata={"worst_rssi_dbm": worst_rssi, "worst_snr_db": worst_snr,
                          "qualifying_samples": len(bad_times),
                          "observed_samples": len({o.timestamp for o in rssi_obs + snr_obs})},
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
            if not query.scope:
                return PeerQueryResult(
                    query_id=query.query_id, status=QueryStatus.INVALID_SCOPE,
                    warnings=["performance.query_metric_window requires an entity scope."],
                    completed_at=now,
                )
            scoped = query_incident_observations(self.repo, query)
            metrics: dict[str, list[MetricObservation]] = defaultdict(list)
            for observation in scoped:
                if isinstance(observation, MetricObservation):
                    metrics[observation.metric_name].append(observation)
            summary = {
                name: {
                    "count": len(items),
                    "min": min(item.value for item in items),
                    "max": max(item.value for item in items),
                    "latest": max(items, key=lambda item: item.timestamp).value,
                    "latest_at": max(item.timestamp for item in items).isoformat(),
                    "evidence_refs": [item.observation_id for item in items],
                }
                for name, items in metrics.items()
            }
            refs = [item.observation_id for items in metrics.values() for item in items]
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.COMPLETED,
                result={"entities": query.scope, "metric_summary": summary, "observation_count": len(scoped)},
                evidence_refs=refs,
                warnings=[] if scoped else ["No matching incident observations were available; no live device query was made."],
                completed_at=now,
            )
        elif query.capability == "performance.detect_congestion":
            if not query.scope:
                return PeerQueryResult(
                    query_id=query.query_id, status=QueryStatus.INVALID_SCOPE,
                    warnings=["performance.detect_congestion requires an entity scope."],
                    completed_at=now,
                )
            scoped = query_incident_observations(self.repo, query)
            findings, hypotheses = self.engine.analyze(query.incident_id, scoped)
            refs = list(dict.fromkeys(ref for finding in findings for ref in finding.evidence_refs))
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.COMPLETED,
                result={
                    "congestion_detected": any(hyp.fault_code == "LINK_CONGESTION" for hyp in hypotheses),
                    "findings": [finding.model_dump(mode="json") for finding in findings],
                    "hypotheses": [hyp.model_dump(mode="json") for hyp in hypotheses],
                },
                evidence_refs=refs,
                warnings=[] if scoped else ["No matching incident observations were available; no live device query was made."],
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
        result, finding_refs, evidence_refs, warnings = investigate_with_engine(
            self.engine, self.repo, task
        )
        return TaskResult(
            result_id=generate_id("RES-PERF"),
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
