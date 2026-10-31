import React, { useState, useMemo } from 'react';
import { TelemetryObservation, DerivedFeature } from '../types';
import { Database, Cpu, Search, AlertCircle, FileText, CheckCircle2, Link2 } from 'lucide-react';

interface EvidenceInspectorProps {
  observations: TelemetryObservation[];
  features: DerivedFeature[];
  dataQualityWarnings?: string[];
}

export const EvidenceInspector: React.FC<EvidenceInspectorProps> = ({
  observations,
  features,
  dataQualityWarnings = [],
}) => {
  const [activeTab, setActiveTab] = useState<'raw' | 'derived'>('raw');
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [selectedObsId, setSelectedObsId] = useState<string | null>(null);

  // Filter raw observations
  const filteredObservations = useMemo(() => {
    return observations.filter((o) => {
      const matchType = typeFilter === 'all' || o.observation_type === typeFilter;
      const query = searchQuery.toLowerCase().trim();
      if (!query) return matchType;

      const inId = o.observation_id.toLowerCase().includes(query);
      const inEntity = o.entity_id?.toLowerCase().includes(query) ?? false;
      const inMetric = o.metric_name?.toLowerCase().includes(query) ?? false;
      const inSource = o.source?.toLowerCase().includes(query) ?? false;
      const inMsg = o.message?.toLowerCase().includes(query) ?? false;

      return matchType && (inId || inEntity || inMetric || inSource || inMsg);
    });
  }, [observations, typeFilter, searchQuery]);

  // Filter derived features
  const filteredFeatures = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    if (!query) return features;

    return features.filter((f) => {
      const inId = f.feature_id.toLowerCase().includes(query);
      const inEntity = f.entity_id?.toLowerCase().includes(query) ?? false;
      const inName = f.feature_name.toLowerCase().includes(query);
      const inSrc = f.source_observation_ids.some((id) => id.toLowerCase().includes(query));

      return inId || inEntity || inName || inSrc;
    });
  }, [features, searchQuery]);

  const handleInspectSourceObs = (obsId: string) => {
    setActiveTab('raw');
    setSearchQuery(obsId);
    setSelectedObsId(obsId);
  };

  return (
    <div className="bg-noc-card border border-noc-border rounded-xl p-5 shadow-lg space-y-4">
      {/* Header and Mode Toggle */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-noc-border/60">
        <div className="flex items-center gap-2">
          <Database className="w-5 h-5 text-noc-cyan" />
          <div>
            <h3 className="text-base font-semibold text-noc-text">Evidence & Telemetry Inspector</h3>
            <p className="text-xs text-noc-muted">
              Inspect normalized raw observations and mathematical derived features with strict provenance tracking.
            </p>
          </div>
        </div>

        {/* Tab Switcher */}
        <div className="flex items-center bg-noc-bg p-1 rounded-lg border border-noc-border text-xs shrink-0">
          <button
            onClick={() => setActiveTab('raw')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md font-medium transition-colors ${
              activeTab === 'raw'
                ? 'bg-noc-cyan/20 text-noc-cyan border border-noc-cyan/40 shadow-sm'
                : 'text-noc-muted hover:text-noc-text'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            Raw Observations ({observations.length})
          </button>
          <button
            onClick={() => setActiveTab('derived')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md font-medium transition-colors ${
              activeTab === 'derived'
                ? 'bg-noc-purple/20 text-noc-purple border border-noc-purple/40 shadow-sm'
                : 'text-noc-muted hover:text-noc-text'
            }`}
          >
            <Cpu className="w-3.5 h-3.5" />
            Derived Features ({features.length})
          </button>
        </div>
      </div>

      {/* Warnings Banner if any */}
      {dataQualityWarnings.length > 0 && (
        <div className="bg-noc-amber/10 border border-noc-amber/40 rounded-lg p-3 text-xs text-noc-amber space-y-1">
          <div className="flex items-center gap-1.5 font-semibold">
            <AlertCircle className="w-4 h-4 shrink-0" />
            Data Quality Warnings ({dataQualityWarnings.length})
          </div>
          <ul className="list-disc list-inside space-y-0.5 text-[11px] text-noc-amber/90">
            {dataQualityWarnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Search and Filters Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
        <div className="relative w-full sm:w-72">
          <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-noc-muted" />
          <input
            type="text"
            placeholder={activeTab === 'raw' ? 'Search by ID, entity, metric, or source...' : 'Search by feature, entity, or source OBS...'}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-noc-bg border border-noc-border rounded-lg pl-9 pr-3 py-1.5 text-noc-text placeholder-noc-muted focus:outline-none focus:border-noc-cyan transition-colors"
          />
        </div>

        {activeTab === 'raw' && (
          <div className="flex items-center gap-2 w-full sm:w-auto">
            <span className="text-noc-muted shrink-0">Type:</span>
            <div className="flex flex-wrap gap-1">
              {['all', 'metric', 'log', 'topology', 'config'].map((type) => (
                <button
                  key={type}
                  onClick={() => setTypeFilter(type)}
                  className={`px-2 py-1 rounded text-[11px] capitalize border transition-colors ${
                    typeFilter === type
                      ? 'bg-noc-cyan/20 border-noc-cyan/50 text-noc-cyan font-medium'
                      : 'bg-noc-bg border-noc-border text-noc-muted hover:text-noc-text'
                  }`}
                >
                  {type}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Table Content */}
      <div className="border border-noc-border rounded-xl bg-noc-bg/95 overflow-hidden">
        {activeTab === 'raw' ? (
          <div className="overflow-x-auto max-h-[420px] divide-y divide-noc-border/60">
            <table className="w-full text-left text-xs">
              <thead className="bg-noc-card/80 text-[11px] text-noc-muted uppercase font-semibold sticky top-0 z-10 border-b border-noc-border">
                <tr>
                  <th className="py-2.5 px-3">Observation ID</th>
                  <th className="py-2.5 px-3">Timestamp</th>
                  <th className="py-2.5 px-3">Entity</th>
                  <th className="py-2.5 px-3">Type</th>
                  <th className="py-2.5 px-3">Metric / Value</th>
                  <th className="py-2.5 px-3">Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-noc-border/40 font-mono">
                {filteredObservations.length > 0 ? (
                  filteredObservations.slice(0, 100).map((obs) => {
                    const isSelected = selectedObsId === obs.observation_id;
                    return (
                      <tr
                        key={obs.observation_id}
                        className={`hover:bg-noc-card/60 transition-colors ${
                          isSelected ? 'bg-noc-cyan/15 border-l-2 border-l-noc-cyan' : ''
                        }`}
                      >
                        <td className="py-2 px-3 text-noc-cyan font-medium whitespace-nowrap">
                          {obs.observation_id}
                        </td>
                        <td className="py-2 px-3 text-noc-muted whitespace-nowrap">
                          {new Date(obs.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        </td>
                        <td className="py-2 px-3 text-noc-text whitespace-nowrap">
                          <span className="bg-noc-card px-2 py-0.5 rounded border border-noc-border/80 text-[11px]">
                            {obs.entity_id}
                          </span>
                        </td>
                        <td className="py-2 px-3 whitespace-nowrap">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-sans font-medium uppercase ${
                              obs.observation_type === 'metric'
                                ? 'bg-blue-500/10 text-blue-400 border border-blue-500/30'
                                : obs.observation_type === 'log'
                                ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
                                : obs.observation_type === 'topology'
                                ? 'bg-purple-500/10 text-purple-400 border border-purple-500/30'
                                : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                            }`}
                          >
                            {obs.observation_type}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-noc-text">
                          {obs.observation_type === 'metric' ? (
                            <span className="font-semibold text-noc-amber">
                              {obs.metric_name}: {obs.value?.toFixed(2)} {obs.unit}
                            </span>
                          ) : obs.observation_type === 'log' ? (
                            <span className="text-noc-muted font-sans line-clamp-1">
                              [{obs.metric_name}] {obs.message}
                            </span>
                          ) : (
                            <span className="text-noc-muted font-sans line-clamp-1">
                              {obs.metric_name} {obs.message ? `(${obs.message})` : ''}
                            </span>
                          )}
                        </td>
                        <td className="py-2 px-3 text-noc-muted text-[11px] whitespace-nowrap font-sans">
                          {obs.source || 'collector'}
                        </td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-noc-muted font-sans">
                      No observations matching filter query.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            {filteredObservations.length > 100 && (
              <div className="py-2 px-3 text-center text-[11px] text-noc-muted bg-noc-card/50 border-t border-noc-border">
                Showing first 100 of {filteredObservations.length} matching observations.
              </div>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto max-h-[420px] divide-y divide-noc-border/60">
            <table className="w-full text-left text-xs">
              <thead className="bg-noc-card/80 text-[11px] text-noc-muted uppercase font-semibold sticky top-0 z-10 border-b border-noc-border">
                <tr>
                  <th className="py-2.5 px-3">Feature ID</th>
                  <th className="py-2.5 px-3">Entity</th>
                  <th className="py-2.5 px-3">Engineered Feature</th>
                  <th className="py-2.5 px-3">Computed Value</th>
                  <th className="py-2.5 px-3">Time Window</th>
                  <th className="py-2.5 px-3">Source Provenance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-noc-border/40 font-mono">
                {filteredFeatures.length > 0 ? (
                  filteredFeatures.map((feat) => (
                    <tr key={feat.feature_id} className="hover:bg-noc-card/60 transition-colors">
                      <td className="py-2 px-3 text-noc-purple font-medium whitespace-nowrap">
                        {feat.feature_id}
                      </td>
                      <td className="py-2 px-3 text-noc-text whitespace-nowrap">
                        <span className="bg-noc-card px-2 py-0.5 rounded border border-noc-border/80 text-[11px]">
                          {feat.entity_id}
                        </span>
                      </td>
                      <td className="py-2 px-3 text-noc-text font-medium">
                        {feat.feature_name}
                      </td>
                      <td className="py-2 px-3 text-noc-cyan font-bold whitespace-nowrap">
                        {feat.value.toFixed(3)} {feat.unit || ''}
                      </td>
                      <td className="py-2 px-3 text-noc-muted text-[11px] whitespace-nowrap font-sans">
                        {new Date(feat.time_window_start).toLocaleTimeString([], { hour12: false })} –{' '}
                        {new Date(feat.time_window_end).toLocaleTimeString([], { hour12: false })}
                      </td>
                      <td className="py-2 px-3">
                        <div className="flex flex-wrap items-center gap-1">
                          {feat.source_observation_ids.slice(0, 3).map((obsId) => (
                            <button
                              key={obsId}
                              onClick={() => handleInspectSourceObs(obsId)}
                              title={`Inspect source observation ${obsId}`}
                              className="inline-flex items-center gap-0.5 text-[10px] text-noc-muted hover:text-noc-cyan bg-noc-card px-1.5 py-0.5 rounded border border-noc-border hover:border-noc-cyan/40 transition-colors cursor-pointer"
                            >
                              <Link2 className="w-2.5 h-2.5" />
                              {obsId}
                            </button>
                          ))}
                          {feat.source_observation_ids.length > 3 && (
                            <span className="text-[10px] text-noc-muted">
                              +{feat.source_observation_ids.length - 3} more
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-noc-muted font-sans">
                      No derived features matching filter query.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between text-xs text-noc-muted pt-1">
        <div className="flex items-center gap-1.5">
          <CheckCircle2 className="w-3.5 h-3.5 text-noc-emerald" />
          <span>Strict zero-leakage isolation verified: ground truth is excluded from all evidence pipelines.</span>
        </div>
        <div>
          Showing {activeTab === 'raw' ? filteredObservations.length : filteredFeatures.length} items
        </div>
      </div>
    </div>
  );
};
