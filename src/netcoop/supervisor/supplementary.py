"""Post-diagnosis context that must not alter the primary diagnosis."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from netcoop.communication.fabric import IntegrationFabric
from netcoop.communication.queries import PeerQuery
from netcoop.models.enums import TowerId
from netcoop.models.observations import CanonicalObservation
from netcoop.models.reports import FinalReport, PathTraceItem, PathTriage, SymptomReasoning
from netcoop.utils.id_generator import generate_id

TRACE_SCHEMA = "netcoop://schemas/capabilities/connectivity-trace-path-output/1.0"
MAX_POST_DIAGNOSIS_PATH_QUERIES = 6


def build_path_triage(
    report: FinalReport,
    incident_id: str,
    observations: list[CanonicalObservation],
    fabric: IntegrationFabric,
) -> tuple[PathTriage, list[dict[str, object]], list[str]]:
    """Trace topology paths between evidence-bearing and predicted-affected entities.

    These queries are issued after gate publication. Earlier service checks remain
    part of the diagnosis pipeline and are deliberately not reused here.
    """
    known_observation_ids = {item.observation_id for item in observations}
    paths: list[PathTraceItem] = []
    interactions: list[dict[str, object]] = []
    query_warnings: list[str] = []
    seen_pairs: set[tuple[str, str]] = set()

    connectivity = fabric.get_tower(TowerId.CONNECTIVITY)
    topology = getattr(connectivity, "topology", None)
    graph = getattr(topology, "graph", None)
    if graph is None:
        return PathTriage(
            status="traced" if paths else "unavailable",
            paths=paths,
            limitations=[] if paths else ["Connectivity topology is unavailable for a supplemental path trace."],
        ), interactions, query_warnings

    nodes = set(graph.nodes)

    def graph_entity(entity: str) -> str:
        if entity in nodes:
            return entity
        device, separator, _interface = entity.partition(":")
        if separator and device in nodes:
            return device
        return entity

    pairs: list[tuple[str, str]] = []
    for impacted in report.inferred_affected_entities:
        for observed in report.observed_symptom_entities:
            source, target = graph_entity(impacted), graph_entity(observed)
            pair = (source, target)
            if source != target and pair not in seen_pairs and pair not in pairs:
                pairs.append(pair)

    for source, target in pairs[:MAX_POST_DIAGNOSIS_PATH_QUERIES]:
        query = PeerQuery(
            query_id=generate_id("QRY-PATH"),
            incident_id=incident_id,
            requester="supervisor",
            recipient="connectivity",
            capability="connectivity.trace_path",
            scope=[source, target],
            expected_schema=TRACE_SCHEMA,
            created_at=datetime.now(timezone.utc),
        )
        try:
            result = fabric.query_peer(query)
            payload = result.result or {}
            refs = [ref for ref in result.evidence_refs if ref in known_observation_ids]
            warning_items = list(result.warnings or [])
            if len(refs) != len(result.evidence_refs):
                warning_items.append("Connectivity returned evidence references outside this incident; they were omitted.")
            reachable = payload.get("reachable")
            paths.append(PathTraceItem(
                source_entity=source,
                target_entity=target,
                reachable=reachable if isinstance(reachable, bool) else None,
                path=[str(node) for node in payload.get("path", [])] if isinstance(payload.get("path", []), list) else [],
                evidence_refs=refs,
                warning=payload.get("warning") or "; ".join(warning_items) or None,
            ))
            interactions.append({
                "query_id": query.query_id,
                "requester": query.requester,
                "recipient": query.recipient,
                "capability": query.capability,
                "scope": query.scope,
                "status": result.status.value,
                "result": payload,
                "evidence_refs": refs,
                "warnings": warning_items,
                "supplementary": True,
            })
            if result.status.value != "completed":
                query_warnings.extend(warning_items or [f"Path query ended with {result.status.value}."])
        except Exception as exc:  # A failed addendum must not fail diagnosis publication.
            message = f"Supplementary path query {source} -> {target} failed: {exc}"
            query_warnings.append(message)

    limitations: list[str] = [
        "Recorded paths describe topology reachability; they do not prove that a path caused the incident."
    ] if paths else []
    if len(pairs) > MAX_POST_DIAGNOSIS_PATH_QUERIES:
        limitations.append(
            f"Path triage was capped at {MAX_POST_DIAGNOSIS_PATH_QUERIES} additional queries."
        )
    if not paths:
        limitations.append(
            "No evidence-bearing and topology-inferred entity pair was available to trace."
        )
    limitations.extend(query_warnings)

    status = "unavailable" if not paths else (
        "partial" if any(item.reachable is None or item.warning for item in paths) or query_warnings else "traced"
    )
    return PathTriage(status=status, paths=paths, limitations=limitations), interactions, query_warnings


def reason_about_symptom(symptom: str, report: FinalReport) -> SymptomReasoning:
    """Perform conservative keyword correlation after the primary diagnosis."""
    normalized = re.sub(r"[^a-z0-9]+", " ", symptom.casefold()).strip()
    domain_faults = {
        "wireless": {"WEAK_WIFI"},
        "dns": {"DNS_FAILURE"},
        "dhcp": {"DHCP_FAILURE"},
        "performance": {"LINK_CONGESTION", "INTERFACE_FAULT", "DEVICE_OVERLOAD"},
        "interface": {"INTERFACE_FAULT"},
        "hardware": {"DEVICE_OVERLOAD"},
        "connectivity": {"ROUTING_FAILURE", "LINK_CONGESTION", "INTERFACE_FAULT"},
    }
    terms = {
        "wireless": ("wifi", "wi fi", "wireless", "rssi", "signal strength"),
        "dns": ("dns", "name resolution", "resolve names", "resolve hostnames", "hostname", "hostnames", "domain name"),
        "dhcp": (
            "dhcp",
            "ip address lease",
            "address lease",
            "cannot get an ip address",
            "can't get an ip address",
            "get an ip address",
            "cannot obtain an ip address",
            "can't obtain an ip address",
            "obtain an ip address",
        ),
        "performance": ("slow", "latency", "lag", "buffering", "throughput"),
        "interface": ("interface", "port", "crc", "flap"),
        "hardware": ("cpu", "memory", "overload"),
        "connectivity": ("no internet", "internet down", "disconnected", "cannot connect", "can't connect", "unreachable"),
    }
    domains = [
        domain for domain, phrases in terms.items()
        if any(phrase in normalized for phrase in phrases)
    ]
    diagnosed = set(re.findall(
        r"\b(?:LINK_CONGESTION|WEAK_WIFI|INTERFACE_FAULT|DEVICE_OVERLOAD|DNS_FAILURE|DHCP_FAILURE|ROUTING_FAILURE|CONFIG_DRIFT)\b",
        " ".join([report.suspected_root_cause, *report.concurrent_causes]),
    ))
    expected = set().union(*(domain_faults[domain] for domain in domains)) if domains else set()
    matched = sorted(expected & diagnosed)
    weak_support = (
        report.confidence < 0.7
        or report.confidence_category.value in {"low", "insufficient"}
        or any(
            "single evidence stream" in limitation.casefold()
            or "limited temporal support" in limitation.casefold()
            for limitation in report.limitations
        )
    )

    if weak_support:
        status = "unclear"
        explanation = (
            "The symptom overlaps with a possible fault category, but the published diagnosis has "
            "limited evidence or confidence. Treat this comparison as unclear; the diagnosis was "
            "made independently and was not changed."
        )
    elif not domains or not diagnosed or ("connectivity" in domains and len(expected) > 3):
        status = "unclear"
        explanation = (
            "The symptom wording is too broad for a reliable rule-based comparison. "
            "The diagnosis was made independently and was not changed."
        )
    elif matched:
        status = "aligned"
        explanation = (
            "The reported wording overlaps with the diagnosed fault category. "
            "This is a consistency check, not proof that the complaint was caused by it; "
            "the diagnosis was made independently."
        )
    else:
        status = "mismatch"
        explanation = (
            "The reported wording does not match the diagnosed fault category. "
            "Treat the complaint as unresolved against this diagnosis; the diagnosis was not changed."
        )

    return SymptomReasoning(
        reported_symptom=symptom,
        status=status,
        recognized_domains=domains,
        diagnosed_fault_codes=sorted(diagnosed),
        matched_fault_codes=matched,
        explanation=explanation,
    )
