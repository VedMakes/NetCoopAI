import React, { useState, useMemo } from 'react';
import { ExecutionEvent, DiagnosticTask } from '../types';
import { Network, Terminal, Search, Filter, ChevronDown, ChevronRight, Clock, Zap } from 'lucide-react';

interface FabricActivityLogProps {
  events: ExecutionEvent[];
  tasks?: DiagnosticTask[];
}

export const FabricActivityLog: React.FC<FabricActivityLogProps> = ({ events, tasks = [] }) => {
  const [activeView, setActiveView] = useState<'events' | 'tasks'>('events');
  const [componentFilter, setComponentFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);

  // Extract unique components
  const components = useMemo(() => {
    const set = new Set<string>();
    events.forEach((e) => {
      if (e.source_component) set.add(e.source_component);
    });
    return Array.from(set).sort();
  }, [events]);

  // Filter events
  const filteredEvents = useMemo(() => {
    return events.filter((e) => {
      const matchComp = componentFilter === 'all' || e.source_component === componentFilter;
      const query = searchQuery.toLowerCase().trim();
      if (!query) return matchComp;

      const inType = e.event_type.toLowerCase().includes(query);
      const inComp = e.source_component.toLowerCase().includes(query);
      const inStatus = e.status.toLowerCase().includes(query);
      const inEntity = e.entity_refs.some((ent) => ent.toLowerCase().includes(query));

      return matchComp && (inType || inComp || inStatus || inEntity);
    });
  }, [events, componentFilter, searchQuery]);

  return (
    <div className="bg-noc-card border border-noc-border rounded-xl p-5 shadow-lg space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-noc-border/60">
        <div>
          <h3 className="text-base font-semibold text-noc-text flex items-center gap-2">
            <Network className="w-5 h-5 text-noc-cyan" />
            Integration Fabric & Activity Log
          </h3>
          <p className="text-xs text-noc-muted">
            Monitors real-time EventBus publications, TaskDispatcher delegations, and inter-tower query transactions.
          </p>
        </div>

        {/* View Switcher */}
        <div className="flex items-center bg-noc-bg p-1 rounded-lg border border-noc-border text-xs shrink-0">
          <button
            onClick={() => setActiveView('events')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md font-medium transition-colors ${
              activeView === 'events'
                ? 'bg-noc-cyan/20 text-noc-cyan border border-noc-cyan/40 shadow-sm'
                : 'text-noc-muted hover:text-noc-text'
            }`}
          >
            <Zap className="w-3.5 h-3.5" />
            EventBus Stream ({events.length})
          </button>
          <button
            onClick={() => setActiveView('tasks')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md font-medium transition-colors ${
              activeView === 'tasks'
                ? 'bg-noc-purple/20 text-noc-purple border border-noc-purple/40 shadow-sm'
                : 'text-noc-muted hover:text-noc-text'
            }`}
          >
            <Terminal className="w-3.5 h-3.5" />
            Task Dispatcher ({tasks.length})
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
        <div className="relative w-full sm:w-72">
          <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-noc-muted" />
          <input
            type="text"
            placeholder={activeView === 'events' ? 'Search event type, component, entity...' : 'Search task, tower, status...'}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-noc-bg border border-noc-border rounded-lg pl-9 pr-3 py-1.5 text-noc-text placeholder-noc-muted focus:outline-none focus:border-noc-cyan transition-colors"
          />
        </div>

        {activeView === 'events' && (
          <div className="flex items-center gap-2 w-full sm:w-auto">
            <Filter className="w-3.5 h-3.5 text-noc-muted shrink-0" />
            <span className="text-noc-muted shrink-0">Component:</span>
            <select
              value={componentFilter}
              onChange={(e) => setComponentFilter(e.target.value)}
              className="bg-noc-bg border border-noc-border text-noc-text text-xs rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-noc-cyan"
            >
              <option value="all">All Components ({components.length})</option>
              {components.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Main View */}
      {activeView === 'events' ? (
        <div className="border border-noc-border rounded-xl bg-noc-bg/95 overflow-hidden">
          <div className="max-h-[440px] overflow-y-auto divide-y divide-noc-border/40 font-mono text-xs">
            {filteredEvents.length > 0 ? (
              filteredEvents.map((ev) => {
                const isExpanded = expandedEventId === ev.event_id;
                return (
                  <div key={ev.event_id} className="hover:bg-noc-card/50 transition-colors">
                    <div
                      onClick={() => setExpandedEventId(isExpanded ? null : ev.event_id)}
                      className="p-3 flex items-start sm:items-center justify-between gap-3 cursor-pointer select-none"
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <button className="text-noc-muted hover:text-noc-text p-0.5">
                          {isExpanded ? (
                            <ChevronDown className="w-3.5 h-3.5" />
                          ) : (
                            <ChevronRight className="w-3.5 h-3.5" />
                          )}
                        </button>
                        <span className="text-noc-muted text-[11px] whitespace-nowrap">
                          {new Date(ev.timestamp).toLocaleTimeString([], {
                            hour12: false,
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit',
                          })}
                        </span>
                        <span
                          className={`text-[10px] font-sans font-bold uppercase px-2 py-0.5 rounded border whitespace-nowrap ${
                            ev.source_component.toLowerCase().includes('performance')
                              ? 'bg-blue-500/10 text-blue-400 border-blue-500/30'
                              : ev.source_component.toLowerCase().includes('infrastructure')
                              ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                              : ev.source_component.toLowerCase().includes('connectivity')
                              ? 'bg-purple-500/10 text-purple-400 border-purple-500/30'
                              : ev.source_component.toLowerCase().includes('services')
                              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                              : ev.source_component.toLowerCase().includes('gate')
                              ? 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30'
                              : 'bg-noc-card text-noc-muted border-noc-border'
                          }`}
                        >
                          {ev.source_component}
                        </span>
                        <span className="text-noc-text font-semibold text-xs truncate">
                          {ev.event_type}
                        </span>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        {ev.entity_refs.length > 0 && (
                          <div className="hidden md:flex items-center gap-1">
                            {ev.entity_refs.slice(0, 2).map((ent) => (
                              <span
                                key={ent}
                                className="text-[10px] bg-noc-card text-noc-muted px-1.5 py-0.5 rounded border border-noc-border"
                              >
                                {ent}
                              </span>
                            ))}
                            {ev.entity_refs.length > 2 && (
                              <span className="text-[10px] text-noc-muted">
                                +{ev.entity_refs.length - 2}
                              </span>
                            )}
                          </div>
                        )}
                        <span
                          className={`text-[10px] uppercase px-1.5 py-0.5 rounded border ${
                            ev.status === 'completed'
                              ? 'bg-noc-emerald/10 text-noc-emerald border-noc-emerald/30'
                              : ev.status === 'running'
                              ? 'bg-noc-cyan/10 text-noc-cyan border-noc-cyan/30'
                              : 'bg-noc-card text-noc-muted border-noc-border'
                          }`}
                        >
                          {ev.status}
                        </span>
                      </div>
                    </div>

                    {/* Expandable Payload */}
                    {isExpanded && (
                      <div className="px-4 pb-3 pt-1 text-[11px] bg-noc-bg/90 border-t border-noc-border/50 space-y-2">
                        <div className="text-noc-muted font-sans flex items-center gap-2">
                          <span>Payload Data</span>
                          <span className="text-[10px] text-noc-border">|</span>
                          <span className="text-[10px] text-noc-muted">ID: {ev.event_id}</span>
                        </div>
                        <pre className="p-2.5 rounded bg-noc-card/80 border border-noc-border text-noc-cyan overflow-x-auto">
                          {JSON.stringify(ev.payload, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                );
              })
            ) : (
              <div className="py-10 text-center text-noc-muted font-sans">
                No events matching query.
              </div>
            )}
          </div>
        </div>
      ) : (
        /* Tasks View */
        <div className="border border-noc-border rounded-xl bg-noc-bg/95 overflow-hidden">
          <div className="overflow-x-auto max-h-[440px]">
            <table className="w-full text-left text-xs">
              <thead className="bg-noc-card/80 text-[11px] text-noc-muted uppercase font-semibold sticky top-0 z-10 border-b border-noc-border">
                <tr>
                  <th className="py-2.5 px-3">Task ID</th>
                  <th className="py-2.5 px-3">Assigned Tower</th>
                  <th className="py-2.5 px-3">Task Type</th>
                  <th className="py-2.5 px-3">Priority</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-noc-border/40 font-mono">
                {tasks.length > 0 ? (
                  tasks.map((task) => (
                    <tr key={task.task_id} className="hover:bg-noc-card/60 transition-colors">
                      <td className="py-2 px-3 text-noc-cyan font-medium whitespace-nowrap">
                        {task.task_id}
                      </td>
                      <td className="py-2 px-3 text-noc-text whitespace-nowrap capitalize">
                        <span className="bg-noc-card px-2 py-0.5 rounded border border-noc-border text-[11px]">
                          {task.assigned_tower}
                        </span>
                      </td>
                      <td className="py-2 px-3 text-noc-muted whitespace-nowrap">
                        {task.task_type}
                      </td>
                      <td className="py-2 px-3 text-noc-text whitespace-nowrap">
                        P{task.priority}
                      </td>
                      <td className="py-2 px-3 whitespace-nowrap">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-sans ${
                            task.status.toLowerCase() === 'completed'
                              ? 'bg-noc-emerald/15 text-noc-emerald border border-noc-emerald/30'
                              : 'bg-noc-cyan/15 text-noc-cyan border border-noc-cyan/30'
                          }`}
                        >
                          {task.status}
                        </span>
                      </td>
                      <td className="py-2 px-3 text-noc-text font-sans text-xs">
                        {task.description}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-noc-muted font-sans">
                      No TaskDispatcher allocations recorded for this run.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Footer Info */}
      <div className="flex items-center justify-between text-xs text-noc-muted pt-1">
        <div className="flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5 text-noc-cyan" />
          <span>Integration Fabric operates asynchronously without blocking caller threads.</span>
        </div>
        <div>
          {activeView === 'events' ? `${filteredEvents.length} events logged` : `${tasks.length} tasks recorded`}
        </div>
      </div>
    </div>
  );
};
