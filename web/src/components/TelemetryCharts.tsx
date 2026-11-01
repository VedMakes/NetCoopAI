import React, { useState, useMemo } from 'react';
import { TelemetryObservation, DerivedFeature } from '../types';
import { Activity, BarChart2, Filter, Info, TrendingUp } from 'lucide-react';

interface TelemetryChartsProps {
  observations: TelemetryObservation[];
  features?: DerivedFeature[];
}

export const TelemetryCharts: React.FC<TelemetryChartsProps> = ({ observations, features = [] }) => {
  // Extract all metric observations
  const metricObs = useMemo(() => {
    return observations.filter(
      (o) => (o.observation_type === 'metric' || o.metric_name) && typeof o.value === 'number'
    );
  }, [observations]);

  // Extract unique entities and metrics
  const entities = useMemo(() => {
    const set = new Set<string>();
    metricObs.forEach((o) => {
      if (o.entity_id) set.add(o.entity_id);
    });
    return Array.from(set).sort();
  }, [metricObs]);

  const metricNames = useMemo(() => {
    const set = new Set<string>();
    metricObs.forEach((o) => {
      if (o.metric_name) set.add(o.metric_name);
    });
    return Array.from(set).sort();
  }, [metricObs]);

  // Selected filters
  const [selectedEntity, setSelectedEntity] = useState<string>('all');
  const [selectedMetric, setSelectedMetric] = useState<string>('');
  const [hoveredPoint, setHoveredPoint] = useState<{
    timestamp: string;
    value: number;
    entity: string;
    unit?: string;
  } | null>(null);

  // Initialize selected metric once metricNames are ready
  React.useEffect(() => {
    if (!selectedMetric && metricNames.length > 0) {
      // Prioritize primary incident indicators if present
      const preferred = ['link_utilization_pct', 'queue_drops', 'packet_loss_pct', 'cpu_utilization_pct', 'rssi_dbm', 'latency_ms'];
      const match = preferred.find((p) => metricNames.includes(p));
      setSelectedMetric(match || metricNames[0]);
    }
  }, [metricNames, selectedMetric]);

  // Filtered series points
  const seriesData = useMemo(() => {
    if (!selectedMetric) return [];
    const filtered = metricObs.filter((o) => {
      const matchMetric = o.metric_name === selectedMetric;
      const matchEntity = selectedEntity === 'all' || o.entity_id === selectedEntity;
      return matchMetric && matchEntity;
    });

    // Sort by timestamp
    return filtered.sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    );
  }, [metricObs, selectedMetric, selectedEntity]);

  // Metrics summary statistics
  const stats = useMemo(() => {
    if (seriesData.length === 0) return null;
    const values = seriesData.map((d) => d.value ?? 0);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const avg = values.reduce((sum, v) => sum + v, 0) / values.length;
    const unit = seriesData[0].unit || '';
    return { min, max, avg, count: values.length, unit };
  }, [seriesData]);

  // SVG Chart Dimensions
  const width = 800;
  const height = 260;
  const padding = { top: 20, right: 30, bottom: 40, left: 60 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  // Coordinate scales
  const chartPoints = useMemo(() => {
    if (seriesData.length < 2 || !stats) return [];
    const minVal = Math.min(0, stats.min);
    const maxVal = stats.max === minVal ? stats.max + 1 : stats.max * 1.1;

    const timeStart = new Date(seriesData[0].timestamp).getTime();
    const timeEnd = new Date(seriesData[seriesData.length - 1].timestamp).getTime();
    const timeSpan = timeEnd === timeStart ? 1 : timeEnd - timeStart;

    return seriesData.map((d) => {
      const t = new Date(d.timestamp).getTime();
      const x = padding.left + ((t - timeStart) / timeSpan) * chartWidth;
      const val = d.value ?? 0;
      const y = padding.top + chartHeight - ((val - minVal) / (maxVal - minVal)) * chartHeight;
      return { x, y, val, timestamp: d.timestamp, entity: d.entity_id, unit: d.unit };
    });
  }, [seriesData, stats, chartWidth, chartHeight, padding.left, padding.top]);

  // Build SVG Path
  const linePath = useMemo(() => {
    if (chartPoints.length < 2) return '';
    return chartPoints.reduce((acc, pt, idx) => {
      return idx === 0 ? `M ${pt.x} ${pt.y}` : `${acc} L ${pt.x} ${pt.y}`;
    }, '');
  }, [chartPoints]);

  const areaPath = useMemo(() => {
    if (chartPoints.length < 2) return '';
    const first = chartPoints[0];
    const last = chartPoints[chartPoints.length - 1];
    const baseline = padding.top + chartHeight;
    return `${linePath} L ${last.x} ${baseline} L ${first.x} ${baseline} Z`;
  }, [chartPoints, linePath, chartHeight, padding.top]);

  // Threshold guideline (e.g. 90% for utilization, 100 for queue drops)
  const thresholdVal = useMemo(() => {
    if (selectedMetric.includes('utilization')) return 90;
    if (selectedMetric.includes('packet_loss')) return 2;
    if (selectedMetric.includes('cpu')) return 85;
    return null;
  }, [selectedMetric]);

  const thresholdY = useMemo(() => {
    if (!thresholdVal || !stats) return null;
    const minVal = Math.min(0, stats.min);
    const maxVal = stats.max === minVal ? stats.max + 1 : stats.max * 1.1;
    if (thresholdVal < minVal || thresholdVal > maxVal) return null;
    return padding.top + chartHeight - ((thresholdVal - minVal) / (maxVal - minVal)) * chartHeight;
  }, [thresholdVal, stats, chartHeight, padding.top]);

  return (
    <div className="bg-noc-card border border-noc-border rounded-xl p-5 shadow-lg space-y-4">
      {/* Header & Controls */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-3 border-b border-noc-border/60">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-noc-cyan" />
          <h3 className="text-base font-semibold text-noc-text">Telemetry Time-Series Visualizer</h3>
          <span className="text-xs text-noc-muted bg-noc-bg/80 px-2 py-0.5 rounded border border-noc-border">
            {seriesData.length} samples
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          {/* Entity Filter */}
          <div className="flex items-center gap-1.5 bg-noc-bg border border-noc-border rounded-lg px-2.5 py-1.5">
            <Filter className="w-3.5 h-3.5 text-noc-muted" />
            <span className="text-noc-muted">Entity:</span>
            <select
              value={selectedEntity}
              onChange={(e) => setSelectedEntity(e.target.value)}
              className="bg-transparent text-noc-text font-medium focus:outline-none cursor-pointer"
            >
              <option value="all" className="bg-noc-bg text-noc-text">
                All Entities ({entities.length})
              </option>
              {entities.map((e) => (
                <option key={e} value={e} className="bg-noc-bg text-noc-text">
                  {e}
                </option>
              ))}
            </select>
          </div>

          {/* Metric Selector */}
          <div className="flex items-center gap-1.5 bg-noc-bg border border-noc-border rounded-lg px-2.5 py-1.5">
            <BarChart2 className="w-3.5 h-3.5 text-noc-cyan" />
            <span className="text-noc-muted">Metric:</span>
            <select
              value={selectedMetric}
              onChange={(e) => setSelectedMetric(e.target.value)}
              className="bg-transparent text-noc-cyan font-semibold focus:outline-none cursor-pointer"
            >
              {metricNames.map((m) => (
                <option key={m} value={m} className="bg-noc-bg text-noc-text">
                  {m}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* KPI Cards Row */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-noc-bg/70 border border-noc-border/80 rounded-lg p-2.5">
            <div className="text-[11px] text-noc-muted uppercase tracking-wider">Peak Value</div>
            <div className="text-base font-bold text-noc-amber mt-0.5">
              {stats.max.toFixed(2)} <span className="text-xs font-normal text-noc-muted">{stats.unit}</span>
            </div>
          </div>
          <div className="bg-noc-bg/70 border border-noc-border/80 rounded-lg p-2.5">
            <div className="text-[11px] text-noc-muted uppercase tracking-wider">Average</div>
            <div className="text-base font-bold text-noc-text mt-0.5">
              {stats.avg.toFixed(2)} <span className="text-xs font-normal text-noc-muted">{stats.unit}</span>
            </div>
          </div>
          <div className="bg-noc-bg/70 border border-noc-border/80 rounded-lg p-2.5">
            <div className="text-[11px] text-noc-muted uppercase tracking-wider">Minimum</div>
            <div className="text-base font-bold text-noc-muted mt-0.5">
              {stats.min.toFixed(2)} <span className="text-xs font-normal text-noc-muted">{stats.unit}</span>
            </div>
          </div>
          <div className="bg-noc-bg/70 border border-noc-border/80 rounded-lg p-2.5">
            <div className="text-[11px] text-noc-muted uppercase tracking-wider">Derived Features</div>
            <div className="text-base font-bold text-noc-cyan mt-0.5">
              {features.length} <span className="text-xs font-normal text-noc-muted">features</span>
            </div>
          </div>
        </div>
      )}

      {/* Interactive SVG Chart */}
      <div className="relative bg-noc-bg/90 border border-noc-border rounded-xl p-3 overflow-hidden">
        {chartPoints.length >= 2 ? (
          <div className="w-full overflow-x-auto">
            <svg
              viewBox={`0 0 ${width} ${height}`}
              className="w-full h-auto max-h-[300px] select-none"
            >
              <defs>
                <linearGradient id="metricAreaGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.35" />
                  <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {/* Grid Lines */}
              {[0, 0.25, 0.5, 0.75, 1].map((pct, i) => {
                const y = padding.top + chartHeight * pct;
                return (
                  <line
                    key={i}
                    x1={padding.left}
                    y1={y}
                    x2={width - padding.right}
                    y2={y}
                    stroke="#1e293b"
                    strokeDasharray="4 4"
                    strokeWidth="1"
                  />
                );
              })}

              {/* Threshold guideline */}
              {thresholdY !== null && thresholdVal !== null && (
                <g>
                  <line
                    x1={padding.left}
                    y1={thresholdY}
                    x2={width - padding.right}
                    y2={thresholdY}
                    stroke="#ef4444"
                    strokeDasharray="5 5"
                    strokeWidth="1.5"
                  />
                  <text
                    x={width - padding.right - 5}
                    y={thresholdY - 5}
                    textAnchor="end"
                    fill="#ef4444"
                    fontSize="10"
                    fontFamily="monospace"
                  >
                    Threshold Alert: {thresholdVal}
                  </text>
                </g>
              )}

              {/* Area fill */}
              <path d={areaPath} fill="url(#metricAreaGrad)" />

              {/* Trend Line */}
              <path
                d={linePath}
                fill="none"
                stroke="#06b6d4"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />

              {/* Interactive Points */}
              {chartPoints.map((pt, i) => (
                <circle
                  key={i}
                  cx={pt.x}
                  cy={pt.y}
                  r={hoveredPoint?.timestamp === pt.timestamp ? 5 : 3}
                  className="fill-noc-cyan hover:fill-noc-amber transition-all cursor-pointer"
                  onMouseEnter={() =>
                    setHoveredPoint({
                      timestamp: pt.timestamp,
                      value: pt.val,
                      entity: pt.entity,
                      unit: pt.unit,
                    })
                  }
                  onMouseLeave={() => setHoveredPoint(null)}
                />
              ))}

              {/* Axis Labels */}
              {stats && (
                <g className="text-[10px] fill-noc-muted" fontFamily="monospace">
                  <text x={padding.left - 8} y={padding.top + 5} textAnchor="end">
                    {stats.max.toFixed(1)}
                  </text>
                  <text x={padding.left - 8} y={padding.top + chartHeight / 2} textAnchor="end">
                    {stats.avg.toFixed(1)}
                  </text>
                  <text x={padding.left - 8} y={padding.top + chartHeight} textAnchor="end">
                    {Math.min(0, stats.min).toFixed(1)}
                  </text>
                  <text
                    x={padding.left}
                    y={height - 10}
                    textAnchor="start"
                  >
                    {new Date(seriesData[0].timestamp).toLocaleTimeString([], { hour12: false })}
                  </text>
                  <text
                    x={width - padding.right}
                    y={height - 10}
                    textAnchor="end"
                  >
                    {new Date(seriesData[seriesData.length - 1].timestamp).toLocaleTimeString([], {
                      hour12: false,
                    })}
                  </text>
                </g>
              )}
            </svg>
          </div>
        ) : (
          <div className="py-12 text-center text-noc-muted space-y-2">
            <TrendingUp className="w-8 h-8 mx-auto text-noc-border" />
            <p className="text-sm">Insufficient telemetry points to render chart for selected entity.</p>
            <p className="text-xs text-noc-muted/80">Try selecting "All Entities" or another metric.</p>
          </div>
        )}

        {/* Hover Tooltip Overlay */}
        {hoveredPoint && (
          <div className="absolute top-4 right-4 bg-noc-card/95 border border-noc-cyan/50 backdrop-blur rounded-lg px-3 py-2 text-xs shadow-xl pointer-events-none">
            <div className="text-noc-cyan font-mono font-bold">
              {hoveredPoint.value.toFixed(2)} {hoveredPoint.unit || ''}
            </div>
            <div className="text-noc-text font-medium">{hoveredPoint.entity}</div>
            <div className="text-noc-muted text-[10px]">
              {new Date(hoveredPoint.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 text-xs text-noc-muted bg-noc-bg/50 px-3 py-2 rounded-lg border border-noc-border/60">
        <Info className="w-4 h-4 text-noc-cyan shrink-0" />
        <span>
          Telemetry metrics represent raw collector observations ingested by NetCoop AI. Threshold breaches trigger anomalous feature computation and tower hypotheses.
        </span>
      </div>
    </div>
  );
};
