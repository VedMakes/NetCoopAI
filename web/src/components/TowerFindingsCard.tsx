import React, { useState } from 'react';
import { TowerReportSummary, TowerFinding, TowerHypothesis } from '../types';
import {
  Activity,
  Server,
  Share2,
  Layers,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  CheckCircle2,
  Tag,
  ShieldAlert,
} from 'lucide-react';

interface TowerFindingsCardProps {
  towers: TowerReportSummary[];
  suspectedRootCause?: string;
}

const TOWER_METADATA: Record<
  string,
  { name: string; icon: React.FC<{ className?: string }>; color: string; description: string }
> = {
  performance: {
    name: 'Performance Tower',
    icon: Activity,
    color: 'text-noc-cyan border-noc-cyan/40 bg-noc-cyan/10',
    description: 'Analyzes latency, packet loss, bandwidth utilization, queue drops, and Wi-Fi RF signal telemetry.',
  },
  infrastructure: {
    name: 'Infrastructure Tower',
    icon: Server,
    color: 'text-noc-amber border-noc-amber/40 bg-noc-amber/10',
    description: 'Monitors CPU/memory exhaustion, interface CRC errors, hardware link flaps, and syslog error bursts.',
  },
  connectivity: {
    name: 'Connectivity Tower',
    icon: Share2,
    color: 'text-noc-purple border-noc-purple/40 bg-noc-purple/10',
    description: 'Constructs topology reachability, traces upstream physical paths, and computes blast radius.',
  },
  services: {
    name: 'Services Tower',
    icon: Layers,
    color: 'text-noc-emerald border-noc-emerald/40 bg-noc-emerald/10',
    description: 'Audits DNS resolver latency, DHCP IP pool exhaustion, NTP synchronization, and config drift.',
  },
};

export const TowerFindingsCard: React.FC<TowerFindingsCardProps> = ({
  towers,
  suspectedRootCause = '',
}) => {
  // Active expanded tower tab or card
  const [expandedTower, setExpandedTower] = useState<string | null>(null);

  // Map tower summaries by tower_id
  const towerMap = React.useMemo(() => {
    const map: Record<string, TowerReportSummary> = {};
    towers.forEach((t) => {
      map[t.tower_id.toLowerCase()] = t;
    });
    return map;
  }, [towers]);

  const allTowerIds = ['performance', 'infrastructure', 'connectivity', 'services'];

  return (
    <div className="bg-noc-card border border-noc-border rounded-xl p-5 shadow-lg space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-noc-border/60">
        <div>
          <h3 className="text-base font-semibold text-noc-text flex items-center gap-2">
            <Layers className="w-5 h-5 text-noc-cyan" />
            Specialist Diagnostic Towers
          </h3>
          <p className="text-xs text-noc-muted">
            Four independent domain specialist agents analyze compartmentalized telemetry streams before supervisor synthesis.
          </p>
        </div>
        <div className="text-xs text-noc-muted font-mono bg-noc-bg px-2.5 py-1 rounded border border-noc-border shrink-0">
          4 Specialist Agents Active
        </div>
      </div>

      {/* 4 Towers Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {allTowerIds.map((towerKey) => {
          const meta = TOWER_METADATA[towerKey] || {
            name: `${towerKey.toUpperCase()} Tower`,
            icon: Activity,
            color: 'text-noc-muted border-noc-border bg-noc-bg',
            description: 'Domain telemetry analysis agent.',
          };
          const report = towerMap[towerKey];
          const hasFindings = report && report.findings_count > 0;
          const hasHypotheses = report && report.hypotheses_count > 0;
          const isExpanded = expandedTower === towerKey;
          const Icon = meta.icon;

          // Check if this tower's hypothesis matches the suspected root cause
          const isPrimaryWinner =
            report?.hypotheses.some((h) =>
              suspectedRootCause.toUpperCase().includes(h.fault_code.toUpperCase())
            ) ?? false;

          return (
            <div
              key={towerKey}
              className={`rounded-xl border transition-all duration-200 overflow-hidden ${
                isPrimaryWinner
                  ? 'border-noc-cyan/60 bg-noc-bg/95 shadow-md shadow-noc-cyan/5'
                  : hasFindings
                  ? 'border-noc-border bg-noc-bg/80'
                  : 'border-noc-border/40 bg-noc-bg/40 opacity-80'
              }`}
            >
              {/* Tower Header */}
              <div className="p-4 space-y-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <div className={`p-2 rounded-lg border ${meta.color}`}>
                      <Icon className="w-4 h-4" />
                    </div>
                    <div>
                      <h4 className="text-sm font-semibold text-noc-text flex items-center gap-2">
                        {meta.name}
                        {isPrimaryWinner && (
                          <span className="text-[10px] bg-noc-cyan/20 text-noc-cyan border border-noc-cyan/40 px-2 py-0.5 rounded-full uppercase font-bold tracking-wide">
                            Supervisor Selected
                          </span>
                        )}
                      </h4>
                      <p className="text-[11px] text-noc-muted leading-relaxed line-clamp-1">
                        {meta.description}
                      </p>
                    </div>
                  </div>

                  <button
                    onClick={() => setExpandedTower(isExpanded ? null : towerKey)}
                    className="text-noc-muted hover:text-noc-text p-1 rounded hover:bg-noc-card transition-colors shrink-0"
                    title={isExpanded ? 'Collapse' : 'Expand findings'}
                  >
                    {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </button>
                </div>

                {/* Counts Bar */}
                <div className="flex items-center gap-2 text-xs">
                  <span
                    className={`px-2 py-0.5 rounded text-[11px] font-medium border ${
                      hasFindings
                        ? 'bg-noc-amber/15 text-noc-amber border-noc-amber/30'
                        : 'bg-noc-card text-noc-muted border-noc-border'
                    }`}
                  >
                    {report?.findings_count ?? 0} Findings
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded text-[11px] font-medium border ${
                      hasHypotheses
                        ? 'bg-noc-purple/15 text-noc-purple border-noc-purple/30'
                        : 'bg-noc-card text-noc-muted border-noc-border'
                    }`}
                  >
                    {report?.hypotheses_count ?? 0} Hypotheses
                  </span>
                  {!hasFindings && (
                    <span className="flex items-center gap-1 text-[11px] text-noc-emerald ml-auto">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Nominal
                    </span>
                  )}
                </div>
              </div>

              {/* Expandable Findings & Hypotheses */}
              {isExpanded && report && (
                <div className="border-t border-noc-border/60 bg-noc-card/40 p-4 space-y-4 text-xs">
                  {/* Hypotheses Proposed */}
                  {report.hypotheses.length > 0 && (
                    <div className="space-y-2">
                      <div className="text-[11px] text-noc-muted font-semibold uppercase tracking-wider flex items-center gap-1.5">
                        <ShieldAlert className="w-3.5 h-3.5 text-noc-purple" />
                        Proposed Hypotheses ({report.hypotheses.length})
                      </div>
                      <div className="space-y-2.5">
                        {report.hypotheses.map((hyp: TowerHypothesis, idx: number) => (
                          <div
                            key={hyp.hypothesis_id || idx}
                            className="bg-noc-bg border border-noc-border/80 rounded-lg p-3 space-y-2"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-mono font-bold text-noc-cyan">
                                {hyp.fault_code}
                              </span>
                              <div className="flex items-center gap-2">
                                <span className="text-[10px] text-noc-muted uppercase">
                                  {hyp.confidence_category}
                                </span>
                                <span className="text-[11px] font-bold text-noc-text bg-noc-card px-2 py-0.5 rounded border border-noc-border font-mono">
                                  {(hyp.confidence * 100).toFixed(0)}%
                                </span>
                              </div>
                            </div>
                            <p className="text-noc-muted text-xs leading-relaxed">
                              {hyp.rationale}
                            </p>
                            {hyp.suspected_entities.length > 0 && (
                              <div className="flex flex-wrap items-center gap-1 pt-1">
                                <span className="text-[10px] text-noc-muted">Suspected:</span>
                                {hyp.suspected_entities.map((ent) => (
                                  <span
                                    key={ent}
                                    className="bg-noc-card text-noc-text text-[10px] font-mono px-1.5 py-0.5 rounded border border-noc-border"
                                  >
                                    {ent}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Findings List */}
                  {report.findings.length > 0 && (
                    <div className="space-y-2">
                      <div className="text-[11px] text-noc-muted font-semibold uppercase tracking-wider flex items-center gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5 text-noc-amber" />
                        Tower Findings ({report.findings.length})
                      </div>
                      <div className="space-y-2">
                        {report.findings.map((f: TowerFinding, idx: number) => (
                          <div
                            key={f.finding_id || idx}
                            className="bg-noc-bg/90 border border-noc-border/80 rounded-lg p-2.5 space-y-1.5"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-semibold text-noc-text text-xs">
                                {f.finding_type}
                              </span>
                              <span
                                className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded border ${
                                  f.severity.toLowerCase() === 'critical'
                                    ? 'bg-red-500/15 text-red-400 border-red-500/30'
                                    : f.severity.toLowerCase() === 'high'
                                    ? 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                                    : 'bg-blue-500/15 text-blue-400 border-blue-500/30'
                                }`}
                              >
                                {f.severity}
                              </span>
                            </div>
                            <p className="text-noc-muted text-[11px] leading-relaxed">
                              {f.description}
                            </p>
                            <div className="flex flex-wrap items-center gap-2 pt-1">
                              {f.entity_refs.map((ent) => (
                                <span
                                  key={ent}
                                  className="inline-flex items-center gap-1 text-[10px] text-noc-cyan bg-noc-card px-1.5 py-0.5 rounded border border-noc-border font-mono"
                                >
                                  <Tag className="w-2.5 h-2.5" />
                                  {ent}
                                </span>
                              ))}
                              {f.evidence_refs.map((ref) => (
                                <span
                                  key={ref}
                                  className="text-[10px] text-noc-muted font-mono bg-noc-card px-1 py-0.5 rounded border border-noc-border"
                                >
                                  {ref}
                                </span>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {!hasFindings && !hasHypotheses && (
                    <div className="py-4 text-center text-noc-muted text-xs">
                      No anomalies detected within this specialist domain.
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
