"""Supervisory RCA Agent for NetCoop AI.

Sole owner of case-level diagnostic reasoning, conflict arbitration, and proposal formulation.
Runs 100% deterministically with LLM mode off; supports pluggable providers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Protocol

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

        # 3. Check if investigation task should be requested in round 1
        if dossier.investigation_round == 1 and not dossier.task_history:
            for conflict in conflicts:
                if conflict.recommended_discriminating_task:
                    # Request targeted investigation task
                    task_req = {
                        "assignee": conflict.competing_towers[0].value,
                        "capability": conflict.recommended_discriminating_task,
                        "objective": {
                            "incident_id": dossier.incident_id,
                            "conflict_type": conflict.conflict_type.value,
                            "target_entities": dossier.affected_entities,
                        },
                    }
                    proposal = SupervisorProposal(
                        proposal_id=generate_id("PROP"),
                        incident_id=dossier.incident_id,
                        decision=ProposalDecision.REQUEST_EVIDENCE,
                        suspected_root_cause=None,
                        affected_entities=dossier.affected_entities,
                        supporting_finding_refs=[f.finding_id for f in severe_findings[:2]],
                        confidence_category=ConfidenceCategory.LOW,
                        alternative_causes=conflict.competing_hypotheses,
                        recommended_actions=[],
                        abstain_reason=None,
                        requested_tasks=[task_req],
                        created_at=datetime.now(timezone.utc),
                    )
                    manifest = ClaimEvidenceManifest(
                        incident_id=dossier.incident_id,
                        claim=f"Ambiguity detected between {conflict.competing_hypotheses}; requesting discriminating evidence.",
                        claimed_entities=dossier.affected_entities,
                        finding_ids=[f.finding_id for f in severe_findings[:2]],
                        observation_ids=[],
                        independence_groups=[],
                        contradiction_ids=conflict.competing_hypotheses,
                        contradiction_disclosures=[conflict.description],
                    )
                    return proposal, manifest

        # 4. Formulate Primary Root Cause Proposal based on causal priority
        return self._arbitrate_diagnosis(dossier, conflicts)

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
            # Demote DNS failure because path interruption isolates DNS resolver
            priority_map["DNS_FAILURE"] = 30

        # Sort hypotheses by adjusted priority * confidence_score
        def score_hyp(h: Hypothesis) -> float:
            base_prio = priority_map.get(h.fault_code, 40)
            return base_prio * (0.5 + h.confidence_score)

        ranked_hypotheses = sorted(hypotheses, key=score_hyp, reverse=True)

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
            root_cause = f"{primary_hyp.fault_code}: {primary_hyp.rationale}"
            supporting_findings = [
                f for f in findings if f.finding_id in primary_hyp.supporting_finding_refs
            ]
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
                if h.fault_code != primary_hyp.fault_code
            ]
            conf_cat = primary_hyp.confidence_category

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
        rec_actions = self._generate_recommendations(root_cause)

        proposal = SupervisorProposal(
            proposal_id=generate_id("PROP"),
            incident_id=dossier.incident_id,
            decision=ProposalDecision.PROPOSE_DIAGNOSIS,
            suspected_root_cause=root_cause,
            affected_entities=affected_entities,
            supporting_finding_refs=[f.finding_id for f in supporting_findings],
            confidence_category=conf_cat,
            alternative_causes=alt_causes,
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
            contradiction_disclosures=[c.description for c in conflicts],
        )

        return proposal, manifest

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

