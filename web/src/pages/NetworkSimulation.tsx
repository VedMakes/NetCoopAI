import React, { useState, useEffect } from 'react';
import { Play, RotateCcw, Activity, Cpu, Server, Radio } from 'lucide-react';
import {
  ExecutionEvent,
  FinalReport,
  RunStatusResponse,
  ScenarioSummary,
  TelemetryObservation,
  TopologyGraph,
  TopologyNode,
} from '../types';
import {
  createRun,
  getRunEvents,
  getRunReport,
  getRunStatus,
  getRunTelemetry,
  getRunTopology,
  getScenarios,
  getScenarioTopology,
} from '../api';
import { TopologyView } from '../components/TopologyView';
import { PlaybackControls } from '../components/PlaybackControls';

interface NetworkSimulationProps {
  onRunCompleted: (runId: string, incidentId: string, report: FinalReport) => void;
  activeRun: RunStatusResponse | null;
  setActiveRun: (run: RunStatusResponse | null) => void;
}

export const NetworkSimulation: React.FC<NetworkSimulationProps> = ({
  onRunCompleted,
  activeRun,
  setActiveRun,
}) => {
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>('link_congestion');
  const [llmMode, setLlmMode] = useState<'off' | 'auto' | 'on'>('off');
  const [topology, setTopology] = useState<TopologyGraph | null>(null);
  const [selectedNode, setSelectedNode] = useState<TopologyNode | null>(null);

  // Playback state
  const [observations, setObservations] = useState<TelemetryObservation[]>([]);
  const [timeSteps, setTimeSteps] = useState<string[]>([]);
  const [currentStep, setCurrentStep] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1);

  // Diagnostic execution state
  const [isLaunching, setIsLaunching] = useState<boolean>(false);
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [report, setReport] = useState<FinalReport | null>(null);

  // 1. Load available scenarios on mount
  useEffect(() => {
    getScenarios()
      .then(data => {
        setScenarios(data);
        if (data.length > 0 && !selectedScenarioId) {
          setSelectedScenarioId(data[0].scenario_id);
        }
      })
      .catch(err => console.error('Failed to load scenarios:', err));
  }, []);

  // 2. Load topology whenever selected scenario changes (if not running a custom run)
  useEffect(() => {
    if (selectedScenarioId) {
      getScenarioTopology(selectedScenarioId)
        .then(setTopology)
        .catch(err => console.error('Failed to load scenario topology:', err));
    }
  }, [selectedScenarioId]);

  // 3. Polling / Event streaming when active run is running
  useEffect(() => {
    if (!activeRun || activeRun.status === 'completed' || activeRun.status === 'failed') return;

    const interval = setInterval(async () => {
      try {
        const st = await getRunStatus(activeRun.run_id);
        setActiveRun(st);

        // Fetch events
        const evts = await getRunEvents(activeRun.run_id);
        setEvents(evts);

        if (st.status === 'completed') {
          clearInterval(interval);
          // Fetch final artifacts
          const rep = await getRunReport(activeRun.run_id);
          setReport(rep);

          const topo = await getRunTopology(activeRun.run_id);
          setTopology(topo);

          const telem = await getRunTelemetry(activeRun.run_id);
          setObservations(telem.observations);

          // Extract distinct timestamps
          const distinctTimes = Array.from(new Set(telem.observations.map(o => o.timestamp))).sort();
          setTimeSteps(distinctTimes);
          setCurrentStep(distinctTimes.length);

          onRunCompleted(activeRun.run_id, activeRun.incident_id, rep);
        }
      } catch (err) {
        console.error('Error polling run:', err);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [activeRun]);

  // 4. Playback animation timer
  useEffect(() => {
    if (!isPlaying || timeSteps.length === 0) return;

    const intervalTime = 1200 / playbackSpeed;
    const timer = setInterval(() => {
      setCurrentStep(prev => {
        if (prev >= timeSteps.length) {
          setIsPlaying(false);
          return prev;
        }
        return prev + 1;
      });
    }, intervalTime);

    return () => clearInterval(timer);
  }, [isPlaying, timeSteps, playbackSpeed]);

  const handleLaunchRun = async () => {
    if (!selectedScenarioId || isLaunching) return;

    setIsLaunching(true);
    setEvents([]);
    setReport(null);
    setCurrentStep(0);
    setIsPlaying(false);

    try {
      const run = await createRun({
        scenario_id: selectedScenarioId,
        llm: llmMode,
      });
      setActiveRun(run);
    } catch (err: any) {
      alert(`Failed to launch run: ${err.message || 'Unknown error'}`);
    } finally {
      setIsLaunching(false);
    }
  };

  const handleReset = () => {
    setActiveRun(null);
    setReport(null);
    setEvents([]);
    setCurrentStep(0);
    setIsPlaying(false);
    if (selectedScenarioId) {
      getScenarioTopology(selectedScenarioId).then(setTopology);
    }
  };

  // Derive visible symptoms up to current playback step
  const visibleObservations = observations.filter(o => {
    if (currentStep === 0) return false;
    const stepTime = timeSteps[currentStep - 1];
    return stepTime && o.timestamp <= stepTime;
  });

  const activeSymptomEntities = Array.from(
    new Set(
      visibleObservations
        .filter(o => o.observation_type === 'metric' && (o.value || 0) > 80) // simple threshold filter for playback
        .map(o => o.entity_id)
    )
  );

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Top Configuration & Control Bar */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Scenario Selector Card */}
        <div className="lg:col-span-2 bg-noc-panel border border-noc-border rounded-xl p-5 shadow-lg">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-bold text-noc-text flex items-center space-x-2">
              <Server className="w-4 h-4 text-indigo-400" />
              <span>Select Benchmark Scenario</span>
            </h2>
            <span className="text-xs text-noc-muted font-mono">{scenarios.length} Scenarios Available</span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
            {scenarios.map(sc => (
              <button
                key={sc.scenario_id}
                onClick={() => {
                  setSelectedScenarioId(sc.scenario_id);
                  handleReset();
                }}
                className={`p-2.5 rounded-lg text-left transition-all border ${
                  selectedScenarioId === sc.scenario_id
                    ? 'bg-indigo-950/60 border-indigo-500/60 shadow-md shadow-indigo-900/20'
                    : 'bg-noc-subpanel hover:bg-noc-hover border-noc-border text-noc-muted'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-noc-bg border border-noc-border text-noc-cyan">
                    {sc.category}
                  </span>
                </div>
                <h4 className="text-xs font-semibold text-noc-text truncate">{sc.name}</h4>
              </button>
            ))}
          </div>

          {/* Selected Scenario Symptoms Summary */}
          {selectedScenarioId && (
            <div className="bg-noc-subpanel border border-noc-border/60 rounded-lg p-3 text-xs flex items-start space-x-3">
              <Activity className="w-4 h-4 text-noc-yellow mt-0.5 flex-shrink-0" />
              <div>
                <span className="font-semibold text-noc-text">Symptoms Profile: </span>
                <span className="text-noc-muted">
                  {scenarios.find(s => s.scenario_id === selectedScenarioId)?.symptoms_summary ||
                    'Nominal network operation with baseline metric load.'}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Diagnostic Run Execution Panel */}
        <div className="bg-noc-panel border border-noc-border rounded-xl p-5 shadow-lg flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-bold text-noc-text flex items-center space-x-2">
                <Cpu className="w-4 h-4 text-noc-amethyst" />
                <span>Diagnostic Engine</span>
              </h2>

              {/* LLM Mode Switch */}
              <div className="flex items-center border border-noc-border rounded-lg bg-noc-subpanel p-0.5">
                {(['off', 'auto', 'on'] as const).map(mode => (
                  <button
                    key={mode}
                    onClick={() => setLlmMode(mode)}
                    className={`px-2 py-0.5 text-[10px] font-mono rounded transition-colors uppercase ${
                      llmMode === mode ? 'bg-indigo-600 text-white font-bold' : 'text-noc-muted hover:text-noc-text'
                    }`}
                  >
                    {mode}
                  </button>
                ))}
              </div>
            </div>

            <p className="text-xs text-noc-muted leading-relaxed mb-4">
              Executes the four specialist towers (Performance, Infra, Conn, Services) through the Supervisory RCA Agent and Evidence Release Gate.
            </p>
          </div>

          <div className="space-y-3">
            <div className="flex items-center space-x-2">
              <button
                onClick={handleLaunchRun}
                disabled={isLaunching || activeRun?.status === 'running'}
                className="flex-1 flex items-center justify-center space-x-2 py-2.5 px-4 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-lg shadow-indigo-600/30 transition-all disabled:opacity-50"
              >
                <Play className="w-4 h-4 fill-current" />
                <span>
                  {activeRun?.status === 'running'
                    ? 'Investigating Incident...'
                    : 'Execute Multi-Agent Diagnosis'}
                </span>
              </button>

              <button
                onClick={handleReset}
                title="Reset Run"
                className="p-2.5 rounded-lg bg-noc-subpanel hover:bg-noc-hover text-noc-muted hover:text-noc-text border border-noc-border text-xs transition-colors"
              >
                <RotateCcw className="w-4 h-4" />
              </button>
            </div>

            {/* Run Status Ticker */}
            {activeRun && (
              <div className="flex items-center justify-between px-3 py-1.5 rounded-lg bg-noc-subpanel border border-noc-border text-xs font-mono">
                <span className="text-noc-muted">Run Status:</span>
                <span
                  className={`font-semibold capitalize ${
                    activeRun.status === 'completed'
                      ? 'text-noc-green'
                      : activeRun.status === 'running'
                      ? 'text-noc-yellow animate-pulse'
                      : activeRun.status === 'failed'
                      ? 'text-noc-red'
                      : 'text-noc-muted'
                  }`}
                >
                  {activeRun.status}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Main Network Topology Graph Canvas */}
      <div className="space-y-4">
        <TopologyView
          topology={topology}
          selectedNodeId={selectedNode?.id}
          onSelectNode={setSelectedNode}
          rootCauseEntity={report?.suspected_root_cause}
          symptomEntities={
            report ? report.observed_symptom_entities : activeSymptomEntities
          }
          inferredEntities={report ? report.inferred_affected_entities : []}
        />

        {/* Simulation Playback Controls */}
        <PlaybackControls
          currentStep={currentStep}
          totalSteps={timeSteps.length || 15}
          isPlaying={isPlaying}
          speed={playbackSpeed}
          simulatedTime={timeSteps[currentStep - 1] || '2026-10-31 12:00:00 UTC'}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onReset={() => {
            setIsPlaying(false);
            setCurrentStep(0);
          }}
          onStepForward={() => setCurrentStep(prev => Math.min(prev + 1, timeSteps.length || 15))}
          onChangeSpeed={setPlaybackSpeed}
          onSeek={setCurrentStep}
          disabled={timeSteps.length === 0}
        />
        {/* Live Execution Event Feed Ticker */}
        {events.length > 0 && (
          <div className="bg-noc-panel/80 border border-noc-border rounded-xl p-3 text-xs font-mono">
            <div className="flex items-center justify-between mb-2 pb-1 border-b border-noc-border text-noc-muted">
              <span className="flex items-center space-x-1.5 text-noc-cyan">
                <Radio className="w-3.5 h-3.5 animate-pulse" />
                <span>Live Investigation Events</span>
              </span>
              <span>{events.length} events logged</span>
            </div>
            <div className="flex items-center space-x-2 overflow-x-auto py-1">
              {events.slice(-4).map((evt, i) => (
                <div key={i} className="flex-shrink-0 bg-noc-subpanel px-2.5 py-1 rounded border border-noc-border text-[11px] flex items-center space-x-1.5">
                  <span className="text-noc-amethyst font-semibold">{evt.source_component}:</span>
                  <span className="text-noc-text">{evt.event_type}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Bottom Diagnostics Milestone Bar */}
      {report && (
        <div className="bg-gradient-to-r from-noc-panel via-noc-subpanel to-noc-panel border border-noc-border rounded-xl p-5 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center space-x-2">
              <span className="text-xs px-2 py-0.5 rounded font-mono font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">
                GATE CERTIFIED
              </span>
              <span className="text-xs text-noc-muted font-mono">Incident ID: {report.incident_id}</span>
            </div>
            <h3 className="text-sm font-bold text-noc-text">{report.suspected_root_cause}</h3>
            <p className="text-xs text-noc-muted">
              Confidence Score: <strong className="text-noc-cyan">{(report.confidence * 100).toFixed(0)}%</strong> • {report.supporting_evidence.length} Verified Evidence Citations
            </p>
          </div>

          <div className="flex items-center space-x-2">
            <span className="text-xs text-noc-muted font-mono">Direct Symptoms:</span>
            <span className="text-xs font-mono font-medium text-amber-300">
              {report.observed_symptom_entities.join(', ') || 'None (Healthy)'}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
