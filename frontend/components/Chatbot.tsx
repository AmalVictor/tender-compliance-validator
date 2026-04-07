'use client';

import React, {
  useState,
  useRef,
  useEffect,
  useCallback,
  useLayoutEffect,
} from 'react';
import type { ChatMessage } from '@/types';
import {
  streamChatMessage,
  sendChatMessage,
  type RichCitation,
} from '../lib/chat-stream';

// ─── Types ────────────────────────────────────────────────────────────────────

interface EnhancedChatMessage extends ChatMessage {
  citations?: RichCitation[];
  vendorsSearched?: string[];
  isStreaming?: boolean;
  id: string;
}

interface ChatbotProps {
  projectId: string;
  chatOpen: boolean;
  onClose: () => void;
  onOpenPdf?: (vendorDocumentId: number, page: number, vendorName: string) => void;
  vendorNames?: string[];
}

// ─── Markdown renderer ────────────────────────────────────────────────────────

function renderMarkdown(text: string): string {
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  return escaped
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/__(.+?)__/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/_([^_]+?)_/g, '<em>$1</em>')
    .replace(/`([^`]+?)`/g, '<code class="inline-code">$1</code>')
    .replace(/\[Citation (\d+)\]/g, '<span class="cite-ref" data-cite="$1">[Citation&nbsp;$1]</span>')
    .replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>')
    .replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>')
    .replace(/^---+$/gm, '<hr class="md-hr" />')
    .replace(/^\s*[-•]\s+(.+)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>)/g, '<ul class="md-ul">$1</ul>')
    .replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>')
    .replace(/\n\n/g, '</p><p class="md-p">')
    .replace(/\n/g, '<br />');
}

// ─── Quick prompts ────────────────────────────────────────────────────────────

interface QuickPrompt { icon: string; label: string; text: string; }

function buildQuickPrompts(vendors: string[]): QuickPrompt[] {
  if (vendors.length === 0) {
    return [
      { icon: '⚠️', label: 'Key risks',        text: 'Summarize key compliance risks' },
      { icon: '🏆', label: 'Best SLA',          text: 'Which vendor best meets SLA requirements?' },
      { icon: '🔴', label: 'Critical findings', text: 'List all critical risk findings' },
      { icon: '💰', label: 'Pricing',           text: 'Compare pricing across vendors' },
    ];
  }
  if (vendors.length === 1) {
    const v = vendors[0];
    return [
      { icon: '📋', label: 'Compliance gaps', text: `Summarize ${v}'s compliance gaps` },
      { icon: '⚠️', label: 'Risk clauses',    text: `What are ${v}'s key risk clauses?` },
      { icon: '✅', label: 'Mandatory reqs',  text: `Does ${v} meet mandatory requirements?` },
      { icon: '📄', label: 'SLA terms',       text: `What is ${v}'s SLA commitment?` },
    ];
  }
  const [v1, v2] = vendors;
  return [
    { icon: '⚖️', label: 'Compare vendors',  text: `Compare ${v1} vs ${v2} on compliance` },
    { icon: '🛡️', label: 'Lowest risk',      text: 'Which vendor has the lowest risk profile?' },
    { icon: '🏆', label: 'Award rec.',        text: 'Which vendor should we award the contract to?' },
    { icon: '📑', label: 'Liability clauses', text: 'Summarize liability clauses across all vendors' },
  ];
}

// ─── Vendor colours ───────────────────────────────────────────────────────────

const VENDOR_PALETTE = ['#6366F1', '#10B981', '#F59E0B', '#EC4899', '#8B5CF6', '#14B8A6'];
function vendorColor(_name: string, index: number): string {
  return VENDOR_PALETTE[index % VENDOR_PALETTE.length];
}

// ─── Citation card ────────────────────────────────────────────────────────────

function CitationCard({ citation, onOpenPdf, vendorColorMap }: {
  citation: RichCitation;
  onOpenPdf?: (docId: number, page: number, name: string) => void;
  vendorColorMap: Record<string, string>;
}) {
  const color = vendorColorMap[citation.vendor_name] ?? '#6366F1';
  return (
    <div className="cite-card" style={{ borderLeft: `3px solid ${color}` }}>
      <div className="cite-card-header">
        <span className="cite-card-num">[{citation.citation_index}]</span>
        <span className="cite-card-vendor" style={{ color }}>{citation.vendor_name}</span>
        {citation.page_number != null && <span className="cite-card-page">· p.{citation.page_number}</span>}
      </div>
      {citation.section_title && <div className="cite-card-section">§ {citation.section_title}</div>}
      <div className="cite-card-text">
        {citation.text.slice(0, 200)}{citation.text.length > 200 ? '…' : ''}
      </div>
      {onOpenPdf && citation.page_number != null && (
        <button className="cite-card-btn" style={{ background: color }}
          onClick={() => onOpenPdf(citation.vendor_document_id, citation.page_number!, citation.vendor_name)}>
          Open PDF →
        </button>
      )}
    </div>
  );
}

// ─── Message bubble ───────────────────────────────────────────────────────────

function MessageBubble({ msg, onOpenPdf, vendorColorMap }: {
  msg: EnhancedChatMessage;
  onOpenPdf?: (docId: number, page: number, name: string) => void;
  vendorColorMap: Record<string, string>;
}) {
  const [expandedCite, setExpandedCite] = useState<number | null>(null);
  const isAi = msg.role === 'assistant';
  const bubbleRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = bubbleRef.current;
    if (!el) return;
    const handler = (e: MouseEvent) => {
      const target = (e.target as HTMLElement).closest('[data-cite]');
      if (!target) return;
      const idx = Number((target as HTMLElement).dataset.cite);
      setExpandedCite(prev => prev === idx ? null : idx);
    };
    el.addEventListener('click', handler);
    return () => el.removeEventListener('click', handler);
  }, []);

  const expandedCitation = (msg.citations ?? []).find(c => c.citation_index === expandedCite);

  // KEY FIX: show dots only when content is empty AND streaming
  // Never render a second bubble element
  const showDots = isAi && msg.isStreaming && !msg.content;

  return (
    <div className={`msg msg-${isAi ? 'ai' : 'user'}`}>
      {isAi && <div className="msg-lbl">TenderAI</div>}

      {isAi && (msg.vendorsSearched ?? []).length > 0 && (
        <div className="vendor-badges">
          {msg.vendorsSearched!.map((v, i) => (
            <span key={v} className="vendor-badge"
              style={{ background: vendorColor(v, i) + '20', color: vendorColor(v, i), border: `1px solid ${vendorColor(v, i)}44` }}>
              {v}
            </span>
          ))}
        </div>
      )}

      {/* ONE bubble only — dots OR text, never both */}
      {showDots ? (
        <div className="bubble bubble-dots"><span /><span /><span /></div>
      ) : (
        <div ref={bubbleRef} className="bubble"
          dangerouslySetInnerHTML={{ __html: `<p class="md-p">${renderMarkdown(msg.content)}</p>` }} />
      )}

      {/* Cursor after content bubble, not a new element */}
      {isAi && msg.isStreaming && !!msg.content && (
        <span className="stream-cursor" aria-hidden />
      )}

      {expandedCitation && (
        <CitationCard citation={expandedCitation} onOpenPdf={onOpenPdf} vendorColorMap={vendorColorMap} />
      )}

      {isAi && !msg.isStreaming && (msg.citations ?? []).length > 0 && (
        <div className="cite-pills">
          {msg.citations!.map(c => {
            const color = vendorColorMap[c.vendor_name] ?? '#6366F1';
            return (
              <span key={c.citation_index} className="cite-pill"
                style={{ borderColor: color + '55', color }}
                onClick={() => setExpandedCite(prev => prev === c.citation_index ? null : c.citation_index)}>
                [{c.citation_index}] {c.vendor_name}{c.page_number != null ? ` p.${c.page_number}` : ''}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function Chatbot({ projectId, chatOpen, onClose, onOpenPdf, vendorNames = [] }: ChatbotProps) {
  const [messages, setMessages]               = useState<EnhancedChatMessage[]>([]);
  const [input, setInput]                     = useState('');
  const [isStreaming, setIsStreaming]         = useState(false);
  const [vendorsSearched, setVendorsSearched] = useState<string[]>([]);
  const [everOpened, setEverOpened]           = useState(false);

  const abortRef     = useRef<AbortController | null>(null);
  const msgsEndRef   = useRef<HTMLDivElement>(null);
  const inputRef     = useRef<HTMLInputElement>(null);
  const userScrolled = useRef(false);
  const listRef      = useRef<HTMLDivElement>(null);

  // Mount panel DOM once opened so slide animation works
  useEffect(() => { if (chatOpen) setEverOpened(true); }, [chatOpen]);

  const vendorColorMap = React.useMemo<Record<string, string>>(() => {
    const all = [...new Set([...vendorNames, ...vendorsSearched])];
    const map: Record<string, string> = {};
    all.forEach((v, i) => { map[v] = vendorColor(v, i); });
    return map;
  }, [vendorNames, vendorsSearched]);

  const quickPrompts = React.useMemo(() => buildQuickPrompts(vendorNames), [vendorNames]);

  useEffect(() => {
    if (chatOpen && messages.length === 0) {
      const vendorList = vendorNames.length > 0 ? `I have full context on **${vendorNames.join(', ')}**. ` : '';
      setMessages([{
        id: 'greeting', role: 'assistant',
        content: `Hi! I'm TenderAI. ${vendorList}Ask me anything — compliance gaps, risk clauses, vendor comparisons, or award recommendations.`,
      }]);
    }
  }, [chatOpen]);

  useEffect(() => {
    if (!userScrolled.current) msgsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleScroll = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    userScrolled.current = el.scrollHeight - el.scrollTop - el.clientHeight > 40;
  }, []);

  useLayoutEffect(() => {
    if (chatOpen) setTimeout(() => inputRef.current?.focus(), 320);
  }, [chatOpen]);

  const stopStreaming = () => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setMessages(prev => prev.map((m, i) => i === prev.length - 1 ? { ...m, isStreaming: false } : m));
  };

  const send = useCallback(async (overrideText?: string) => {
    const text = (overrideText ?? input).trim();
    if (!text || isStreaming) return;

    const userMsgId = `user-${Date.now()}`;
    const asMsgId   = `ai-${Date.now()}`;

    const userMsg: EnhancedChatMessage = { id: userMsgId, role: 'user', content: text };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsStreaming(true);
    userScrolled.current = false;

    // Single placeholder — starts empty (renders dots), fills with content as tokens arrive
    setMessages(prev => [...prev, { id: asMsgId, role: 'assistant', content: '', isStreaming: true }]);

    const history: ChatMessage[] = messages.concat(userMsg).map(m => ({ role: m.role, content: m.content }));
    let streamWorked = false;

    abortRef.current = streamChatMessage(projectId, { message: text, history, documentIds: [] }, {
      onVendors: (vendors) => {
        setVendorsSearched(vendors);
        setMessages(prev => prev.map(m => m.id === asMsgId ? { ...m, vendorsSearched: vendors } : m));
      },
      onToken: (_token, accumulated) => {
        streamWorked = true;
        const display = accumulated
          .replace(/^\s*\{?\s*"reply"\s*:\s*"/, '')
          .replace(/"\s*\}?\s*$/, '');
        setMessages(prev => prev.map(m => m.id === asMsgId ? { ...m, content: display } : m));
      },
      onCitations: (citations) => {
        setMessages(prev => prev.map(m => m.id === asMsgId ? { ...m, citations } : m));
      },
      onDone: (fullReply, citations) => {
        const clean = fullReply
          .replace(/^\s*\{?\s*"reply"\s*:\s*"/, '')
          .replace(/"\s*\}?\s*$/, '');
        setMessages(prev => prev.map(m =>
          m.id === asMsgId ? { ...m, content: clean, citations, isStreaming: false } : m
        ));
        setIsStreaming(false);
      },
      onError: async () => {
        if (!streamWorked) {
          try {
            const resp = await sendChatMessage(projectId, { message: text, history });
            setMessages(prev => prev.map(m =>
              m.id === asMsgId ? { ...m, content: resp.reply, citations: resp.citations, vendorsSearched: resp.vendors_searched, isStreaming: false } : m
            ));
          } catch {
            setMessages(prev => prev.map(m =>
              m.id === asMsgId ? { ...m, content: "I'm sorry, I encountered an error. Please try again.", isStreaming: false } : m
            ));
          }
        } else {
          setMessages(prev => prev.map(m => m.id === asMsgId ? { ...m, isStreaming: false } : m));
        }
        setIsStreaming(false);
      },
    });
  }, [input, isStreaming, messages, projectId]);

  const handleSuggestion = (text: string) => { if (!isStreaming) setTimeout(() => send(text), 10); };
  const showQuickPrompts = messages.length <= 1 && !isStreaming;

  if (!everOpened) return null;

  return (
    <>
      <style>{CHAT_STYLES + CHAT_STYLES_ADDITIONS}</style>

      {/* Backdrop */}
      <div className={`chat-backdrop ${chatOpen ? 'chat-backdrop--on' : ''}`} onClick={onClose} />

      {/* Slide-in panel */}
      <div className={`rp-v2 ${chatOpen ? 'rp-v2--open' : ''}`}>

        {/* Header */}
        <div className="rp-head">
          <div className="rp-head-icon">
            <svg width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="white" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="rp-title">TenderAI</div>
            <div className="rp-subtitle">
              {isStreaming
                ? <span className="rp-live">● Analysing proposals…</span>
                : vendorsSearched.length > 0
                  ? `${vendorsSearched.length} vendor${vendorsSearched.length > 1 ? 's' : ''} in context`
                  : 'Procurement assistant'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {isStreaming && (
              <button className="btn-stop" onClick={stopStreaming}>
                <svg width="9" height="9" viewBox="0 0 9 9" fill="currentColor"><rect width="9" height="9" rx="1.5" /></svg>
                Stop
              </button>
            )}
            <button className="rp-close" onClick={onClose} aria-label="Close">
              <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="chat-msgs" ref={listRef} onScroll={handleScroll}>
          {messages.map((msg, idx) => (
            <div
              key={msg.id}
              className="chat-msg-wrapper"
              style={{ animationDelay: idx === 0 ? '0ms' : '0ms' }}
            >
              <MessageBubble msg={msg} onOpenPdf={onOpenPdf} vendorColorMap={vendorColorMap} />
            </div>
          ))}
          <div ref={msgsEndRef} />
        </div>

        {/* Quick prompts — 2×2 card grid */}
        {showQuickPrompts && (
          <div className="quick-section">
            <div className="quick-label">Suggested questions</div>
            <div className="quick-grid">
              {quickPrompts.map(p => (
                <button key={p.text} className="quick-card" onClick={() => handleSuggestion(p.text)}>
                  <span className="quick-card-icon">{p.icon}</span>
                  <span className="quick-card-label">{p.label}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Input */}
        <div className="ci">
          <input
            ref={inputRef}
            className="ci-input"
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder={isStreaming ? 'Generating…' : 'Ask about compliance, risks, vendors…'}
            disabled={isStreaming}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); send(); } }}
          />
          <button className="ci-send" disabled={!input.trim() || isStreaming} onClick={() => send()} aria-label="Send">
            <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
            </svg>
          </button>
        </div>
      </div>
    </>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const CHAT_STYLES = `
.chat-backdrop {
  position: fixed; inset: 0; z-index: 49;
  background: transparent; pointer-events: none;
  transition: background 0.3s ease;
}
.chat-backdrop--on {
  background: rgba(0,0,0,0.22);
  pointer-events: all;
}

.rp-v2 {
  position: fixed; top: 0; right: 0; bottom: 0;
  width: 390px; max-width: 95vw; z-index: 50;
  display: flex; flex-direction: column;
  background: var(--bg, #ffffff);
  box-shadow: -6px 0 32px rgba(0,0,0,0.1);
  border-left: 1px solid var(--border, #e5e7eb);
  transform: translateX(100%);
  transition: transform 0.32s cubic-bezier(0.32,0.72,0,1);
}
.rp-v2--open { transform: translateX(0); }

.rp-head {
  display: flex; align-items: center; gap: 10px;
  padding: 14px 16px 13px;
  border-bottom: 1px solid var(--border, #e5e7eb);
  flex-shrink: 0;
}
.rp-head-icon {
  width: 32px; height: 32px; flex-shrink: 0;
  background: var(--ac, #6366F1); border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 8px rgba(99,102,241,0.3);
}
.rp-title   { font-size: 13.5px; font-weight: 700; color: var(--fg, #111827); line-height: 1.2; }
.rp-subtitle { font-size: 11px; color: var(--fg2, #6b7280); margin-top: 1px; }
.rp-live    { color: #10b981; font-weight: 500; }
.rp-close {
  width: 28px; height: 28px; border-radius: 7px; border: none;
  display: flex; align-items: center; justify-content: center;
  background: transparent; cursor: pointer; color: var(--fg2, #6b7280);
  transition: background 0.15s;
}
.rp-close:hover { background: var(--bg2, #f3f4f6); color: var(--fg, #111); }

.btn-stop {
  display: flex; align-items: center; gap: 4px;
  font-size: 11px; font-weight: 600; padding: 4px 10px;
  border-radius: 6px; background: #fee2e2; color: #dc2626;
  border: 1px solid #fca5a5; cursor: pointer;
}
.btn-stop:hover { background: #fecaca; }

.chat-msgs {
  flex: 1; overflow-y: auto;
  padding: 16px 14px;
  display: flex; flex-direction: column; gap: 14px;
  scroll-behavior: smooth;
}
.chat-msgs::-webkit-scrollbar { width: 4px; }
.chat-msgs::-webkit-scrollbar-thumb { background: #e5e7eb; border-radius: 4px; }

.msg { display: flex; flex-direction: column; gap: 4px; }
.msg-user { align-items: flex-end; }
.msg-lbl {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--ac, #6366F1); margin-bottom: 1px;
}

.bubble {
  padding: 10px 13px; border-radius: 14px;
  font-size: 13px; line-height: 1.65; word-break: break-word;
  color: var(--fg, #111827); max-width: 100%;
}
.msg-ai .bubble {
  background: var(--bg2, #f9fafb);
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 4px 14px 14px 14px;
}
.msg-user .bubble {
  background: var(--ac, #6366F1); color: #fff;
  border-radius: 14px 14px 4px 14px; max-width: 86%;
}

/* Typing dots — ONE bubble, no sibling bubble */
.bubble-dots {
  display: flex; align-items: center; gap: 5px;
  padding: 13px 16px; width: fit-content;
  background: var(--bg2, #f9fafb);
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 4px 14px 14px 14px;
}
.bubble-dots span {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--ac, #6366F1); opacity: 0.4;
  animation: tdots 1.3s ease-in-out infinite;
}
.bubble-dots span:nth-child(2) { animation-delay: 0.18s; }
.bubble-dots span:nth-child(3) { animation-delay: 0.36s; }
@keyframes tdots {
  0%,80%,100% { transform: scale(0.6); opacity: 0.3; }
  40%          { transform: scale(1);   opacity: 1;   }
}

.stream-cursor {
  display: inline-block; width: 2px; height: 14px;
  background: var(--ac, #6366F1); border-radius: 1px;
  vertical-align: text-bottom; margin-left: 2px;
  animation: blink 0.75s step-end infinite;
}
@keyframes blink { 50% { opacity: 0; } }

.bubble .md-p  { margin: 0 0 6px; }
.bubble .md-p:last-child { margin: 0; }
.bubble .md-h3 { font-size: 13px; font-weight: 700; margin: 10px 0 4px; }
.bubble .md-h4 { font-size: 12px; font-weight: 600; margin: 8px 0 3px; }
.bubble .md-ul { padding-left: 18px; margin: 4px 0; }
.bubble .md-ul li { margin-bottom: 3px; }
.bubble .md-hr { border: none; border-top: 1px solid #e5e7eb; margin: 8px 0; }
.bubble .inline-code {
  font-family: monospace; font-size: 11.5px;
  background: rgba(99,102,241,0.09); color: #6366F1;
  padding: 1px 5px; border-radius: 4px;
}
.bubble .cite-ref {
  font-size: 11px; font-weight: 700;
  color: var(--ac, #6366F1); background: rgba(99,102,241,0.1);
  padding: 0 4px; border-radius: 4px; cursor: pointer;
  border-bottom: 1px dashed rgba(99,102,241,0.5);
}
.bubble .cite-ref:hover { background: rgba(99,102,241,0.2); }

.vendor-badges { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 5px; }
.vendor-badge { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 20px; letter-spacing: 0.02em; }

.cite-pills { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 7px; }
.cite-pill {
  font-size: 10.5px; font-weight: 500; padding: 3px 9px;
  border-radius: 20px; border: 1px solid; cursor: pointer;
  background: transparent; transition: opacity 0.15s;
}
.cite-pill:hover { opacity: 0.7; }

.cite-card {
  margin-top: 7px; padding: 9px 11px; border-radius: 9px;
  background: var(--bg, #fff); border: 1px solid var(--border, #e5e7eb);
  font-size: 11.5px; animation: fadeSlide 0.18s ease;
}
@keyframes fadeSlide { from { opacity:0; transform:translateY(-3px); } to { opacity:1; transform:none; } }
.cite-card-header { display: flex; align-items: center; gap: 5px; margin-bottom: 3px; }
.cite-card-num    { font-weight: 700; }
.cite-card-vendor { font-weight: 700; }
.cite-card-page   { color: var(--fg2, #6b7280); }
.cite-card-section { font-size: 11px; color: var(--fg2, #6b7280); margin-bottom: 5px; }
.cite-card-text   { color: var(--fg, #374151); line-height: 1.5; margin-bottom: 7px; }
.cite-card-btn    { font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 5px; color: #fff; border: none; cursor: pointer; }
.cite-card-btn:hover { opacity: 0.85; }

/* Quick prompts — 2×2 card grid */
.quick-section {
  padding: 0 14px 12px;
  border-top: 1px solid var(--border, #f0f0f0);
}
.quick-label {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.07em; color: var(--fg2, #9ca3af); padding: 10px 0 8px;
}
.quick-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.quick-card {
  display: flex; flex-direction: column; align-items: flex-start;
  gap: 4px; padding: 9px 11px; border-radius: 10px;
  background: var(--bg2, #f9fafb); border: 1px solid var(--border, #e5e7eb);
  cursor: pointer; text-align: left;
  transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
}
.quick-card:hover {
  border-color: rgba(99,102,241,0.4); background: rgba(99,102,241,0.04);
  box-shadow: 0 2px 8px rgba(99,102,241,0.08);
}
.quick-card-icon  { font-size: 16px; line-height: 1; }
.quick-card-label { font-size: 11.5px; font-weight: 600; color: var(--fg, #374151); line-height: 1.3; }

/* Input */
.ci {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px; border-top: 1px solid var(--border, #e5e7eb);
  background: var(--bg, #fff); flex-shrink: 0;
}
.ci-input {
  flex: 1; min-width: 0; font-size: 13px; padding: 8px 12px;
  border: 1.5px solid var(--border, #e5e7eb); border-radius: 10px;
  outline: none; background: var(--bg2, #f9fafb); color: var(--fg, #111827);
  transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
}
.ci-input:focus {
  border-color: var(--ac, #6366F1); background: var(--bg, #fff);
  box-shadow: 0 0 0 3px rgba(99,102,241,0.1);
}
.ci-input:disabled { opacity: 0.45; cursor: not-allowed; }
.ci-send {
  width: 36px; height: 36px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: var(--ac, #6366F1); color: #fff;
  border: none; border-radius: 10px; cursor: pointer;
  transition: background 0.15s, transform 0.1s;
}
.ci-send:hover:not(:disabled) { background: #4f52d9; }
.ci-send:active:not(:disabled) { transform: scale(0.93); }
.ci-send:disabled { opacity: 0.35; cursor: not-allowed; }
`;

const CHAT_STYLES_ADDITIONS = `
/* ── Message entrance animation ── */
.chat-msg-wrapper {
  animation: chatMsgIn 0.22s cubic-bezier(0.32, 0.72, 0, 1) both;
}
@keyframes chatMsgIn {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

/* ── Quick card hover lift ── */
.quick-card {
  transition: border-color 0.15s, background 0.15s, box-shadow 0.15s, transform 0.15s !important;
}
.quick-card:hover {
  transform: translateY(-1px) !important;
}
.quick-card:active {
  transform: scale(0.97) !important;
}

/* ── Send button — press animation ── */
.ci-send:active:not(:disabled) {
  transform: scale(0.9) !important;
}

/* ── Streaming live indicator pulse ── */
.rp-live {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.rp-live::before {
  content: '';
  display: inline-block;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #10b981;
  animation: livePing 1.6s ease infinite;
}
@keyframes livePing {
  0%,100% { opacity: 1; transform: scale(1); box-shadow: 0 0 0 0 rgba(16,185,129,.4); }
  50%      { opacity: .9; transform: scale(1.1); box-shadow: 0 0 0 5px rgba(16,185,129,0); }
}
`;

export { CHAT_STYLES_ADDITIONS };