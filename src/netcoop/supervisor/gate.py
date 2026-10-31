"""Evidence and Release Gate for NetCoop AI.

Independent, deterministic verification gate validating whether a proposed diagnosis
meets all objective publication standards, citation provenance, scope, and freshness rules.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from netcoop.models.enums import ConfidenceCategory, FindingStatus, ProposalDecision
from netcoop.models.findings import Finding
from netcoop.models.observations import CanonicalObservation, TopologyObservation
from netcoop.models.reports import FinalReport, SupportingEvidenceItem
from netcoop.supervisor.models import GateCheckResult, GateOutcome, GateResult

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
    root_set = set(roots)
    inferred: list[str] = []
    for obs in observations:
        if not isinstance(obs, TopologyObservation):
            continue
        if obs.interface_name in root_set:
            inferred.extend([obs.source_entity, obs.target_entity])
        elif obs.relationship_type in {"dns", "dhcp", "wireless_access"}:
            if obs.target_entity in root_set:
                inferred.append(obs.source_entity)
            if obs.relationship_type == "wireless_access" and obs.source_entity in root_set:
                inferred.append(obs.target_entity)
        elif obs.relationship_type == "connected_to":
            if obs.source_entity in root_set:
                inferred.append(obs.target_entity)
            if obs.target_entity in root_set:
                inferred.append(obs.source_entity)
    return list(dict.fromkeys(entity for entity in inferred if entity not in root_set))


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

            final_report = FinalReport(
                incident_id=inc_id,
                status="insufficient_evidence",
                suspected_root_cause=f"ABSTAIN: {proposal.abstain_reason or 'Insufficient diagnostic evidence'}",
                confidence=0.0,
                affected_devices=proposal.affected_entities,
                supporting_evidence=[],
                alternative_causes=proposal.alternative_causes,
                recommended_actions=proposal.recommended_actions,
                evidence_sources=[],
                limitations=["Diagnostic engines abstained due to ambiguity or insufficient evidence."],
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

        # 5. Check Contradiction Disclosure
        if competing_hypotheses:
            for alt in competing_hypotheses:
                # Disclosed if in proposal alternative_causes or in manifest contradiction disclosures
                disclosed = alt in proposal.alternative_causes or alt in proposal.concurrent_causes
                primary_code = (proposal.suspected_root_cause or "").split(":", 1)[0]
                if primary_code and alt.startswith(f"{primary_code}: "):
                    disclosed = True
                if manifest and (alt in manifest.contradiction_ids or any(alt in d for d in manifest.contradiction_disclosures)):
                    disclosed = True

                if not disclosed:
                    warn = f"Unresolved competing hypothesis '{alt}' was not disclosed in alternative_causes or manifest."
                    warnings.append(warn)
                    limitations.append(f"Competing hypothesis '{alt}' was identified across towers but not explicitly dispositioned.")
                    checks.append(GateCheckResult(check_name="contradiction_disclosure", passed=False, message=warn, severity="warning"))
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
                status="diagnosed",
                suspected_root_cause=proposal.suspected_root_cause or "UNKNOWN",
                confidence=num_conf,
                affected_devices=list(dict.fromkeys(
                    proposal.affected_entities + _infer_affected_entities(proposal.affected_entities, observations_for_impact)
                )),
                inferred_affected_entities=_infer_affected_entities(proposal.affected_entities, observations_for_impact),
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
            errors=errors,
            warnings=warnings,
            limitations=limitations,
            certified_final_report=certified_report,
            evaluated_at=datetime.now(timezone.utc),
        )
