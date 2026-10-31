import React from 'react';
import { GateResultDetail, GateCheckResult } from '../types';
import { ShieldCheck, ShieldAlert, CheckCircle2, XCircle, AlertTriangle, Info, Clock } from 'lucide-react';

interface EvidenceGateCardProps {
  gate: GateResultDetail | null;
  limitations?: string[];
}

export const EvidenceGateCard: React.FC<EvidenceGateCardProps> = ({ gate, limitations = [] }) => {
  if (!gate) {
    return (
      <div className="bg-noc-card border border-noc-border rounded-xl p-5 shadow-lg space-y-3">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-5 h-5 text-noc-muted" />
          <h3 className="text-base font-semibold text-noc-text">Evidence Release Gate</h3>
        </div>
        <p className="text-xs text-noc-muted">
          Gate verification results will become available once the supervisor proposal has undergone independent audit.
        </p>
      </div>
    );
  }

  const isPassed = gate.passed;
  const isLimited = gate.outcome.includes('LIMITATIONS');
  const allLimitations = Array.from(new Set([...(gate.limitations || []), ...limitations]));

  return (
    <div
      className={`rounded-xl border p-5 shadow-lg space-y-5 transition-all ${
        isPassed && !isLimited
          ? 'bg-noc-card border-noc-emerald/50 shadow-noc-emerald/5'
          : isPassed
          ? 'bg-noc-card border-noc-amber/50 shadow-noc-amber/5'
          : 'bg-noc-card border-red-500/50 shadow-red-500/5'
      }`}
    >
      {/* Gate Top Header & Outcome Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-noc-border/60">
        <div className="flex items-center gap-3">
          <div
            className={`p-2.5 rounded-xl border ${
              isPassed && !isLimited
                ? 'bg-noc-emerald/15 text-noc-emerald border-noc-emerald/40'
                : isPassed
                ? 'bg-noc-amber/15 text-noc-amber border-noc-amber/40'
                : 'bg-red-500/15 text-red-400 border-red-500/40'
            }`}
          >
            {isPassed ? <ShieldCheck className="w-6 h-6" /> : <ShieldAlert className="w-6 h-6" />}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-noc-text">Evidence Release Gate Audit</h3>
              <span
                className={`text-xs font-mono font-bold px-2.5 py-0.5 rounded-full uppercase tracking-wide border ${
                  isPassed && !isLimited
                    ? 'bg-noc-emerald/20 text-noc-emerald border-noc-emerald/40'
                    : isPassed
                    ? 'bg-noc-amber/20 text-noc-amber border-noc-amber/40'
                    : 'bg-red-500/20 text-red-400 border-red-500/40'
                }`}
              >
                {gate.outcome}
              </span>
            </div>
            <p className="text-xs text-noc-muted mt-0.5">
              Independent deterministic gatekeeper preventing ungrounded claims or hallucinated diagnoses.
            </p>
          </div>
        </div>

        {gate.evaluated_at && (
          <div className="flex items-center gap-1.5 text-[11px] text-noc-muted font-mono bg-noc-bg px-2.5 py-1 rounded border border-noc-border self-start sm:self-auto shrink-0">
            <Clock className="w-3.5 h-3.5 text-noc-cyan" />
            <span>Audit: {new Date(gate.evaluated_at).toLocaleTimeString([], { hour12: false })}</span>
          </div>
        )}
      </div>

      {/* Purpose Description */}
      <div className="bg-noc-bg/80 border border-noc-border/80 rounded-lg p-3 text-xs text-noc-muted space-y-1.5">
        <div className="flex items-center gap-1.5 font-semibold text-noc-text">
          <Info className="w-3.5 h-3.5 text-noc-cyan" />
          Deterministic Release Gate Guarantee
        </div>
        <p className="text-[11px] leading-relaxed">
          The supervisory RCA agent cannot publish a diagnostic report directly. Every proposal is subjected to deterministic code-level release checks. If supporting observations cannot be verified against the SQLite Knowledge Plane, or if contradictions are concealed, the gate strictly denies release.
        </p>
      </div>

      {/* Deterministic Checks Breakdown */}
      <div className="space-y-2.5">
        <div className="text-xs font-semibold text-noc-text uppercase tracking-wider flex items-center justify-between">
          <span>Release Gate Check Breakdown ({gate.checks.length})</span>
          <span className="text-[11px] font-normal text-noc-muted">
            {gate.checks.filter((c) => c.passed).length} of {gate.checks.length} passed
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
          {gate.checks.map((check: GateCheckResult, i: number) => (
            <div
              key={check.check_name || i}
              className={`p-3 rounded-lg border bg-noc-bg/90 flex items-start gap-2.5 transition-colors ${
                check.passed ? 'border-noc-border/80' : 'border-red-500/40 bg-red-950/20'
              }`}
            >
              {check.passed ? (
                <CheckCircle2 className="w-4 h-4 text-noc-emerald shrink-0 mt-0.5" />
              ) : (
                <XCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
              )}
              <div className="space-y-1 min-w-0 flex-1">
                <div className="flex items-center justify-between gap-1">
                  <span className="text-xs font-semibold text-noc-text font-mono truncate">
                    {check.check_name.replace(/_/g, ' ')}
                  </span>
                  <span
                    className={`text-[9px] font-mono uppercase px-1.5 py-0.2 rounded border ${
                      check.passed
                        ? 'text-noc-emerald bg-noc-emerald/10 border-noc-emerald/30'
                        : 'text-red-400 bg-red-500/10 border-red-500/30'
                    }`}
                  >
                    {check.passed ? 'PASSED' : 'FAILED'}
                  </span>
                </div>
                <p className="text-[11px] text-noc-muted leading-relaxed line-clamp-2">
                  {check.message}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Warnings & Limitations Section */}
      {(gate.warnings.length > 0 || allLimitations.length > 0) && (
        <div className="pt-3 border-t border-noc-border/60 grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
          {gate.warnings.length > 0 && (
            <div className="bg-noc-amber/10 border border-noc-amber/30 rounded-lg p-3 space-y-1">
              <div className="flex items-center gap-1.5 font-semibold text-noc-amber text-[11px] uppercase tracking-wider">
                <AlertTriangle className="w-3.5 h-3.5" />
                Gate Warnings ({gate.warnings.length})
              </div>
              <ul className="list-disc list-inside space-y-1 text-[11px] text-noc-amber/90">
                {gate.warnings.map((w, idx) => (
                  <li key={idx} className="leading-relaxed">
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {allLimitations.length > 0 && (
            <div className="bg-noc-bg/80 border border-noc-border rounded-lg p-3 space-y-1">
              <div className="flex items-center gap-1.5 font-semibold text-noc-muted text-[11px] uppercase tracking-wider">
                <Info className="w-3.5 h-3.5 text-noc-cyan" />
                System Limitations & Boundary Conditions
              </div>
              <ul className="list-disc list-inside space-y-1 text-[11px] text-noc-muted leading-relaxed">
                {allLimitations.map((lim, idx) => (
                  <li key={idx}>{lim}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
