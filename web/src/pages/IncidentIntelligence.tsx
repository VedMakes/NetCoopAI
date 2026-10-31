import React, { useState, useEffect } from 'react';
import {
  FinalReport,
  RunStatusResponse,
  TelemetryResponse,
  TowerReportSummary,
  ExecutionEvent,
  DiagnosticTask,
  GateResultDetail,
  EvaluationResponse,
} from '../types';
import {
  getRunTelemetry,
  getRunFindings,
  getRunEvents,
  getRunTasks,
  getRunGate,
  getRunEvaluation,
  getRunReport,
} from '../api';
import { TelemetryCharts } from '../components/TelemetryCharts';
import { EvidenceInspector } from '../components/EvidenceInspector';
import { TowerFindingsCard } from '../components/TowerFindingsCard';
import { EvidenceGateCard } from '../components/EvidenceGateCard';
import { FabricActivityLog } from '../components/FabricActivityLog';
import { DisputeResolutionCard } from '../components/DisputeResolutionCard';
import { FinalReportView } from '../components/FinalReportView';
import { EvaluationCard } from '../components/EvaluationCard';
import {
  FileText,
  Layers,
  Activity,
  Network,
  Award,
  RefreshCw,
  AlertCircle,
} from 'lucide-react';

interface IncidentIntelligenceProps {
  activeRun: RunStatusResponse | null;
  report: FinalReport | null;
}

export const IncidentIntelligence: React.FC<IncidentIntelligenceProps> = ({
  activeRun,
  report: initialReport,
}) => {
  const [report, setReport] = useState<FinalReport | null>(initialReport);
  const [telemetry, setTelemetry] = useState<TelemetryResponse | null>(null);
  const [towers, setTowers] = useState<TowerReportSummary[]>([]);
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [tasks, setTasks] = useState<DiagnosticTask[]>([]);
  const [gate, setGate] = useState<GateResultDetail | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationResponse | null>(null);

  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [activeSubTab, setActiveSubTab] = useState<
    'overview' | 'towers' | 'evidence' | 'fabric' | 'evaluation'
  >('overview');

  // Load all artifacts for active run
  const loadArtifacts = async (runId: string) => {
    setLoading(true);
    setError(null);
    try {
      // 1. Report
      let currentReport = report;
      if (!currentReport) {
        try {
          currentReport = await getRunReport(runId);
          setReport(currentReport);
        } catch {
          // Report might be pending
        }
      }

      // 2. Telemetry
      try {
        const telem = await getRunTelemetry(runId);
        setTelemetry(telem);
      } catch (err: any) {
        console.warn('Could not load telemetry:', err);
      }

      // 3. Findings
      try {
        const findings = await getRunFindings(runId);
        setTowers(findings);
      } catch (err: any) {
        console.warn('Could not load findings:', err);
      }

      // 4. Events
      try {
        const evList = await getRunEvents(runId);
        setEvents(evList);
      } catch (err: any) {
        console.warn('Could not load events:', err);
      }

      // 5. Tasks
      try {
        const taskList = await getRunTasks(runId);
        setTasks(taskList);
      } catch (err: any) {
        console.warn('Could not load tasks:', err);
      }

      // 6. Gate
      try {
        const gateData = await getRunGate(runId);
        setGate(gateData);
      } catch (err: any) {
        console.warn('Could not load gate result:', err);
      }

      // 7. Evaluation against hidden ground truth
      try {
        const evalData = await getRunEvaluation(runId);
        setEvaluation(evalData);
      } catch (err: any) {
        console.warn('Evaluation not available (e.g. non-scenario run):', err);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to fetch incident artifacts');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeRun?.run_id) {
      loadArtifacts(activeRun.run_id);
    }
  }, [activeRun?.run_id]);

  if (!activeRun) {
    return (
      <div className="p-12 max-w-4xl mx-auto text-center flex flex-col items-center justify-center space-y-4">
        <div className="w-16 h-16 rounded-2xl bg-noc-card border border-noc-border flex items-center justify-center text-noc-muted">
          <FileText className="w-8 h-8 opacity-40 text-noc-cyan" />
        </div>
        <h2 className="text-base font-bold text-noc-text">No Active Incident Run Loaded</h2>
        <p className="text-xs text-noc-muted max-w-md leading-relaxed">
          Launch a benchmark simulation run from the <span className="text-noc-cyan font-medium">Network Simulation & Topology</span> page to view verified telemetry, specialist tower findings, evidence gate verification, and the certified FinalReport.
        </p>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Top Incident Summary Bar */}
      <div className="bg-noc-card border border-noc-border rounded-xl p-4 shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                activeRun.status === 'completed'
                  ? 'bg-noc-emerald shadow-sm shadow-noc-emerald'
                  : activeRun.status === 'running'
                  ? 'bg-noc-cyan animate-pulse'
                  : 'bg-noc-amber'
              }`}
            />
            <h2 className="text-base font-bold text-noc-text flex items-center gap-2">
              Incident Intelligence: <span className="font-mono text-noc-cyan">{activeRun.incident_id}</span>
            </h2>
            <span
              className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded border ${
                activeRun.status === 'completed'
                  ? 'bg-noc-emerald/15 text-noc-emerald border-noc-emerald/30'
                  : 'bg-noc-cyan/15 text-noc-cyan border-noc-cyan/30'
              }`}
            >
              {activeRun.status}
            </span>
          </div>
          <p className="text-xs text-noc-muted">
            Scenario: <span className="text-noc-text font-medium">{activeRun.scenario_id || 'Custom Capture'}</span>
            {report && (
              <>
                {' '}• Root Cause:{' '}
                <span className="text-noc-cyan font-mono font-medium truncate inline-block max-w-sm align-bottom">
                  {report.suspected_root_cause}
                </span>
              </>
            )}
          </p>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => loadArtifacts(activeRun.run_id)}
            disabled={loading}
            className="flex items-center gap-1.5 bg-noc-bg hover:bg-noc-card border border-noc-border text-xs px-3 py-1.5 rounded-lg text-noc-muted hover:text-noc-text transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-noc-cyan' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 bg-red-950/20 border border-red-500/40 rounded-xl text-xs text-red-400 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Sub-Tabs Navigation */}
      <div className="flex items-center gap-2 border-b border-noc-border/80 pb-2 overflow-x-auto text-xs">
        <button
          onClick={() => setActiveSubTab('overview')}
          className={`flex items-center gap-1.5 px-3.5 py-2 rounded-lg font-medium transition-colors whitespace-nowrap ${
            activeSubTab === 'overview'
              ? 'bg-noc-cyan/20 text-noc-cyan border border-noc-cyan/40 shadow-sm'
              : 'text-noc-muted hover:text-noc-text hover:bg-noc-card/60'
          }`}
        >
          <FileText className="w-4 h-4" />
          Executive Brief & Gate Audit
        </button>

        <button
          onClick={() => setActiveSubTab('towers')}
          className={`flex items-center gap-1.5 px-3.5 py-2 rounded-lg font-medium transition-colors whitespace-nowrap ${
            activeSubTab === 'towers'
              ? 'bg-noc-purple/20 text-noc-purple border border-noc-purple/40 shadow-sm'
              : 'text-noc-muted hover:text-noc-text hover:bg-noc-card/60'
          }`}
        >
          <Layers className="w-4 h-4" />
          Specialist Towers ({towers.length})
        </button>

        <button
          onClick={() => setActiveSubTab('evidence')}
          className={`flex items-center gap-1.5 px-3.5 py-2 rounded-lg font-medium transition-colors whitespace-nowrap ${
            activeSubTab === 'evidence'
              ? 'bg-noc-cyan/20 text-noc-cyan border border-noc-cyan/40 shadow-sm'
              : 'text-noc-muted hover:text-noc-text hover:bg-noc-card/60'
          }`}
        >
          <Activity className="w-4 h-4" />
          Telemetry & Evidence ({telemetry?.total_observations ?? 0})
        </button>

        <button
          onClick={() => setActiveSubTab('fabric')}
          className={`flex items-center gap-1.5 px-3.5 py-2 rounded-lg font-medium transition-colors whitespace-nowrap ${
            activeSubTab === 'fabric'
              ? 'bg-noc-amber/20 text-noc-amber border border-noc-amber/40 shadow-sm'
              : 'text-noc-muted hover:text-noc-text hover:bg-noc-card/60'
          }`}
        >
          <Network className="w-4 h-4" />
          Integration Fabric Trace ({events.length})
        </button>

        <button
          onClick={() => setActiveSubTab('evaluation')}
          className={`flex items-center gap-1.5 px-3.5 py-2 rounded-lg font-medium transition-colors whitespace-nowrap ${
            activeSubTab === 'evaluation'
              ? 'bg-noc-emerald/20 text-noc-emerald border border-noc-emerald/40 shadow-sm'
              : 'text-noc-muted hover:text-noc-text hover:bg-noc-card/60'
          }`}
        >
          <Award className="w-4 h-4" />
          Benchmark Evaluation
        </button>
      </div>

      {/* Tab Panels */}
      {activeSubTab === 'overview' && (
        <div className="space-y-6">
          {report ? (
            <>
              {/* Certified Final Report View */}
              <FinalReportView report={report} />

              {/* Evidence Release Gate Audit Card */}
              <EvidenceGateCard gate={gate} limitations={report.limitations} />

              {/* Dispute Resolution Breakdown */}
              <DisputeResolutionCard report={report} towers={towers} />
            </>
          ) : (
            <div className="bg-noc-card border border-noc-border rounded-xl p-8 text-center text-noc-muted text-xs space-y-2">
              <RefreshCw className="w-6 h-6 mx-auto text-noc-cyan animate-spin" />
              <p>Diagnosis in progress or report still undergoing Evidence Gate audit...</p>
            </div>
          )}
        </div>
      )}

      {activeSubTab === 'towers' && (
        <TowerFindingsCard
          towers={towers}
          suspectedRootCause={report?.suspected_root_cause}
        />
      )}

      {activeSubTab === 'evidence' && telemetry && (
        <div className="space-y-6">
          {/* Time Series Charts */}
          <TelemetryCharts
            observations={telemetry.observations}
            features={telemetry.features}
          />

          {/* Raw vs Derived Feature Inspector */}
          <EvidenceInspector
            observations={telemetry.observations}
            features={telemetry.features}
            dataQualityWarnings={report?.data_quality_warnings}
          />
        </div>
      )}

      {activeSubTab === 'fabric' && (
        <FabricActivityLog events={events} tasks={tasks} />
      )}

      {activeSubTab === 'evaluation' && (
        <EvaluationCard evaluation={evaluation} />
      )}
    </div>
  );
};
