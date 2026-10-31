"""Base protocols and interfaces for diagnostic tower controllers."""

from typing import Any, Protocol, runtime_checkable

from netcoop.communication.queries import PeerQuery, PeerQueryResult
from netcoop.communication.registry import TowerCapability
from netcoop.communication.tasks import HypothesisReview, InvestigationTask, TaskResult
from netcoop.models.enums import TowerId
from netcoop.models.observations import (
    CanonicalObservation,
    ConfigObservation,
    LogObservation,
    MetricObservation,
)
from netcoop.models.reports import TowerReport


def query_incident_observations(repository: Any, query: PeerQuery) -> list[CanonicalObservation]:
    """Return bounded, read-only observations matching a peer query scope and window."""
    if repository is None:
        return []
    scope = set(query.scope)
    metric_names = set(query.constraints.get("metric_names", []))
    limit = max(1, min(int(query.constraints.get("limit", 250)), 1000))
    start, end = query.time_window or (None, None)
    selected: list[CanonicalObservation] = []
    for observation in repository.get_observations(query.incident_id):
        entity_match = (
            not scope
            or observation.entity_id in scope
            or any(observation.entity_id.startswith(f"{entity}:") for entity in scope)
            or getattr(observation, "source_entity", None) in scope
            or getattr(observation, "target_entity", None) in scope
        )
        if not entity_match or (start and observation.timestamp < start) or (end and observation.timestamp > end):
            continue
        if metric_names and (
            not isinstance(observation, MetricObservation)
            or observation.metric_name not in metric_names
        ):
            continue
        selected.append(observation)
        if len(selected) >= limit:
            break
    return selected


def investigate_with_engine(
    engine: Any, repository: Any, task: InvestigationTask
) -> tuple[dict[str, Any], list[str], list[str], list[str]]:
    """Run a task against persisted incident observations and return a typed artifact payload."""
    if repository is None:
        return {
            "incident_id": task.incident_id,
            "capability": task.capability,
            "target_entities": task.objective.get("target_entities", []),
            "findings": [], "hypotheses": [], "finding_refs": [], "evidence_refs": [], "observation_count": 0,
            "summary": "No incident repository is configured.",
        }, [], [], ["Task could not inspect telemetry without a repository."]

    observations = repository.get_observations(task.incident_id)
    targets = (
        task.objective.get("target_entities")
        or task.objective.get("scope")
        or task.constraints.get("scope")
        or []
    )
    if targets:
        target_set = set(targets)
        observations = [
            obs for obs in observations
            if obs.entity_id in target_set
            or any(obs.entity_id.startswith(f"{target}:") for target in target_set)
            or (getattr(obs, "source_entity", None) in target_set)
            or (getattr(obs, "target_entity", None) in target_set)
        ]
    if not observations:
        return {
            "incident_id": task.incident_id,
            "capability": task.capability,
            "target_entities": targets,
            "findings": [], "hypotheses": [], "finding_refs": [], "evidence_refs": [], "observation_count": 0,
            "summary": "No telemetry matched the task scope.",
        }, [], [], ["No telemetry matched the task scope."]

    review_code = task.objective.get("hypothesis_code")
    if review_code:
        review_findings, review_hypotheses = engine.analyze(task.incident_id, observations)
        review = _review_hypothesis(
            engine, str(review_code), observations, review_findings, review_hypotheses
        )
        review_refs = list(dict.fromkeys(
            review.supporting_evidence_refs
            + review.contradicting_evidence_refs
            + review.inspected_evidence_refs
        ))
        result = {
            "incident_id": task.incident_id,
            "capability": task.capability,
            "target_entities": targets,
            "findings": [],
            "hypotheses": [],
            "finding_refs": [],
            "evidence_refs": review_refs,
            "observation_count": len(observations),
            "summary": review.summary,
            "hypothesis_reviews": [review.model_dump(mode="json")],
        }
        return result, [], review_refs, []

    findings, hypotheses = engine.analyze(task.incident_id, observations)
    if targets:
        target_set = set(targets)
        findings = [f for f in findings if any(
            ent in target_set or any(ent.startswith(f"{target}:") for target in target_set)
            for ent in f.entity_refs
        )]
        hypotheses = [h for h in hypotheses if any(
            ent in target_set or any(ent.startswith(f"{target}:") for target in target_set)
            for ent in h.suspected_entities
        )]
    finding_refs = [f.finding_id for f in findings]
    evidence_refs = list(dict.fromkeys(ref for finding in findings for ref in finding.evidence_refs))
    result = {
        "incident_id": task.incident_id,
        "capability": task.capability,
        "target_entities": targets,
        "findings": [f.model_dump(mode="json") for f in findings],
        "hypotheses": [h.model_dump(mode="json") for h in hypotheses],
        "finding_refs": finding_refs,
        "evidence_refs": evidence_refs,
        "observation_count": len(observations),
        "summary": f"{len(findings)} finding(s) and {len(hypotheses)} hypothesis(es) returned for {len(observations)} scoped observations.",
    }
    return result, finding_refs, evidence_refs, []


def _review_hypothesis(
    engine: Any,
    fault_code: str,
    observations: list[CanonicalObservation],
    findings: list[Any],
    hypotheses: list[Any],
) -> HypothesisReview:
    """Recheck a hypothesis against its expected signals and explicit counter-signals."""
    supporting_hypotheses = [item for item in hypotheses if item.fault_code == fault_code]
    support_findings = [
        finding for finding in findings
        if any(finding.finding_id in hyp.supporting_finding_refs for hyp in supporting_hypotheses)
    ]
    supporting_refs = list(dict.fromkeys(
        ref for finding in support_findings for ref in finding.evidence_refs
    ))
    metric_names: set[str]
    discriminators: dict[str, str] = {
        "DEVICE_OVERLOAD": "Repeated CPU and memory utilization at or above configured warning thresholds.",
        "INTERFACE_FAULT": "Interface error or flap counters across multiple polls.",
        "LINK_CONGESTION": "Time-correlated high utilization with queue, loss, or latency pressure.",
        "WEAK_WIFI": "Repeated RSSI and SNR measurements from the affected access point.",
        "DNS_FAILURE": "DNS-specific error responses or repeated resolver latency measurements.",
        "DHCP_FAILURE": "DHCP-specific allocation, NAK, pool-exhaustion, or lease evidence.",
        "CONFIG_DRIFT": "Current and baseline configuration values for a sensitive key.",
        "ROUTING_FAILURE": "A scoped path trace or routing-state observation between affected entities.",
    }
    metrics_by_code = {
        "DEVICE_OVERLOAD": {"cpu_utilization_pct", "memory_utilization_pct"},
        "INTERFACE_FAULT": {"interface_errors", "link_flaps"},
        "LINK_CONGESTION": {"link_utilization_pct", "queue_drops", "packet_loss_pct", "latency_ms"},
        "WEAK_WIFI": {"rssi_dbm", "snr_db"},
        "DNS_FAILURE": {"latency_ms"},
        "DHCP_FAILURE": {"latency_ms", "packet_loss_pct"},
    }
    metric_names = metrics_by_code.get(fault_code, set())
    relevant = [
        item for item in observations
        if (isinstance(item, MetricObservation) and item.metric_name in metric_names)
        or (fault_code == "CONFIG_DRIFT" and isinstance(item, ConfigObservation))
        or (fault_code in {"DNS_FAILURE", "DHCP_FAILURE"} and isinstance(item, LogObservation))
        or (fault_code == "ROUTING_FAILURE" and item.observation_type == "topology")
    ]
    inspected_refs = [item.observation_id for item in relevant]
    contradicting_refs: list[str] = []
    missing: list[str] = []
    status = "supported" if supporting_hypotheses else "inconclusive"

    metric_relevant = [item for item in relevant if isinstance(item, MetricObservation)]
    same_time_conflicts: dict[tuple[str, str, Any], list[MetricObservation]] = {}
    for item in metric_relevant:
        same_time_conflicts.setdefault((item.entity_id, item.metric_name, item.timestamp), []).append(item)
    for items in same_time_conflicts.values():
        if len({item.value for item in items}) > 1:
            contradicting_refs.extend(item.observation_id for item in items)
    sample_count = len({item.timestamp for item in metric_relevant})
    if not supporting_hypotheses:
        if not relevant:
            missing = [discriminators.get(fault_code, "A discriminating signal for this hypothesis.")]
        elif fault_code == "DEVICE_OVERLOAD" and sample_count >= 2:
            infra_rules = getattr(engine, "rules", {})
            cpu_warn = float(infra_rules.get("cpu_warning_pct", 75.0))
            mem_warn = float(infra_rules.get("memory_warning_pct", 80.0))
            values_below = all(
                (item.metric_name == "cpu_utilization_pct" and item.value < cpu_warn)
                or (item.metric_name == "memory_utilization_pct" and item.value < mem_warn)
                for item in metric_relevant
            )
            if values_below:
                status = "weakened"
                contradicting_refs = [item.observation_id for item in metric_relevant]
            else:
                missing = [discriminators[fault_code]]
        elif fault_code == "WEAK_WIFI" and sample_count >= 2:
            if all(
                (item.metric_name != "rssi_dbm" or item.value > -67)
                and (item.metric_name != "snr_db" or item.value > 20)
                for item in metric_relevant
            ):
                status = "weakened"
                contradicting_refs = [item.observation_id for item in metric_relevant]
            else:
                missing = [discriminators[fault_code]]
        elif fault_code == "INTERFACE_FAULT" and sample_count >= 2:
            infra_rules = getattr(engine, "rules", {})
            err_warn = float(infra_rules.get("interface_errors_warning", 10.0))
            if all(
                (item.metric_name != "interface_errors" or item.value < err_warn)
                and (item.metric_name != "link_flaps" or item.value == 0)
                for item in metric_relevant
            ):
                status = "weakened"
                contradicting_refs = [item.observation_id for item in metric_relevant]
            else:
                missing = [discriminators[fault_code]]
        elif fault_code == "LINK_CONGESTION" and sample_count >= 2:
            perf_rules = getattr(engine, "rules", {})
            high_util = float(perf_rules.get("high_utilization_pct", 85.0))
            latency_warn = float(perf_rules.get("latency_ms_warning", 100.0))
            pressure_metrics = [
                item for item in metric_relevant
                if (item.metric_name == "queue_drops" and item.value > 0)
                or (item.metric_name == "packet_loss_pct" and item.value >= 1.0)
                or (item.metric_name == "latency_ms" and item.value >= latency_warn)
            ]
            utilization = [item for item in metric_relevant if item.metric_name == "link_utilization_pct"]
            if utilization and not pressure_metrics and all(item.value < high_util for item in utilization):
                status = "weakened"
                contradicting_refs = [item.observation_id for item in utilization]
            else:
                missing = [discriminators[fault_code]]
        elif fault_code == "DNS_FAILURE" and relevant:
            service_rules = getattr(engine, "rules", {})
            latency_warn = float(service_rules.get("dns_latency_warning_ms", 150.0))
            has_error = any(
                isinstance(item, LogObservation)
                and any(token in item.message.upper() for token in ("SERVFAIL", "NXDOMAIN", "REFUSED", "TIMEOUT", "DNS_FAILURE"))
                for item in relevant
            )
            dns_latencies = [
                item for item in metric_relevant
                if item.metric_name == "latency_ms"
            ]
            if not has_error and len({item.timestamp for item in dns_latencies}) >= 2 and all(
                item.value < latency_warn for item in dns_latencies
            ):
                status = "weakened"
                contradicting_refs = [item.observation_id for item in dns_latencies]
            else:
                missing = [discriminators[fault_code]]
        else:
            missing = [discriminators.get(fault_code, "A repeated, hypothesis-specific measurement.")]

    if supporting_hypotheses and contradicting_refs:
        status = "inconclusive"
        missing = ["Resolve conflicting same-time readings before treating the hypothesis as confirmed."]
    summary = (
        f"{fault_code} review: {status}; inspected {len(relevant)} scoped observation(s), "
        f"including {len(supporting_refs)} supporting and {len(contradicting_refs)} counterevidence reference(s)."
    )
    return HypothesisReview(
        fault_code=fault_code,
        status=status,
        supporting_evidence_refs=supporting_refs,
        contradicting_evidence_refs=contradicting_refs,
        inspected_evidence_refs=inspected_refs,
        missing_measurements=missing,
        discriminating_measurement=discriminators.get(
            fault_code, "A repeated, hypothesis-specific measurement."
        ),
        summary=summary,
    )


@runtime_checkable
class TowerController(Protocol):
    """Protocol implemented by each of the four diagnostic tower controllers."""

    @property
    def tower_id(self) -> TowerId:
        ...

    @property
    def capabilities(self) -> list[TowerCapability]:
        ...

    def handle_query(self, query: PeerQuery) -> PeerQueryResult:
        """Executes a bounded, synchronous, read-only peer query."""
        ...

    def execute_task(self, task: InvestigationTask) -> TaskResult:
        """Executes a persistent, supervisor-authorized investigation task."""
        ...

    def analyze_incident(
        self, incident_id: str, observations: list[CanonicalObservation] | None = None
    ) -> TowerReport:
        """Runs the deterministic diagnostic engines on the incident scope and emits a TowerReport."""
        ...
