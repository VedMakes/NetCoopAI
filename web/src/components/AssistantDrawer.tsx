import React, { useState, useRef, useEffect } from 'react';
import {
  X,
  Send,
  Bot,
  User,
  Sparkles,
  ShieldCheck,
  RotateCcw,
  Cpu,
  Copy,
  Check,
  Info,
} from 'lucide-react';
import { askSessionAssistant, clearSessionAssistantHistory, getSessionAssistantHistory } from '../api';
import { AssistantTurn, RunStatusResponse, SymptomReasoning } from '../types';

interface AssistantDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  sessionId: string | null;
  sessionTitle: string;
  runs: RunStatusResponse[];
  hasSessionContext: boolean;
  latestSymptomReasoning: SymptomReasoning | null;
  canAddTelemetry: boolean;
  onRequestAddTelemetry: () => void;
}

interface EnrichedMessage extends AssistantTurn {
  provider?: string;
  citedEvidence?: string[];
  citedFindings?: string[];
}

const PRESET_QUESTIONS = [
  "Why was this root cause diagnosed?",
  "What evidence supports this diagnosis?",
  "What remediation steps should be taken first?",
  "What are the limitations or uncertainties of this report?",
  "Why were competing alternative causes rejected?",
  "What findings did the Performance Tower produce?",
  "What was the Evidence Release Gate outcome?",
];

export const AssistantDrawer: React.FC<AssistantDrawerProps> = ({
  isOpen,
  onClose,
  sessionId,
  sessionTitle,
  runs,
  hasSessionContext,
  latestSymptomReasoning,
  canAddTelemetry,
  onRequestAddTelemetry,
}) => {
  const [messages, setMessages] = useState<EnrichedMessage[]>([
    {
      role: 'assistant',
      content:
        "Hello! I am the NetCoop AI Incident Explanation Assistant.\n\nI can explain the certified root cause, specialist tower findings, supporting telemetry evidence, and Evidence Release Gate checks strictly grounded in certified incident artifacts.\n\nHow can I help you understand this incident?",
      provider: 'deterministic',
    },
  ]);
  const [inputQuestion, setInputQuestion] = useState('');
  const [llmMode, setLlmMode] = useState<'off' | 'auto' | 'on'>('auto');
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isClearingHistory, setIsClearingHistory] = useState(false);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const requestIdRef = useRef(0);

  // Auto-scroll to bottom on message update
  useEffect(() => {
    if (isOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isLoading, isOpen]);

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    setIsLoading(false);
    setIsClearingHistory(false);
    setIsLoadingHistory(Boolean(sessionId));
    setMessages([
      {
        role: 'assistant',
        content: sessionId
          ? `This conversation belongs to “${sessionTitle}”. It can explain completed diagnoses in this session and compare results after a new analysis.`
          : 'Create or select an investigation session to start.',
        provider: 'deterministic',
      },
    ]);
    setInputQuestion('');
    if (sessionId) {
      getSessionAssistantHistory(sessionId)
        .then((history) => {
          if (requestIdRef.current !== requestId || history.length === 0) return;
          setMessages((current) => [current[0], ...history.map((turn) => ({ ...turn, provider: 'stored' }))]);
        })
        .catch((error) => console.warn('Could not restore session conversation:', error))
        .finally(() => {
          if (requestIdRef.current === requestId) setIsLoadingHistory(false);
        });
    } else {
      setIsLoadingHistory(false);
    }
  }, [sessionId, sessionTitle]);

  if (!isOpen) return null;

  const handleClearHistory = async () => {
    const requestId = ++requestIdRef.current;
    setIsLoading(false);
    if (!sessionId) return;
    setIsClearingHistory(true);
    try {
      await clearSessionAssistantHistory(sessionId);
      if (requestIdRef.current !== requestId) return;
      setMessages([
        {
          role: 'assistant',
          content: 'Conversation reset. The completed run reports remain in this session and can still be discussed.',
          provider: 'deterministic',
        },
      ]);
    } catch (error) {
      if (requestIdRef.current === requestId) {
        console.error('Could not clear session conversation:', error);
      }
    } finally {
      if (requestIdRef.current === requestId) setIsClearingHistory(false);
    }
  };

  const handleCopyMessage = (text: string, idx: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 2000);
  };

  const handleSend = async (questionToSend?: string) => {
    const q = questionToSend || inputQuestion;
    if (!q.trim() || isLoading || isLoadingHistory || isClearingHistory) return;

    if (!sessionId || !hasSessionContext) {
      setMessages((prev) => [
        ...prev,
        { role: 'user', content: q },
        {
          role: 'assistant',
          content: 'Complete a diagnosis in this session before asking questions about its evidence.',
          provider: 'system',
        },
      ]);
      setInputQuestion('');
      return;
    }

    const userTurn: EnrichedMessage = { role: 'user', content: q };
    const requestedSessionId = sessionId;
    const requestId = ++requestIdRef.current;
    setMessages((prev) => [...prev, userTurn]);
    setInputQuestion('');
    setIsLoading(true);

    try {
      const resp = await askSessionAssistant(requestedSessionId, q, llmMode);
      if (requestIdRef.current !== requestId) return;
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: resp.answer,
          provider: resp.provider_used,
          citedEvidence: resp.cited_evidence_ids,
          citedFindings: resp.cited_findings,
        },
      ]);
    } catch (err: any) {
      if (requestIdRef.current !== requestId) return;
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `Assistant inquiry failed: ${err.message || 'Unknown error'}`,
          provider: 'error',
        },
      ]);
    } finally {
      if (requestIdRef.current === requestId) setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full sm:w-[500px] bg-noc-panel border-l border-noc-border shadow-2xl flex flex-col font-sans">
      {/* Drawer Header */}
      <div className="h-16 px-5 border-b border-noc-border flex items-center justify-between bg-noc-subpanel/60">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-indigo-600/25 border border-indigo-500/40 flex items-center justify-center">
            <Bot className="w-4 h-4 text-indigo-400" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-noc-text flex items-center gap-2">
              <span>Investigation Assistant</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded font-mono bg-noc-subpanel text-noc-cyan border border-noc-border">
                Session Chat
              </span>
            </h3>
            <p className="text-[11px] text-noc-muted truncate max-w-56">{sessionTitle}</p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={handleClearHistory}
            disabled={!sessionId || isClearingHistory || isLoadingHistory}
            className="p-1.5 rounded-lg hover:bg-noc-hover text-noc-muted hover:text-noc-text transition-colors disabled:opacity-40"
            title="Reset conversation"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-noc-hover text-noc-muted hover:text-noc-text transition-colors"
            title="Close drawer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      </div>

      <div className="px-5 py-3 border-b border-noc-border/60 bg-noc-bg/40 space-y-2">
        <div className="flex items-center justify-between gap-3 text-[11px]">
          <span className="text-noc-muted">
            Context: {runs.filter((run) => run.status === 'completed').length} completed run(s)
            {runs.filter((run) => run.status === 'completed').length > 5 ? ' · using 5 most recent' : ''}
          </span>
          <button
            type="button"
            onClick={onRequestAddTelemetry}
            disabled={!canAddTelemetry}
            className="shrink-0 rounded-md border border-noc-amethyst/40 bg-noc-amethyst/10 px-2.5 py-1.5 text-[11px] font-semibold text-noc-amethyst hover:bg-noc-amethyst/20 disabled:cursor-not-allowed disabled:opacity-40"
            title={canAddTelemetry ? 'Open the explicit upload and new analysis flow' : 'Wait for the current analysis to finish'}
          >
            Add telemetry & re-analyze
          </button>
        </div>
        <p className="text-[10px] leading-relaxed text-noc-muted">
          Uploading starts a separate analysis in this session. The assistant reopens when it finishes. Chat messages are context only; they are never added as telemetry.
        </p>
      </div>

      {latestSymptomReasoning && (
        <div className="mx-4 mt-3 rounded-lg border border-noc-amethyst/30 bg-noc-amethyst/5 p-3 text-xs">
          <div className="flex items-center justify-between gap-2">
            <span className="font-semibold text-noc-amethyst">Optional symptom review</span>
            <span className="rounded border border-noc-border px-1.5 py-0.5 text-[10px] uppercase text-noc-muted">
              {latestSymptomReasoning.status}
            </span>
          </div>
          <p className="mt-1 text-noc-text">“{latestSymptomReasoning.reported_symptom}”</p>
          <p className="mt-1 leading-relaxed text-noc-muted">{latestSymptomReasoning.explanation}</p>
          <p className="mt-1 text-[10px] text-noc-muted">Compared after diagnosis; it did not steer or change the diagnosis.</p>
        </div>
      )}

      {/* Mode & Environment Bar */}
      <div className="px-5 py-2.5 bg-noc-bg/60 border-b border-noc-border/60 flex items-center justify-between text-xs">
        <div className="flex items-center gap-1.5 text-noc-muted">
          <Cpu className="w-3.5 h-3.5 text-noc-cyan" />
          <span className="text-[11px]">Provider Mode:</span>
        </div>

        <div className="flex items-center gap-1 bg-noc-subpanel p-0.5 rounded-lg border border-noc-border text-[11px]">
          {(['auto', 'off', 'on'] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setLlmMode(mode)}
              className={`px-2 py-0.5 rounded capitalize font-medium transition-colors ${
                llmMode === mode
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-noc-muted hover:text-noc-text'
              }`}
            >
              {mode === 'auto' ? 'Auto LLM' : mode === 'off' ? 'Deterministic' : 'LLM Only'}
            </button>
          ))}
        </div>
      </div>

      {/* Suggested Prompt Pills */}
      {hasSessionContext && messages.length <= 3 && (
        <div className="p-4 border-b border-noc-border/50 bg-noc-bg/40 space-y-2">
          <p className="text-[11px] text-noc-muted font-mono flex items-center gap-1">
            <Sparkles className="w-3 h-3 text-noc-cyan" />
            <span>Suggested Inquiries:</span>
          </p>
          <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto">
            {PRESET_QUESTIONS.map((q, idx) => (
              <button
                key={idx}
                onClick={() => handleSend(q)}
                className="text-[11px] text-left px-2.5 py-1 rounded-lg bg-noc-subpanel hover:bg-noc-hover text-noc-text border border-noc-border transition-all cursor-pointer"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((m, idx) => {
          const isUser = m.role === 'user';
          return (
            <div
              key={idx}
              className={`flex items-start gap-2.5 ${isUser ? 'justify-end' : 'justify-start'}`}
            >
              {!isUser && (
                <div className="w-7 h-7 rounded-full bg-indigo-600/20 border border-indigo-500/40 flex items-center justify-center shrink-0 mt-0.5">
                  <Bot className="w-3.5 h-3.5 text-indigo-400" />
                </div>
              )}

              <div
                className={`max-w-[85%] rounded-xl px-4 py-3 text-xs leading-relaxed space-y-2 ${
                  isUser
                    ? 'bg-indigo-600 text-white shadow-md'
                    : 'bg-noc-subpanel border border-noc-border text-noc-text font-sans'
                }`}
              >
                <div className="whitespace-pre-wrap">{m.content}</div>

                {/* Metadata Footer on Assistant Messages */}
                {!isUser && (
                  <div className="pt-2 border-t border-noc-border/50 flex flex-wrap items-center justify-between gap-2 text-[10px] text-noc-muted font-mono">
                    <span className="flex items-center gap-1">
                      <ShieldCheck className="w-3 h-3 text-noc-emerald" />
                      <span>{m.provider || 'deterministic'}</span>
                    </span>

                    <button
                      onClick={() => handleCopyMessage(m.content, idx)}
                      className="hover:text-noc-text flex items-center gap-1 transition-colors"
                      title="Copy response"
                    >
                      {copiedIdx === idx ? (
                        <>
                          <Check className="w-3 h-3 text-noc-emerald" />
                          <span>Copied</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3 h-3" />
                          <span>Copy</span>
                        </>
                      )}
                    </button>
                  </div>
                )}

                {/* Grounded Evidence Citations */}
                {!isUser && m.citedEvidence && m.citedEvidence.length > 0 && (
                  <div className="pt-1.5 flex flex-wrap items-center gap-1">
                    <span className="text-[10px] text-noc-muted">Citations:</span>
                    {m.citedEvidence.slice(0, 4).map((cid) => (
                      <span
                        key={cid}
                        className="text-[9px] font-mono bg-noc-bg text-noc-cyan px-1 py-0.2 rounded border border-noc-border"
                      >
                        {cid}
                      </span>
                    ))}
                    {m.citedEvidence.length > 4 && (
                      <span className="text-[9px] text-noc-muted font-mono">
                        +{m.citedEvidence.length - 4} more
                      </span>
                    )}
                  </div>
                )}
              </div>

              {isUser && (
                <div className="w-7 h-7 rounded-full bg-noc-hover border border-noc-border flex items-center justify-center shrink-0 mt-0.5">
                  <User className="w-3.5 h-3.5 text-noc-muted" />
                </div>
              )}
            </div>
          );
        })}

        {(isLoading || isLoadingHistory) && (
          <div className="flex items-center gap-2 text-xs text-noc-muted font-mono py-2 pl-9">
            <div className="w-2 h-2 rounded-full bg-indigo-500 animate-ping" />
            <span>{isLoadingHistory ? 'Restoring session conversation...' : 'Consulting completed session reports...'}</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Box */}
      <div className="p-4 border-t border-noc-border bg-noc-subpanel/50 space-y-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          className="flex items-center gap-2"
        >
          <input
            type="text"
            value={inputQuestion}
            onChange={(e) => setInputQuestion(e.target.value)}
            placeholder={
              hasSessionContext
                ? "Ask about this session's runs, evidence, or symptom..."
                : "Complete a diagnosis to start session Q&A..."
            }
            disabled={isLoading || isLoadingHistory || isClearingHistory || !sessionId || !hasSessionContext}
            className="flex-1 bg-noc-bg border border-noc-border rounded-lg px-3.5 py-2.5 text-xs text-noc-text placeholder-noc-muted focus:outline-none focus:border-indigo-500 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={isLoading || isLoadingHistory || isClearingHistory || !inputQuestion.trim() || !sessionId || !hasSessionContext}
            className="px-3.5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors disabled:opacity-40 flex items-center justify-center cursor-pointer"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>

        <div className="flex items-center justify-between text-[11px] text-noc-muted">
          <span className="flex items-center gap-1 text-[10px]">
            <Info className="w-3 h-3 text-noc-cyan" />
            Read-only assistant strictly restricted from altering incident records.
          </span>
          <span className="font-mono text-[10px]">{messages.length} messages</span>
        </div>
      </div>
    </div>
  );
};
