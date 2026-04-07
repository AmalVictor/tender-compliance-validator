'use client';

/**
 * DeepDive.tsx — Traceability Inspector
 *
 *
 */

import React, { useState, useCallback, useEffect } from 'react';
import { createPortal } from 'react-dom';
import type { AuditResults } from '@/types';
import { recordDecision, getDecisionsByProject, getDocumentFileUrl } from '../lib/api';
import { useToast } from '@/context/ToastContext';
import { StatusBadge } from './StatusBadge';
import TracePdfViewer from './TracePdfViewer';

// ─── Portal modal shell ───────────────────────────────────────────────────────

function FloatingModal({
  onClose, children, width = 460,
}: {
  onClose: () => void; children: React.ReactNode; width?: number;
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', h);
    return () => document.removeEventListener('keydown', h);
  }, [onClose]);

  return createPortal(
    <div className="fm-backdrop" onClick={onClose}>
      <div
        className="fm-panel"
        style={{ width, maxWidth: 'min(95vw, 95%)' }}
        onClick={e => e.stopPropagation()}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}

function FMHead({ title, onClose }: { title: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fm-head">
      <div className="fm-title">{title}</div>
      <button className="fm-close" onClick={onClose} aria-label="Close">
        <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}

function FMFoot({ children }: { children: React.ReactNode }) {
  return <div className="fm-foot">{children}</div>;
}

// ─── Context strip ────────────────────────────────────────────────────────────

function MatchCtx({ clauseRef, vendorName, status, confidence }: {
  clauseRef: string; vendorName: string; status: string; confidence: number;
}) {
  const clr: Record<string, [string, string]> = {
    FULL: ['#27500A', '#EAF3DE'], PARTIAL: ['#633806', '#FAEEDA'], NONE: ['#791F1F', '#FCEBEB'],
  };
  const [fg, bg] = clr[status] ?? ['var(--fg)', 'var(--bg2)'];
  return (
    <div className="fm-context">
      <strong style={{ display: 'block', marginBottom: 4, fontSize: 12 }}>{clauseRef} · {vendorName}</strong>
      <span style={{ fontSize: 11, color: 'var(--fg2)' }}>
        AI verdict:{' '}
        <span style={{ fontWeight: 600, color: fg, background: bg, padding: '1px 6px', borderRadius: 4 }}>
          {status}
        </span>
        {' · '}{Math.round(confidence * 100)}% confidence
      </span>
    </div>
  );
}

// ─── Verdict picker ───────────────────────────────────────────────────────────

const VP_OPTIONS = [
  { v: 'FULL', icon: '✓', label: 'Full', cls: 'vp-full' },
  { v: 'PARTIAL', icon: '⚠', label: 'Partial', cls: 'vp-partial' },
  { v: 'NONE', icon: '✗', label: 'None', cls: 'vp-none' },
] as const;

function VerdictPicker({ value, onChange }: {
  value: 'FULL' | 'PARTIAL' | 'NONE';
  onChange: (v: 'FULL' | 'PARTIAL' | 'NONE') => void;
}) {
  return (
    <div className="verdict-pick">
      {VP_OPTIONS.map(o => (
        <button key={o.v} type="button"
          className={`vp-option ${value === o.v ? o.cls : ''}`}
          onClick={() => onChange(o.v)}>
          <span className="vp-icon">{o.icon}</span>
          <span className="vp-label">{o.label}</span>
        </button>
      ))}
    </div>
  );
}

// ─── Annotate modal ───────────────────────────────────────────────────────────

function AnnotateModal({
  clauseRef, vendorName, matchStatus, confidence, onClose, onSuccess,
  matchId, requirementId, vendorDocumentId,
}: {
  clauseRef: string; vendorName: string; matchStatus: string; confidence: number;
  onClose: () => void; onSuccess: (data: { message: string; note: string }) => void;
  matchId: number; requirementId: number; vendorDocumentId: number;
}) {
  const [note, setNote] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [busy, setBusy] = useState(false);
  const { showError } = useToast();

  const submit = async () => {
    if (!note.trim()) { showError('Please enter a note.'); return; }
    setBusy(true);
    try {
      await recordDecision({
        match_id: matchId, requirement_id: requirementId, vendor_document_id: vendorDocumentId,
        decision_type: 'ANNOTATED', reviewer_note: note, reviewer_name: reviewer || 'Reviewer',
      });
      onSuccess({ message: 'Annotation recorded.', note }); onClose();
    } catch (e: any) { showError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <FloatingModal onClose={onClose}>
      <FMHead title="Add annotation" onClose={onClose} />
      <div className="fm-body">
        <MatchCtx clauseRef={clauseRef} vendorName={vendorName} status={matchStatus} confidence={confidence} />
        <div className="fm-field">
          <label className="fm-label">Your note</label>
          <p className="fm-hint">Add context the AI may have missed — verbal clarifications, Q&amp;A responses, site visits.</p>
          <textarea className="fm-textarea" rows={4}
            placeholder="e.g. Vendor verbally confirmed 99.9% SLA upgrade in Q&A on 5 Apr — awaiting written confirmation."
            value={note} onChange={e => setNote(e.target.value)} disabled={busy} />
        </div>
        <div className="fm-field" style={{ marginBottom: 0 }}>
          <label className="fm-label">Reviewer name <span className="fm-opt">optional</span></label>
          <input className="fm-input" type="text" placeholder="Your name"
            value={reviewer} onChange={e => setReviewer(e.target.value)} disabled={busy} />
        </div>
      </div>
      <FMFoot>
        <button className="fm-btn-cancel" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="fm-btn-submit" onClick={submit} disabled={busy || !note.trim()}>
          {busy ? 'Saving…' : 'Record annotation'}
        </button>
      </FMFoot>
    </FloatingModal>
  );
}

// ─── Override modal ───────────────────────────────────────────────────────────

function OverrideModal({
  clauseRef, vendorName, matchStatus, confidence, onClose, onSuccess,
  matchId, requirementId, vendorDocumentId,
}: {
  clauseRef: string; vendorName: string; matchStatus: string; confidence: number;
  onClose: () => void; onSuccess: (data: { message: string; verdict: string; note: string }) => void;
  matchId: number; requirementId: number; vendorDocumentId: number;
}) {
  const [verdict, setVerdict] = useState<'FULL' | 'PARTIAL' | 'NONE'>('PARTIAL');
  const [note, setNote] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [busy, setBusy] = useState(false);
  const { showError } = useToast();

  const submit = async () => {
    if (!note.trim()) { showError('Please explain why you are overriding.'); return; }
    setBusy(true);
    try {
      await recordDecision({
        match_id: matchId, requirement_id: requirementId, vendor_document_id: vendorDocumentId,
        decision_type: 'OVERRIDDEN', override_status: verdict,
        reviewer_note: note, reviewer_name: reviewer || 'Reviewer',
      });
      onSuccess({ message: `Verdict overridden to ${verdict}.`, verdict, note }); onClose();
    } catch (e: any) { showError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <FloatingModal onClose={onClose}>
      <FMHead title="Override AI verdict" onClose={onClose} />
      <div className="fm-body">
        <MatchCtx clauseRef={clauseRef} vendorName={vendorName} status={matchStatus} confidence={confidence} />
        <div className="fm-field">
          <label className="fm-label">New verdict</label>
          <VerdictPicker value={verdict} onChange={setVerdict} />
        </div>
        <div className="fm-field">
          <label className="fm-label">
            Reason for override <span className="fm-req">required</span>
          </label>
          <p className="fm-hint">Recorded in the audit trail and exported PDF.</p>
          <textarea className="fm-textarea" rows={4}
            placeholder="Explain why you disagree with the AI classification."
            value={note} onChange={e => setNote(e.target.value)} disabled={busy} />
        </div>
        <div className="fm-field" style={{ marginBottom: 0 }}>
          <label className="fm-label">Reviewer name <span className="fm-opt">optional</span></label>
          <input className="fm-input" type="text" placeholder="Your name"
            value={reviewer} onChange={e => setReviewer(e.target.value)} disabled={busy} />
        </div>
      </div>
      <FMFoot>
        <button className="fm-btn-cancel" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="fm-btn-submit fm-btn-danger" onClick={submit} disabled={busy || !note.trim()}>
          {busy ? 'Saving…' : `Override to ${verdict}`}
        </button>
      </FMFoot>
    </FloatingModal>
  );
}

// ─── Diff modal ───────────────────────────────────────────────────────────────

function DiffModal({ matrix, vendor_scores, selectedReqId, onClose }: {
  matrix: AuditResults['matrix'];
  vendor_scores: AuditResults['vendor_scores'];
  selectedReqId: string;
  onClose: () => void;
}) {
  const [v1, setV1] = useState(0);
  const [v2, setV2] = useState(Math.min(1, vendor_scores.length - 1));

  
  const row = matrix.find(r => String(r.requirement.id) === String(selectedReqId));
  const req = row?.requirement;

  const pairs: Array<[number, number]> = [];
  for (let i = 0; i < vendor_scores.length; i++)
    for (let j = i + 1; j < vendor_scores.length; j++)
      pairs.push([i, j]);

  return (
    <FloatingModal onClose={onClose} width={760}>
      <FMHead
        title={
          <span>
            Vendor comparison{' '}
            <span style={{ fontWeight: 400, fontSize: 12, color: 'var(--fg2)' }}>
              {req?.rfp_clause_ref ?? req?.id}
            </span>
          </span>
        }
        onClose={onClose}
      />
      <div className="fm-body">
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
          {pairs.map(([i, j]) => (
            <button key={`${i}-${j}`}
              className={`diff-pair-btn ${v1 === i && v2 === j ? 'on' : ''}`}
              onClick={() => { setV1(i); setV2(j); }}>
              {vendor_scores[i].vendor_name.split(' ')[0]} vs {vendor_scores[j].vendor_name.split(' ')[0]}
            </button>
          ))}
        </div>
        <div className="diff-cols">
          {[v1, v2].map((vIdx, colIdx) => {
            const vs = vendor_scores[vIdx];
            const match = row?.matches[vIdx];
            const conf = match ? Math.round((match.confidence ?? 0) * 100) : 0;
            return (
              <div key={colIdx} className="diff-col">
                <div className="diff-col-head">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: vs?.vendor_color ?? '#888' }} />
                    <span style={{ fontWeight: 600, fontSize: 13 }}>{vs?.vendor_name}</span>
                  </div>
                  {match && <StatusBadge status={match.status} size="chip" />}
                </div>
                <div className="doc-viewer">
                  <div className="doc-viewer-head">{vs?.vendor_name} · Proposal</div>
                  {match?.evidence || match?.evidence_quote ? (
                    <span className={match.status === 'FULL' ? 'hl-ev' : 'hl-miss'}>
                      {match.evidence ?? match.evidence_quote}
                    </span>
                  ) : (
                    <span style={{ color: 'var(--t3)', fontStyle: 'italic' }}>No evidence found.</span>
                  )}
                </div>
                {match && (
                  <div className="ai-box" style={{ marginTop: 8 }}>
                    <div className="ai-head"><div className="ai-spark">✦</div>AI assessment</div>
                    <div className="ai-body-txt" style={{ fontSize: 12 }}>
                      {match.explanation ?? `Confidence: ${conf}%`}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <FMFoot>
        <button className="fm-btn-cancel" onClick={onClose}>Close</button>
      </FMFoot>
    </FloatingModal>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

type ModalKind = 'annotate' | 'override' | 'diff' | null;

interface DeepDiveProps {
  auditResults: AuditResults;
  initialReqId?: string;
}

export function DeepDive({ auditResults, initialReqId }: DeepDiveProps) {
  const { matrix, vendor_scores } = auditResults;
  const { showError, showSuccess } = useToast();

  // Initialise selectedReqId as a string, coercing the first id if needed
  const [selectedReqId, setSelectedReqId] = useState(
    initialReqId ?? String(matrix[0]?.requirement.id ?? ''),
  );
  const [selectedVendorIdx, setSelectedVendorIdx] = useState(0);
  const [trailOpen, setTrailOpen] = useState(false);
  const [modal, setModal] = useState<ModalKind>(null);
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [decisions, setDecisions] = useState<Record<string, any>>({});
  const [pdfModalOpen, setPdfModalOpen] = useState(false);
  const [pdfConfig, setPdfConfig] = useState<{ url: string; pageNumber: number; bbox?: number[] | null } | null>(null);

  // Load decisions from backend on mount
  useEffect(() => {
    async function loadDecisions() {
      try {
        const data = await getDecisionsByProject((auditResults as any).project_id);
        const map: Record<string, any> = {};
        data.forEach((d: any) => {
          const key = `${d.requirement_id}-${d.vendor_document_id}`;
          map[key] = d;
        });
        setDecisions(map);
      } catch (e) {
        console.error('Failed to load decisions', e);
      }
    }
    loadDecisions();
  }, [(auditResults as any).project_id]);

  const vendorNames = vendor_scores.map(v => v.vendor_name);

  
  const selectedRow = matrix.find(r => String(r.requirement.id) === String(selectedReqId)) ?? matrix[0];
  const selectedMatch = selectedRow?.matches[selectedVendorIdx];
  const selectedVendor = vendor_scores[selectedVendorIdx];
  const reqId = Number(selectedReqId);
  const vendorDocId = selectedMatch?.vendor_document_id ? Number(selectedMatch.vendor_document_id) : 0;
  const acceptKey = `${reqId}-${vendorDocId}`;
  const decision = decisions[`${reqId}-${vendorDocId}`];
  const isAccepted = accepted[acceptKey] ?? false;
  const closeModal = useCallback(() => setModal(null), []);

  if (!selectedRow) {
    return (
      <div className="card" style={{ padding: 40, textAlign: 'center', color: 'var(--t3)' }}>
        No audit data available. Run an audit first.
      </div>
    );
  }

  const req = selectedRow.requirement;
  const clauseRef = req.rfp_clause_ref ?? `Clause ${req.id}`;
  let conf = selectedMatch?.confidence ?? 0;
  let displayStatus = selectedMatch?.status;
  if (decision?.type === 'OVERRIDDEN' || decision?.decision_type === 'OVERRIDDEN') {
    displayStatus = decision.override_status || decision.override;
    conf = 1.0;
  }
  const matchId = Number((selectedMatch as any)?.id ?? 0);

  const handleAccept = async () => {
    setAccepted(prev => ({ ...prev, [acceptKey]: true }));
    try {
      await recordDecision({
        match_id: matchId, requirement_id: reqId, vendor_document_id: vendorDocId,
        decision_type: 'ACCEPTED', reviewer_name: 'Reviewer',
      });
      showSuccess('Decision recorded: Accepted.');
    } catch (e: any) {
      showError(e.message);
      setAccepted(prev => ({ ...prev, [acceptKey]: false }));
    }
  };

  const handleOpenPdf = () => {
    if (!selectedMatch?.vendor_document_id) {
      showError('Document ID not found.');
      return;
    }
    let pageNum = (selectedMatch as any).page_number;
    if (!pageNum && selectedMatch.section_ref) {
      const m = selectedMatch.section_ref.match(/PAGE\s*(\d+)/i);
      if (m) pageNum = parseInt(m[1], 10);
    }
    setPdfConfig({
      url: getDocumentFileUrl(selectedMatch.vendor_document_id),
      pageNumber: pageNum || 1,
      bbox: (selectedMatch as any).bbox || null,
    });
    setPdfModalOpen(true);
  };

  const VM: Record<string, { icon: string; label: string; sub: string; bg: string; iconBg: string }> = {
    FULL: { icon: '✓', label: 'Fully addressed', sub: `${selectedVendor?.vendor_name} satisfies this requirement. Confidence ${Math.round(conf * 100)}%.`, bg: '#EAF3DE', iconBg: '#C0DD97' },
    PARTIAL: { icon: '⚠', label: 'Partially addressed', sub: `${selectedVendor?.vendor_name} partially meets this requirement. Review evidence carefully.`, bg: '#FAEEDA', iconBg: '#FAC775' },
    NONE: { icon: '✗', label: 'Not addressed', sub: `No evidence found in ${selectedVendor?.vendor_name}'s proposal.`, bg: '#FCEBEB', iconBg: '#F7C1C1' },
  };
  const vm = VM[displayStatus ?? ''] ?? null;

  const auditLog = [
    { dot: 'var(--ac)', text: <>AI extracted <strong>{clauseRef}</strong> from RFP</>, human: false },
    { dot: '#10B981',   text: <>User <strong>confirmed</strong> requirement during review</>, human: true },
    selectedMatch ? { dot: selectedVendor?.vendor_color ?? '#888', text: <>AI classified <strong>{selectedMatch.status}</strong> · {Math.round((selectedMatch.confidence ?? 0) * 100)}% confidence</>, human: false } : null,
    isAccepted    ? { dot: 'var(--ac)', text: <>User <strong>accepted</strong> AI assessment for {selectedVendor?.vendor_name}</>, human: true } : null,
    (decision?.type === 'ANNOTATED' || decision?.decision_type === 'ANNOTATED') ? { dot: '#6366F1', text: <>User <strong>annotated</strong>: "{decision.note || decision.reviewer_note}"</>, human: true } : null,
    (decision?.type === 'OVERRIDDEN' || decision?.decision_type === 'OVERRIDDEN') ? { dot: '#DC2626', text: <>User <strong>overrode</strong> verdict to <strong>{decision.override || decision.override_status}</strong></>, human: true } : null,
  ].filter(Boolean) as Array<{ dot: string; text: React.ReactNode; human: boolean }>;

  return (
    <>
      <style>{STYLES}</style>

      {/* Selector */}
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="ch">
          <div className="ct">Traceability inspector</div>
          <div className="dd-selector">
            <select className="req-select" value={selectedReqId}
              onChange={e => { setSelectedReqId(e.target.value); setSelectedVendorIdx(0); }}>
              {matrix.map(row => (
                <option key={row.requirement.id} value={row.requirement.id}>
                  {row.requirement.rfp_clause_ref || row.requirement.id} — {(row.requirement.normalised || row.requirement.raw_text).substring(0, 60)}
                </option>
              ))}
            </select>
            <div className="vendor-btns">
              {vendorNames.map((name, i) => (
                <button key={name} className={`vbtn ${selectedVendorIdx === i ? 'on' : ''}`}
                  onClick={() => setSelectedVendorIdx(i)}>
                  {name.split(' ')[0]}
                </button>
              ))}
            </div>
            {vendorNames.length >= 2 && (
              <button className="btn btn-g btn-sm" onClick={() => setModal('diff')}>Compare 2 vendors</button>
            )}
          </div>
        </div>
      </div>

      {/* Split pane */}
      <div className="dd-grid">
        {/* Left: RFP */}
        <div className="dd-pane">
          <div className="dp-head">
            <div className="dp-ht">RFP requirement</div>
            <div className="dp-ref">{clauseRef}{req.page_number ? `, page ${req.page_number}` : ''}</div>
          </div>
          <div className="dp-body">
            <div style={{ fontSize: 13.5, lineHeight: 1.8, marginBottom: 14 }}>
              <strong>{req.rfp_clause_ref ? `Clause ${req.rfp_clause_ref} — ` : ''}</strong>
              {req.normalised || req.raw_text}
            </div>
            <div className="dp-sub-label">Source document</div>
            <div className="doc-viewer">
              <div className="doc-viewer-head">RFP Document{req.section_title ? ` · ${req.section_title}` : ''}{req.page_number ? ` · Page ${req.page_number}` : ''}</div>
              <div>...{req.rfp_clause_ref ? `§${req.rfp_clause_ref} ` : ''}The vendor shall{' '}
                <span className="hl-rfp">{req.normalised || req.raw_text}</span>
                {'. '}This obligation is mandatory...
              </div>
              {req.page_number && <div className="doc-page-num">Page {req.page_number}</div>}
            </div>
            <div className="ai-box intent-box" style={{ marginTop: 12 }}>
              <div className="ai-head intent-head">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 21 12 17.77 5.82 21 7 14.14l-5-4.87 6.91-1.01L12 2z" />
                </svg>
                RFP intent
              </div>
              <div className="ai-body-txt" style={{ color: '#0A5954', fontSize: 12 }}>
                This is a <strong>{req.criticality === 'Mandatory' ? 'hard mandatory requirement' : 'recommended requirement'}</strong>.{' '}
                {req.criticality === 'Mandatory'
                  ? 'Non-compliance cannot be waived and would require renegotiation or disqualification before award.'
                  : 'Non-compliance may be acceptable with suitable justification.'}
              </div>
            </div>
          </div>
        </div>

        {/* Right: Vendor */}
        <div className="dd-pane">
          <div className="dp-head">
            <div className="dp-ht" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: selectedVendor?.vendor_color ?? '#888' }} />
              {selectedVendor?.vendor_name ?? 'Vendor'}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {selectedMatch && <StatusBadge status={displayStatus as any} size="chip" />}
              {(decision?.type === 'OVERRIDDEN' || decision?.decision_type === 'OVERRIDDEN') && (
                <span style={{ fontSize: 11, padding: '2px 6px', background: '#FCEBEB', color: '#7f1d1d', borderRadius: 4, fontWeight: 600 }}>
                  🔄 Overridden
                </span>
              )}
              {selectedMatch && <span className="mono text-xs" style={{ color: 'var(--t3)' }}>{Math.round(conf * 100)}% conf.</span>}
            </div>
          </div>
          <div className="dp-body">
            <div className="dp-sub-label">
              Evidence source{' '}
              {selectedMatch?.section_ref && (
                <span className="src-link" onClick={handleOpenPdf} style={{ cursor: 'pointer', textDecoration: 'underline' }}>
                  📎 {selectedMatch.section_ref} ↗
                </span>
              )}
            </div>
            <div className="doc-viewer">
              <div className="doc-viewer-head">
                {selectedVendor?.vendor_name ?? 'Vendor'} proposal{selectedMatch?.section_ref ? ` · ${selectedMatch.section_ref}` : ''}
              </div>
              {selectedMatch?.evidence || selectedMatch?.evidence_quote ? (
                <div>...<span className={selectedMatch.status === 'FULL' ? 'hl-ev' : selectedMatch.status === 'NONE' ? 'hl-miss' : 'hl-rfp'}>
                  {selectedMatch.evidence ?? selectedMatch.evidence_quote}
                </span>...</div>
              ) : (
                <div style={{ color: 'var(--t3)', fontStyle: 'italic' }}>
                  {selectedMatch?.status === 'NONE' ? 'No relevant passage found.' : 'Evidence quote not available.'}
                </div>
              )}
            </div>

            {vm && (
              <div className="verdict-row" style={{ background: vm.bg, border: `1px solid ${vm.iconBg}` }}>
                <div className="verdict-icon" style={{ background: vm.iconBg }}>{vm.icon}</div>
                <div className="verdict-text">
                  <div className="verdict-label">{vm.label}</div>
                  <div className="verdict-sub">{vm.sub}</div>
                </div>
              </div>
            )}

            <div className="ai-box">
              <div className="ai-head"><div className="ai-spark">✦</div>AI assessment</div>
              <div className="ai-body-txt">
                {selectedMatch?.explanation ?? (
                  selectedMatch?.status === 'FULL' ? `${selectedVendor?.vendor_name} fully satisfies this requirement. Confidence ${Math.round(conf * 100)}%.`
                    : selectedMatch?.status === 'NONE' ? `No evidence found in ${selectedVendor?.vendor_name}'s proposal.`
                      : `${selectedVendor?.vendor_name} partially addresses this requirement. Review evidence carefully.`
                )}
              </div>
              <div className="ai-foot">
                <span>llama-3.3-70b</span>
                <span>Conf: {Math.round(conf * 100)}%</span>
                <span>Stage 1+2 retrieval</span>
              </div>
            </div>

            {(decision?.type === 'ANNOTATED' || decision?.decision_type === 'ANNOTATED') && (
              <div className="ai-box" style={{ marginTop: 8, background: '#EEF2FF', borderColor: '#C7D2FE' }}>
                <div className="ai-head" style={{ color: '#4338CA' }}>📝 Reviewer note</div>
                <div className="ai-body-txt">{decision.note || decision.reviewer_note}</div>
              </div>
            )}

            <div className="action-row">
              <button className={`act-btn ${isAccepted ? 'act-done' : 'act-accept'}`} onClick={handleAccept} disabled={isAccepted}>
                {isAccepted ? '✓ Accepted' : '✓ Accept'}
              </button>
              <button className="act-btn act-adj" onClick={() => setModal('annotate')}>✏ Annotate</button>
              <button className="act-btn act-rej" onClick={() => setModal('override')}>✗ Override</button>
            </div>

            <div className="audit-trail">
              <button className="at-toggle" onClick={() => setTrailOpen(o => !o)}>
                <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Audit trail ({auditLog.length} events)
                <svg width="10" height="10" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}
                  style={{ marginLeft: 'auto', transform: trailOpen ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {trailOpen && (
                <div className="at-log">
                  {auditLog.map((e, i) => (
                    <div key={i} className="at-entry">
                      <div className="at-dot" style={{ background: e.dot }} />
                      <div className="at-text">{e.text}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Portalled modals */}
      {modal === 'annotate' && (
        <AnnotateModal clauseRef={clauseRef} vendorName={selectedVendor?.vendor_name ?? 'Vendor'}
          matchStatus={displayStatus ?? ''} confidence={conf}
          onClose={closeModal} onSuccess={(data) => {
            showSuccess(data.message);
            setDecisions(prev => ({ ...prev, [`${reqId}-${vendorDocId}`]: { type: 'ANNOTATED', decision_type: 'ANNOTATED', reviewer_note: data.note, note: data.note } }));
          }}
          matchId={matchId} requirementId={reqId} vendorDocumentId={vendorDocId} />
      )}
      {modal === 'override' && (
        <OverrideModal clauseRef={clauseRef} vendorName={selectedVendor?.vendor_name ?? 'Vendor'}
          matchStatus={displayStatus ?? ''} confidence={conf}
          onClose={closeModal} onSuccess={(data) => {
            showSuccess(data.message);
            setDecisions(prev => ({ ...prev, [`${reqId}-${vendorDocId}`]: { type: 'OVERRIDDEN', decision_type: 'OVERRIDDEN', override_status: data.verdict, override: data.verdict, reviewer_note: data.note, note: data.note } }));
          }}
          matchId={matchId} requirementId={reqId} vendorDocumentId={vendorDocId} />
      )}
      {modal === 'diff' && (
        <DiffModal matrix={matrix} vendor_scores={vendor_scores} selectedReqId={selectedReqId} onClose={closeModal} />
      )}

      {/* PDF viewer portal */}
      {pdfModalOpen && pdfConfig && createPortal(
        <div className="fm-backdrop" onClick={() => setPdfModalOpen(false)}>
          <div
            className="fm-panel"
            style={{ width: '900px', maxWidth: '95vw', height: '80vh', display: 'flex', flexDirection: 'column' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="fm-head">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 10, height: 10, borderRadius: '50%', background: selectedVendor?.vendor_color ?? '#888' }} />
                <span style={{ fontWeight: 600 }}>📄 Source Document — {selectedVendor?.vendor_name} Proposal</span>
              </div>
              <button className="fm-close" onClick={() => setPdfModalOpen(false)} aria-label="Close">
                <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div style={{ flex: 1, overflow: 'hidden', background: '#F4F3EF' }}>
              <TracePdfViewer
                fileUrl={pdfConfig.url}
                pageNumber={pdfConfig.pageNumber}
                bbox={pdfConfig.bbox}    
              />
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const STYLES = `
.fm-backdrop {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0,0,0,0.35);
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
  animation: fmIn 0.16s ease;
}
@keyframes fmIn { from { opacity:0 } to { opacity:1 } }

.fm-panel {
  background: var(--bg,#fff);
  border-radius: 14px;
  border: 0.5px solid var(--border,#e5e7eb);
  box-shadow: 0 24px 64px rgba(0,0,0,0.18), 0 4px 16px rgba(0,0,0,0.07);
  display: flex; flex-direction: column;
  max-height: 90vh; overflow: hidden;
  animation: fmUp 0.26s cubic-bezier(0.34,1.56,0.64,1);
}
@keyframes fmUp { from { opacity:0; transform:translateY(10px) scale(0.98) } to { opacity:1; transform:none } }

.fm-head {
  display:flex; align-items:center; justify-content:space-between;
  padding: 14px 18px 13px;
  border-bottom: 0.5px solid var(--border,#e5e7eb);
  flex-shrink: 0;
}
.fm-title { font-size:14px; font-weight:600; color:var(--fg,#111); }
.fm-close {
  width:26px; height:26px; border-radius:7px; border:0.5px solid var(--border,#e5e7eb);
  background:var(--bg2,#f3f4f6); display:flex; align-items:center; justify-content:center;
  cursor:pointer; color:var(--fg2,#6b7280); transition:background .15s;
}
.fm-close:hover { background:var(--border,#e5e7eb); }
.fm-body { padding:16px 18px; overflow-y:auto; flex:1; }
.fm-context {
  background:var(--bg2,#f9fafb); border-left:3px solid #7F77DD;
  border-radius:0 8px 8px 0; padding:10px 12px; margin-bottom:16px;
  border-top:0.5px solid var(--border,#e5e7eb);
  border-right:0.5px solid var(--border,#e5e7eb);
  border-bottom:0.5px solid var(--border,#e5e7eb);
}
.fm-field { margin-bottom:14px; }
.fm-label { display:block; font-size:12px; font-weight:600; color:var(--fg,#111); margin-bottom:4px; }
.fm-hint  { font-size:11.5px; color:var(--fg2,#6b7280); margin-bottom:6px; line-height:1.5; }
.fm-opt   { font-weight:400; font-size:11px; color:var(--fg2,#6b7280); }
.fm-req   { font-weight:400; font-size:11px; color:#dc2626; }
.fm-input, .fm-textarea {
  width:100%; font-size:13px; padding:8px 10px;
  border:1px solid var(--border,#e5e7eb); border-radius:8px;
  background:var(--bg,#fff); color:var(--fg,#111); font-family:inherit; outline:none;
  transition:border-color .15s, box-shadow .15s;
}
.fm-input:focus, .fm-textarea:focus { border-color:#6366F1; box-shadow:0 0 0 3px rgba(99,102,241,0.1); }
.fm-textarea { resize:vertical; line-height:1.55; min-height:90px; }
.fm-foot {
  padding:12px 18px; border-top:0.5px solid var(--border,#e5e7eb);
  display:flex; justify-content:flex-end; gap:8px; flex-shrink:0;
}
.fm-btn-cancel {
  font-size:13px; padding:7px 16px; border-radius:8px;
  border:1px solid var(--border,#e5e7eb); background:var(--bg2,#f9fafb);
  color:var(--fg,#111); cursor:pointer; font-family:inherit;
}
.fm-btn-cancel:hover { background:var(--border,#e5e7eb); }
.fm-btn-submit {
  font-size:13px; padding:7px 16px; border-radius:8px; border:none;
  background:#534AB7; color:#EEEDFE; cursor:pointer; font-weight:600;
  font-family:inherit; transition:background .15s;
}
.fm-btn-submit:hover:not(:disabled) { background:#4338CA; }
.fm-btn-submit:disabled { opacity:.45; cursor:not-allowed; }
.fm-btn-danger { background:#A32D2D !important; color:#FCEBEB !important; }
.fm-btn-danger:hover:not(:disabled) { background:#7f1d1d !important; }

.verdict-pick { display:flex; gap:6px; }
.vp-option {
  flex:1; padding:10px 8px; border-radius:8px; text-align:center;
  border:1px solid var(--border,#e5e7eb); background:var(--bg2,#f9fafb);
  cursor:pointer; display:flex; flex-direction:column; align-items:center; gap:4px;
  transition:border-color .15s, background .15s; font-family:inherit;
}
.vp-icon  { font-size:15px; display:block; }
.vp-label { font-size:12px; display:block; color:var(--fg,#111); }
.vp-full    { background:#EAF3DE !important; border-color:#C0DD97 !important; }
.vp-full .vp-label { color:#27500A; font-weight:600; }
.vp-partial { background:#FAEEDA !important; border-color:#FAC775 !important; }
.vp-partial .vp-label { color:#633806; font-weight:600; }
.vp-none    { background:#FCEBEB !important; border-color:#F7C1C1 !important; }
.vp-none .vp-label { color:#791F1F; font-weight:600; }

.verdict-row {
  display:flex; align-items:flex-start; gap:10px;
  padding:10px 12px; border-radius:8px; margin-bottom:4px;
}
.verdict-icon {
  width:28px; height:28px; border-radius:50%; flex-shrink:0;
  display:flex; align-items:center; justify-content:center; font-size:13px; margin-top:1px;
}
.verdict-label { font-size:12.5px; font-weight:600; color:var(--fg,#111); }
.verdict-sub   { font-size:11.5px; color:var(--fg2,#6b7280); margin-top:2px; line-height:1.5; }

.diff-pair-btn {
  font-size:12px; padding:5px 12px; border-radius:7px;
  border:1px solid var(--border,#e5e7eb); background:var(--bg2,#f9fafb);
  color:var(--fg2,#6b7280); cursor:pointer; font-family:inherit;
}
.diff-pair-btn.on { background:#EEEDFE; border-color:#AFA9EC; color:#3C3489; font-weight:600; }
.diff-cols { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
.diff-col-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }

.act-btn {
  flex:1; padding:8px 10px; border-radius:8px; border:1px solid;
  cursor:pointer; font-size:12.5px; font-weight:600;
  text-align:center; font-family:inherit; transition:opacity .15s; background:none;
}
.act-btn:hover:not(:disabled) { opacity:0.8; }
.act-btn:disabled { opacity:0.5; cursor:not-allowed; }
.act-accept { background:#EAF3DE !important; border-color:#C0DD97 !important; color:#27500A !important; }
.act-done   { background:#EAF3DE !important; border-color:#C0DD97 !important; color:#27500A !important; }
.act-adj    { background:var(--bg2,#f9fafb) !important; border-color:var(--border,#e5e7eb) !important; color:var(--fg,#111) !important; }
.act-rej    { background:#FCEBEB !important; border-color:#F7C1C1 !important; color:#791F1F !important; }

.dp-sub-label {
  font-size:10px; font-weight:700; text-transform:uppercase;
  letter-spacing:.08em; color:var(--t3); margin-bottom:5px;
}
.intent-box { background:#D4EDEA !important; border-color:#A7D9D6 !important; }
.intent-head { color:#0A5954 !important; }

.audit-trail { border-top:1px solid var(--border,#e5e7eb); margin-top:8px; padding-top:10px; }
.at-toggle {
  display:flex; align-items:center; gap:5px; width:100%;
  font-size:11.5px; color:var(--fg2,#6b7280); background:none; border:none;
  cursor:pointer; font-family:inherit; padding:0;
}
.at-toggle:hover { color:var(--fg,#111); }
.at-log { margin-top:10px; display:flex; flex-direction:column; gap:7px; }
.at-entry { display:flex; align-items:flex-start; gap:8px; font-size:11.5px; color:var(--fg2,#6b7280); }
.at-dot { width:7px; height:7px; border-radius:50%; margin-top:4px; flex-shrink:0; }
.at-text { line-height:1.55; }
.at-text strong { color:var(--fg,#111); font-weight:600; }
`;