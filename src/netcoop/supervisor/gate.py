"""Evidence and Release Gate for NetCoop AI.

Independent, deterministic verification gate validating whether a proposed diagnosis
meets all objective publication standards, citation provenance, scope, and freshness rules.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from netcoop.models.enums import ConfidenceCategory, FindingStatus, ProposalDecision
from netcoop.models.findings import Finding
from netcoop.models.observations import (
    CanonicalObservation,
    LogObservation,
    MetricObservation,
    TopologyObservation,
)
from netcoop.models.reports import (
    FinalReport,
    PredictedImpact,
    ReportStatus,
    SupportingEvidenceItem,
)
from netcoop.supervisor.models import GateCheckResult, GateIssue, GateOutcome, GateResult

_GATE_ISSUE_POLICY: dict[str, tuple[str, bool]] = {
    "root_cause_present": ("missing_root_cause", True),
    "confidence_sufficient": ("confidence_insufficient", False),
    "supporting_findings_present": ("missing_support", True),
    "finding_existence": ("invalid_finding_reference", True),
    "manifest_finding_existence": ("invalid_finding_reference", True),
    "observation_existence": ("invalid_observation_reference", True),
    "finding_scope": ("finding_scope_mismatch", False),
    "observation_scope": ("observation_scope_mismatch", False),
    "claim_evidence_semantic_consistency": ("semantic_evidence_mismatch", False),
    "finding_not_superseded": ("stale_finding", False),
    "finding_not_retracted": ("retracted_finding", False),
    "contradiction_disclosure": ("unresolved_hypothesis", True),
    "same_time_measurement_consistency": ("measurement_conflict", True),
}


def _issues_from_checks(checks: list[GateCheckResult]) -> list[GateIssue]:
    issues: list[GateIssue] = []
    for check in checks:
        if check.passed:
            continue
        code, retryable = _GATE_ISSUE_POLICY.get(
            check.check_name, ("gate_check_failed", False)
        )
        issues.append(GateIssue(
            code=code,
            check_name=check.check_name,
            message=check.message,
            retryable=retryable,
        ))
    return issues

if TYPE_CHECKING:
    from netcoop.models.reports import ClaimEvidenceManifest, SupervisorProposal
    from netcoop.storage.sqlite import SQLiteRepository


def _confidence_to_numeric(category: ConfidenceCategory, has_limitations: bool) -> float:
    """Deterministic mapping from ConfidenceCategory to numeric confidence score."""
    mapping = {
        ConfidenceCategory.HIGH: 0.90 if not has_limitations else 0.80,
        ConfidenceCategory.MODERATE: 0.70 if not has_limitations else 0.65,
        ConfidenceCategory.LOW: 0.45 if not has_limitations else 0.40,
        ConfidenceCategory.INSUFFICIENT: 0.0,
    }
    return mapping.get(category, 0.50)


def _infer_affected_entities(
    roots: list[str], observations: list[CanonicalObservation]
) -> list[str]:
    """Infer direct impact from explicit topology and dependency relationships."""
    return list(dict.fromkeys(item.entity_id for item in _infer_impact_records(roots, observations)))


def _infer_impact_records(
    roots: list[str], observations: list[CanonicalObservation]
) -> list[PredictedImpact]:
    """Traverse declared dependencies/links, retaining the path behind each candidate."""
    root_set = set(roots)
    root_devices = {root.partition(":")[0] for root in roots if ":" in root}
    dependency_types = {
        "dns", "dhcp", "wireless_access", "uplink", "default_gateway", "depends_on",
    }
    physical_types = {"connected_to", "ethernet", "trunk", "wireless", "fiber", "uplink_of"}
    adjacency: dict[str, list[tuple[str, str, str, str]]] = {}

    def add_edge(source: str, target: str, relation: str, evidence_ref: str, kind: str) -> None:
        adjacency.setdefault(source, []).append((target, relation, evidence_ref, kind))

    for obs in observations:
        if not isinstance(obs, TopologyObservation):
            continue
        relation = obs.relationship_type.casefold()
        if relation in dependency_types:
            # Topology records consumer -> provider; impact propagates provider -> consumer.
            add_edge(obs.target_entity, obs.source_entity, relation, obs.observation_id, "dependency")
        elif relation in physical_types or relation == "connected_to":
            add_edge(obs.source_entity, obs.target_entity, relation, obs.observation_id, "physical")
            add_edge(obs.target_entity, obs.source_entity, relation, obs.observation_id, "physical")

        # Capture-folder links identify the source endpoint's interface. Connect an
        # interface-level root directly to its peer, without labeling its parent device impacted.
        interface = obs.interface_name
        if interface:
            for root in roots:
                if root == interface or root.endswith(f":{interface}") or interface.endswith(f":{root}"):
                    add_edge(root, obs.target_entity, relation or "interface_link", obs.observation_id, "physical")

    results: dict[str, PredictedImpact] = {}
    max_hops = 3
    max_candidates = 50
    for root in roots:
        root_edges = adjacency.get(root, [])
        dependency_mode = any(kind == "dependency" for _target, _rel, _ref, kind in root_edges)
        queue: list[tuple[str, list[str], list[str], list[str]]] = [(root, [root], [], [])]
        visited_depth = {root: 0}
        while queue:
            current, path, relations, evidence_refs = queue.pop(0)
            hops = len(relations)
            if hops >= max_hops:
                continue
            for target, relation, evidence_ref, edge_kind in adjacency.get(current, []):
                if dependency_mode and edge_kind != "dependency":
                    continue
                next_depth = hops + 1
                if target in root_set or target in root_devices or target in path:
                    continue
                if visited_depth.get(target, max_hops + 1) <= next_depth:
                    continue
                visited_depth[target] = next_depth
                next_path = [*path, target]
                next_relations = [*relations, relation]
                next_evidence = [*evidence_refs, evidence_ref]
                results.setdefault(target, PredictedImpact(
                    entity_id=target,
                    relation=" → ".join(next_relations),
                    inferred_from=root,
                    path=next_path,
                    hops=next_depth,
                    topology_evidence_refs=next_evidence,
                ))
                if len(results) >= max_candidates:
                    return list(results.values())
                queue.append((target, next_path, next_relations, next_evidence))
    return sorted(results.values(), key=lambda item: (item.hops, item.entity_id))


class EvidenceReleaseGate:
    """Independent deterministic release verifier for case-level diagnostic proposals."""

    def __init__(self, repository: SQLiteRepository | None = None) -> None:
        self.repo = repository

    def evaluate(
        self,
        proposal: SupervisorProposal,
        manifest: ClaimEvidenceManifest | None = None,
        incident_id: str | None = None,
        known_observations: list[CanonicalObservation] | None = None,
        known_findings: list[Finding] | None = None,
        competing_hypotheses: list[str] | None = None,
        data_quality_warnings: list[str] | None = None,
        orchestration_warnings: list[str] | None = None,
        peer_interactions: list[dict[str, Any]] | None = None,
        network_profile: dict[str, str] | None = None,
    ) -> GateResult:
        """Evaluates a supervisor proposal and claim manifest against known incident facts."""
        inc_id = incident_id or proposal.incident_id
        checks: list[GateCheckResult] = []
        errors: list[str] = []
        warnings: list[str] = []
        limitations: list[str] = []

        # 1. Resolve repository state if not provided
        obs_map: dict[str, CanonicalObservation] = {}
        if known_observations is not None:
            for obs in known_observations:
                obs_map[obs.observation_id] = obs
        elif self.repo is not None:
            for obs in self.repo.get_observations(inc_id):
                obs_map[obs.observation_id] = obs

        findings_map: dict[str, Finding] = {}
        if known_findings is not None:
            for f in known_findings:
                findings_map[f.finding_id] = f
        elif self.repo is not None:
            for f_id in proposal.supporting_finding_refs:
                f_obj = self.repo.get_finding_by_id(f_id)
                if f_obj:
                    findings_map[f_id] = f_obj
            for f in self.repo.get_findings(inc_id):
                findings_map[f.finding_id] = f

        data_quality_warnings = list(dict.fromkeys(data_quality_warnings or []))
        orchestration_warnings = list(dict.fromkeys(orchestration_warnings or []))
        peer_interactions = peer_interactions or []
        observations_for_impact = known_observations or list(obs_map.values())

        # Handle explicit Abstention proposals
        if proposal.decision == ProposalDecision.ABSTAIN:
            if not proposal.abstain_reason:
                err = "Proposal decision is ABSTAIN but no abstain_reason was provided."
                errors.append(err)
                checks.append(GateCheckResult(check_name="abstain_reason_present", passed=False, message=err))
            else:
                checks.append(
                    GateCheckResult(
                        check_name="abstain_reason_present",
                        passed=True,
                        message=f"Valid abstention: {proposal.abstain_reason}",
                    )
                )

            reason = proposal.abstain_reason or "Insufficient diagnostic evidence"
            if proposal.abstain_type:
                diag_status = proposal.abstain_type
            elif "Normal telemetry" in reason:
                diag_status = "NORMAL"
            elif any(kw in reason.lower() for kw in ("inconclusive", "competing", "unresolved", "ambiguity")):
                diag_status = "ABSTAIN_UNRESOLVED"
            else:
                diag_status = "INSUFFICIENT_EVIDENCE"

            rep_status = "insufficient_evidence"

            final_report = FinalReport(
                incident_id=inc_id,
                status=rep_status,
                diagnostic_status=diag_status,
                suspected_root_cause=f"ABSTAIN: {reason}",
                confidence=0.0,
                affected_devices=proposal.affected_entities,
                directly_affected_entities=proposal.affected_entities,
                observed_symptom_entities=[],
                supporting_evidence=[],
                alternative_causes=proposal.alternative_causes,
                operator_questions=proposal.operator_questions,
                recommended_actions=proposal.recommended_actions,
                evidence_sources=[],
                limitations=[f"Supervisor decision: {diag_status.lower().replace('_', ' ')}."],
                confidence_category=ConfidenceCategory.INSUFFICIENT,
                data_quality_warnings=data_quality_warnings,
                orchestration_warnings=orchestration_warnings,
                peer_interactions=peer_interactions,
                network_profile=network_profile,
                generated_at=datetime.now(timezone.utc),
            )
            return GateResult(
                outcome=GateOutcome.ABSTAIN if not errors else GateOutcome.REJECT,
                passed=len(errors) == 0,
                checks=checks,
                issues=_issues_from_checks(checks),
                errors=errors,
                warnings=warnings,
                limitations=limitations,
                certified_final_report=final_report if not errors else None,
            )

        # 2. Check Required Fields & Schema Consistency
        if proposal.decision == ProposalDecision.PROPOSE_DIAGNOSIS:
            if not proposal.suspected_root_cause or not proposal.suspected_root_cause.strip():
                err = "Proposal decision is PROPOSE_DIAGNOSIS but suspected_root_cause is missing or empty."
                errors.append(err)
                checks.append(GateCheckResult(check_name="root_cause_present", passed=False, message=err))
            else:
                checks.append(
                    GateCheckResult(
                        check_name="root_cause_present",
                        passed=True,
                        message=f"Root cause specified: {proposal.suspected_root_cause}",
                    )
                )

            if proposal.confidence_category == ConfidenceCategory.INSUFFICIENT:
                err = "Proposal cannot propose a diagnosis with confidence category INSUFFICIENT."
                errors.append(err)
                checks.append(GateCheckResult(check_name="confidence_sufficient", passed=False, message=err))
            else:
                checks.append(
                    GateCheckResult(
                        check_name="confidence_sufficient",
                        passed=True,
                        message=f"Confidence category: {proposal.confidence_category.value}",
                    )
                )

            if not proposal.supporting_finding_refs:
                err = "Proposal proposes diagnosis without any supporting_finding_refs."
                errors.append(err)
                checks.append(GateCheckResult(check_name="supporting_findings_present", passed=False, message=err))
            else:
                checks.append(
                    GateCheckResult(
                        check_name="supporting_findings_present",
                        passed=True,
                        message=f"Found {len(proposal.supporting_finding_refs)} cited finding references.",
                    )
                )

        # 3. Check Finding Existence, Scope, and Supersession
        cited_findings: list[Finding] = []
        for f_id in proposal.supporting_finding_refs:
            if f_id not in findings_map:
                err = f"Cited finding '{f_id}' does not exist in incident repository."
                errors.append(err)
                checks.append(GateCheckResult(check_name="finding_existence", passed=False, message=err))
                continue

            finding = findings_map[f_id]
            cited_findings.append(finding)

            # Check Incident Scope
            if finding.incident_id != inc_id:
                err = (
                    f"Finding '{f_id}' belongs to different incident '{finding.incident_id}', expected '{inc_id}'."
                )
                errors.append(err)
                checks.append(GateCheckResult(check_name="finding_scope", passed=False, message=err))

            # Check Supersession / Retraction
            if finding.status == FindingStatus.SUPERSEDED:
                err = f"Finding '{f_id}' is SUPERSEDED and cannot be cited as valid supporting evidence."
                errors.append(err)
                checks.append(GateCheckResult(check_name="finding_not_superseded", passed=False, message=err))
            elif finding.status == FindingStatus.RETRACTED:
                err = f"Finding '{f_id}' is RETRACTED and cannot be cited as valid supporting evidence."
                errors.append(err)
                checks.append(GateCheckResult(check_name="finding_not_retracted", passed=False, message=err))

            # Check Finding Provenance
            if not finding.evidence_refs:
                warn = f"Finding '{f_id}' has empty evidence_refs; lacks direct observational provenance."
                warnings.append(warn)
                checks.append(GateCheckResult(check_name="finding_provenance", passed=True, message=warn, severity="warning"))

        # 4. Check Observation Existence and Scope from Manifest
        cited_obs_ids: list[str] = []
        seen_obs_ids: set[str] = set()

        def cite_observation(obs_id: str) -> None:
            if obs_id not in seen_obs_ids:
                seen_obs_ids.add(obs_id)
                cited_obs_ids.append(obs_id)

        if manifest is not None:
            # Check manifest finding references
            for mf_id in manifest.finding_ids:
                if mf_id not in findings_map:
                    err = f"Manifest cites finding '{mf_id}' which does not exist in repository."
                    errors.append(err)
                    checks.append(GateCheckResult(check_name="manifest_finding_existence", passed=False, message=err))

            # Check manifest observation references
            for obs_id in manifest.observation_ids:
                cite_observation(obs_id)
                if obs_id not in obs_map:
                    err = f"Manifest cites invented or missing observation ID '{obs_id}'."
                    errors.append(err)
                    checks.append(GateCheckResult(check_name="observation_existence", passed=False, message=err))
                else:
                    obs = obs_map[obs_id]
                    if obs.incident_id != inc_id:
                        err = f"Observation '{obs_id}' belongs to incident '{obs.incident_id}', not '{inc_id}'."
                        errors.append(err)
                        checks.append(GateCheckResult(check_name="observation_scope", passed=False, message=err))

        # Check observation IDs cited by findings
        for f in cited_findings:
            for obs_id in f.evidence_refs:
                cite_observation(obs_id)
                if obs_id not in obs_map:
                    warn = f"Finding '{f.finding_id}' links observation '{obs_id}' which is not in known observations."
                    warnings.append(warn)

        # 4b. Domain Semantic Evidence Validation
        # Verify that cited supporting observations semantically support the claimed fault and entity.
        if proposal.decision == ProposalDecision.PROPOSE_DIAGNOSIS and proposal.suspected_root_cause:
            fault_code = proposal.suspected_root_cause.split(":", 1)[0].strip()
            affected_entities = set(proposal.affected_entities)
            supporting_obs_ids = set(cited_obs_ids)
            for f in cited_findings:
                supporting_obs_ids.update(f.evidence_refs)
            supporting_obs = [obs_map[oid] for oid in supporting_obs_ids if oid in obs_map]

            if not supporting_obs:
                err = f"Claimed root cause '{fault_code}' has no resolvable supporting observations in repository."
                errors.append(err)
                checks.append(GateCheckResult(check_name="claim_evidence_semantic_consistency", passed=False, message=err))
            else:
                entity_matching_obs = []
                for o in supporting_obs:
                    o_ent = o.entity_id
                    if any(o_ent == ent or o_ent.startswith(f"{ent}:") or ent.startswith(f"{o_ent}:") for ent in affected_entities):
                        entity_matching_obs.append(o)

                if not entity_matching_obs and affected_entities:
                    obs_ents = sorted(list(set(o.entity_id for o in supporting_obs)))
                    err = (
                        f"Semantic validation failed: None of the cited supporting observations ({obs_ents[:3]}) "
                        f"correspond to claimed root-cause entity '{sorted(list(affected_entities))}'."
                    )
                    errors.append(err)
                    checks.append(GateCheckResult(check_name="claim_evidence_semantic_consistency", passed=False, message=err))
                else:
                    eval_obs = entity_matching_obs if entity_matching_obs else supporting_obs
                    semantic_error = self._validate_fault_semantics(fault_code, eval_obs, affected_entities)
                    if semantic_error:
                        errors.append(semantic_error)
                        checks.append(GateCheckResult(
                            check_name="claim_evidence_semantic_consistency",
                            passed=False,
                            message=semantic_error,
                        ))
                    else:
                        checks.append(GateCheckResult(
                            check_name="claim_evidence_semantic_consistency",
                            passed=True,
                            message=f"Semantic evidence validation passed: cited observations match '{fault_code}' domain requirements.",
                        ))

        # 5. Check Contradiction Disclosure
        if competing_hypotheses:
            for alt in competing_hypotheses:
                # Disclosed if in proposal alternative_causes or in manifest contradiction disclosures
                alt_code = alt.split(":", 1)[0].strip()
                disclosed_codes = {
                    candidate.split(":", 1)[0].strip()
                    for candidate in proposal.alternative_causes + proposal.concurrent_causes
                }
                disclosed = (
                    alt in proposal.alternative_causes
                    or alt in proposal.concurrent_causes
                    or alt_code in disclosed_codes
                )
                primary_code = (proposal.suspected_root_cause or "").split(":", 1)[0].strip()
                if primary_code and alt.startswith(f"{primary_code}: "):
                    disclosed = True
                if manifest and (
                    alt in manifest.contradiction_ids
                    or alt_code in {item.split(":", 1)[0].strip() for item in manifest.contradiction_ids}
                    or any(alt in disclosure or alt_code in disclosure for disclosure in manifest.contradiction_disclosures)
                ):
                    disclosed = True

                if not disclosed:
                    err = f"Unresolved competing hypothesis '{alt}' was not disclosed in alternative_causes or manifest."
                    errors.append(err)
                    checks.append(GateCheckResult(check_name="contradiction_disclosure", passed=False, message=err))
                else:
                    checks.append(GateCheckResult(check_name="contradiction_disclosure", passed=True, message=f"Disclosed competing hypothesis: {alt}"))

        # 6. Check Independence Groups
        independence_groups: set[str] = set()
        for f in cited_findings:
            independence_groups.add(f.independence_group or f.source_tower.value)
            qualifying = f.metadata.get("qualifying_samples")
            observed = f.metadata.get("observed_samples")
            if isinstance(qualifying, int) and isinstance(observed, int) and observed > 0:
                coverage = qualifying / observed
                if qualifying < 3 or coverage < 0.5:
                    limitation = (
                        f"{f.finding_type} on {', '.join(f.entity_refs)} has limited temporal support: "
                        f"{qualifying} qualifying sample(s) out of {observed}; verify persistence before remediation."
                    )
                    limitations.append(limitation)

        if len(independence_groups) <= 1 and proposal.confidence_category == ConfidenceCategory.HIGH:
            warn = "Proposal claims HIGH confidence but supporting evidence is from only a single independence group."
            warnings.append(warn)
            limitations.append("Diagnosis based on a single evidence stream without independent cross-domain corroboration.")
            # Downgrade confidence category
            proposal.confidence_category = ConfidenceCategory.MODERATE

        # Check temporal persistence & single snapshot
        cited_metric_obs = [
            obs for obs_id in cited_obs_ids
            if (obs := obs_map.get(obs_id)) is not None and isinstance(obs, MetricObservation)
        ]
        unique_metric_timestamps = {o.timestamp for o in cited_metric_obs}
        qualifying_samples_list = [
            f.metadata.get("qualifying_samples") for f in cited_findings
            if isinstance(f.metadata, dict) and isinstance(f.metadata.get("qualifying_samples"), int)
        ]
        is_single_snapshot = (
            len(unique_metric_timestamps) <= 1
            or (qualifying_samples_list and max(qualifying_samples_list, default=1) <= 1)
        )
        if is_single_snapshot and proposal.decision == ProposalDecision.PROPOSE_DIAGNOSIS:
            single_snapshot_note = (
                "Single-snapshot observation: Evidence was captured in a single polling interval without "
                "demonstrated temporal persistence; verify ongoing state before taking intrusive remediation actions."
            )
            if single_snapshot_note not in limitations:
                limitations.append(single_snapshot_note)
            if proposal.confidence_category == ConfidenceCategory.HIGH:
                warn = "Proposal claims HIGH confidence but evidence is from a single snapshot; downgraded to MODERATE."
                warnings.append(warn)
                proposal.confidence_category = ConfidenceCategory.MODERATE

        # Conflicting values for the same metric, entity, and timestamp weaken
        # support even when one tower's threshold rule can still identify a fault.
        metric_samples: dict[tuple[str, str, datetime], list[CanonicalObservation]] = {}
        target_entities = set(proposal.affected_entities)
        for observation in obs_map.values():
            if not isinstance(observation, MetricObservation):
                continue
            if target_entities and observation.entity_id not in target_entities:
                continue
            metric_samples.setdefault(
                (observation.entity_id, observation.metric_name, observation.timestamp), []
            ).append(observation)
        conflict_groups = [
            (key, items) for key, items in metric_samples.items()
            if len({item.value for item in items}) > 1
        ]
        for (entity_id, metric_name, observed_at), items in conflict_groups:
            values = ", ".join(
                f"{item.value:g} {item.unit} ({item.observation_id})" for item in items
            )
            message = (
                f"Conflicting {metric_name} readings for {entity_id} at "
                f"{observed_at.isoformat()}: {values}."
            )
            warnings.append(message)
            limitations.append(
                f"Conflicting same-time telemetry for {entity_id}.{metric_name}; verify the source before acting."
            )
            checks.append(GateCheckResult(
                check_name="same_time_measurement_consistency",
                passed=False,
                message=message,
                severity="warning",
            ))
        if conflict_groups and proposal.confidence_category in {
            ConfidenceCategory.HIGH, ConfidenceCategory.MODERATE,
        }:
            proposal.confidence_category = ConfidenceCategory.LOW

        # 7. Synthesize Supporting Evidence Items for Final Report
        evidence_items: list[SupportingEvidenceItem] = []
        for f in cited_findings:
            evidence_items.append(
                SupportingEvidenceItem(
                    metric=f"{f.source_tower.value}.{f.finding_type}",
                    value=f"{f.severity.value}: {f.entity_refs}",
                    interpretation=f.description,
                )
            )

        # If observations available, include up to 5 top observation metrics
        selected_obs_ids: list[str] = []
        selected_metric_keys: set[tuple[str, str]] = set()
        for obs_id in cited_obs_ids:
            obs = obs_map.get(obs_id)
            metric_name = getattr(obs, "metric_name", None) if obs is not None else None
            if metric_name is not None:
                key = (obs.entity_id, metric_name)
                if key not in selected_metric_keys:
                    selected_metric_keys.add(key)
                    selected_obs_ids.append(obs_id)
        for obs_id in cited_obs_ids:
            if obs_id not in selected_obs_ids:
                selected_obs_ids.append(obs_id)

        for obs_id in selected_obs_ids[:5]:
            if obs_id in obs_map:
                obs = obs_map[obs_id]
                val = getattr(obs, "value", None)
                if val is None:
                    val = getattr(obs, "message", None)
                if val is None:
                    val = getattr(obs, "connected_entity", None)
                if val is None:
                    val = "N/A"
                metric_name = getattr(obs, "metric_name", None) or obs.observation_type
                unit = getattr(obs, "unit", None)
                evidence_items.append(
                    SupportingEvidenceItem(
                        metric=f"raw.{obs.entity_id}.{metric_name}",
                        value=val,
                        interpretation=f"Source observation {obs_id} from {obs.source}",
                        entity_id=obs.entity_id,
                        unit=unit,
                        observed_at=obs.timestamp,
                        source=obs.source,
                    )
                )

        # 8. Determine Gate Outcome
        passed = len(errors) == 0
        if not passed:
            outcome = GateOutcome.REJECT
            certified_report = None
        else:
            warnings.extend(data_quality_warnings)
            warnings.extend(orchestration_warnings)
            has_warnings_or_limitations = bool(warnings or limitations)
            outcome = GateOutcome.PASS_WITH_LIMITATIONS if has_warnings_or_limitations else GateOutcome.PASS

            num_conf = _confidence_to_numeric(proposal.confidence_category, has_limitations=has_warnings_or_limitations)
            all_limits = list(dict.fromkeys(limitations + proposal.alternative_causes))

            certified_report = FinalReport(
                incident_id=inc_id,
                status=ReportStatus("diagnosed"),
                diagnostic_status="DIAGNOSIS",
                suspected_root_cause=proposal.suspected_root_cause or "UNKNOWN",
                confidence=num_conf,
                affected_devices=list(dict.fromkeys(
                    proposal.affected_entities + _infer_affected_entities(proposal.affected_entities, observations_for_impact)
                )),
                directly_affected_entities=proposal.affected_entities,
                observed_symptom_entities=list(dict.fromkeys(
                    item.entity_id for item in evidence_items if item.entity_id
                )),
                inferred_affected_entities=_infer_affected_entities(proposal.affected_entities, observations_for_impact),
                predicted_impacts=_infer_impact_records(proposal.affected_entities, observations_for_impact),
                operator_questions=proposal.operator_questions,
                supporting_evidence=evidence_items,
                alternative_causes=proposal.alternative_causes,
                recommended_actions=proposal.recommended_actions,
                evidence_sources=sorted(list(independence_groups)),
                limitations=all_limits,
                confidence_category=proposal.confidence_category,
                concurrent_causes=proposal.concurrent_causes,
                data_quality_warnings=data_quality_warnings,
                orchestration_warnings=orchestration_warnings,
                peer_interactions=peer_interactions,
                network_profile=network_profile,
                generated_at=datetime.now(timezone.utc),
            )

        return GateResult(
            outcome=outcome,
            passed=passed,
            checks=checks,
            issues=_issues_from_checks(checks),
            errors=errors,
            warnings=warnings,
            limitations=limitations,
            certified_final_report=certified_report,
            evaluated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _validate_fault_semantics(
        fault_code: str, observations: list[CanonicalObservation], entities: set[str]
    ) -> str | None:
        """Deterministically validate that cited observations semantically corroborate the claimed fault."""
        metrics: dict[str, list[float]] = {}
        for obs in observations:
            if isinstance(obs, MetricObservation):
                metrics.setdefault(obs.metric_name, []).append(obs.value)

        log_messages = [
            obs.message for obs in observations if isinstance(obs, LogObservation)
        ]

        if fault_code == "LINK_CONGESTION":
            has_util = any(val >= 75.0 for val in metrics.get("link_utilization_pct", []))
            has_drops = any(val > 0 for val in metrics.get("queue_drops", []))
            has_loss = any(val > 0 for val in metrics.get("packet_loss_pct", []))
            has_lat = any(val >= 100.0 for val in metrics.get("latency_ms", []))
            if not (has_util or has_drops or has_loss or has_lat):
                return (
                    f"Congestion claim on '{sorted(list(entities))}' lacks supporting link utilization "
                    f"(>= 75%) or buffer pressure (queue drops, packet loss) in cited observations."
                )

        elif fault_code == "DEVICE_OVERLOAD":
            has_cpu = any(val >= 75.0 for val in metrics.get("cpu_utilization_pct", []))
            has_mem = any(val >= 75.0 for val in metrics.get("memory_utilization_pct", []))
            if not (has_cpu or has_mem):
                return (
                    f"Device overload claim on '{sorted(list(entities))}' lacks supporting CPU or "
                    f"memory saturation measurements (>= 75%) in cited observations."
                )

        elif fault_code == "WEAK_WIFI":
            has_rssi = any(val <= -65.0 for val in metrics.get("rssi_dbm", []))
            has_snr = any(val <= 25.0 for val in metrics.get("snr_db", []))
            if not (has_rssi or has_snr):
                return (
                    f"Weak Wi-Fi claim on '{sorted(list(entities))}' lacks supporting RF signal "
                    f"measurements (RSSI <= -65dBm or SNR <= 25dB) in cited observations."
                )

        elif fault_code == "INTERFACE_FAULT":
            has_errs = any(val > 0 for val in metrics.get("interface_errors", []))
            has_crc = any(val > 0 for val in metrics.get("crc_errors", []))
            has_flaps = any(val > 0 for val in metrics.get("link_flaps", []))
            has_input_errs = any(val > 0 for val in metrics.get("input_errors", []))
            has_err_log = any(
                any(kw in msg.upper() for kw in ("ERROR", "CRC", "FLAP", "DOWN", "RESET"))
                for msg in log_messages
            )
            if not (has_errs or has_crc or has_flaps or has_input_errs or has_err_log):
                return (
                    f"Interface fault claim on '{sorted(list(entities))}' lacks supporting interface error counters "
                    f"or error logs in cited observations."
                )

        elif fault_code == "DNS_FAILURE":
            has_lat = any(val >= 100.0 for val in metrics.get("latency_ms", []))
            has_dns_lat = any(val >= 100.0 for val in metrics.get("dns_latency_ms", []))
            has_log = any(
                any(kw in msg.upper() for kw in ("SERVFAIL", "TIMEOUT", "REFUSED", "NXDOMAIN"))
                for msg in log_messages
            )
            if not (has_lat or has_dns_lat or has_log):
                return (
                    f"DNS failure claim on '{sorted(list(entities))}' lacks supporting DNS resolution latency "
                    f"or error logs in cited observations."
                )

        elif fault_code == "DHCP_FAILURE":
            has_pool = any(val >= 90.0 for val in metrics.get("dhcp_pool_utilization_pct", []))
            has_lat = any(val >= 500.0 for val in metrics.get("latency_ms", []))
            has_loss = any(val >= 10.0 for val in metrics.get("packet_loss_pct", []))
            has_log = any(
                any(kw in msg.upper() for kw in ("EXHAUST", "NAK", "DEPLETED", "FULL", "DHCP", "TIMEOUT", "FAIL"))
                for msg in log_messages
            )
            if not (has_pool or has_lat or has_loss or has_log):
                return (
                    f"DHCP failure claim on '{sorted(list(entities))}' lacks supporting DHCP service metrics "
                    f"(latency, packet loss, pool utilization) or DHCP error logs in cited observations."
                )

        return None
