import React from 'react';
import { Network, FileText } from 'lucide-react';

interface NavigationProps {
  currentTab: 'simulation' | 'intelligence';
  onSelectTab: (tab: 'simulation' | 'intelligence') => void;
  hasIncident: boolean;
}

export const Navigation: React.FC<NavigationProps> = ({ currentTab, onSelectTab, hasIncident }) => {
  return (
    <nav className="h-12 bg-noc-panel/80 backdrop-blur border-b border-noc-border px-6 flex items-center justify-between">
      <div className="flex items-center space-x-2">
        <button
          onClick={() => onSelectTab('simulation')}
          className={`flex items-center space-x-2 px-4 py-2 rounded-lg text-xs font-medium transition-all ${
            currentTab === 'simulation'
              ? 'bg-noc-hover text-noc-text border border-noc-border shadow-sm'
              : 'text-noc-muted hover:text-noc-text hover:bg-noc-subpanel'
          }`}
        >
          <Network className="w-4 h-4 text-indigo-400" />
          <span>Run a diagnosis</span>
        </button>

        <button
          onClick={() => onSelectTab('intelligence')}
          className={`flex items-center space-x-2 px-4 py-2 rounded-lg text-xs font-medium transition-all ${
            currentTab === 'intelligence'
              ? 'bg-noc-hover text-noc-text border border-noc-border shadow-sm'
              : 'text-noc-muted hover:text-noc-text hover:bg-noc-subpanel'
          }`}
        >
          <FileText className="w-4 h-4 text-emerald-400" />
          <span>Results & evidence</span>
          {hasIncident && (
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 ml-1" />
          )}
        </button>
      </div>

      <div className="hidden items-center gap-2 text-[10px] text-noc-muted sm:flex">
        <span className="h-1.5 w-1.5 rounded-full bg-noc-green" />
        <span>4 specialist towers</span><span className="text-noc-border">·</span><span>evidence-gated diagnosis</span>
      </div>
    </nav>
  );
};
