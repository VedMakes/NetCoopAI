import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Database, Minus, Plus, RotateCcw, Router, Server, Wifi } from 'lucide-react';
import { TopologyGraph, TopologyNode } from '../types';

interface TopologyViewProps {
  topology: TopologyGraph | null;
  layoutKey?: string;
  selectedNodeId?: string;
  onSelectNode: (node: TopologyNode | null) => void;
  symptomEntities?: string[];
  inferredEntities?: string[];
}

interface Point { x: number; y: number }
interface PositionedNode extends TopologyNode { x: number; y: number }

const CANVAS = { width: 1120, height: 660 };
const NODE_SPACING = { x: 190, y: 112 };

const nodeLayer = (node: TopologyNode): number => {
  const role = `${node.role} ${node.type}`.toLowerCase();
  if (/gateway|edge|border_router/.test(role)) return 0;
  if (/core|backbone/.test(role)) return 1;
  if (/distribution|dist_switch/.test(role)) return 2;
  if (/service|dns|dhcp|database/.test(role)) return 2;
  if (/access_point|wireless|\bap\b|access_switch/.test(role)) return 3;
  if (/segment|client|endpoint|hostel_zone/.test(role)) return 4;
  return 2;
};

const buildLayout = (topology: TopologyGraph): Record<string, Point> => {
  const groups = new Map<number, TopologyNode[]>();
  topology.nodes.forEach((node) => {
    const layer = nodeLayer(node);
    groups.set(layer, [...(groups.get(layer) ?? []), node]);
  });
  const positions: Record<string, Point> = {};
  groups.forEach((nodes, layer) => {
    const sorted = [...nodes].sort((a, b) => `${a.role}:${a.name}:${a.id}`.localeCompare(`${b.role}:${b.name}:${b.id}`));
    const x = 100 + layer * NODE_SPACING.x;
    const totalHeight = Math.max(0, sorted.length - 1) * NODE_SPACING.y;
    const startY = Math.max(90, (CANVAS.height - totalHeight) / 2);
    sorted.forEach((node, index) => { positions[node.id] = { x, y: startY + index * NODE_SPACING.y }; });
  });
  return positions;
};

const statusStyle = (status: string) => {
  if (status === 'probable_root_cause') return { stroke: '#FB7185', fill: '#321B2A', dot: '#FB7185', label: 'Probable cause' };
  if (status === 'symptom') return { stroke: '#F5C26B', fill: '#302818', dot: '#F5C26B', label: 'Observed symptom' };
  if (status === 'impacted') return { stroke: '#C4A1F2', fill: '#291F38', dot: '#C4A1F2', label: 'Predicted impact' };
  return { stroke: '#55C6B0', fill: '#172A2B', dot: '#55C6B0', label: 'No observed impact' };
};

const shapeFor = (node: TopologyNode): 'gateway' | 'switch' | 'wireless' | 'service' | 'segment' => {
  const role = `${node.role} ${node.type}`.toLowerCase();
  if (/service|dns|dhcp|database/.test(role)) return 'service';
  if (/wireless|access_point|\bap\b/.test(role)) return 'wireless';
  if (/gateway|edge|border_router/.test(role)) return 'gateway';
  if (/segment|client|endpoint|hostel_zone/.test(role)) return 'segment';
  return 'switch';
};

const titleFor = (node: TopologyNode) => node.name && node.name !== node.id ? node.name : node.id;

export const TopologyView: React.FC<TopologyViewProps> = ({
  topology,
  layoutKey: externalLayoutKey,
  selectedNodeId,
  onSelectNode,
  symptomEntities = [],
  inferredEntities = [],
}) => {
  const [positions, setPositions] = useState<Record<string, Point>>({});
  const [zoom, setZoom] = useState(1);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ id: string; moved: boolean; startX: number; startY: number } | null>(null);
  const layoutKey = topology ? `${externalLayoutKey ?? ''}:${topology.topology_id}:${topology.nodes.map((node) => node.id).join('|')}` : '';

  useEffect(() => {
    if (topology) setPositions(buildLayout(topology));
    setZoom(1);
  }, [layoutKey]);

  const positionedNodes = useMemo<PositionedNode[]>(() => (topology?.nodes ?? []).map((node) => ({
    ...node,
    ...(positions[node.id] ?? { x: CANVAS.width / 2, y: CANVAS.height / 2 }),
  })), [topology, positions]);
  const nodeMap = useMemo(() => new Map(positionedNodes.map((node) => [node.id, node])), [positionedNodes]);

  const nodeStatus = (node: TopologyNode) => {
    if (node.status === 'probable_root_cause') return 'probable_root_cause';
    if (symptomEntities.includes(node.id)) return 'symptom';
    if (inferredEntities.includes(node.id)) return 'impacted';
    return node.status || 'nominal';
  };

  const handlePointerDown = (event: React.PointerEvent<SVGGElement>, node: TopologyNode) => {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { id: node.id, moved: false, startX: event.clientX, startY: event.clientY };
  };

  const handlePointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current;
    const svg = svgRef.current;
    if (!drag || !svg) return;
    const screenMatrix = svg.getScreenCTM();
    if (!screenMatrix) return;
    const pointer = svg.createSVGPoint();
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    const point = pointer.matrixTransform(screenMatrix.inverse());
    if (Math.abs(event.clientX - drag.startX) + Math.abs(event.clientY - drag.startY) > 4) drag.moved = true;
    if (!drag.moved) return;
    const center = { x: CANVAS.width / 2, y: CANVAS.height / 2 };
    setPositions((current) => ({ ...current, [drag.id]: {
      x: Math.max(78, Math.min(CANVAS.width - 78, center.x + (point.x - center.x) / zoom)),
      y: Math.max(55, Math.min(CANVAS.height - 55, center.y + (point.y - center.y) / zoom)),
    } }));
  };

  const handlePointerUp = (event: React.PointerEvent<SVGGElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    if (!drag.moved) onSelectNode(drag.id === selectedNodeId ? null : nodeMap.get(drag.id) ?? null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    dragRef.current = null;
  };

  const selectWithKeyboard = (event: React.KeyboardEvent<SVGGElement>, node: PositionedNode) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onSelectNode(node.id === selectedNodeId ? null : node);
    }
  };

  if (!topology || topology.nodes.length === 0) {
    return (
      <section className="rounded-2xl border border-noc-border bg-noc-panel/70 p-7 shadow-panel">
        <div className="flex min-h-[360px] flex-col items-center justify-center text-center">
          <div className="mb-4 rounded-2xl border border-noc-border bg-noc-subpanel p-4 text-noc-amethyst"><Router className="h-8 w-8" /></div>
          <h3 className="text-sm font-semibold text-noc-text">Your network map will appear here</h3>
          <p className="mt-2 max-w-md text-xs leading-6 text-noc-muted">Choose a simulation case or upload telemetry with a topology map. You can drag nodes into a layout that makes sense for your site.</p>
        </div>
      </section>
    );
  }

  const selectedNode = selectedNodeId ? nodeMap.get(selectedNodeId) : null;
  const zoomBy = (direction: number) => setZoom((current) => Math.max(0.65, Math.min(1.7, current + direction)));

  return (
    <section className="overflow-hidden rounded-2xl border border-noc-border bg-noc-panel/75 shadow-panel">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-noc-border px-5 py-4">
        <div>
          <div className="flex items-center gap-2 text-noc-amethyst"><Activity className="h-4 w-4" /><span className="text-[10px] font-semibold uppercase tracking-[0.18em]">Live network map</span></div>
          <h2 className="mt-1 text-sm font-semibold text-noc-text">{topology.topology_id.replace(/[_-]+/g, ' ')}</h2>
          <p className="mt-1 text-[11px] text-noc-muted">{topology.nodes.length} devices · {topology.links.length} relationships <span className="mx-1.5 text-noc-border">/</span> Drag a node to arrange the map</p>
        </div>
        <div className="flex items-center gap-1 rounded-xl border border-noc-border bg-noc-bg/70 p-1">
          <button aria-label="Zoom out" title="Zoom out" onClick={() => zoomBy(-0.12)} className="rounded-lg p-2 text-noc-muted hover:bg-noc-hover hover:text-noc-text"><Minus className="h-3.5 w-3.5" /></button>
          <span className="min-w-12 text-center font-mono text-[10px] text-noc-muted">{Math.round(zoom * 100)}%</span>
          <button aria-label="Zoom in" title="Zoom in" onClick={() => zoomBy(0.12)} className="rounded-lg p-2 text-noc-muted hover:bg-noc-hover hover:text-noc-text"><Plus className="h-3.5 w-3.5" /></button>
          <span className="mx-1 h-5 w-px bg-noc-border" />
          <button aria-label="Reset map layout" title="Reset map layout" onClick={() => { setPositions(buildLayout(topology)); setZoom(1); }} className="rounded-lg p-2 text-noc-muted hover:bg-noc-hover hover:text-noc-text"><RotateCcw className="h-3.5 w-3.5" /></button>
        </div>
        <div className="flex w-full flex-wrap gap-x-4 gap-y-2 border-t border-noc-border/60 pt-3 text-[10px] text-noc-muted sm:w-auto sm:border-0 sm:pt-0">
          {[
            ['#55C6B0', 'No observed impact'], ['#F5C26B', 'Observed symptom'], ['#C4A1F2', 'Predicted impact'], ['#FB7185', 'Probable cause'],
          ].map(([color, label]) => <span key={label} className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />{label}</span>)}
        </div>
      </div>

      <div className="relative h-[460px] bg-[radial-gradient(ellipse_at_center,_rgba(124,91,162,0.11),_transparent_68%)] sm:h-[560px]">
        <svg
          ref={svgRef}
          className="h-full w-full touch-none"
          viewBox={`0 0 ${CANVAS.width} ${CANVAS.height}`}
          aria-label={`Network topology containing ${topology.nodes.length} nodes and ${topology.links.length} links`}
          onPointerMove={handlePointerMove}
          onWheel={(event) => { event.preventDefault(); zoomBy(event.deltaY < 0 ? 0.08 : -0.08); }}
        >
          <defs>
            <pattern id="topology-grid" width="32" height="32" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#8B7AA7" fillOpacity="0.18" /></pattern>
            <filter id="node-shadow" x="-35%" y="-35%" width="170%" height="170%"><feDropShadow dx="0" dy="5" stdDeviation="6" floodColor="#080811" floodOpacity="0.55" /></filter>
            <marker id="edge-dot" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto"><circle cx="3" cy="3" r="2" fill="#8F83A8" /></marker>
            <marker id="edge-alert" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto"><circle cx="3.5" cy="3.5" r="2.5" fill="#FB7185" /></marker>
          </defs>
          <rect width={CANVAS.width} height={CANVAS.height} fill="url(#topology-grid)" />
          <g transform={`translate(${CANVAS.width / 2} ${CANVAS.height / 2}) scale(${zoom}) translate(${-CANVAS.width / 2} ${-CANVAS.height / 2})`}>
            <g aria-hidden="true">
              {topology.links.map((link, index) => {
                const source = nodeMap.get(link.source);
                const target = nodeMap.get(link.target);
                if (!source || !target) return null;
                const degraded = ['congested', 'degraded', 'down'].includes(link.status);
                const bend = (index % 2 ? 1 : -1) * Math.min(30, Math.abs(target.y - source.y) * 0.08 + 10);
                const midX = (source.x + target.x) / 2;
                const midY = (source.y + target.y) / 2 + bend;
                return <g key={link.id}>
                  <path d={`M ${source.x} ${source.y} Q ${midX} ${midY} ${target.x} ${target.y}`} fill="none" stroke={degraded ? '#FB7185' : '#766A8D'} strokeWidth={degraded ? 2.5 : 1.6} strokeOpacity={degraded ? 0.82 : 0.48} strokeDasharray={link.status === 'down' ? '6 7' : undefined} markerEnd={`url(#${degraded ? 'edge-alert' : 'edge-dot'})`} />
                </g>;
              })}
            </g>
            {positionedNodes.map((node) => {
              const status = nodeStatus(node);
              const palette = statusStyle(status);
              const selected = selectedNodeId === node.id;
              const hovered = hoveredNodeId === node.id;
              const shape = shapeFor(node);
              const label = titleFor(node);
              const clippedLabel = label.length > 21 ? `${label.slice(0, 20)}…` : label;
              return (
                <g
                  key={node.id}
                  transform={`translate(${node.x} ${node.y})`}
                  role="button"
                  tabIndex={0}
                  aria-label={`${label}, ${node.role.replace(/_/g, ' ')}, ${palette.label}. Drag to move.`}
                  className="cursor-grab outline-none active:cursor-grabbing"
                  onPointerDown={(event) => handlePointerDown(event, node)}
                  onPointerUp={handlePointerUp}
                  onPointerCancel={handlePointerUp}
                  onKeyDown={(event) => selectWithKeyboard(event, node)}
                  onMouseEnter={() => setHoveredNodeId(node.id)}
                  onMouseLeave={() => setHoveredNodeId(null)}
                >
                  <g filter="url(#node-shadow)">
                    {shape === 'gateway' && <polygon points="-53,-30 38,-30 58,-15 58,15 38,30 -53,30 -62,0" fill={palette.fill} stroke={palette.stroke} strokeWidth={selected || hovered ? 2.6 : 1.6} />}
                    {shape === 'switch' && <rect x="-63" y="-29" width="126" height="58" rx="13" fill={palette.fill} stroke={palette.stroke} strokeWidth={selected || hovered ? 2.6 : 1.6} />}
                    {shape === 'wireless' && <ellipse cx="0" cy="0" rx="65" ry="29" fill={palette.fill} stroke={palette.stroke} strokeWidth={selected || hovered ? 2.6 : 1.6} />}
                    {shape === 'service' && <path d="M -58 -20 C -58 -34 58 -34 58 -20 L 58 20 C 58 34 -58 34 -58 20 Z M -58 -20 C -58 -6 58 -6 58 -20" fill={palette.fill} stroke={palette.stroke} strokeWidth={selected || hovered ? 2.6 : 1.6} />}
                    {shape === 'segment' && <polygon points="-50,-29 50,-29 65,0 50,29 -50,29 -65,0" fill={palette.fill} stroke={palette.stroke} strokeWidth={selected || hovered ? 2.6 : 1.6} />}
                  </g>
                  <circle cx="-44" cy="0" r="4.5" fill={palette.dot} />
                  <text x="-34" y="-3" fill="#F5EFFB" fontSize="11" fontWeight="600" fontFamily="ui-monospace, monospace" pointerEvents="none">{clippedLabel}</text>
                  <text x="-34" y="14" fill="#A99DB7" fontSize="9" fontFamily="Inter, sans-serif" pointerEvents="none">{node.role.replace(/_/g, ' ').slice(0, 22)}</text>
                  {selected && <circle cx="55" cy="-23" r="4" fill="#F1D6AA" stroke="#12111A" strokeWidth="2" />}
                </g>
              );
            })}
          </g>
        </svg>

        {selectedNode && <div className="absolute bottom-4 right-4 z-10 w-[min(320px,calc(100%-2rem))] rounded-2xl border border-noc-border bg-noc-bg/95 p-4 shadow-2xl backdrop-blur">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-noc-amethyst">{shapeFor(selectedNode) === 'service' ? <Database className="h-4 w-4" /> : shapeFor(selectedNode) === 'wireless' ? <Wifi className="h-4 w-4" /> : shapeFor(selectedNode) === 'gateway' ? <Router className="h-4 w-4" /> : <Server className="h-4 w-4" />}<span className="text-[10px] font-semibold uppercase tracking-widest">Selected device</span></div>
              <h3 className="mt-1 text-sm font-semibold text-noc-text">{titleFor(selectedNode)}</h3>
              <p className="mt-1 text-[11px] text-noc-muted">{selectedNode.role.replace(/_/g, ' ')} · {selectedNode.type}</p>
            </div>
            <button aria-label="Close node details" onClick={() => onSelectNode(null)} className="rounded-lg px-2 py-1 text-xs text-noc-muted hover:bg-noc-hover hover:text-noc-text">×</button>
          </div>
          <div className="mt-3 flex items-center gap-2 border-t border-noc-border pt-3 text-xs" style={{ color: statusStyle(nodeStatus(selectedNode)).dot }}>
            <i className="h-2 w-2 rounded-full" style={{ backgroundColor: statusStyle(nodeStatus(selectedNode)).dot }} />{statusStyle(nodeStatus(selectedNode)).label}
          </div>
        </div>}
      </div>
    </section>
  );
};
