"""Supervisory RCA Agent for NetCoop AI.

Sole owner of case-level diagnostic reasoning, conflict arbitration, and proposal formulation.
Runs 100% deterministically with LLM mode off; supports pluggable providers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from netcoop.models.enums import ConfidenceCategory, ProposalDecision, TowerId
from netcoop.models.reports import ClaimEvidenceManifest, SupervisorProposal
from netcoop.supervisor.models import ConflictItem, ConflictType, IncidentDossier
from netcoop.utils.id_generator import generate_id

if TYPE_CHECKING:
    from netcoop.models.hypotheses import Hypothesis


class RCAProvider(Protocol):
    """Protocol for Supervisory RCA Agent reasoning backends."""

    def diagnose(self, dossier: IncidentDossier) -> tuple[SupervisorProposal, ClaimEvidenceManifest]:
        ...


class DeterministicRCAProvider:
    """Deterministic, rule-based cross-domain arbitration engine for RCA reasoning."""

    def diagnose(self, dossier: IncidentDossier) -> tuple[SupervisorProposal, ClaimEvidenceManifest]:
        # 1. Analyze findings and hypotheses across all towers
        findings = dossier.findings
        hypotheses = dossier.hypotheses

        # If no active hypotheses and findings are empty or purely info
        severe_findings = [f for f in findings if f.severity.value in {"high", "critical", "medium"}]
        if not hypotheses and not severe_findings:
            proposal = SupervisorProposal(
                proposal_id=generate_id("PROP"),
                incident_id=dossier.incident_id,
                decision=ProposalDecision.ABSTAIN,
                suspected_root_cause=None,
                affected_entities=[],
                supporting_finding_refs=[],
                confidence_category=ConfidenceCategory.INSUFFICIENT,
                alternative_causes=[],
                recommended_actions=["Continue continuous telemetry monitoring."],
                abstain_reason="Normal telemetry: no significant anomalies, service failures, or degraded states identified across any domain.",
                requested_tasks=[],
                created_at=datetime.now(timezone.utc),
            )
            manifest = ClaimEvidenceManifest(
                incident_id=dossier.incident_id,
                claim="Normal healthy telemetry verified across all towers.",
                claimed_entities=[],
                finding_ids=[],
                observation_ids=[],
                independence_groups=[],
                contradiction_ids=[],
                contradiction_disclosures=[],
            )
            return proposal, manifest

        # 2. Classify conflicts across towers
        conflicts = self._classify_conflicts(dossier)
        dossier.conflicts = conflicts

        if dossier.gate_feedback:
            gate_tasks = self._gate_feedback_tasks(dossier)
            if gate_tasks:
                issue_codes = [item.get("code") for item in dossier.gate_feedback]
                proposal = SupervisorProposal(
                    proposal_id=generate_id("PROP-GATE-RETRY"),
                    incident_id=dossier.incident_id,
                    decision=ProposalDecision.REQUEST_EVIDENCE,
                    suspected_root_cause=None,
                    affected_entities=dossier.affected_entities,
                    supporting_finding_refs=[],
                    confidence_category=ConfidenceCategory.LOW,
                    alternative_causes=[hyp.fault_code for hyp in dossier.hypotheses],
                    recommended_actions=[],
                    abstain_reason=None,
                    requested_tasks=gate_tasks,
                    created_at=datetime.now(timezone.utc),
                )
                manifest = ClaimEvidenceManifest(
                    incident_id=dossier.incident_id,
                    claim=f"Gate requested a targeted evidence review for issue(s): {issue_codes}.",
                    claimed_entities=dossier.affected_entities,
                    finding_ids=[], observation_ids=[], independence_groups=[],
                    contradiction_ids=[hyp.fault_code for hyp in dossier.hypotheses],
                    contradiction_disclosures=[str(item.get("message", "")) for item in dossier.gate_feedback],
                )
                return proposal, manifest

        # 3. Check if investigation task should be requested in round 1
        if dossier.investigation_round == 1 and not dossier.task_history:
            task_requests: list[dict[str, Any]] = []
            challenge_capabilities = {
                "LINK_CONGESTION": (TowerId.PERFORMANCE, "performance.challenge_congestion_hypothesis"),
                "WEAK_WIFI": (TowerId.PERFORMANCE, "performance.challenge_wifi_hypothesis"),
                "DEVICE_OVERLOAD": (TowerId.INFRASTRUCTURE, "infrastructure.challenge_device_overload_hypothesis"),
                "INTERFACE_FAULT": (TowerId.INFRASTRUCTURE, "infrastructure.challenge_interface_hypothesis"),
                "DNS_FAILURE": (TowerId.SERVICES, "services.challenge_service_failure_hypothesis"),
                "DHCP_FAILURE": (TowerId.SERVICES, "services.challenge_service_failure_hypothesis"),
                "CONFIG_DRIFT": (TowerId.SERVICES, "services.challenge_config_hypothesis"),
                "ROUTING_FAILURE": (TowerId.CONNECTIVITY, "ANALYZE_REACHABILITY"),
                "UPLINK_SATURATION": (TowerId.CONNECTIVITY, "connectivity.inspect_common_upstream"),
            }
            for conflict in conflicts:
                for index, fault_code in enumerate(conflict.competing_hypotheses):
                    route = challenge_capabilities.get(fault_code)
                    if route is None:
                        continue
                    assignee, capability = route
                    hypothesis = next((h for h in dossier.hypotheses if h.fault_code == fault_code), None)
                    target_entities = hypothesis.suspected_entities if hypothesis else dossier.affected_entities
                    task_requests.append({
                        "assignee": assignee.value,
                        "capability": capability,
                        "objective": {
                            "incident_id": dossier.incident_id,
                            "conflict_type": conflict.conflict_type.value,
                            "hypothesis_code": fault_code if ".challenge_" in capability else None,
                            "competing_hypotheses": conflict.competing_hypotheses,
                            "target_entities": target_entities,
                            "question": (
                                f"Review {fault_code} against its supporting and contradicting evidence. "
                                f"Name the measurement that would distinguish it from the competing hypothesis."
                            ),
                            "discriminating_measurement": conflict.disposition,
                        },
                    })

            if task_requests:
                all_competing = list(dict.fromkeys(
                    code for conflict in conflicts for code in conflict.competing_hypotheses
                ))
                proposal = SupervisorProposal(
                    proposal_id=generate_id("PROP"),
                    incident_id=dossier.incident_id,
                    decision=ProposalDecision.REQUEST_EVIDENCE,
                    suspected_root_cause=None,
                    affected_entities=dossier.affected_entities,
                    supporting_finding_refs=[f.finding_id for f in severe_findings[:2]],
                    confidence_category=ConfidenceCategory.LOW,
                    alternative_causes=all_competing,
                    recommended_actions=[],
                    abstain_reason=None,
                    requested_tasks=task_requests,
                    created_at=datetime.now(timezone.utc),
                )
                manifest = ClaimEvidenceManifest(
                    incident_id=dossier.incident_id,
                    claim=f"Ambiguities detected between {all_competing}; requesting discriminating evidence.",
                    claimed_entities=dossier.affected_entities,
                    finding_ids=[f.finding_id for f in severe_findings[:2]],
                    observation_ids=[],
                    independence_groups=[],
                    contradiction_ids=all_competing,
                    contradiction_disclosures=[conflict.description for conflict in conflicts],
                )
                return proposal, manifest

        # 4. Formulate Primary Root Cause Proposal based on causal priority
        return self._arbitrate_diagnosis(dossier, conflicts)

    @staticmethod
    def _gate_feedback_tasks(dossier: IncidentDossier) -> list[dict[str, Any]]:
        """Select one existing read-only specialist capability for a gate evidence gap."""
        retryable_codes = {item.get("code") for item in dossier.gate_feedback}
        if not retryable_codes.intersection({"missing_support", "invalid_finding_reference"}):
            return []
        already_reviewed = {
            review.get("fault_code")
            for entry in dossier.task_history
            for review in entry.get("hypothesis_reviews", [])
            if isinstance(review, dict)
        }
        capability_by_fault = {
            "LINK_CONGESTION": ("performance", "INVESTIGATE_CONGESTION"),
            "WEAK_WIFI": ("performance", "ANALYZE_WIFI_QUALITY"),
            "DEVICE_OVERLOAD": ("infrastructure", "INVESTIGATE_DEVICE"),
            "INTERFACE_FAULT": ("infrastructure", "ANALYZE_INTERFACE"),
            "DNS_FAILURE": ("services", "INVESTIGATE_DNS"),
            "DHCP_FAILURE": ("services", "INVESTIGATE_DHCP"),
            "CONFIG_DRIFT": ("services", "ANALYZE_CONFIG_DRIFT"),
        }
        for hypothesis in sorted(dossier.hypotheses, key=lambda item: item.confidence_score, reverse=True):
            if hypothesis.fault_code in already_reviewed or hypothesis.fault_code not in capability_by_fault:
                continue
            assignee, capability = capability_by_fault[hypothesis.fault_code]
            return [{
                "assignee": assignee,
                "capability": capability,
                "objective": {
                    "target_entities": hypothesis.suspected_entities,
                    "question": "Reinspect incident evidence supporting this hypothesis after a gate support issue.",
                    "gate_issue_codes": sorted(retryable_codes),
                },
            }]
        return []

    def _classify_conflicts(self, dossier: IncidentDossier) -> list[ConflictItem]:
        """Identifies and classifies disagreements across tower findings and hypotheses."""
        conflicts: list[ConflictItem] = []
        fault_codes = {h.fault_code for h in dossier.hypotheses}

        # Conflict 1: Link Congestion vs Device Overload (Performance vs Infrastructure)
        if "LINK_CONGESTION" in fault_codes and "DEVICE_OVERLOAD" in fault_codes:
            conflicts.append(
                ConflictItem(
                    conflict_type=ConflictType.CAUSAL,
                    competing_towers=[TowerId.PERFORMANCE, TowerId.INFRASTRUCTURE],
                    competing_hypotheses=["LINK_CONGESTION", "DEVICE_OVERLOAD"],
                    description="Performance reports link congestion while Infrastructure reports device overload.",
                    recommended_discriminating_task="INVESTIGATE_DEVICE",
                    recommended_assignee=TowerId.INFRASTRUCTURE,
                    disposition="Device CPU overload can induce buffer drops; or egress queue saturation can raise CPU.",
                )
            )

        # Conflict 2: DNS Failure vs Routing Failure (Services vs Connectivity)
        if "DNS_FAILURE" in fault_codes and "ROUTING_FAILURE" in fault_codes:
            conflicts.append(
                ConflictItem(
                    conflict_type=ConflictType.DOMAIN_INTERPRETATION,
                    competing_towers=[TowerId.SERVICES, TowerId.CONNECTIVITY],
                    competing_hypotheses=["DNS_FAILURE", "ROUTING_FAILURE"],
                    description="Services reports DNS query failures while Connectivity reports path interruption.",
                    recommended_discriminating_task="ANALYZE_REACHABILITY",
                    recommended_assignee=TowerId.CONNECTIVITY,
                    disposition="DNS server may be healthy but unreachable due to backbone network partition.",
                )
            )

        # Conflict 3: Link Congestion on multiple leaves vs Common Uplink Saturation
        leaf_congestion = [
            h
            for h in dossier.hypotheses
            if h.fault_code == "LINK_CONGESTION" and any(":" in ent for ent in h.suspected_entities)
        ]
        if len(leaf_congestion) >= 2:
            conflicts.append(
                ConflictItem(
                    conflict_type=ConflictType.CAUSAL,
                    competing_towers=[TowerId.PERFORMANCE, TowerId.CONNECTIVITY],
                    competing_hypotheses=["LINK_CONGESTION", "UPLINK_SATURATION"],
                    description="Multiple leaf links show high latency/loss; suspected shared upstream chokepoint.",
                    recommended_discriminating_task="connectivity.inspect_common_upstream",
                    recommended_assignee=TowerId.CONNECTIVITY,
                    disposition="Check common uplink switch in topology to avoid blaming healthy leaf links.",
                )
            )

        return conflicts

    def _arbitrate_diagnosis(
        self, dossier: IncidentDossier, conflicts: list[ConflictItem]
    ) -> tuple[SupervisorProposal, ClaimEvidenceManifest]:
        """Arbitrates between competing hypotheses using evidence weight and causal priority."""
        hypotheses = sorted(dossier.hypotheses, key=lambda h: h.confidence_score, reverse=True)
        findings = dossier.findings

        # Causal Priority hierarchy:
        # 1. Configuration Drift (often root cause of subsequent network or service failures)
        # 2. Hardware / Device / Interface Fault (physical degradation causes packet loss)
        # 3. Routing / Topology Partition (reachability breakdown)
        # 4. Service Failures (DNS / DHCP failures)
        # 5. Link Congestion / Capacity Exhaustion
        # 6. Wireless degradation (Weak WiFi)
        priority_map = {
            "CONFIG_DRIFT": 100,
            "HARDWARE_FAULT": 90,
            "DEVICE_OVERLOAD": 85,
            "INTERFACE_FAULT": 80,
            "ROUTING_FAILURE": 75,
            "DNS_FAILURE": 70,
            "DHCP_FAILURE": 70,
            "LINK_CONGESTION": 60,
            "WEAK_WIFI": 50,
        }

        # Check if routing failure explains DNS failure
        has_partition = any(h.fault_code == "ROUTING_FAILURE" for h in hypotheses)
        has_dns = any(h.fault_code == "DNS_FAILURE" for h in hypotheses)
        if has_partition and has_dns:
            reachability = self._task_reachability_result(dossier)
            if reachability is False:
                # A completed path probe supports a network partition over an independent DNS fault.
                priority_map["DNS_FAILURE"] = 30
            elif reachability is True:
                # A reachable resolver path weakens routing as the explanation for DNS symptoms.
                priority_map["ROUTING_FAILURE"] = 20

        # Sort hypotheses by adjusted priority * confidence_score
        reviews: dict[str, dict[str, Any]] = {}
        for entry in dossier.task_history:
            for review in entry.get("hypothesis_reviews", []):
                if isinstance(review, dict) and review.get("fault_code"):
                    reviews[review["fault_code"]] = review

        def score_hyp(h: Hypothesis) -> float:
            base_prio = priority_map.get(h.fault_code, 40)
            review_status = reviews.get(h.fault_code, {}).get("status")
            multiplier = {"supported": 1.0, "weakened": 0.2, "inconclusive": 0.75}.get(review_status, 1.0)
            return base_prio * (0.5 + h.confidence_score) * multiplier

        ranked_hypotheses = sorted(hypotheses, key=score_hyp, reverse=True)
        concurrent_causes: list[str] = []

        if not ranked_hypotheses:
            # Fallback to findings if hypotheses list was empty
            top_finding = max(findings, key=lambda f: f.severity.value, default=None)
            if top_finding:
                root_cause = f"FAULT: {top_finding.finding_type} on {top_finding.entity_refs}"
                supporting_findings = [top_finding]
                alt_causes = []
                conf_cat = ConfidenceCategory.MODERATE
            else:
                return self._abstain_unresolved(dossier, "No conclusive faults or hypotheses identified.")
        else:
            primary_hyp = ranked_hypotheses[0]
            coexisting_hypotheses = []
            primary_entities = set(primary_hyp.suspected_entities)
            explicitly_competing = {
                code for conflict in conflicts for code in conflict.competing_hypotheses
            }
            for candidate in ranked_hypotheses[1:]:
                disjoint = primary_entities.isdisjoint(candidate.suspected_entities)
                is_classified_conflict = any(
                    candidate.fault_code in conflict.competing_hypotheses
                    for conflict in conflicts
                )
                if disjoint and not is_classified_conflict and candidate.fault_code not in explicitly_competing:
                    coexisting_hypotheses.append(candidate)

            root_cause = f"{primary_hyp.fault_code}: {primary_hyp.rationale}"
            supported_hypotheses = [primary_hyp, *coexisting_hypotheses]
            supporting_refs = {
                finding_id for hyp in supported_hypotheses for finding_id in hyp.supporting_finding_refs
            }
            supporting_findings = [f for f in findings if f.finding_id in supporting_refs]
            if not supporting_findings:
                # Correlate findings by suspected entities or source tower
                supporting_findings = [
                    f
                    for f in findings
                    if any(ent in f.entity_refs for ent in primary_hyp.suspected_entities)
                ]
            if not supporting_findings and findings:
                supporting_findings = findings[:2]

            alt_causes = [
                f"{h.fault_code}: {h.suspected_entities}"
                for h in ranked_hypotheses[1:]
                if h.fault_code != primary_hyp.fault_code and h not in coexisting_hypotheses
            ]
            conf_cat = primary_hyp.confidence_category
            for conflict in conflicts:
                statuses = [reviews.get(code, {}).get("status") for code in conflict.competing_hypotheses]
                if len(statuses) > 1 and all(status in {"supported", "inconclusive"} for status in statuses):
                    conf_cat = ConfidenceCategory.LOW
            concurrent_causes = [
                f"{h.fault_code}: {h.suspected_entities}" for h in coexisting_hypotheses
            ]

        # Collect evidence observation IDs from supporting findings
        all_obs_ids: list[str] = []
        independence_groups: set[str] = set()
        affected_entities: list[str] = []

        for f in supporting_findings:
            all_obs_ids.extend(f.evidence_refs)
            independence_groups.add(f.independence_group or f.source_tower.value)
            affected_entities.extend(f.entity_refs)

        # Deduplicate
        all_obs_ids = list(dict.fromkeys(all_obs_ids))
        affected_entities = list(dict.fromkeys(affected_entities))

        # Recommended safe read-only actions
        cause_strings = [root_cause, *concurrent_causes]
        rec_actions = list(dict.fromkeys(
            action for cause in cause_strings for action in self._generate_recommendations(cause)
        ))

        proposal = SupervisorProposal(
            proposal_id=generate_id("PROP"),
            incident_id=dossier.incident_id,
            decision=ProposalDecision.PROPOSE_DIAGNOSIS,
            suspected_root_cause=root_cause,
            affected_entities=affected_entities,
            supporting_finding_refs=[f.finding_id for f in supporting_findings],
            confidence_category=conf_cat,
            alternative_causes=alt_causes,
            concurrent_causes=concurrent_causes,
            recommended_actions=rec_actions,
            abstain_reason=None,
            requested_tasks=[],
            created_at=datetime.now(timezone.utc),
        )

        manifest = ClaimEvidenceManifest(
            incident_id=dossier.incident_id,
            claim=f"Root cause identified as {root_cause}",
            claimed_entities=affected_entities,
            finding_ids=[f.finding_id for f in supporting_findings],
            observation_ids=all_obs_ids,
            independence_groups=sorted(list(independence_groups)),
            contradiction_ids=[c.competing_hypotheses[0] for c in conflicts if c.competing_hypotheses],
            contradiction_disclosures=[c.description for c in conflicts] + self._task_disclosures(dossier),
        )

        return proposal, manifest

    @staticmethod
    def _task_reachability_result(dossier: IncidentDossier) -> bool | None:
        for entry in reversed(dossier.peer_query_history):
            if entry.get("status") != "completed" or entry.get("capability") != "connectivity.trace_path":
                continue
            result = entry.get("result") or {}
            if isinstance(result.get("reachable"), bool):
                if result.get("warning") and "not found" in result["warning"].lower():
                    continue
                return result["reachable"]
        for entry in reversed(dossier.task_history):
            if entry.get("status") != "COMPLETED" or entry.get("capability") != "ANALYZE_REACHABILITY":
                continue
            result = entry.get("result") or {}
            analysis = result.get("analysis", result)
            if isinstance(analysis, dict) and isinstance(analysis.get("reachable"), bool):
                if analysis.get("warning") and "not found" in analysis["warning"].lower():
                    return None
                return analysis["reachable"]
        return None

    @staticmethod
    def _task_disclosures(dossier: IncidentDossier) -> list[str]:
        disclosures = []
        for entry in dossier.task_history:
            result = entry.get("result") or {}
            summary = result.get("summary")
            analysis = result.get("analysis", result)
            if summary:
                disclosures.append(f"Task {entry.get('task_id')} ({entry.get('capability')}): {summary}")
            if isinstance(analysis, dict) and analysis.get("warning"):
                disclosures.append(f"Task {entry.get('task_id')} limitation: {analysis['warning']}")
        return disclosures

    def _abstain_unresolved(self, dossier: IncidentDossier, reason: str) -> tuple[SupervisorProposal, ClaimEvidenceManifest]:
        proposal = SupervisorProposal(
            proposal_id=generate_id("PROP"),
            incident_id=dossier.incident_id,
            decision=ProposalDecision.ABSTAIN,
            suspected_root_cause=None,
            affected_entities=dossier.affected_entities,
            supporting_finding_refs=[],
            confidence_category=ConfidenceCategory.INSUFFICIENT,
            alternative_causes=[],
            recommended_actions=["Perform manual triage and verify cross-domain telemetry sources."],
            abstain_reason=reason,
            requested_tasks=[],
            created_at=datetime.now(timezone.utc),
        )
        manifest = ClaimEvidenceManifest(
            incident_id=dossier.incident_id,
            claim="Diagnostic abstention due to lack of conclusive evidence.",
            claimed_entities=dossier.affected_entities,
            finding_ids=[],
            observation_ids=[],
            independence_groups=[],
            contradiction_ids=[],
            contradiction_disclosures=[],
        )
        return proposal, manifest

    def _generate_recommendations(self, root_cause: str) -> list[str]:
        rc = root_cause.upper()
        if "LINK_CONGESTION" in rc:
            return [
                "Inspect interface QoS queue policies and drop statistics on affected link.",
                "Review top talkers and traffic flows traversing the congested interface.",
                "Evaluate traffic shaping or rerouting paths away from saturated uplink.",
            ]
        elif "DEVICE_OVERLOAD" in rc or "HARDWARE_FAULT" in rc:
            return [
                "Inspect switch CPU process utilization and memory buffers.",
                "Check hardware environmental counters (fan, temperature, power supplies).",
                "Verify whether control-plane policing or storm control is active.",
            ]
        elif "ROUTING_FAILURE" in rc:
            return [
                "Inspect dynamic routing adjacency states and BGP/OSPF neighbor logs.",
                "Verify next-hop reachability along backbone links.",
                "Review recent routing table churn or prefix withdrawals.",
            ]
        elif "DNS_FAILURE" in rc:
            return [
                "Verify reachability to configured upstream DNS resolvers.",
                "Review DNS server query logs for SERVFAIL, NXDOMAIN, or response timeouts.",
                "Check authoritative DNS server service daemon health.",
            ]
        elif "DHCP_FAILURE" in rc:
            return [
                "Check DHCP pool utilization and scope lease availability.",
                "Verify DHCP relay agent forwarding and IP helper configurations.",
            ]
        elif "CONFIG_DRIFT" in rc:
            return [
                "Audit recent configuration commits and compare diff with golden baseline.",
                "Review changed MTU, VLAN, and ACL definitions on affected device.",
            ]
        elif "WEAK_WIFI" in rc:
            return [
                "Inspect wireless AP channel utilization and RF interference.",
                "Evaluate client association SNR, RSSI, and 802.11 retransmission rates.",
            ]
        return [
            "Perform targeted read-only health checks on the affected network entity.",
            "Inspect physical connectivity and error counters on relevant interfaces.",
        ]


class FakeLLMProvider:
    """Mock LLM provider for testing provider adapter interfaces and fallback mechanics."""

    def __init__(self, should_fail: bool = False, custom_decision: ProposalDecision | None = None) -> None:
        self.should_fail = should_fail
        self.custom_decision = custom_decision
        self.fallback = DeterministicRCAProvider()

    def diagnose(self, dossier: IncidentDossier) -> tuple[SupervisorProposal, ClaimEvidenceManifest]:
        if self.should_fail:
            raise RuntimeError("FakeLLMProvider simulated provider API connection failure")

        proposal, manifest = self.fallback.diagnose(dossier)
        if self.custom_decision is not None:
            proposal.decision = self.custom_decision
        return proposal, manifest


def get_rca_provider(
    llm_mode: str = "off",
    api_key: str | None = None,
    model: str | None = None,
) -> RCAProvider:
    """Factory creating the appropriate RCAProvider based on LLM mode and available credentials."""
    from netcoop.supervisor.openrouter import OpenRouterProvider
    from netcoop.utils.env import load_dotenv

    load_dotenv()
    mode = llm_mode.lower()

    if mode == "off":
        return DeterministicRCAProvider()

    import os
    resolved_key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")

    if mode == "on":
        if not resolved_key:
            raise ValueError(
                "LLM mode 'on' was requested, but OPENROUTER_API_KEY was not found in environment or .env file."
            )
        return OpenRouterProvider(api_key=resolved_key, model=model)

    if mode == "auto":
        if resolved_key:
            return OpenRouterProvider(api_key=resolved_key, model=model)
        return DeterministicRCAProvider()

    return DeterministicRCAProvider()


class SupervisoryRCAAgent:
    """Supervisory RCA Agent coordinating case-level hypothesis generation and arbitration."""

    def __init__(self, provider: RCAProvider | None = None, llm_mode: str = "off") -> None:
        self.llm_mode = llm_mode.lower()
        if provider is not None:
            self.provider = provider
        else:
            self.provider = get_rca_provider(llm_mode=self.llm_mode)

    def diagnose(self, dossier: IncidentDossier) -> tuple[SupervisorProposal, ClaimEvidenceManifest]:
        """Formulates case-level proposal and claim manifest from compact incident dossier."""
        try:
            return self.provider.diagnose(dossier)
        except Exception:
            # Safe deterministic fallback if custom or remote provider raises
            return DeterministicRCAProvider().diagnose(dossier)

