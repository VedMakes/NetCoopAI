import React from 'react';
import { EvaluationResponse } from '../types';
import { Award, CheckCircle2, XCircle, ShieldCheck, Info } from 'lucide-react';

interface EvaluationCardProps {
  evaluation: EvaluationResponse | null;
}

export const EvaluationCard: React.FC<EvaluationCardProps> = ({ evaluation }) => {
  if (!evaluation) {
    return (
      <div className="bg-noc-card border border-noc-border rounded-xl p-5 shadow-lg space-y-3">
        <div className="flex items-center gap-2">
          <Award className="w-5 h-5 text-noc-muted" />
          <h3 className="text-base font-semibold text-noc-text">Benchmark Accuracy Evaluation</h3>
        </div>
        <p className="text-xs text-noc-muted">
          Benchmark evaluation against hidden ground truth becomes available once diagnostic pipeline completes.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-noc-card border border-noc-border rounded-xl p-5 shadow-lg space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-noc-border/60">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-lg bg-noc-emerald/10 border border-noc-emerald/30 text-noc-emerald">
            <Award className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-bold text-noc-text flex items-center gap-2">
              Benchmark Accuracy Evaluation
              <span className="text-[10px] font-mono uppercase bg-noc-bg px-2 py-0.5 rounded border border-noc-border text-noc-muted">
                Post-Diagnosis Quarantine Release
              </span>
            </h3>
            <p className="text-xs text-noc-muted">
              Audits diagnostic outcome against hidden ground-truth injection for scenario: <span className="text-noc-cyan font-mono">{evaluation.scenario_id}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5 text-xs text-noc-emerald bg-noc-emerald/10 border border-noc-emerald/30 px-2.5 py-1 rounded shrink-0">
          <ShieldCheck className="w-4 h-4" />
          <span>Zero Runtime Leakage</span>
        </div>
      </div>

      {/* Accuracy KPI Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-noc-bg/80 border border-noc-border rounded-lg p-3 space-y-1">
          <div className="text-[11px] text-noc-muted uppercase font-semibold">Class Match</div>
          <div className="flex items-center gap-1.5 pt-0.5">
            {evaluation.class_match ? (
              <>
                <CheckCircle2 className="w-5 h-5 text-noc-emerald" />
                <span className="text-sm font-bold text-noc-emerald">MATCH</span>
              </>
            ) : (
              <>
                <XCircle className="w-5 h-5 text-red-400" />
                <span className="text-sm font-bold text-red-400">MISMATCH</span>
              </>
            )}
          </div>
        </div>

        <div className="bg-noc-bg/80 border border-noc-border rounded-lg p-3 space-y-1">
          <div className="text-[11px] text-noc-muted uppercase font-semibold">Target Entity</div>
          <div className="flex items-center gap-1.5 pt-0.5">
            {evaluation.target_match ? (
              <>
                <CheckCircle2 className="w-5 h-5 text-noc-emerald" />
                <span className="text-sm font-bold text-noc-emerald">LOCALIZED</span>
              </>
            ) : (
              <>
                <XCircle className="w-5 h-5 text-noc-amber" />
                <span className="text-sm font-bold text-noc-amber">OFF-TARGET</span>
              </>
            )}
          </div>
        </div>

        <div className="bg-noc-bg/80 border border-noc-border rounded-lg p-3 space-y-1">
          <div className="text-[11px] text-noc-muted uppercase font-semibold">Precision</div>
          <div className="text-base font-bold font-mono text-noc-cyan pt-0.5">
            {(evaluation.precision * 100).toFixed(0)}%
          </div>
        </div>

        <div className="bg-noc-bg/80 border border-noc-border rounded-lg p-3 space-y-1">
          <div className="text-[11px] text-noc-muted uppercase font-semibold">Recall / F1</div>
          <div className="text-base font-bold font-mono text-noc-purple pt-0.5">
            {(evaluation.recall * 100).toFixed(0)}% / {(evaluation.f1 * 100).toFixed(0)}%
          </div>
        </div>
      </div>

      {/* Comparison Details */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
        <div className="bg-noc-bg/70 border border-noc-border rounded-lg p-3 space-y-2">
          <div className="text-[11px] text-noc-muted uppercase font-semibold">
            Injected Ground Truth
          </div>
          <div className="space-y-1 font-mono">
            <div>
              <span className="text-noc-muted">Injected Fault: </span>
              <span className="text-noc-amber font-bold">{evaluation.injected_fault_class}</span>
            </div>
            {evaluation.target_entity && (
              <div>
                <span className="text-noc-muted">Target Entity: </span>
                <span className="text-noc-text">{evaluation.target_entity}</span>
              </div>
            )}
            <div className="pt-1">
              <span className="text-noc-muted block text-[10px] uppercase font-sans">
                Intended Affected Entities ({evaluation.intended_affected_entities.length}):
              </span>
              <div className="flex flex-wrap gap-1 mt-1">
                {evaluation.intended_affected_entities.map((e) => (
                  <span
                    key={e}
                    className="bg-noc-card px-1.5 py-0.5 rounded border border-noc-border text-[11px] text-noc-text"
                  >
                    {e}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="bg-noc-bg/70 border border-noc-border rounded-lg p-3 space-y-2">
          <div className="text-[11px] text-noc-muted uppercase font-semibold">
            Diagnosed Release Report
          </div>
          <div className="space-y-1 font-mono">
            <div>
              <span className="text-noc-muted">Suspected Fault: </span>
              <span className="text-noc-cyan font-bold">{evaluation.diagnosed_root_cause}</span>
            </div>
            <div className="pt-1">
              <span className="text-noc-muted block text-[10px] uppercase font-sans">
                Reported Affected Entities ({evaluation.reported_affected_entities.length}):
              </span>
              <div className="flex flex-wrap gap-1 mt-1">
                {evaluation.reported_affected_entities.map((e) => (
                  <span
                    key={e}
                    className="bg-noc-card px-1.5 py-0.5 rounded border border-noc-border text-[11px] text-noc-cyan"
                  >
                    {e}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 text-xs text-noc-muted bg-noc-bg/50 px-3 py-2 rounded-lg border border-noc-border/60">
        <Info className="w-4 h-4 text-noc-cyan shrink-0" />
        <span>
          Ground truth is strictly isolated in evaluation fixtures and is never accessed by towers, supervisor runtime, or the assistant during live analysis.
        </span>
      </div>
    </div>
  );
};
