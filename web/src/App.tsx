import React, { useState } from 'react';
import { Header } from './components/Header';
import { Navigation } from './components/Navigation';
import { NetworkSimulation } from './pages/NetworkSimulation';
import { IncidentIntelligence } from './pages/IncidentIntelligence';
import { AssistantDrawer } from './components/AssistantDrawer';
import { FinalReport, RunStatusResponse } from './types';

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<'simulation' | 'intelligence'>('simulation');
  const [isAssistantOpen, setIsAssistantOpen] = useState<boolean>(false);
  const [activeRun, setActiveRun] = useState<RunStatusResponse | null>(null);
  const [certifiedReport, setCertifiedReport] = useState<FinalReport | null>(null);

  const handleRunCompleted = (_runId: string, _incidentId: string, report: FinalReport) => {
    setCertifiedReport(report);
  };

  return (
    <div className="min-h-screen bg-noc-bg text-noc-text flex flex-col font-sans">
      {/* Top Application Header */}
      <Header
        activeIncidentId={activeRun?.incident_id}
        activeRunId={activeRun?.run_id}
        isAssistantOpen={isAssistantOpen}
        onToggleAssistant={() => setIsAssistantOpen(prev => !prev)}
        hasCertifiedReport={Boolean(certifiedReport)}
      />

      {/* Main Navigation Bar */}
      <Navigation
        currentTab={currentTab}
        onSelectTab={setCurrentTab}
        hasIncident={Boolean(certifiedReport)}
      />

      {/* Main Page Body */}
      <main className="flex-1 overflow-x-hidden">
        {currentTab === 'simulation' ? (
          <NetworkSimulation
            onRunCompleted={handleRunCompleted}
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
        runId={activeRun?.run_id}
        hasCertifiedReport={Boolean(certifiedReport)}
      />
    </div>
  );
};

export default App;
