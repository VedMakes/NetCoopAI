import React, { useState, useEffect, useLayoutEffect, useRef } from 'react';
import {
  AlertCircle, ArrowRight, Check, FileJson, FileText,
  FolderOpen, Info, LoaderCircle, Network, Play, Radio, RotateCcw, Search,
  Sparkles, Upload, X,
} from 'lucide-react';
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
  onOpenIntelligence: () => void;
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
  onOpenIntelligence,
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
  const [scenarioSuite, setScenarioSuite] = useState<'challenge' | 'netcoop' | 'edge'>('challenge');
  const [scenarioSearch, setScenarioSearch] = useState('');
  const [scenarioLoadError, setScenarioLoadError] = useState<string | null>(null);
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
  const [isTelemetryDragActive, setIsTelemetryDragActive] = useState(false);
  const [isTopologyDragActive, setIsTopologyDragActive] = useState(false);
  const activeRunIdRef = useRef<string | null>(activeRun?.run_id ?? null);
  const sessionIdRef = useRef<string | null>(sessionId);
  const topologyRequestIdRef = useRef(0);
  const scenarioTopologyIdRef = useRef<string | null>(null);
  const uploadSectionRef = useRef<HTMLElement>(null);
  const telemetryInputRef = useRef<HTMLInputElement>(null);
  const topologyInputRef = useRef<HTMLInputElement>(null);
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
        if (topologyRequestIdRef.current === requestId) {
          scenarioTopologyIdRef.current = scenarioId;
          setTopology(graph);
        }
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
      if (scenarioTopologyIdRef.current !== activeRun.scenario_id) {
        loadScenarioTopology(activeRun.scenario_id);
      }
    } else if (activeRun) {
      topologyRequestIdRef.current += 1;
      scenarioTopologyIdRef.current = null;
      setTopology(null);
    }
  }, [activeRun?.run_id]);

  // 1. Load available scenarios on mount
  useEffect(() => {
    getScenarios()
      .then(data => {
        setScenarios(data);
        setScenarioLoadError(null);
        if (data.length > 0 && !selectedScenarioId) {
          setSelectedScenarioId(data[0].scenario_id);
        }
      })
      .catch(err => {
        console.error('Failed to load scenarios:', err);
        setScenarioLoadError(err instanceof Error ? err.message : 'Could not load simulation cases');
      });
  }, []);

  // 2. Load topology whenever selected scenario changes (if not running a custom run)
  useEffect(() => {
    if (!activeRun && selectedScenarioId && scenarioTopologyIdRef.current !== selectedScenarioId) {
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
        if (topologyRequestIdRef.current === topologyRequestId) {
          if (activeRun.scenario_id) {
            // Keep the selected fixture's graph shape stable. The run endpoint
            // also adds telemetry-only nodes and links, which made the map
            // appear to jump to a different topology after completion.
            try {
              const scenarioGraph = await getScenarioTopology(activeRun.scenario_id);
              if (cancelled || activeRunIdRef.current !== runId) return;
              scenarioTopologyIdRef.current = activeRun.scenario_id;
              const runNodes = new Map(topologyResult.value.nodes.map((node) => [node.id, node]));
              setTopology({
                ...scenarioGraph,
                nodes: scenarioGraph.nodes.map((node) => ({
                  ...node,
                  status: runNodes.get(node.id)?.status ?? node.status,
                })),
              });
            } catch (error) {
              console.error('Could not reload selected scenario topology after completion:', error);
              // Keep the already displayed scenario graph rather than replacing
              // it with a telemetry-augmented graph if the base fetch fails.
            }
          } else {
            setTopology(topologyResult.value);
          }
        }
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

  const chooseTelemetryFile = (file?: File) => {
    if (!file) return;
    const suffix = file.name.split('.').pop()?.toLowerCase();
    if (!['json', 'jsonl', 'csv', 'log'].includes(suffix || '')) {
      setUploadError('Choose a .json, .jsonl, .csv, or .log file containing JSON Lines.');
      return;
    }
    if (file.size > 20_000_000) {
      setUploadError('Telemetry files must be 20 MB or smaller.');
      return;
    }
    setTelemetryFile(file);
    setUploadError(null);
  };

  const chooseTopologyFile = (file?: File) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.json')) {
      setUploadError('The network map must be a JSON file.');
      return;
    }
    if (file.size > 5_000_000) {
      setUploadError('Topology files must be 5 MB or smaller.');
      return;
    }
    setTopologyFile(file);
    setUploadError(null);
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
      setTelemetryFile(null);
      setTopologyFile(null);
      if (telemetryInputRef.current) telemetryInputRef.current.value = '';
      if (topologyInputRef.current) topologyInputRef.current.value = '';
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
  };

  const chooseScenario = (scenarioId: string) => {
    topologyRequestIdRef.current += 1;
    scenarioTopologyIdRef.current = null;
    setTopology(null);
    setSelectedNode(null);
    setSelectedScenarioId(scenarioId);
    handleReset();
  };

  const selectScenarioSuite = (suite: 'challenge' | 'netcoop' | 'edge') => {
    setScenarioSuite(suite);
    const suiteScenarios = scenarios.filter((scenario) => scenario.suite === suite);
    if (suiteScenarios.length > 0 && !suiteScenarios.some((scenario) => scenario.scenario_id === selectedScenarioId)) {
      chooseScenario(suiteScenarios[0].scenario_id);
    }
  };

  const scenarioGroups = [
    { id: 'challenge' as const, label: 'Challenge suite', caption: 'Provided cases' },
    { id: 'netcoop' as const, label: 'NetCoop regression', caption: '3 seeds per fault' },
    { id: 'edge' as const, label: 'Edge cases', caption: 'Ambiguous & messy' },
  ];
  const groupCount = (suite: 'challenge' | 'netcoop' | 'edge') => scenarios.filter((item) => item.suite === suite).length;
  const visibleScenarios = scenarios
    .filter((item) => item.suite === scenarioSuite)
    .filter((item) => `${item.name} ${item.category} ${item.description}`.toLowerCase().includes(scenarioSearch.toLowerCase()));
  const selectedScenario = scenarios.find((item) => item.scenario_id === selectedScenarioId);
  const readableSize = (size: number) => size >= 1_000_000 ? `${(size / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(size / 1_000))} KB`;

  return (
    <div className="mx-auto max-w-[1500px] space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <section className="relative overflow-hidden rounded-[28px] border border-noc-border bg-[linear-gradient(115deg,rgba(30,24,45,0.98),rgba(18,22,36,0.94)_55%,rgba(23,34,43,0.96))] p-6 shadow-panel sm:p-8">
        <div className="pointer-events-none absolute -right-8 -top-24 h-64 w-64 rounded-full bg-noc-amethyst/10 blur-3xl" />
          <div className="relative flex flex-col justify-between gap-6 lg:flex-row lg:items-end">
          <div className="max-w-2xl">
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-noc-amethyst/25 bg-noc-amethyst/10 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-noc-amethyst"><Sparkles className="h-3.5 w-3.5" />NetCoop investigation workspace</div>
            <h1 className="text-2xl font-semibold tracking-tight text-noc-text sm:text-3xl">Investigate a network</h1>
            <p className="mt-2 max-w-xl text-sm leading-6 text-noc-muted">Choose a known case or bring your own capture. NetCoop will analyze the evidence, then show what it found and where.</p>
            <button type="button" onClick={() => uploadSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })} className="mt-4 inline-flex items-center gap-2 rounded-xl border border-noc-amethyst/30 bg-noc-amethyst/10 px-3.5 py-2.5 text-[11px] font-medium text-noc-amethyst transition hover:bg-noc-amethyst/15"><Upload className="h-3.5 w-3.5" />Upload my own data</button>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[11px]">
            {[
              ['01', 'Choose data'], ['02', 'Run analysis'], ['03', 'Review evidence'],
            ].map(([number, label], index) => <div key={number} className="flex items-center gap-2">
              <span className={`flex h-7 w-7 items-center justify-center rounded-full border font-mono ${index === 0 ? 'border-noc-amethyst/50 bg-noc-amethyst/15 text-noc-amethyst' : 'border-noc-border bg-noc-bg/50 text-noc-muted'}`}>{number}</span>
              <span className={index === 0 ? 'text-noc-text' : 'text-noc-muted'}>{label}</span>
              {index < 2 && <ArrowRight className="mx-1 h-3.5 w-3.5 text-noc-border" />}
            </div>)}
          </div>
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.75fr)]">
        <section className="rounded-2xl border border-noc-border bg-noc-panel/80 p-5 shadow-panel sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-noc-amethyst">Step 1 · Pick a simulation</p>
              <h2 className="mt-1 text-base font-semibold text-noc-text">Start with a known case</h2>
              <p className="mt-1 text-xs text-noc-muted">The challenge suite has 7 provided cases; the NetCoop suite has 21 seed-based regression cases.</p>
            </div>
            <div className="rounded-xl border border-noc-border bg-noc-bg/70 px-3 py-2 text-right">
              <span className="block font-mono text-lg font-semibold text-noc-text">{scenarios.length}</span>
              <span className="text-[9px] uppercase tracking-wider text-noc-muted">runnable cases</span>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap gap-2" role="tablist" aria-label="Simulation case suites">
            {scenarioGroups.map((group) => {
              const selected = scenarioSuite === group.id;
              return <button key={group.id} type="button" role="tab" aria-selected={selected} disabled={runInProgress} onClick={() => selectScenarioSuite(group.id)} className={`rounded-xl border px-3.5 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${selected ? 'border-noc-amethyst/45 bg-noc-amethyst/10 text-noc-text' : 'border-noc-border bg-noc-bg/40 text-noc-muted hover:bg-noc-subpanel hover:text-noc-text'}`}>
                <span className="flex items-center gap-2 text-xs font-medium">{group.label}<span className={`rounded-full px-1.5 py-0.5 font-mono text-[9px] ${selected ? 'bg-noc-amethyst/15 text-noc-amethyst' : 'bg-noc-subpanel text-noc-muted'}`}>{groupCount(group.id)}</span></span>
                <span className="mt-0.5 block text-[9px] text-noc-muted">{group.caption}</span>
              </button>;
            })}
          </div>

          <label className="relative mt-4 block">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-noc-muted" />
            <input value={scenarioSearch} onChange={(event) => setScenarioSearch(event.target.value)} placeholder="Find a case by fault, seed, or symptom" aria-label="Search simulation cases" className="w-full rounded-xl border border-noc-border bg-noc-bg/70 py-2.5 pl-9 pr-3 text-xs text-noc-text outline-none placeholder:text-noc-muted/70 focus:border-noc-amethyst/60 focus:ring-2 focus:ring-noc-amethyst/10" />
          </label>

          {scenarioLoadError && <p role="alert" className="mt-3 flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-950/20 px-3 py-2 text-xs text-red-300"><AlertCircle className="h-4 w-4" />{scenarioLoadError}</p>}
          <div className="mt-3 grid max-h-[370px] grid-cols-1 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
            {visibleScenarios.map((scenario) => {
              const selected = selectedScenarioId === scenario.scenario_id;
              return <button key={scenario.scenario_id} type="button" disabled={runInProgress} onClick={() => chooseScenario(scenario.scenario_id)} className={`group rounded-xl border p-3.5 text-left transition-all disabled:cursor-not-allowed disabled:opacity-50 ${selected ? 'border-noc-amethyst/50 bg-noc-amethyst/[0.08] shadow-[0_0_24px_rgba(199,167,239,0.08)]' : 'border-noc-border bg-noc-bg/35 hover:border-noc-border/90 hover:bg-noc-subpanel/80'}`}>
                <div className="flex items-start justify-between gap-3"><div className="min-w-0"><span className="text-[9px] font-semibold uppercase tracking-[0.13em] text-noc-muted">{scenario.category}</span><h3 className={`mt-1 text-xs font-semibold ${selected ? 'text-noc-amethyst' : 'text-noc-text'}`}>{scenario.name}</h3></div>{selected ? <span className="mt-1 rounded-full bg-noc-amethyst/15 p-1 text-noc-amethyst"><Check className="h-3.5 w-3.5" /></span> : <ArrowRight className="mt-1 h-3.5 w-3.5 text-noc-muted opacity-0 transition-opacity group-hover:opacity-100" />}</div>
                <p className="mt-2 line-clamp-2 text-[10px] leading-4 text-noc-muted">{scenario.description}</p>
              </button>;
            })}
            {visibleScenarios.length === 0 && !scenarioLoadError && <div className="col-span-full rounded-xl border border-dashed border-noc-border px-4 py-8 text-center text-xs text-noc-muted">No cases match that search in this suite.</div>}
          </div>
          {selectedScenario && <div className="mt-3 flex flex-col gap-2 rounded-xl border border-noc-border/80 bg-noc-subpanel/50 px-3.5 py-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="min-w-0 text-[11px] leading-5 text-noc-muted"><span className="font-medium text-noc-text">Selected:</span> {selectedScenario.name} <span className="mx-1 text-noc-border">·</span>{selectedScenario.symptoms_summary}</p>
            <span className={`shrink-0 rounded-full px-2 py-1 text-[9px] font-medium ${scenarioSuite === 'edge' ? 'bg-noc-yellow/10 text-noc-yellow' : 'bg-noc-green/10 text-noc-green'}`}>{scenarioSuite === 'edge' ? 'Diagnostic case · no score target' : 'Ground-truth evaluation available'}</span>
          </div>}
        </section>

        <section className="flex flex-col rounded-2xl border border-noc-border bg-noc-panel/80 p-5 shadow-panel sm:p-6">
          <div><p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-noc-amethyst">Step 2 · Configure</p><h2 className="mt-1 text-base font-semibold text-noc-text">Run the investigation</h2><p className="mt-1 text-xs leading-5 text-noc-muted">All four specialist towers see the normalized capture. The evidence gate checks the final proposal.</p></div>
          <div className="mt-4 rounded-xl border border-noc-border bg-noc-bg/45 p-3.5"><div className="flex items-center justify-between gap-3"><div><span className="text-[10px] font-semibold uppercase tracking-wider text-noc-muted">Model assistance</span><p className="mt-1 text-[10px] text-noc-muted">{llmMode === 'off' ? 'Deterministic, no model calls' : llmMode === 'auto' ? 'Use a model when configured' : 'Require a configured model'}</p></div><div className="flex rounded-lg border border-noc-border bg-noc-bg p-1" role="group" aria-label="Model assistance mode">{(['off', 'auto', 'on'] as const).map((mode) => <button key={mode} type="button" aria-pressed={llmMode === mode} onClick={() => setLlmMode(mode)} className={`rounded-md px-2.5 py-1.5 text-[9px] font-semibold uppercase tracking-wider transition-colors ${llmMode === mode ? 'bg-noc-amethyst/20 text-noc-amethyst' : 'text-noc-muted hover:text-noc-text'}`}>{mode}</button>)}</div></div></div>
          <label className="mt-4 block space-y-1.5"><span className="text-[10px] font-semibold uppercase tracking-wider text-noc-muted">Optional symptom chat</span><input type="text" maxLength={2000} value={callerSymptom} onChange={(event) => setCallerSymptom(event.target.value)} disabled={runInProgress} placeholder="e.g. Wi-Fi drops in the second-floor meeting rooms" className="w-full rounded-xl border border-noc-border bg-noc-bg/60 px-3 py-2.5 text-xs text-noc-text outline-none placeholder:text-noc-muted/70 focus:border-noc-amethyst/60 focus:ring-2 focus:ring-noc-amethyst/10 disabled:opacity-50" /><span className="block text-[10px] leading-4 text-noc-muted">Reviewed after diagnosis by the LLM and shown in session chat. It does not steer the diagnosis. If LLM inference is unavailable, the review is marked unavailable.</span></label>
          <div className="mt-auto pt-5"><button type="button" onClick={handleLaunchRun} disabled={!selectedScenarioId || !sessionId || runInProgress} className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-[#7953a6] to-[#8f65b2] px-4 py-3 text-xs font-semibold text-white shadow-[0_8px_24px_rgba(121,83,166,0.2)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-45">{runInProgress ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-current" />}{activeRun?.status === 'queued' || activeRun?.status === 'running' ? 'Analysis in progress' : 'Run selected case'}</button>
            <div className="mt-3 flex items-center justify-between gap-3 text-[10px] text-noc-muted">{activeRun ? <span className="flex items-center gap-1.5"><i className={`h-1.5 w-1.5 rounded-full ${activeRun.status === 'completed' ? 'bg-noc-green' : activeRun.status === 'failed' ? 'bg-noc-red' : 'animate-pulse bg-noc-yellow'}`} />Latest run: {activeRun.status}</span> : <span>Results attach to the selected session</span>}<button type="button" onClick={handleReset} disabled={runInProgress} className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-noc-muted hover:bg-noc-subpanel hover:text-noc-text disabled:opacity-40"><RotateCcw className="h-3 w-3" />Reset</button></div>
            {(activeRun?.status === 'failed' || runError) && <p role="alert" className="mt-3 flex items-start gap-2 rounded-xl border border-red-500/35 bg-red-950/20 px-3 py-2.5 text-[11px] text-red-300"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{activeRun?.error || runError}</p>}
          </div>
        </section>
      </div>

      <section ref={uploadSectionRef} tabIndex={-1} aria-labelledby="upload-title" className="scroll-mt-5 rounded-2xl border border-noc-amethyst/20 bg-[linear-gradient(115deg,rgba(24,24,38,0.94),rgba(17,24,34,0.94))] p-5 shadow-panel focus:outline-none focus:ring-2 focus:ring-noc-amethyst/40 sm:p-6">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start"><div className="max-w-2xl"><p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-noc-amethyst">Or bring your own capture</p><h2 id="upload-title" className="mt-1 text-base font-semibold text-noc-text">Analyze your network data</h2><p className="mt-1 text-xs leading-5 text-noc-muted">Telemetry is required. A topology map is optional, but helps NetCoop identify affected segments. Your chat messages are never treated as uploaded data.</p></div><span className="inline-flex items-center gap-1.5 self-start rounded-full border border-noc-border bg-noc-bg/50 px-2.5 py-1.5 text-[9px] text-noc-muted"><Info className="h-3 w-3 text-noc-amethyst" />Local session · max 20 MB telemetry</span></div>
        <div className="mt-5 grid gap-3 lg:grid-cols-2">
          <input ref={telemetryInputRef} type="file" accept=".json,.jsonl,.csv,.log" className="hidden" onChange={(event) => { chooseTelemetryFile(event.target.files?.[0]); event.currentTarget.value = ''; }} />
          <div onDragEnter={(event) => { event.preventDefault(); setIsTelemetryDragActive(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setIsTelemetryDragActive(false); }} onDrop={(event) => { event.preventDefault(); setIsTelemetryDragActive(false); chooseTelemetryFile(event.dataTransfer.files[0]); }} className={`rounded-2xl border border-dashed p-4 transition-colors ${isTelemetryDragActive ? 'border-noc-amethyst bg-noc-amethyst/10' : 'border-noc-border bg-noc-bg/35 hover:border-noc-amethyst/40'}`}>
            <div className="flex items-start gap-3"><div className="rounded-xl bg-noc-amethyst/10 p-2.5 text-noc-amethyst"><FileText className="h-5 w-5" /></div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="text-xs font-semibold text-noc-text">Telemetry capture <span className="text-noc-red">· required</span></h3><span className="rounded bg-noc-subpanel px-1.5 py-0.5 text-[9px] text-noc-muted">JSON · JSONL · CSV · LOG</span></div>
              {telemetryFile ? <div className="mt-2 flex items-center justify-between gap-3 rounded-lg border border-noc-border bg-noc-panel/70 px-2.5 py-2"><div className="flex min-w-0 items-center gap-2"><FileJson className="h-4 w-4 shrink-0 text-noc-green" /><div className="min-w-0"><p className="truncate text-[11px] text-noc-text">{telemetryFile.name}</p><p className="text-[9px] text-noc-muted">{readableSize(telemetryFile.size)}</p></div></div><button aria-label="Remove telemetry file" onClick={() => { setTelemetryFile(null); if (telemetryInputRef.current) telemetryInputRef.current.value = ''; }} className="rounded p-1 text-noc-muted hover:bg-noc-hover hover:text-noc-text"><X className="h-3.5 w-3.5" /></button></div> : <><p className="mt-1 text-[10px] text-noc-muted">Drop a file here, or choose it from your device. Limit 20 MB.</p><button type="button" onClick={() => telemetryInputRef.current?.click()} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-noc-border bg-noc-subpanel px-3 py-2 text-[10px] font-medium text-noc-text hover:border-noc-amethyst/40 hover:bg-noc-hover"><FolderOpen className="h-3.5 w-3.5 text-noc-amethyst" />Choose telemetry file</button></>}
            </div></div>
          </div>

          <input ref={topologyInputRef} type="file" accept=".json,application/json" className="hidden" onChange={(event) => { chooseTopologyFile(event.target.files?.[0]); event.currentTarget.value = ''; }} />
          <div onDragEnter={(event) => { event.preventDefault(); setIsTopologyDragActive(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setIsTopologyDragActive(false); }} onDrop={(event) => { event.preventDefault(); setIsTopologyDragActive(false); chooseTopologyFile(event.dataTransfer.files[0]); }} className={`rounded-2xl border border-dashed p-4 transition-colors ${isTopologyDragActive ? 'border-noc-cyan bg-noc-cyan/10' : 'border-noc-border bg-noc-bg/35 hover:border-noc-cyan/40'}`}>
            <div className="flex items-start gap-3"><div className="rounded-xl bg-noc-cyan/10 p-2.5 text-noc-cyan"><Network className="h-5 w-5" /></div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="text-xs font-semibold text-noc-text">Topology map <span className="text-noc-muted">· optional</span></h3><span className="rounded bg-noc-subpanel px-1.5 py-0.5 text-[9px] text-noc-muted">JSON · max 5 MB</span></div>
              {topologyFile ? <div className="mt-2 flex items-center justify-between gap-3 rounded-lg border border-noc-border bg-noc-panel/70 px-2.5 py-2"><div className="flex min-w-0 items-center gap-2"><Network className="h-4 w-4 shrink-0 text-noc-cyan" /><div className="min-w-0"><p className="truncate text-[11px] text-noc-text">{topologyFile.name}</p><p className="text-[9px] text-noc-muted">{readableSize(topologyFile.size)}</p></div></div><button aria-label="Remove topology map" onClick={() => { setTopologyFile(null); if (topologyInputRef.current) topologyInputRef.current.value = ''; }} className="rounded p-1 text-noc-muted hover:bg-noc-hover hover:text-noc-text"><X className="h-3.5 w-3.5" /></button></div> : <><p className="mt-1 text-[10px] text-noc-muted">Attach a site map to improve segment and downstream impact estimates.</p><button type="button" onClick={() => topologyInputRef.current?.click()} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-noc-border bg-noc-subpanel px-3 py-2 text-[10px] font-medium text-noc-text hover:border-noc-cyan/40 hover:bg-noc-hover"><FolderOpen className="h-3.5 w-3.5 text-noc-cyan" />Choose topology JSON</button></>}
            </div></div>
          </div>
        </div>
        {uploadError && <p role="alert" className="mt-3 flex items-center gap-2 rounded-lg border border-red-500/35 bg-red-950/20 px-3 py-2 text-[11px] text-red-300"><AlertCircle className="h-4 w-4" />{uploadError}</p>}
        <div className="mt-4 flex flex-col justify-between gap-3 border-t border-noc-border/70 pt-4 sm:flex-row sm:items-center"><p className="text-[10px] leading-4 text-noc-muted">A JSON topology should contain nodes and links. NetCoop reports when the map is incomplete or cannot support an impact estimate.</p><button type="button" onClick={handleUploadRun} disabled={!telemetryFile || !sessionId || runInProgress} className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-noc-amethyst px-4 py-2.5 text-xs font-semibold text-[#18121f] shadow-[0_6px_20px_rgba(199,167,239,0.18)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40">{isLaunching ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}{isLaunching ? 'Preparing analysis…' : 'Analyze uploaded capture'}</button></div>
      </section>

      <div className="space-y-4">
        <TopologyView topology={topology} layoutKey={topology?.topology_id ?? selectedScenarioId} selectedNodeId={selectedNode?.id} onSelectNode={setSelectedNode} symptomEntities={report?.observed_symptom_entities ?? []} inferredEntities={report?.inferred_affected_entities ?? []} />
        <PlaybackControls currentStep={currentStep} totalSteps={timeSteps.length || 15} isPlaying={isPlaying} speed={playbackSpeed} simulatedTime={timeSteps[currentStep - 1] || 'No timeline loaded'} onPlay={() => setIsPlaying(true)} onPause={() => setIsPlaying(false)} onReset={() => { setIsPlaying(false); setCurrentStep(0); }} onStepForward={() => setCurrentStep((prev) => Math.min(prev + 1, timeSteps.length || 15))} onChangeSpeed={setPlaybackSpeed} onSeek={setCurrentStep} disabled={timeSteps.length === 0} />
        {events.length > 0 && <section className="rounded-2xl border border-noc-border bg-noc-panel/70 p-4"><div className="flex items-center justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-noc-amethyst">Investigation activity</p><h3 className="mt-1 text-xs font-semibold text-noc-text">What NetCoop has done</h3></div><span className="rounded-full border border-noc-border bg-noc-bg/60 px-2.5 py-1 font-mono text-[9px] text-noc-muted">{events.length} events</span></div><div className="mt-3 flex gap-2 overflow-x-auto pb-1">{events.slice(-8).map((event) => <div key={event.event_id} className="min-w-[150px] rounded-xl border border-noc-border bg-noc-bg/45 px-3 py-2"><span className="flex items-center gap-1.5 text-[9px] font-medium text-noc-amethyst"><Radio className="h-3 w-3" />{event.source_component}</span><p className="mt-1 text-[10px] text-noc-text">{event.event_type.replace(/[._]/g, ' ')}</p></div>)}</div></section>}
      </div>

      {report && <section className="rounded-2xl border border-noc-border bg-noc-panel/80 p-5 shadow-panel sm:p-6"><div className="flex flex-col justify-between gap-4 md:flex-row md:items-center"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className={`rounded-full border px-2.5 py-1 text-[9px] font-semibold uppercase tracking-wider ${report.status === 'diagnosed' ? 'border-noc-green/30 bg-noc-green/10 text-noc-green' : 'border-noc-yellow/30 bg-noc-yellow/10 text-noc-yellow'}`}>{report.status === 'diagnosed' ? 'Evidence gate passed' : 'Evidence limited'}</span><span className="font-mono text-[10px] text-noc-muted">{report.incident_id}</span></div><h3 className="mt-2 truncate text-sm font-semibold text-noc-text">{report.suspected_root_cause}</h3><p className="mt-1 text-[11px] text-noc-muted">{(report.confidence * 100).toFixed(0)}% confidence · {report.supporting_evidence.length} cited evidence items</p></div><div className="rounded-xl border border-noc-border bg-noc-bg/45 px-4 py-3 md:max-w-[40%]"><span className="text-[9px] font-semibold uppercase tracking-wider text-noc-muted">Observed symptom entities</span><p className="mt-1 break-words text-xs text-noc-yellow">{report.observed_symptom_entities.join(', ') || 'No explicit symptom entities observed'}</p></div><button type="button" onClick={onOpenIntelligence} className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-noc-subpanel px-4 py-2.5 text-[11px] font-medium text-noc-text transition hover:bg-noc-hover">Review evidence and agent trace <ArrowRight className="h-3.5 w-3.5" /></button></div></section>}
    </div>
  );
};
