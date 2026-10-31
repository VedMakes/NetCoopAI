import React, { useState } from 'react';
import { TopologyGraph, TopologyNode } from '../types';
import { Server, Wifi, Cpu, Database } from 'lucide-react';

interface TopologyViewProps {
  topology: TopologyGraph | null;
  selectedNodeId?: string;
  onSelectNode: (node: TopologyNode | null) => void;
  rootCauseEntity?: string;
  symptomEntities?: string[];
  inferredEntities?: string[];
}

// Preset coordinate mapping for canonical campus network
const PRESET_COORDINATES: Record<string, { x: number; y: number }> = {
  GW_EDGE_01: { x: 450, y: 50 },
  SW_CORE_01: { x: 450, y: 160 },
  SW_DIST_HOSTEL: { x: 250, y: 280 },
  SW_DIST_DEPT: { x: 650, y: 280 },
  AP_HOSTEL_A: { x: 150, y: 400 },
  AP_HOSTEL_B: { x: 300, y: 400 },
  SW_ACCESS_LAB: { x: 650, y: 400 },
  SRV_DNS_01: { x: 750, y: 140 },
  SRV_DHCP_01: { x: 750, y: 200 },
};

export const TopologyView: React.FC<TopologyViewProps> = ({
  topology,
  selectedNodeId,
  onSelectNode,
  rootCauseEntity,
  symptomEntities = [],
  inferredEntities = [],
}) => {
  const [hoveredNode, setHoveredNode] = useState<TopologyNode | null>(null);

  if (!topology || topology.nodes.length === 0) {
    return (
      <div className="w-full h-full min-h-[480px] flex flex-col items-center justify-center bg-noc-panel/40 border border-noc-border rounded-xl text-noc-muted">
        <Server className="w-10 h-10 mb-2 opacity-30" />
        <p className="text-sm font-mono">No topology loaded. Select a scenario above.</p>
      </div>
    );
  }

  // Calculate layout coordinates
  const nodesWithCoords = topology.nodes.map((node, index) => {
    if (PRESET_COORDINATES[node.id]) {
      return { ...node, ...PRESET_COORDINATES[node.id] };
    }
    // Fallback circular layout for arbitrary topologies
    const angle = (index / topology.nodes.length) * 2 * Math.PI;
    const x = 450 + 260 * Math.cos(angle);
    const y = 250 + 170 * Math.sin(angle);
    return { ...node, x, y };
  });

  const nodeMap = new Map(nodesWithCoords.map(n => [n.id, n]));

  const getNodeRoleIcon = (role: string, type: string) => {
    const r = role.toLowerCase();
    if (r.includes('gateway') || r.includes('edge')) return <Server className="w-4 h-4 text-cyan-400" />;
    if (r.includes('core')) return <Cpu className="w-4 h-4 text-indigo-400" />;
    if (r.includes('dist') || r.includes('access')) return <Server className="w-4 h-4 text-noc-muted" />;
    if (r.includes('wireless') || r.includes('ap')) return <Wifi className="w-4 h-4 text-amber-400" />;
    if (r.includes('dns') || r.includes('dhcp') || type === 'service') return <Database className="w-4 h-4 text-purple-400" />;
    return <Server className="w-4 h-4 text-noc-muted" />;
  };

  const getNodeStatus = (node: TopologyNode): 'nominal' | 'symptom' | 'impacted' | 'probable_root_cause' => {
    if (rootCauseEntity && (node.id.includes(rootCauseEntity) || rootCauseEntity.includes(node.id))) {
      return 'probable_root_cause';
    }
    if (symptomEntities.some(s => node.id.includes(s) || s.includes(node.id))) {
      return 'symptom';
    }
    if (inferredEntities.some(i => node.id.includes(i) || i.includes(node.id))) {
      return 'impacted';
    }
    return node.status || 'nominal';
  };

  return (
    <div className="relative w-full h-[520px] bg-noc-panel/60 border border-noc-border rounded-xl overflow-hidden select-none shadow-inner">
      {/* Topology Header & Status Legend */}
      <div className="absolute top-4 left-4 z-10 flex flex-col space-y-2 pointer-events-none">
        <div className="flex items-center space-x-2 bg-noc-bg/80 backdrop-blur px-3 py-1.5 rounded-lg border border-noc-border text-xs">
          <span className="font-mono font-medium text-noc-text">{topology.topology_id}</span>
          <span className="text-noc-muted">({topology.nodes.length} nodes, {topology.links.length} links)</span>
        </div>

        {/* Legend */}
        <div className="flex items-center space-x-3 bg-noc-bg/80 backdrop-blur px-3 py-1.5 rounded-lg border border-noc-border text-[11px] font-mono">
          <span className="flex items-center space-x-1.5 text-noc-cyan">
            <span className="w-2 h-2 rounded-full bg-noc-cyan" />
            <span>Nominal</span>
          </span>
          <span className="flex items-center space-x-1.5 text-noc-yellow">
            <span className="w-2 h-2 rounded-full bg-noc-yellow animate-ping" />
            <span>Observed Symptom</span>
          </span>
          <span className="flex items-center space-x-1.5 text-noc-purple">
            <span className="w-2 h-2 rounded-full bg-noc-purple" />
            <span>Inferred Impact</span>
          </span>
          <span className="flex items-center space-x-1.5 text-noc-red">
            <span className="w-2.5 h-2.5 rounded-full bg-noc-red ring-2 ring-noc-red/40" />
            <span>Probable Root Cause</span>
          </span>
        </div>
      </div>

      {/* SVG Canvas */}
      <svg className="w-full h-full" viewBox="0 0 900 500">
        <defs>
          <filter id="glow-root" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="0" stdDeviation="6" floodColor="#F43F5E" floodOpacity="0.8" />
          </filter>
          <filter id="glow-symptom" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="0" stdDeviation="4" floodColor="#F59E0B" floodOpacity="0.7" />
          </filter>
          <filter id="glow-impact" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="0" stdDeviation="4" floodColor="#A855F7" floodOpacity="0.6" />
          </filter>
        </defs>

        {/* Render Links */}
        <g className="links">
          {topology.links.map(link => {
            const src = nodeMap.get(link.source);
            const tgt = nodeMap.get(link.target);
            if (!src || !tgt) return null;

            const isDegraded = link.status === 'congested' || link.status === 'degraded';
            const strokeColor = isDegraded ? '#F43F5E' : '#2A3452';
            const strokeWidth = isDegraded ? 2.5 : 1.5;

            return (
              <g key={link.id}>
                <line
                  x1={src.x}
                  y1={src.y}
                  x2={tgt.x}
                  y2={tgt.y}
                  stroke={strokeColor}
                  strokeWidth={strokeWidth}
                  strokeOpacity={0.8}
                  className={isDegraded ? 'animate-link-congested' : 'animate-link-pulse'}
                />
              </g>
            );
          })}
        </g>

        {/* Render Nodes */}
        <g className="nodes">
          {nodesWithCoords.map(node => {
            const status = getNodeStatus(node);
            const isSelected = selectedNodeId === node.id;
            const isHovered = hoveredNode?.id === node.id;

            let borderColor = '#2E3A5F';
            let fillColor = '#121624';
            let filter = undefined;

            if (status === 'probable_root_cause') {
              borderColor = '#F43F5E';
              fillColor = '#2D1520';
              filter = 'url(#glow-root)';
            } else if (status === 'symptom') {
              borderColor = '#F59E0B';
              fillColor = '#251D14';
              filter = 'url(#glow-symptom)';
            } else if (status === 'impacted') {
              borderColor = '#A855F7';
              fillColor = '#1F172B';
              filter = 'url(#glow-impact)';
            } else if (isSelected || isHovered) {
              borderColor = '#818CF8';
            }

            return (
              <g
                key={node.id}
                transform={`translate(${node.x}, ${node.y})`}
                className="cursor-pointer transition-transform duration-150"
                onClick={() => onSelectNode(isSelected ? null : node)}
                onMouseEnter={() => setHoveredNode(node)}
                onMouseLeave={() => setHoveredNode(null)}
              >
                {/* Node Outer Container */}
                <rect
                  x="-65"
                  y="-22"
                  width="130"
                  height="44"
                  rx="8"
                  fill={fillColor}
                  stroke={borderColor}
                  strokeWidth={isSelected ? 2.5 : status !== 'nominal' ? 2 : 1.5}
                  filter={filter}
                />

                {/* Node Status Indicator Pill */}
                <circle
                  cx="-48"
                  cy="0"
                  r="5"
                  fill={
                    status === 'probable_root_cause'
                      ? '#F43F5E'
                      : status === 'symptom'
                      ? '#F59E0B'
                      : status === 'impacted'
                      ? '#A855F7'
                      : '#10B981'
                  }
                />

                {/* Node Label Text */}
                <text
                  x="-35"
                  y="-4"
                  fill="#F1F5F9"
                  fontSize="10.5"
                  fontWeight="600"
                  fontFamily="monospace"
                  className="pointer-events-none"
                >
                  {node.id}
                </text>

                {/* Node Subtitle (Role) */}
                <text
                  x="-35"
                  y="11"
                  fill="#94A3B8"
                  fontSize="8.5"
                  fontFamily="sans-serif"
                  className="pointer-events-none capitalize"
                >
                  {node.role.replace(/_/g, ' ')}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* Selected Node Details Drawer in Bottom Right */}
      {selectedNodeId && nodeMap.get(selectedNodeId) && (
        <div className="absolute bottom-4 right-4 z-20 w-80 bg-noc-panel/95 backdrop-blur border border-noc-border rounded-xl p-4 shadow-xl">
          {(() => {
            const node = nodeMap.get(selectedNodeId)!;
            const status = getNodeStatus(node);
            return (
              <div>
                <div className="flex items-center justify-between pb-2 border-b border-noc-border mb-3">
                  <div className="flex items-center space-x-2">
                    {getNodeRoleIcon(node.role, node.type)}
                    <span className="font-mono font-bold text-sm text-noc-text">{node.id}</span>
                  </div>
                  <button
                    onClick={() => onSelectNode(null)}
                    className="text-noc-muted hover:text-noc-text text-xs"
                  >
                    ✕
                  </button>
                </div>

                <div className="space-y-2 text-xs font-mono">
                  <div className="flex justify-between">
                    <span className="text-noc-muted">Role:</span>
                    <span className="text-noc-text">{node.role}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-noc-muted">Type:</span>
                    <span className="text-noc-text capitalize">{node.type}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-noc-muted">Status:</span>
                    <span
                      className={`px-2 py-0.5 rounded text-[11px] font-semibold ${
                        status === 'probable_root_cause'
                          ? 'bg-rose-950 text-rose-300 border border-rose-800'
                          : status === 'symptom'
                          ? 'bg-amber-950 text-amber-300 border border-amber-800'
                          : status === 'impacted'
                          ? 'bg-purple-950 text-purple-300 border border-purple-800'
                          : 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                      }`}
                    >
                      {status.replace(/_/g, ' ').toUpperCase()}
                    </span>
                  </div>
                  <div className="pt-2 text-[11px] text-noc-muted border-t border-noc-border">
                    {status === 'probable_root_cause' && (
                      <p className="text-rose-300">Certified by Evidence Gate as root cause candidate.</p>
                    )}
                    {status === 'symptom' && (
                      <p className="text-amber-300">Observed active telemetry or log anomalies.</p>
                    )}
                    {status === 'impacted' && (
                      <p className="text-purple-300">Predicted impact candidate via topology reachability.</p>
                    )}
                    {status === 'nominal' && (
                      <p className="text-emerald-300">Operating within healthy baseline thresholds.</p>
                    )}
                  </div>
                </div>
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
};
