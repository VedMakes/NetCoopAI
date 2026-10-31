import React, { useState } from 'react';
import { X, Send, Bot, User, Sparkles, ShieldCheck } from 'lucide-react';
import { askAssistant } from '../api';
import { AssistantTurn } from '../types';

interface AssistantDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  runId?: string;
  hasCertifiedReport: boolean;
}

const PRESET_QUESTIONS = [
  "Why was this root cause diagnosed?",
  "What evidence was verified by the Evidence Gate?",
  "Which entities are directly observed vs topology inferred?",
  "What findings did the Performance Tower produce?",
  "Why were competing alternative causes rejected?",
];

export const AssistantDrawer: React.FC<AssistantDrawerProps> = ({
  isOpen,
  onClose,
  runId,
  hasCertifiedReport,
}) => {
  const [messages, setMessages] = useState<AssistantTurn[]>([
    {
      role: 'assistant',
      content:
        "Hello! I am the NetCoop AI Incident Explanation Assistant. I can explain the certified root cause, specialist tower findings, supporting evidence, and Evidence Gate audit checks for this incident.",
    },
  ]);
  const [inputQuestion, setInputQuestion] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [citedEvidence, setCitedEvidence] = useState<string[]>([]);
  const [citedFindings, setCitedFindings] = useState<string[]>([]);

  if (!isOpen) return null;

  const handleSend = async (questionToSend?: string) => {
    const q = questionToSend || inputQuestion;
    if (!q.trim() || isLoading) return;

    if (!runId) {
      setMessages(prev => [
        ...prev,
        { role: 'user', content: q },
        { role: 'assistant', content: 'No active incident run selected. Please launch or select a scenario run first.' },
      ]);
      setInputQuestion('');
      return;
    }

    const newMessages: AssistantTurn[] = [...messages, { role: 'user', content: q }];
    setMessages(newMessages);
    setInputQuestion('');
    setIsLoading(true);

    try {
      const resp = await askAssistant(runId, q, newMessages, 'auto');
      setMessages(prev => [...prev, { role: 'assistant', content: resp.answer }]);
      if (resp.cited_evidence_ids?.length) {
        setCitedEvidence(resp.cited_evidence_ids);
      }
      if (resp.cited_findings?.length) {
        setCitedFindings(resp.cited_findings);
      }
    } catch (err: any) {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `Error querying assistant: ${err.message || 'Unknown error'}` },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full sm:w-[480px] bg-noc-panel border-l border-noc-border shadow-2xl flex flex-col">
      {/* Drawer Header */}
      <div className="h-16 px-6 border-b border-noc-border flex items-center justify-between bg-noc-subpanel/50">
        <div className="flex items-center space-x-2.5">
          <div className="w-8 h-8 rounded-lg bg-indigo-600/30 border border-indigo-500/40 flex items-center justify-center">
            <Bot className="w-4 h-4 text-indigo-400" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-noc-text flex items-center space-x-1.5">
              <span>Incident Assistant</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded font-mono bg-noc-subpanel text-noc-cyan border border-noc-border">
                Read-Only
              </span>
            </h3>
            <p className="text-[11px] text-noc-muted">Ground-truth isolated • Zero RAG</p>
          </div>
        </div>

        <button
          onClick={onClose}
          className="p-1.5 rounded-lg hover:bg-noc-hover text-noc-muted hover:text-noc-text transition-colors"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Suggested Prompt Pills */}
      {hasCertifiedReport && messages.length <= 2 && (
        <div className="p-4 border-b border-noc-border/50 bg-noc-bg/40">
          <p className="text-[11px] text-noc-muted font-mono mb-2 flex items-center space-x-1">
            <Sparkles className="w-3 h-3 text-noc-cyan" />
            <span>Suggested Inquiries:</span>
          </p>
          <div className="flex flex-wrap gap-1.5">
            {PRESET_QUESTIONS.map((q, idx) => (
              <button
                key={idx}
                onClick={() => handleSend(q)}
                className="text-[11px] text-left px-2.5 py-1 rounded bg-noc-subpanel hover:bg-noc-hover text-noc-text border border-noc-border transition-all"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((m, idx) => (
          <div
            key={idx}
            className={`flex items-start space-x-3 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {m.role === 'assistant' && (
              <div className="w-7 h-7 rounded-full bg-indigo-600/20 border border-indigo-500/40 flex items-center justify-center flex-shrink-0 mt-0.5">
                <Bot className="w-3.5 h-3.5 text-indigo-400" />
              </div>
            )}

            <div
              className={`max-w-[85%] rounded-xl px-4 py-3 text-xs leading-relaxed ${
                m.role === 'user'
                  ? 'bg-indigo-600 text-white shadow-md'
                  : 'bg-noc-subpanel border border-noc-border text-noc-text font-sans whitespace-pre-wrap'
              }`}
            >
              {m.content}
            </div>

            {m.role === 'user' && (
              <div className="w-7 h-7 rounded-full bg-noc-hover border border-noc-border flex items-center justify-center flex-shrink-0 mt-0.5">
                <User className="w-3.5 h-3.5 text-noc-muted" />
              </div>
            )}
          </div>
        ))}

        {isLoading && (
          <div className="flex items-center space-x-2 text-xs text-noc-muted font-mono py-2">
            <div className="w-2 h-2 rounded-full bg-indigo-500 animate-ping" />
            <span>Synthesizing explanation from certified artifacts...</span>
          </div>
        )}
      </div>

      {/* Grounded Citation Badges */}
      {(citedEvidence.length > 0 || citedFindings.length > 0) && (
        <div className="px-4 py-2 bg-noc-subpanel border-t border-noc-border text-[11px] font-mono">
          <div className="flex items-center justify-between text-noc-muted mb-1">
            <span className="flex items-center space-x-1">
              <ShieldCheck className="w-3 h-3 text-emerald-400" />
              <span>Grounded Citations:</span>
            </span>
            <span>{citedEvidence.length} Observations</span>
          </div>
          <div className="flex flex-wrap gap-1 max-h-16 overflow-y-auto">
            {citedEvidence.slice(0, 6).map((id, i) => (
              <span key={i} className="px-1.5 py-0.5 rounded bg-noc-bg border border-noc-border text-noc-cyan">
                {id}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Input Box */}
      <div className="p-4 border-t border-noc-border bg-noc-subpanel/50">
        <form
          onSubmit={e => {
            e.preventDefault();
            handleSend();
          }}
          className="flex items-center space-x-2"
        >
          <input
            type="text"
            value={inputQuestion}
            onChange={e => setInputQuestion(e.target.value)}
            placeholder={runId ? "Ask about root cause, evidence, or gate checks..." : "Launch a run first..."}
            disabled={isLoading || !runId}
            className="flex-1 bg-noc-bg border border-noc-border rounded-lg px-3.5 py-2 text-xs text-noc-text placeholder-noc-muted focus:outline-none focus:border-indigo-500 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={isLoading || !inputQuestion.trim() || !runId}
            className="px-3.5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors disabled:opacity-40"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
};
