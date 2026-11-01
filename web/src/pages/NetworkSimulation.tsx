import React, { useState, useEffect, useLayoutEffect, useRef } from 'react';
import { Play, RotateCcw, Activity, Cpu, Server, Radio } from 'lucide-react';
import {
  ExecutionEvent,
  FinalReport,
  RunStatusResponse,
  ScenarioSummary,
  TopologyGraph,
  TopologyNode,
} from '../types';
import {
  createRun,
  createUploadedRun,
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
  onRunStarted: (openChatAfterRun: boolean) => void;
  onRunCleared: () => void;
  onRunCreated: (run: RunStatusResponse) => void;
  sessionId: string | null;
  isLoadingSelection: boolean;
  uploadFocusRequestId: number;
  activeRun: RunStatusResponse | null;
  setActiveRun: (run: RunStatusResponse | null) => void;
}

export const NetworkSimulation: React.FC<NetworkSimulationProps> = ({
  onRunCompleted,
  onRunStarted,
  onRunCleared,
  onRunCreated,
  sessionId,
  isLoadingSelection,
  uploadFocusRequestId,
  activeRun,
  setActiveRun,
}) => {
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>('link_congestion');
  const [llmMode, setLlmMode] = useState<'off' | 'auto' | 'on'>('off');
  const [callerSymptom, setCallerSymptom] = useState('');
  const [topology, setTopology] = useState<TopologyGraph | null>(null);
  const [selectedNode, setSelectedNode] = useState<TopologyNode | null>(null);

  // Playback state
  const [timeSteps, setTimeSteps] = useState<string[]>([]);
  const [currentStep, setCurrentStep] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1);

  // Diagnostic execution state
  const [isLaunching, setIsLaunching] = useState<boolean>(false);
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [report, setReport] = useState<FinalReport | null>(null);
  const [telemetryFile, setTelemetryFile] = useState<File | null>(null);
  const [topologyFile, setTopologyFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const activeRunIdRef = useRef<string | null>(activeRun?.run_id ?? null);
  const sessionIdRef = useRef<string | null>(sessionId);
  const topologyRequestIdRef = useRef(0);
  const uploadSectionRef = useRef<HTMLElement>(null);
  const runInProgress = isLaunching || isLoadingSelection || activeRun?.status === 'queued' || activeRun?.status === 'running';

  useEffect(() => {
    if (uploadFocusRequestId > 0) {
      uploadSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      uploadSectionRef.current?.focus({ preventScroll: true });
    }
  }, [uploadFocusRequestId]);

  const loadScenarioTopology = (scenarioId: string) => {
    const requestId = ++topologyRequestIdRef.current;
    getScenarioTopology(scenarioId)
      .then((graph) => {
        if (topologyRequestIdRef.current === requestId) setTopology(graph);
      })
      .catch((err) => {
        if (topologyRequestIdRef.current === requestId) {
          console.error('Failed to load scenario topology:', err);
        }
      });
  };

  useLayoutEffect(() => {
    activeRunIdRef.current = activeRun?.run_id ?? null;
  }, [activeRun?.run_id]);

  useLayoutEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    setReport(null);
    setEvents([]);
    setTimeSteps([]);
    setCurrentStep(0);
    setIsPlaying(false);
    setSelectedNode(null);
    if (activeRun?.scenario_id) {
      loadScenarioTopology(activeRun.scenario_id);
    } else if (activeRun) {
      topologyRequestIdRef.current += 1;
      setTopology(null);
    } else if (selectedScenarioId) {
      loadScenarioTopology(selectedScenarioId);
    }
  }, [activeRun?.run_id]);

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
    if (!activeRun && selectedScenarioId) {
      loadScenarioTopology(selectedScenarioId);
    }
  }, [selectedScenarioId, activeRun?.run_id]);

  // 3. Polling / Event streaming when active run is running
  useEffect(() => {
    if (!activeRun || activeRun.status === 'completed' || activeRun.status === 'failed') return;
    const runId = activeRun.run_id;

    const interval = setInterval(async () => {
      try {
        const st = await getRunStatus(runId);
        if (activeRunIdRef.current !== runId) return;
        setActiveRun(st);

        // Fetch events
        const evts = await getRunEvents(runId);
        if (activeRunIdRef.current !== runId) return;
        setEvents(evts);

        if (st.status === 'completed') {
          clearInterval(interval);
          return;
        }
      } catch (err) {
        console.error('Error polling run:', err);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [activeRun?.run_id, activeRun?.status]);

  useEffect(() => {
    if (!activeRun || activeRun.status !== 'completed') return;
    const runId = activeRun.run_id;
    const incidentId = activeRun.incident_id;
    const topologyRequestId = ++topologyRequestIdRef.current;
    let cancelled = false;
    const loadCompletedArtifacts = async () => {
      const [reportResult, topologyResult, telemetryResult] = await Promise.allSettled([
          getRunReport(runId),
          getRunTopology(runId),
          getRunTelemetry(runId),
      ]);
      if (cancelled || activeRunIdRef.current !== runId) return;

      if (reportResult.status === 'fulfilled') {
        setReport(reportResult.value);
        onRunCompleted(runId, incidentId, reportResult.value);
      } else {
        console.error('Could not load completed run report:', reportResult.reason);
      }
      if (topologyResult.status === 'fulfilled') {
        if (topologyRequestIdRef.current === topologyRequestId) setTopology(topologyResult.value);
      } else {
        console.error('Could not load completed run topology:', topologyResult.reason);
        if (activeRun.scenario_id) loadScenarioTopology(activeRun.scenario_id);
      }
      if (telemetryResult.status === 'fulfilled') {
        const distinctTimes = Array.from(new Set(telemetryResult.value.observations.map((o) => o.timestamp))).sort();
        setTimeSteps(distinctTimes);
        setCurrentStep(distinctTimes.length);
      } else {
        console.error('Could not load completed run telemetry:', telemetryResult.reason);
      }
    };
    void loadCompletedArtifacts();
    return () => { cancelled = true; };
  }, [activeRun?.run_id, activeRun?.status]);

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
    if (!selectedScenarioId || !sessionId || runInProgress) return;
    const requestedSessionId = sessionId;
    const requestedSymptom = callerSymptom.trim();

    prepareNewRun(Boolean(requestedSymptom));

    try {
      const run = await createRun({
        scenario_id: selectedScenarioId,
        session_id: requestedSessionId,
        llm: llmMode,
        ...(requestedSymptom ? { symptom_chat: requestedSymptom } : {}),
      });
      if (requestedSymptom) setCallerSymptom('');
      onRunCreated(run);
      if (sessionIdRef.current === requestedSessionId) {
        activeRunIdRef.current = run.run_id;
        setActiveRun(run);
      }
    } catch (err: any) {
      setRunError(`Failed to launch run: ${err.message || 'Unknown error'}`);
    } finally {
      setIsLaunching(false);
    }
  };

  const prepareNewRun = (openChatAfterRun = false) => {
    activeRunIdRef.current = null;
    onRunStarted(openChatAfterRun);
    setActiveRun(null);
    setIsLaunching(true);
    setEvents([]);
    setReport(null);
    setTimeSteps([]);
    setCurrentStep(0);
    setIsPlaying(false);
    setSelectedNode(null);
    setUploadError(null);
    setRunError(null);
  };

  const handleUploadRun = async () => {
    if (!telemetryFile || !sessionId || runInProgress) return;
    const requestedSessionId = sessionId;
    const requestedSymptom = callerSymptom.trim();
    const telemetrySuffix = telemetryFile.name.split('.').pop()?.toLowerCase();
    if (!['json', 'jsonl', 'csv', 'log'].includes(telemetrySuffix || '')) {
      setUploadError('Choose a .json, .jsonl, .csv, or .log telemetry file.');
      return;
    }
    if (telemetryFile.size > 20_000_000) {
      setUploadError('Telemetry files must be 20 MB or smaller.');
      return;
    }
    if (topologyFile && (!topologyFile.name.toLowerCase().endsWith('.json') || topologyFile.size > 5_000_000)) {
      setUploadError('The optional topology must be a JSON file no larger than 5 MB.');
      return;
    }

    prepareNewRun(Boolean(requestedSymptom));
    try {
      const request = {
        telemetry_filename: telemetryFile.name,
        telemetry_content: await telemetryFile.text(),
        ...(topologyFile
          ? { topology_filename: topologyFile.name, topology_content: await topologyFile.text() }
          : {}),
        session_id: requestedSessionId,
        llm: llmMode,
        ...(requestedSymptom ? { symptom_chat: requestedSymptom } : {}),
      };
      const run = await createUploadedRun(request);
      if (requestedSymptom) setCallerSymptom('');
      onRunCreated(run);
      if (sessionIdRef.current === requestedSessionId) {
        activeRunIdRef.current = run.run_id;
        setActiveRun(run);
      }
    } catch (err: any) {
      setUploadError(`Upload failed: ${err.message || 'Unknown error'}`);
    } finally {
      setIsLaunching(false);
    }
  };

  const handleReset = () => {
    activeRunIdRef.current = null;
    onRunCleared();
    setActiveRun(null);
    setReport(null);
    setEvents([]);
    setTimeSteps([]);
    setCurrentStep(0);
    setIsPlaying(false);
    setSelectedNode(null);
    setUploadError(null);
    setRunError(null);
    if (selectedScenarioId) loadScenarioTopology(selectedScenarioId);
  };

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
                disabled={runInProgress}
                onClick={() => {
                  setSelectedScenarioId(sc.scenario_id);
                  handleReset();
                }}
                className={`p-2.5 rounded-lg text-left transition-all border disabled:cursor-not-allowed disabled:opacity-50 ${
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
            <label className="mb-4 block space-y-1.5 text-xs text-noc-muted">
              <span>Optional symptom chat</span>
              <input
                type="text"
                maxLength={2000}
                value={callerSymptom}
                onChange={(event) => setCallerSymptom(event.target.value)}
                disabled={runInProgress}
                placeholder="e.g. Wi-Fi drops in the second-floor meeting rooms"
                className="w-full rounded-md border border-noc-border bg-noc-subpanel px-3 py-2 text-xs text-noc-text placeholder-noc-muted disabled:opacity-50"
              />
              <span className="block text-[10px] leading-relaxed">Adds a post-diagnosis symptom review and opens session chat after the run. It does not steer or change the diagnosis.</span>
            </label>
          </div>

          <div className="space-y-3">
            <div className="flex items-center space-x-2">
              <button
                onClick={handleLaunchRun}
                disabled={!sessionId || runInProgress}
                className="flex-1 flex items-center justify-center space-x-2 py-2.5 px-4 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-lg shadow-indigo-600/30 transition-all disabled:opacity-50"
              >
                <Play className="w-4 h-4 fill-current" />
                <span>
                  {activeRun?.status === 'queued' || activeRun?.status === 'running'
                    ? 'Investigating Incident...'
                    : 'Execute Multi-Agent Diagnosis'}
                </span>
              </button>

              <button
                onClick={handleReset}
                disabled={runInProgress}
                title="Reset Run"
                className="p-2.5 rounded-lg bg-noc-subpanel hover:bg-noc-hover text-noc-muted hover:text-noc-text border border-noc-border text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50"
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
            {activeRun?.status === 'failed' && (
              <p role="alert" className="rounded border border-red-500/40 bg-red-950/30 px-3 py-2 text-xs text-red-300">
                {activeRun.error || 'The investigation failed. Start a new run after checking the capture.'}
              </p>
            )}
            {runError && <p role="alert" className="rounded border border-red-500/40 bg-red-950/30 px-3 py-2 text-xs text-red-300">{runError}</p>}
          </div>
        </div>
      </div>

      <section
        ref={uploadSectionRef}
        tabIndex={-1}
        aria-labelledby="capture-upload-heading"
        className="bg-noc-panel border border-noc-border rounded-xl p-5 shadow-lg space-y-3 focus:outline-none focus:ring-2 focus:ring-noc-amethyst/60"
      >
        <div>
          <h2 id="capture-upload-heading" className="text-sm font-bold text-noc-text">Add Telemetry & Run a New Analysis</h2>
          <p className="mt-1 text-xs text-noc-muted">Choose a telemetry export and optionally a separate network map. Files are stored in this local NetCoop instance for the investigation session.</p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
          <label className="block space-y-1.5 text-xs text-noc-muted">
            <span>Telemetry (.json, .jsonl, .csv, or JSON Lines in .log)</span>
            <input type="file" accept=".json,.jsonl,.csv,.log" onChange={(event) => setTelemetryFile(event.target.files?.[0] ?? null)} className="block w-full text-xs file:mr-3 file:rounded-md file:border-0 file:bg-indigo-600 file:px-3 file:py-2 file:text-white" />
          </label>
          <label className="block space-y-1.5 text-xs text-noc-muted">
            <span>Optional topology (.json)</span>
            <input type="file" accept=".json" onChange={(event) => setTopologyFile(event.target.files?.[0] ?? null)} className="block w-full text-xs file:mr-3 file:rounded-md file:border-0 file:bg-noc-subpanel file:px-3 file:py-2 file:text-noc-text" />
          </label>
          <button onClick={handleUploadRun} disabled={!telemetryFile || !sessionId || runInProgress} className="rounded-lg bg-noc-amethyst px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-40">
            {isLaunching ? 'Starting investigation…' : 'Run on uploaded data'}
          </button>
        </div>
        {uploadError && <p role="alert" className="text-xs text-red-300">{uploadError}</p>}
      </section>

      {/* Main Network Topology Graph Canvas */}
      <div className="space-y-4">
        <TopologyView
          topology={topology}
          selectedNodeId={selectedNode?.id}
          onSelectNode={setSelectedNode}
          symptomEntities={report?.observed_symptom_entities ?? []}
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
