import React from 'react';
import { FinalReport, RunStatusResponse } from '../types';
import { FileText } from 'lucide-react';

interface IncidentIntelligenceProps {
  activeRun: RunStatusResponse | null;
  report: FinalReport | null;
}

export const IncidentIntelligence: React.FC<IncidentIntelligenceProps> = ({ activeRun, report }) => {
  if (!activeRun || !report) {
    return (
      <div className="p-12 max-w-4xl mx-auto text-center flex flex-col items-center justify-center space-y-4">
        <div className="w-16 h-16 rounded-2xl bg-noc-panel border border-noc-border flex items-center justify-center text-noc-muted">
          <FileText className="w-8 h-8 opacity-40" />
        </div>
        <h2 className="text-base font-bold text-noc-text">No Incident Report Loaded</h2>
        <p className="text-xs text-noc-muted max-w-md leading-relaxed font-mono">
          Execute a diagnostic run from the Network Simulation page to inspect specialist tower findings, evidence gate verification checks, and the certified FinalReport.
        </p>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Executive Summary Card */}
      <div className="bg-noc-panel border border-noc-border rounded-xl p-6 shadow-xl">
        <div className="flex items-center justify-between pb-4 border-b border-noc-border mb-4">
          <div className="flex items-center space-x-3">
            <span className="w-3 h-3 rounded-full bg-emerald-400" />
            <h2 className="text-base font-bold text-noc-text">
              Incident RCA Brief: {report.incident_id}
            </h2>
          </div>
          <span className="text-xs font-mono px-3 py-1 rounded bg-noc-subpanel border border-noc-border text-noc-cyan">
            Status: {report.status.toUpperCase()}
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs mb-6">
          <div className="bg-noc-subpanel p-3.5 rounded-lg border border-noc-border">
            <span className="text-noc-muted block mb-1">Suspected Root Cause</span>
            <span className="text-sm font-bold text-noc-text">{report.suspected_root_cause}</span>
          </div>

          <div className="bg-noc-subpanel p-3.5 rounded-lg border border-noc-border">
            <span className="text-noc-muted block mb-1">Confidence Score</span>
            <span className="text-sm font-bold text-noc-cyan">
              {(report.confidence * 100).toFixed(0)}% ({report.confidence_category || 'calibrated'})
            </span>
          </div>

          <div className="bg-noc-subpanel p-3.5 rounded-lg border border-noc-border">
            <span className="text-noc-muted block mb-1">Evidence Sources</span>
            <span className="text-sm font-bold text-noc-amethyst">
              {report.supporting_evidence.length} Verified Items
            </span>
          </div>
        </div>

        {/* Evidence Items List */}
        <div>
          <h3 className="text-xs font-bold text-noc-muted uppercase tracking-wider mb-3">
            Gate-Certified Supporting Evidence Citations
          </h3>
          <div className="space-y-2">
            {report.supporting_evidence.map((ev, i) => (
              <div
                key={i}
                className="bg-noc-subpanel/60 border border-noc-border/80 rounded-lg p-3 text-xs flex items-start justify-between"
              >
                <div>
                  <span className="font-mono font-bold text-noc-cyan mr-2">{ev.metric}:</span>
                  <span className="text-noc-text">{ev.interpretation}</span>
                </div>
                <span className="font-mono text-noc-muted bg-noc-bg px-2 py-0.5 rounded border border-noc-border ml-4 flex-shrink-0">
                  Value: {String(ev.value)}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Recommended Actions */}
        {report.recommended_actions?.length > 0 && (
          <div className="mt-6 pt-4 border-t border-noc-border">
            <h3 className="text-xs font-bold text-noc-muted uppercase tracking-wider mb-2">
              Recommended Next Steps
            </h3>
            <ul className="space-y-1.5 text-xs text-noc-text">
              {report.recommended_actions.map((act, i) => (
                <li key={i} className="flex items-center space-x-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-indigo-400" />
                  <span>{act}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
};
