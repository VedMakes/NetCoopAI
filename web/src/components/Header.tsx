import React, { useEffect, useState } from 'react';
import { Activity, Cpu, ShieldCheck, MessageSquare, Terminal } from 'lucide-react';
import { getHealth } from '../api';

interface HeaderProps {
  activeIncidentId?: string;
  activeRunId?: string;
  isAssistantOpen: boolean;
  onToggleAssistant: () => void;
  hasCertifiedReport: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  activeIncidentId,
  activeRunId,
  isAssistantOpen,
  onToggleAssistant,
  hasCertifiedReport,
}) => {
  const [healthStatus, setHealthStatus] = useState<'healthy' | 'degraded' | 'offline'>('offline');
  const [componentSummary, setComponentSummary] = useState<string>('Connecting to backend...');

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const data = await getHealth();
        setHealthStatus(data.status === 'healthy' ? 'healthy' : 'degraded');
        const okCount = Object.values(data.components).filter(c => c.status === 'OK').length;
        setComponentSummary(`${okCount}/6 Services Online`);
      } catch {
        setHealthStatus('offline');
        setComponentSummary('API Disconnected');
      }
    };
    checkHealth();
    const interval = setInterval(checkHealth, 15000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="h-16 bg-noc-panel border-b border-noc-border px-6 flex items-center justify-between select-none">
      {/* Brand Identity */}
      <div className="flex items-center space-x-3">
        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
          <Terminal className="w-5 h-5 text-white" />
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <span className="font-bold text-lg tracking-wider text-noc-text">NetCoop</span>
            <span className="text-xs px-2 py-0.5 rounded font-mono font-medium bg-noc-amethyst/20 text-noc-amethyst border border-noc-amethyst/30">
              AI NOC
            </span>
          </div>
          <p className="text-[11px] text-noc-muted tracking-tight">Cooperative Multi-Agent Fault Diagnosis</p>
        </div>
      </div>

      {/* Center Operational Metadata */}
      <div className="hidden md:flex items-center space-x-4">
        {/* Backend Health Pill */}
        <div className="flex items-center space-x-2 px-3 py-1.5 rounded-full bg-noc-subpanel border border-noc-border text-xs">
          <span
            className={`w-2 h-2 rounded-full ${
              healthStatus === 'healthy'
                ? 'bg-noc-green animate-pulse'
                : healthStatus === 'degraded'
                ? 'bg-noc-yellow'
                : 'bg-noc-red'
            }`}
          />
          <span className="text-noc-muted font-mono">{componentSummary}</span>
        </div>

        {/* Active Incident Tag */}
        {activeIncidentId ? (
          <div className="flex items-center space-x-2 px-3 py-1.5 rounded-full bg-indigo-950/40 border border-indigo-500/30 text-xs">
            <Activity className="w-3.5 h-3.5 text-indigo-400" />
            <span className="text-indigo-300 font-mono font-medium">{activeIncidentId}</span>
            {activeRunId && <span className="text-noc-muted font-mono">({activeRunId})</span>}
          </div>
        ) : (
          <div className="flex items-center space-x-2 px-3 py-1.5 rounded-full bg-noc-subpanel border border-noc-border text-xs text-noc-muted">
            <Activity className="w-3.5 h-3.5" />
            <span>Ready for Scenario Run</span>
          </div>
        )}

        {/* Evidence Gate Certified Badge */}
        {hasCertifiedReport && (
          <div className="flex items-center space-x-1.5 px-3 py-1.5 rounded-full bg-emerald-950/40 border border-emerald-500/30 text-xs text-emerald-300">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span>Gate Certified</span>
          </div>
        )}
      </div>

      {/* Right Controls */}
      <div className="flex items-center space-x-3">
        <div className="hidden sm:flex items-center space-x-1 px-2.5 py-1 rounded bg-noc-subpanel border border-noc-border text-[11px] text-noc-muted font-mono">
          <Cpu className="w-3.5 h-3.5 text-noc-cyan mr-1" />
          <span>Deterministic Offline</span>
        </div>

        {/* Assistant Drawer Button */}
        <button
          onClick={onToggleAssistant}
          className={`relative flex items-center space-x-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
            isAssistantOpen
              ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
              : 'bg-noc-subpanel hover:bg-noc-hover text-noc-text border border-noc-border'
          }`}
        >
          <MessageSquare className="w-4 h-4 text-indigo-400" />
          <span>Incident Assistant</span>
          {hasCertifiedReport && !isAssistantOpen && (
            <span className="w-2 h-2 rounded-full bg-noc-green absolute -top-0.5 -right-0.5 ring-2 ring-noc-bg" />
          )}
        </button>
      </div>
    </header>
  );
};
