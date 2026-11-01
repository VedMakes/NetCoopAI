import React, { useEffect, useRef, useState } from 'react';
import { Header } from './components/Header';
import { Navigation } from './components/Navigation';
import { NetworkSimulation } from './pages/NetworkSimulation';
import { IncidentIntelligence } from './pages/IncidentIntelligence';
import { AssistantDrawer } from './components/AssistantDrawer';
import { createSession, getRunReport, getRunStatus, getSession, getSessions } from './api';
import { FinalReport, InvestigationSession, RunStatusResponse } from './types';

let bootstrapSessionPromise: Promise<InvestigationSession> | null = null;
const ACTIVE_SESSION_KEY = 'netcoop.active_session_id';

const readSavedSessionId = (): string | null => {
  try {
    return window.localStorage.getItem(ACTIVE_SESSION_KEY);
  } catch {
    return null;
  }
};

const saveSessionId = (sessionId: string) => {
  try {
    window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  } catch {
    // Session selection still works for this page load when browser storage is disabled.
  }
};

const clearSavedSessionId = () => {
  try {
    window.localStorage.removeItem(ACTIVE_SESSION_KEY);
  } catch {
    // Ignore unavailable browser storage; the API remains the source of session data.
  }
};

const getOrCreateBootstrapSession = (): Promise<InvestigationSession> => {
  if (!bootstrapSessionPromise) {
    bootstrapSessionPromise = createSession().catch((error) => {
      bootstrapSessionPromise = null;
      throw error;
    });
  }
  return bootstrapSessionPromise;
};

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<'simulation' | 'intelligence'>('simulation');
  const [isAssistantOpen, setIsAssistantOpen] = useState<boolean>(false);
  const [resumeAssistantSessionId, setResumeAssistantSessionId] = useState<string | null>(null);
  const [activeRun, setActiveRun] = useState<RunStatusResponse | null>(null);
  const [certifiedReport, setCertifiedReport] = useState<FinalReport | null>(null);
  const [certifiedRunId, setCertifiedRunId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<InvestigationSession[]>([]);
  const [activeSession, setActiveSession] = useState<InvestigationSession | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [isLoadingSelection, setIsLoadingSelection] = useState(false);
  const [uploadFocusRequestId, setUploadFocusRequestId] = useState(0);
  const sessionRequestId = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++sessionRequestId.current;
    setIsLoadingSelection(true);
    const restoreSession = async () => {
      try {
        let available = await getSessions();
        const savedId = readSavedSessionId();
        let selected = available.find((item) => item.session_id === savedId);
        if (savedId && !selected) {
          try {
            selected = await getSession(savedId);
            available = [selected, ...available];
          } catch {
            clearSavedSessionId();
          }
        }
        if (!selected) {
          selected = available[0] ?? await getOrCreateBootstrapSession();
          if (!available.some((item) => item.session_id === selected?.session_id)) {
            available = [selected, ...available];
          }
        }
        selected = await getSession(selected.session_id);
        if (cancelled || sessionRequestId.current !== requestId) return;
        setSessions(available);
        setActiveSession(selected);
        saveSessionId(selected.session_id);
        setSessionError(null);
        if (selected.current_run_id) {
          const run = await getRunStatus(selected.current_run_id);
          if (cancelled || sessionRequestId.current !== requestId) return;
          setActiveRun(run);
          if (run.status === 'completed') {
            const report = await getRunReport(run.run_id);
            if (cancelled || sessionRequestId.current !== requestId) return;
            setCertifiedReport(report);
            setCertifiedRunId(run.run_id);
          }
        }
      } catch (err) {
        if (!cancelled && sessionRequestId.current === requestId) {
          setSessionError(err instanceof Error ? err.message : 'Could not restore a session');
        }
      } finally {
        if (!cancelled && sessionRequestId.current === requestId) setIsLoadingSelection(false);
      }
    };
    void restoreSession();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!activeRun) return;
    setActiveSession((current) => {
      if (!current || current.session_id !== activeRun.session_id) return current;
      return {
        ...current,
        runs: (current.runs ?? []).map((run) => run.run_id === activeRun.run_id ? activeRun : run),
      };
    });
  }, [activeRun?.run_id, activeRun?.status]);

  const handleRunStarted = (openChatAfterRun = false) => {
    setCertifiedReport(null);
    setCertifiedRunId(null);
    if (openChatAfterRun && activeSession) {
      setResumeAssistantSessionId(activeSession.session_id);
      setIsAssistantOpen(false);
    }
  };

  const handleRunCleared = () => {
    setResumeAssistantSessionId(null);
    handleRunStarted(false);
  };

  const handleNewSession = async () => {
    const requestId = ++sessionRequestId.current;
    setResumeAssistantSessionId(null);
    setIsLoadingSelection(true);
    try {
      const session = await createSession();
      if (sessionRequestId.current !== requestId) return;
      setSessions((current) => [session, ...current]);
      setActiveSession(session);
      setActiveRun(null);
      setCertifiedReport(null);
      setCertifiedRunId(null);
      saveSessionId(session.session_id);
      setSessionError(null);
    } catch (err) {
      setSessionError(err instanceof Error ? err.message : 'Could not create a session');
    } finally {
      if (sessionRequestId.current === requestId) setIsLoadingSelection(false);
    }
  };

  const handleSelectSession = async (sessionId: string) => {
    const requestId = ++sessionRequestId.current;
    setResumeAssistantSessionId(null);
    setIsLoadingSelection(true);
    try {
      const session = await getSession(sessionId);
      if (sessionRequestId.current !== requestId) return;
      setActiveSession(session);
      setSessions((current) => [session, ...current.filter((item) => item.session_id !== sessionId)]);
      saveSessionId(session.session_id);
      setActiveRun(null);
      setCertifiedReport(null);
      setCertifiedRunId(null);
      if (session.current_run_id) {
        const run = await getRunStatus(session.current_run_id);
        if (sessionRequestId.current !== requestId) return;
        setActiveRun(run);
        if (run.status === 'completed') {
          const report = await getRunReport(run.run_id);
          if (sessionRequestId.current !== requestId) return;
          setCertifiedReport(report);
          setCertifiedRunId(run.run_id);
        }
      }
      setSessionError(null);
    } catch (err) {
      if (sessionRequestId.current === requestId) {
        setSessionError(err instanceof Error ? err.message : 'Could not switch sessions');
      }
    } finally {
      if (sessionRequestId.current === requestId) setIsLoadingSelection(false);
    }
  };

  const handleRefreshSessions = async () => {
    const requestId = sessionRequestId.current;
    const currentSessionId = activeSession?.session_id;
    try {
      const available = await getSessions();
      if (sessionRequestId.current !== requestId) return;
      setSessions(available);
      if (currentSessionId) {
        const refreshed = await getSession(currentSessionId);
        if (sessionRequestId.current !== requestId) return;
        setActiveSession(refreshed);
      }
      setSessionError(null);
    } catch (err) {
      setSessionError(err instanceof Error ? err.message : 'Could not refresh sessions');
    }
  };

  const handleRunCompleted = (runId: string, _incidentId: string, report: FinalReport) => {
    setCertifiedReport(report);
    setCertifiedRunId(runId);
    setActiveSession((current) => current ? {
      ...current,
      runs: (current.runs ?? []).map((run) => run.run_id === runId ? { ...run, status: 'completed' } : run),
    } : current);
    if (resumeAssistantSessionId && activeSession?.session_id === resumeAssistantSessionId) {
      setIsAssistantOpen(true);
      setResumeAssistantSessionId(null);
    }
  };

  useEffect(() => {
    if (
      resumeAssistantSessionId
      && activeRun?.status === 'failed'
      && activeRun.session_id === resumeAssistantSessionId
      && activeSession?.session_id === resumeAssistantSessionId
    ) {
      setIsAssistantOpen(true);
      setResumeAssistantSessionId(null);
    }
  }, [activeRun?.run_id, activeRun?.status, activeRun?.session_id, activeSession?.session_id, resumeAssistantSessionId]);

  const handleSelectRun = async (runId: string) => {
    const requestId = ++sessionRequestId.current;
    setIsLoadingSelection(true);
    try {
      const run = await getRunStatus(runId);
      if (sessionRequestId.current !== requestId) return;
      setActiveRun(run);
      setCertifiedReport(null);
      setCertifiedRunId(null);
      if (run.status === 'completed') {
        const report = await getRunReport(runId);
        if (sessionRequestId.current !== requestId) return;
        setCertifiedReport(report);
        setCertifiedRunId(runId);
      }
    } catch (err) {
      if (sessionRequestId.current === requestId) {
        setSessionError(err instanceof Error ? err.message : 'Could not open this run');
      }
    } finally {
      if (sessionRequestId.current === requestId) setIsLoadingSelection(false);
    }
  };

  const handleRunCreated = (run: RunStatusResponse) => {
    setActiveSession((current) => {
      if (!current || current.session_id !== run.session_id) return current;
      return {
        ...current,
        current_run_id: run.run_id,
        run_count: current.run_count + 1,
        updated_at: run.created_at,
        runs: [...(current.runs ?? []), run],
      };
    });
    setSessions((current) => current.map((session) => session.session_id === run.session_id
      ? { ...session, current_run_id: run.run_id, run_count: session.run_count + 1, updated_at: run.created_at }
      : session));
  };

  const currentSessionReport = activeSession?.current_run_id === certifiedRunId
    ? certifiedReport
    : null;

  return (
    <div className="min-h-screen bg-noc-bg text-noc-text flex flex-col font-sans">
      {/* Top Application Header */}
      <Header
        activeIncidentId={activeRun?.incident_id}
        activeRunId={activeRun?.run_id}
        isAssistantOpen={isAssistantOpen}
        onToggleAssistant={() => setIsAssistantOpen(prev => !prev)}
        hasCertifiedReport={Boolean(certifiedReport && certifiedRunId === activeRun?.run_id)}
        isLoadingSelection={isLoadingSelection}
        activeSessionId={activeSession?.session_id ?? null}
        sessions={sessions}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
        onRefreshSessions={handleRefreshSessions}
        runs={activeSession?.runs ?? []}
        onSelectRun={handleSelectRun}
      />

      {/* Main Navigation Bar */}
      <Navigation
        currentTab={currentTab}
        onSelectTab={setCurrentTab}
        hasIncident={Boolean(certifiedReport && certifiedRunId === activeRun?.run_id)}
      />

      {/* Main Page Body */}
      <main className="flex-1 overflow-x-hidden">
        {sessionError && <div className="mx-6 mt-4 rounded-lg border border-red-500/40 bg-red-950/30 px-4 py-2 text-xs text-red-300">{sessionError}</div>}
        {currentTab === 'simulation' ? (
          <NetworkSimulation
            onRunCompleted={handleRunCompleted}
            onRunStarted={handleRunStarted}
            onRunCleared={handleRunCleared}
            onRunCreated={handleRunCreated}
            sessionId={activeSession?.session_id ?? null}
            isLoadingSelection={isLoadingSelection}
            uploadFocusRequestId={uploadFocusRequestId}
            activeRun={activeRun}
            setActiveRun={setActiveRun}
          />
        ) : (
          <IncidentIntelligence
            activeRun={activeRun}
            report={certifiedReport}
          />
        )}
      </main>

      {/* Slide-over Incident Explanation Assistant */}
      <AssistantDrawer
        isOpen={isAssistantOpen}
        onClose={() => setIsAssistantOpen(false)}
        sessionId={activeSession?.session_id ?? null}
        sessionTitle={activeSession?.title ?? 'Investigation'}
        runs={activeSession?.runs ?? []}
        hasSessionContext={Boolean(activeSession?.runs?.some((run) => run.status === 'completed'))}
        latestSymptomReasoning={currentSessionReport?.symptom_reasoning ?? null}
        canAddTelemetry={Boolean(activeSession) && !isLoadingSelection && activeRun?.status !== 'queued' && activeRun?.status !== 'running'}
        onRequestAddTelemetry={() => {
          setResumeAssistantSessionId(activeSession?.session_id ?? null);
          setIsAssistantOpen(false);
          setCurrentTab('simulation');
          setUploadFocusRequestId((current) => current + 1);
        }}
      />
    </div>
  );
};

export default App;
