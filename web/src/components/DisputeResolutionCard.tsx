import React from 'react';
import { FinalReport, TowerReportSummary } from '../types';
import { GitCompare, CheckCircle2, XCircle, ArrowRight, ShieldAlert, GitFork, Info } from 'lucide-react';

interface DisputeResolutionCardProps {
  report: FinalReport;
  towers?: TowerReportSummary[];
}

export const DisputeResolutionCard: React.FC<DisputeResolutionCardProps> = ({ report, towers = [] }) => {
  // Extract all competing hypotheses across towers that were NOT selected as primary
  const competingHypotheses = React.useMemo(() => {
    const list: Array<{
      towerId: string;
      faultCode: string;
      confidence: number;
      category: string;
      rationale: string;
      isSelected: boolean;
    }> = [];

    const rootCauseUpper = report.suspected_root_cause.toUpperCase();

    towers.forEach((tower) => {
      tower.hypotheses.forEach((hyp) => {
        const isMatch = rootCauseUpper.includes(hyp.fault_code.toUpperCase());
        list.push({
          towerId: tower.tower_id,
          faultCode: hyp.fault_code,
          confidence: hyp.confidence,
          category: hyp.confidence_category,
          rationale: hyp.rationale,
          isSelected: isMatch,
        });
      });
    });

    return list;
  }, [report, towers]);

  const winningHypothesis = competingHypotheses.find((h) => h.isSelected);
  const rejectedHypotheses = competingHypotheses.filter((h) => !h.isSelected);

  return (
    <div className="bg-noc-card border border-noc-border rounded-xl p-5 shadow-lg space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-noc-border/60">
        <div>
          <h3 className="text-base font-semibold text-noc-text flex items-center gap-2">
            <GitCompare className="w-5 h-5 text-noc-cyan" />
            Supervisor Conflict Arbitration & Dispute Resolution
          </h3>
          <p className="text-xs text-noc-muted">
            Audits how the supervisory RCA agent evaluated competing tower hypotheses and weighed trade-offs.
          </p>
        </div>
        <div className="text-xs text-noc-cyan font-mono bg-noc-cyan/10 border border-noc-cyan/30 px-2.5 py-1 rounded shrink-0">
          Deterministic Consensus
        </div>
      </div>

      {/* Selected Root Cause Consensus Banner */}
      <div className="bg-noc-bg/90 border border-noc-cyan/50 rounded-xl p-4 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <div className="text-[11px] text-noc-cyan font-semibold uppercase tracking-wider flex items-center gap-1.5">
              <CheckCircle2 className="w-4 h-4 text-noc-emerald" />
              Consensus Selected Root Cause
            </div>
            <div className="text-sm font-bold text-noc-text font-mono">
              {report.suspected_root_cause}
            </div>
          </div>
          <div className="text-right shrink-0">
            <div className="text-[10px] text-noc-muted uppercase">Confidence</div>
            <div className="text-base font-bold text-noc-cyan font-mono">
              {(report.confidence * 100).toFixed(0)}%
            </div>
          </div>
        </div>

        {winningHypothesis && (
          <p className="text-xs text-noc-muted leading-relaxed border-t border-noc-border/60 pt-2.5">
            <span className="text-noc-text font-semibold">Selection Rationale: </span>
            {winningHypothesis.rationale}
          </p>
        )}
      </div>

      {/* Competing & Rejected Hypotheses */}
      <div className="space-y-2.5">
        <div className="text-xs font-semibold text-noc-text uppercase tracking-wider flex items-center gap-1.5">
          <ShieldAlert className="w-3.5 h-3.5 text-noc-amber" />
          Alternative Hypotheses Evaluated & Downweighted ({rejectedHypotheses.length + report.alternative_causes.length})
        </div>

        {rejectedHypotheses.length > 0 ? (
          <div className="space-y-2">
            {rejectedHypotheses.map((hyp, i) => (
              <div
                key={i}
                className="bg-noc-bg/70 border border-noc-border rounded-lg p-3 space-y-1.5 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <XCircle className="w-3.5 h-3.5 text-noc-muted shrink-0" />
                    <span className="font-mono font-bold text-noc-muted">{hyp.faultCode}</span>
                    <span className="text-[10px] text-noc-muted uppercase bg-noc-card px-1.5 py-0.5 rounded border border-noc-border">
                      {hyp.towerId}
                    </span>
                  </div>
                  <span className="text-[11px] font-mono text-noc-muted">
                    Score: {(hyp.confidence * 100).toFixed(0)}% ({hyp.category})
                  </span>
                </div>
                <p className="text-noc-muted text-[11px] leading-relaxed pl-5">
                  <span className="text-noc-text font-medium">Rejection Reason: </span>
                  {hyp.rationale || 'Insufficient independent corroborating evidence or lower anomaly correlation score.'}
                </p>
              </div>
            ))}
          </div>
        ) : report.alternative_causes.length > 0 ? (
          <div className="space-y-1.5">
            {report.alternative_causes.map((alt, i) => (
              <div
                key={i}
                className="bg-noc-bg/70 border border-noc-border rounded-lg p-3 text-xs text-noc-muted flex items-center gap-2"
              >
                <XCircle className="w-3.5 h-3.5 text-noc-muted shrink-0" />
                <span>{alt}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-3 bg-noc-bg/50 border border-noc-border rounded-lg text-xs text-noc-muted">
            No contradictory hypotheses required downweighting; telemetry unambiguously pinpointed single primary fault.
          </div>
        )}
      </div>

      {/* Path Triage Reachability Section if available */}
      {report.path_triage && report.path_triage.paths && report.path_triage.paths.length > 0 && (
        <div className="space-y-2 pt-2 border-t border-noc-border/60">
          <div className="text-xs font-semibold text-noc-text uppercase tracking-wider flex items-center gap-1.5">
            <GitFork className="w-3.5 h-3.5 text-noc-purple" />
            Topological Path Triage & Reachability
          </div>
          <div className="space-y-1.5 max-h-48 overflow-y-auto">
            {report.path_triage.paths.map((p, idx) => (
              <div
                key={idx}
                className="bg-noc-bg/90 border border-noc-border rounded-lg p-2.5 text-xs flex flex-col sm:flex-row sm:items-center justify-between gap-2"
              >
                <div className="flex items-center gap-1.5 font-mono text-noc-cyan flex-wrap">
                  {p.path.map((node, nIdx) => (
                    <React.Fragment key={node}>
                      <span className="bg-noc-card px-1.5 py-0.5 rounded border border-noc-border text-[11px]">
                        {node}
                      </span>
                      {nIdx < p.path.length - 1 && (
                        <ArrowRight className="w-3 h-3 text-noc-muted shrink-0" />
                      )}
                    </React.Fragment>
                  ))}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span
                    className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                      p.reachable
                        ? 'bg-noc-emerald/15 text-noc-emerald border-noc-emerald/30'
                        : 'bg-red-500/15 text-red-400 border-red-500/30'
                    }`}
                  >
                    {p.reachable ? 'REACHABLE' : 'UNREACHABLE'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Caveat Footer */}
      <div className="flex items-center gap-2 text-xs text-noc-muted bg-noc-bg/50 px-3 py-2 rounded-lg border border-noc-border/60">
        <Info className="w-4 h-4 text-noc-cyan shrink-0" />
        <span>
          Conflict arbitration uses deterministic ranking matrices to prevent confirmation bias between competing diagnostic towers.
        </span>
      </div>
    </div>
  );
};
