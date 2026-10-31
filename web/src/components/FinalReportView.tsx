import React, { useState } from 'react';
import { FinalReport } from '../types';
import {
  FileCheck2,
  Copy,
  Check,
  AlertTriangle,
  Layers,
  ArrowRight,
  Wrench,
  Link,
  Info,
  Network,
} from 'lucide-react';

interface FinalReportViewProps {
  report: FinalReport;
}

export const FinalReportView: React.FC<FinalReportViewProps> = ({ report }) => {
  const [viewMode, setViewMode] = useState<'brief' | 'json'>('brief');
  const [copied, setCopied] = useState(false);

  const handleCopyJson = () => {
    navigator.clipboard.writeText(JSON.stringify(report, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const isDiagnosed = report.status.toLowerCase() === 'diagnosed';

  return (
    <div className="bg-noc-card border border-noc-border rounded-xl p-5 shadow-lg space-y-5">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-noc-border/60">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-lg bg-noc-cyan/10 border border-noc-cyan/30 text-noc-cyan">
            <FileCheck2 className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-noc-text">Certified Final Diagnostic Report</h3>
              <span
                className={`text-xs font-mono font-bold px-2 py-0.5 rounded uppercase border ${
                  isDiagnosed
                    ? 'bg-noc-emerald/15 text-noc-emerald border-noc-emerald/30'
                    : 'bg-noc-amber/15 text-noc-amber border-noc-amber/30'
                }`}
              >
                {report.status}
              </span>
            </div>
            <p className="text-xs text-noc-muted">
              Incident ID: <span className="font-mono text-noc-cyan">{report.incident_id}</span>
            </p>
          </div>
        </div>

        {/* View Toggle and Copy */}
        <div className="flex items-center gap-2">
          <div className="flex items-center bg-noc-bg p-1 rounded-lg border border-noc-border text-xs">
            <button
              onClick={() => setViewMode('brief')}
              className={`px-3 py-1.5 rounded-md font-medium transition-colors ${
                viewMode === 'brief'
                  ? 'bg-noc-cyan/20 text-noc-cyan border border-noc-cyan/40 shadow-sm'
                  : 'text-noc-muted hover:text-noc-text'
              }`}
            >
              Executive Brief
            </button>
            <button
              onClick={() => setViewMode('json')}
              className={`px-3 py-1.5 rounded-md font-medium transition-colors ${
                viewMode === 'json'
                  ? 'bg-noc-purple/20 text-noc-purple border border-noc-purple/40 shadow-sm'
                  : 'text-noc-muted hover:text-noc-text'
              }`}
            >
              Raw JSON
            </button>
          </div>

          {viewMode === 'json' && (
            <button
              onClick={handleCopyJson}
              className="flex items-center gap-1.5 bg-noc-bg hover:bg-noc-card border border-noc-border text-noc-muted hover:text-noc-text text-xs px-2.5 py-1.5 rounded-lg transition-colors"
              title="Copy JSON to clipboard"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-noc-emerald" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
          )}
        </div>
      </div>

      {viewMode === 'brief' ? (
        <div className="space-y-5">
          {/* Root Cause Banner */}
          <div className="bg-noc-bg/90 border border-noc-cyan/50 rounded-xl p-4 space-y-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] text-noc-cyan font-bold uppercase tracking-wider flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 text-noc-cyan" />
                Diagnosed Root Cause
              </span>
              <div className="flex items-center gap-2">
                {report.confidence_category && (
                  <span className="text-[10px] text-noc-muted uppercase bg-noc-card px-2 py-0.5 rounded border border-noc-border">
                    {report.confidence_category}
                  </span>
                )}
                <span className="text-sm font-bold font-mono text-noc-cyan bg-noc-cyan/15 px-2.5 py-0.5 rounded border border-noc-cyan/40">
                  {(report.confidence * 100).toFixed(0)}% Confidence
                </span>
              </div>
            </div>
            <p className="text-sm text-noc-text font-mono font-semibold leading-relaxed">
              {report.suspected_root_cause}
            </p>
          </div>

          {/* Affected Entities & Blast Radius */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="bg-noc-bg/70 border border-noc-border rounded-xl p-3.5 space-y-2">
              <div className="text-[11px] text-noc-muted uppercase font-semibold flex items-center gap-1.5">
                <Network className="w-3.5 h-3.5 text-noc-amber" />
                Directly Affected
              </div>
              <div className="flex flex-wrap gap-1.5">
                {report.directly_affected_entities.length > 0 ? (
                  report.directly_affected_entities.map((ent) => (
                    <span
                      key={ent}
                      className="text-xs font-mono font-medium bg-noc-card text-noc-amber px-2 py-1 rounded border border-noc-border"
                    >
                      {ent}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-noc-muted">None directly localized</span>
                )}
              </div>
            </div>

            <div className="bg-noc-bg/70 border border-noc-border rounded-xl p-3.5 space-y-2">
              <div className="text-[11px] text-noc-muted uppercase font-semibold flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-noc-cyan" />
                Observed Symptoms
              </div>
              <div className="flex flex-wrap gap-1.5">
                {report.observed_symptom_entities.length > 0 ? (
                  report.observed_symptom_entities.map((ent) => (
                    <span
                      key={ent}
                      className="text-xs font-mono font-medium bg-noc-card text-noc-cyan px-2 py-1 rounded border border-noc-border"
                    >
                      {ent}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-noc-muted">No explicit symptoms</span>
                )}
              </div>
            </div>

            <div className="bg-noc-bg/70 border border-noc-border rounded-xl p-3.5 space-y-2">
              <div className="text-[11px] text-noc-muted uppercase font-semibold flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-noc-purple" />
                Inferred Blast Radius
              </div>
              <div className="flex flex-wrap gap-1.5">
                {report.inferred_affected_entities && report.inferred_affected_entities.length > 0 ? (
                  report.inferred_affected_entities.map((ent) => (
                    <span
                      key={ent}
                      className="text-xs font-mono font-medium bg-noc-card text-noc-purple px-2 py-1 rounded border border-noc-border"
                    >
                      {ent}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-noc-muted">Isolated to direct entity</span>
                )}
              </div>
            </div>
          </div>

          {/* Predicted Impacts Table if available */}
          {report.predicted_impacts && report.predicted_impacts.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-semibold text-noc-text uppercase tracking-wider flex items-center gap-1.5">
                <Network className="w-3.5 h-3.5 text-noc-purple" />
                Predicted Topology Impacts & Blast Propagation ({report.predicted_impacts.length})
              </div>
              <div className="border border-noc-border rounded-xl bg-noc-bg/95 overflow-hidden">
                <div className="overflow-x-auto max-h-48">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-noc-card/80 text-[11px] text-noc-muted uppercase font-semibold sticky top-0 border-b border-noc-border">
                      <tr>
                        <th className="py-2 px-3">Impacted Entity</th>
                        <th className="py-2 px-3">Propagation Path</th>
                        <th className="py-2 px-3">Hops</th>
                        <th className="py-2 px-3">Relationship</th>
                        <th className="py-2 px-3">Certainty</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-noc-border/40 font-mono">
                      {report.predicted_impacts.map((imp, idx) => (
                        <tr key={idx} className="hover:bg-noc-card/50 transition-colors">
                          <td className="py-2 px-3 text-noc-cyan font-bold whitespace-nowrap">
                            {imp.entity_id}
                          </td>
                          <td className="py-2 px-3 text-noc-text whitespace-nowrap">
                            <div className="flex items-center gap-1">
                              {imp.path.map((node, nIdx) => (
                                <React.Fragment key={node}>
                                  <span className="text-[11px] bg-noc-card px-1.5 py-0.2 rounded border border-noc-border">
                                    {node}
                                  </span>
                                  {nIdx < imp.path.length - 1 && (
                                    <ArrowRight className="w-2.5 h-2.5 text-noc-muted" />
                                  )}
                                </React.Fragment>
                              ))}
                            </div>
                          </td>
                          <td className="py-2 px-3 text-noc-muted">{imp.hops}</td>
                          <td className="py-2 px-3 text-noc-muted font-sans text-[11px]">
                            {imp.relation}
                          </td>
                          <td className="py-2 px-3">
                            <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-noc-card border border-noc-border text-noc-text">
                              {imp.certainty}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* Supporting Evidence Breakdown */}
          <div className="space-y-2">
            <div className="text-xs font-semibold text-noc-text uppercase tracking-wider flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <Link className="w-3.5 h-3.5 text-noc-cyan" />
                Verified Supporting Evidence Items ({report.supporting_evidence.length})
              </span>
              <span className="text-[11px] font-normal text-noc-emerald">
                100% Verified by Evidence Gate
              </span>
            </div>

            <div className="border border-noc-border rounded-xl bg-noc-bg/95 overflow-hidden">
              <div className="overflow-x-auto max-h-56">
                <table className="w-full text-left text-xs">
                  <thead className="bg-noc-card/80 text-[11px] text-noc-muted uppercase font-semibold sticky top-0 border-b border-noc-border">
                    <tr>
                      <th className="py-2 px-3">Metric / Item</th>
                      <th className="py-2 px-3">Value</th>
                      <th className="py-2 px-3">Entity</th>
                      <th className="py-2 px-3">Interpretation</th>
                      <th className="py-2 px-3">Source</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-noc-border/40 font-mono">
                    {report.supporting_evidence.map((item, idx) => (
                      <tr key={idx} className="hover:bg-noc-card/50 transition-colors">
                        <td className="py-2 px-3 text-noc-cyan font-medium whitespace-nowrap">
                          {item.metric}
                        </td>
                        <td className="py-2 px-3 text-noc-amber font-bold whitespace-nowrap">
                          {typeof item.value === 'number'
                            ? `${item.value.toFixed(2)} ${item.unit || ''}`
                            : String(item.value)}
                        </td>
                        <td className="py-2 px-3 text-noc-text whitespace-nowrap">
                          {item.entity_id || '—'}
                        </td>
                        <td className="py-2 px-3 text-noc-text font-sans text-xs">
                          {item.interpretation}
                        </td>
                        <td className="py-2 px-3 text-noc-muted text-[11px] whitespace-nowrap font-sans">
                          {item.source || 'telemetry'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Recommended Actions */}
          {report.recommended_actions.length > 0 && (
            <div className="space-y-2.5">
              <div className="text-xs font-semibold text-noc-text uppercase tracking-wider flex items-center gap-1.5">
                <Wrench className="w-3.5 h-3.5 text-noc-emerald" />
                Recommended Remediation Actions ({report.recommended_actions.length})
              </div>
              <div className="space-y-2">
                {report.recommended_actions.map((act, idx) => (
                  <div
                    key={idx}
                    className="bg-noc-bg/80 border border-noc-border rounded-lg p-3 text-xs flex items-start gap-3"
                  >
                    <span className="font-bold text-noc-emerald bg-noc-emerald/10 border border-noc-emerald/30 w-5 h-5 rounded-full flex items-center justify-center text-[10px] shrink-0 mt-0.5">
                      {idx + 1}
                    </span>
                    <p className="text-noc-text leading-relaxed">{act}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* System Limitations Footer */}
          {report.limitations && report.limitations.length > 0 && (
            <div className="p-3 bg-noc-bg/60 border border-noc-border rounded-lg text-xs text-noc-muted space-y-1">
              <div className="font-semibold text-noc-muted text-[11px] uppercase flex items-center gap-1.5">
                <Info className="w-3.5 h-3.5 text-noc-cyan" />
                Caveats & Boundaries
              </div>
              <ul className="list-disc list-inside space-y-0.5 text-[11px]">
                {report.limitations.map((lim, i) => (
                  <li key={i}>{lim}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        /* Raw JSON Viewer */
        <div className="bg-noc-bg rounded-xl border border-noc-border p-4 overflow-x-auto max-h-[500px]">
          <pre className="text-xs font-mono text-noc-cyan leading-relaxed">
            {JSON.stringify(report, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
};
