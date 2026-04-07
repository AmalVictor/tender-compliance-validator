'use client';

// components/RequirementsReview.tsx

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import type { Requirement, RequirementCategory } from '@/types';
import { useProject } from '@/context/ProjectContext';
import { useToast } from '@/context/ToastContext';
import dynamic from 'next/dynamic';
import { StatusBadge } from './StatusBadge';
import { patchRequirement, bulkConfirmRequirements } from '../lib/api';

// Lazy-load the PDF viewer — heavy dependency, no SSR
const TracePdfViewer = dynamic(() => import('@/components/TracePdfViewer'), {
  ssr: false,
  loading: () => (
    <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, color: 'var(--t3)' }}>
      Initialising PDF engine…
    </div>
  ),
});

// Error boundary so a PDF crash never takes down the whole page
class PdfErrorBoundary extends React.Component<
  { children: React.ReactNode; fallback: React.ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode; fallback: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() { return { hasError: true }; }
  // Reset when children change (new requirement selected)
  componentDidUpdate(prev: { children: React.ReactNode }) {
    if (prev.children !== this.props.children && this.state.hasError) {
      this.setState({ hasError: false });
    }
  }
  render() {
    return this.state.hasError ? this.props.fallback : this.props.children;
  }
}

// ── Helper to get document file URL ──────────────────────────────────────────
function getDocumentFileUrl(documentId: string | number): string {
  const base = (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api').replace(/\/$/, '');
  return `${base}/documents/file/${documentId}`;
}

interface RequirementsReviewProps {
  requirements: Requirement[];
}

const CATEGORIES: ('All' | RequirementCategory)[] = [
  'All', 'Technical', 'Legal', 'Financial', 'Administrative',
];

export function RequirementsReview({ requirements = [] }: RequirementsReviewProps) {
  const { project, loadRequirements } = useProject();
  const toast = useToast();

  const [catFilter,      setCatFilter]      = useState<RequirementCategory | 'All'>('All');
  const [confirmedReqs,  setConfirmedReqs]  = useState<Set<string>>(new Set());
  // [MOTION] tracks which requirement IDs just got confirmed (for flash animation)
  const [recentlyConfirmed, setRecentlyConfirmed] = React.useState<Set<string>>(new Set());
  const [processingId,   setProcessingId]   = useState<string | null>(null);
  const [bulkProcessing, setBulkProcessing] = useState(false);
  const [traceReqId,     setTraceReqId]     = useState<string | null>(null);

  // Sync confirmed state from props whenever they change
  useEffect(() => {
    setConfirmedReqs(new Set(requirements.filter((r) => r.confirmed || r.is_confirmed).map((r) => r.id)));
  }, [requirements]);

  const filtered = useMemo(() =>
    requirements.filter((r) => catFilter === 'All' || r.category === catFilter),
    [requirements, catFilter],
  );

  const isAllConfirmed = filtered.length > 0 && filtered.every((r) => confirmedReqs.has(r.id));

  // The requirement currently open in the trace drawer
  const traceReq = useMemo(() =>
    traceReqId ? requirements.find((r) => r.id === traceReqId) ?? null : null,
    [requirements, traceReqId],
  );

  // PDF source URL — uses rfp_document_id field set by the backend
  const traceFileUrl = useMemo(() => {
    const docId = (traceReq as any)?.rfp_document_id;
    return docId ? getDocumentFileUrl(docId) : null;
  }, [traceReq]);

  const tracePageNumber = (traceReq?.page_number ?? 1);
  const traceBbox       = (traceReq as any)?.bbox ?? null;

  // ── Toggle single requirement ─────────────────────────────────────────────
  const toggleConfirm = useCallback(async (id: string) => {
    if (!project || processingId) return;
    const willConfirm = !confirmedReqs.has(id);
    setProcessingId(id);

    // Optimistic update
    setConfirmedReqs((prev) => {
      const next = new Set(prev);
      if (willConfirm) next.add(id); else next.delete(id);
      return next;
    });

    try {
      await patchRequirement(id, { is_confirmed: willConfirm } as any);
      await loadRequirements(project.id);
      if (willConfirm) {
        // [MOTION] trigger confirm flash
        setRecentlyConfirmed(prev => new Set([...prev, id]));
        setTimeout(() => {
          setRecentlyConfirmed(prev => {
            const next = new Set(prev);
            next.delete(id);
            return next;
          });
        }, 800);
      }
    } catch (err) {
      // Rollback
      setConfirmedReqs((prev) => {
        const next = new Set(prev);
        if (willConfirm) next.delete(id); else next.add(id);
        return next;
      });
      toast.showError('Failed to update requirement');
    } finally {
      setProcessingId(null);
    }
  }, [project, processingId, confirmedReqs, loadRequirements, toast]);

  // ── Bulk confirm ──────────────────────────────────────────────────────────
  const setAllInView = useCallback(async (confirm: boolean) => {
    if (!project || bulkProcessing || filtered.length === 0) return;
    setBulkProcessing(true);
    try {
      const ids = filtered.map((r) => r.id);
      await bulkConfirmRequirements(ids, confirm);
      await loadRequirements(project.id);
      toast.showSuccess(confirm ? `Confirmed ${ids.length} requirements` : `Unconfirmed ${ids.length} requirements`);
      if (confirm) {
        // [MOTION] ripple flash down the list
        ids.forEach((id, index) => {
          setTimeout(() => {
            setRecentlyConfirmed(prev => new Set([...prev, id]));
            setTimeout(() => {
              setRecentlyConfirmed(prev => {
                const next = new Set(prev);
                next.delete(id);
                return next;
              });
            }, 800);
          }, index * 50);
        });
      }
    } catch {
      toast.showError('Bulk operation failed');
    } finally {
      setBulkProcessing(false);
    }
  }, [project, bulkProcessing, filtered, loadRequirements, toast]);

  // ── Confidence helpers ────────────────────────────────────────────────────
  function confPct(req: Requirement): number {
    const c = (req as any).confidence ?? 0;
    const pct = c <= 1 ? c * 100 : c;
    return Math.max(0, Math.min(100, Math.round(pct)));
  }
  function confColor(pct: number) {
    return pct >= 80 ? 'var(--full)' : pct >= 60 ? 'var(--part)' : 'var(--none)';
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap' }}>
          {CATEGORIES.map((c) => (
            <button
              key={c}
              className={`fb ${catFilter === c ? 'on' : ''}`}
              onClick={() => setCatFilter(c)}
            >
              {c}{' '}
              ({c === 'All' ? requirements.length : requirements.filter((r) => r.category === c).length})
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            className="btn btn-g btn-sm"
            onClick={() => setAllInView(true)}
            disabled={isAllConfirmed || filtered.length === 0 || bulkProcessing}
          >
            <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
            {bulkProcessing ? 'Processing…' : 'Confirm All in View'}
          </button>
        </div>
      </div>

      {/* Requirements table */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        {/* Table header */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '80px 1fr 110px 110px 130px 70px 70px',
          gap: 0,
          padding: '8px 18px',
          background: '#FAFAF8',
          borderBottom: '2px solid var(--border-s)',
          fontSize: 10,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '.08em',
          color: 'var(--t3)',
        }}>
          <div>Ref</div>
          <div>Requirement</div>
          <div>Category</div>
          <div>Criticality</div>
          <div>Confidence</div>
          <div>Trace</div>
          <div style={{ textAlign: 'right' }}>Confirm</div>
        </div>

        {/* Rows */}
        {filtered.map((req) => {
          const isConfirmed  = confirmedReqs.has(req.id);
          const pct          = confPct(req);
          const color        = confColor(pct);
          const needsReview  = pct < 70;
          const displayText  = (req as any).normalised_intent || req.normalised || req.raw_text;
          const displayRef   = (req as any).rfp_clause_ref || req.ref || req.id;

          return (
            <div
              key={req.id}
              className={`req-row ${recentlyConfirmed.has(req.id) ? 'row-confirm-flash' : ''}`}
              // [MOTION] ^^ adds green pulse on confirm
              style={{
                display: 'grid',
                gridTemplateColumns: '80px 1fr 110px 110px 130px 70px 70px',
                gap: 0,
                padding: '10px 18px',
                borderBottom: '1px solid var(--border)',
                alignItems: 'center',
                background: isConfirmed ? '#FAFFFC' : 'var(--surface)',
                transition: 'background .15s',
                borderLeft: `3px solid ${isConfirmed ? 'var(--full)' : 'var(--border)'}`,
              }}
            >
              {/* Ref */}
              <div style={{ fontSize: 11, fontFamily: 'var(--font-mono), monospace', color: 'var(--t2)', wordBreak: 'break-all' }}>
                {displayRef}
              </div>

              {/* Text */}
              <div style={{ fontSize: 13, color: 'var(--t1)', lineHeight: 1.5, paddingRight: 12 }}>
                {displayText}
              </div>

              {/* Category */}
              <div><StatusBadge status={req.category} size="badge" /></div>

              {/* Criticality */}
              <div><StatusBadge status={req.criticality} size="badge" /></div>

              {/* Confidence */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <div className="conf-bar" style={{ width: 60, height: 4 }}>
                    <div className="conf-fill" style={{ width: `${pct}%`, background: color }} />
                  </div>
                  <span className="mono text-xs" style={{ color, fontWeight: 700 }}>{pct}%</span>
                </div>
                {needsReview && (
                  <span style={{
                    display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 9, fontWeight: 700,
                    color: 'var(--part)', background: 'var(--part-bg)', borderRadius: 4,
                    padding: '1px 5px', marginTop: 4,
                  }}>
                    ⚑ Review
                  </span>
                )}
              </div>

              {/* Trace button */}
              <div>
                <button
                  className="btn btn-g btn-sm"
                  onClick={() => setTraceReqId(req.id)}
                  title="Open source PDF with highlight"
                >
                  Trace
                </button>
              </div>

              {/* Confirm toggle */}
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                {isConfirmed && (
                  <span
                    key={req.id + '-check'}
                    style={{
                      display: 'inline-block',
                      marginRight: 8,
                      color: 'var(--full)',
                      fontWeight: 800,
                      animation: 'checkBounce .35s cubic-bezier(0.34,1.4,0.64,1) forwards',
                    }}
                  >
                    ✓
                  </span>
                )}
                <button
                  type="button"
                  className={`toggle ${isConfirmed ? 'on' : ''}`}
                  onClick={() => toggleConfirm(req.id)}
                  disabled={processingId === req.id}
                  aria-pressed={isConfirmed}
                  title={isConfirmed ? 'Confirmed — click to mark pending' : 'Click to confirm'}
                />
              </div>
            </div>
          );
        })}

        {filtered.length === 0 && (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--t3)', background: 'var(--surface)' }}>
            No requirements found for this filter.
          </div>
        )}
      </div>

      {/* ── Trace modal overlay ── */}
      {traceReq && (
        <>
          {/* Dimmed backdrop */}
          <div
            style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.4)', zIndex: 600 }}
            onClick={() => setTraceReqId(null)}
          />

          {/* Modal */}
          <div style={{
            position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
            width: 'min(1100px, 94vw)', maxHeight: '90vh',
            background: 'var(--surface)', borderRadius: 14, boxShadow: 'var(--sh3)',
            zIndex: 601, display: 'flex', flexDirection: 'column', overflow: 'hidden',
          }}>
            {/* Modal header */}
            <div style={{
              padding: '14px 20px', borderBottom: '1px solid var(--border)',
              display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12,
              flexShrink: 0,
            }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--t1)', marginBottom: 2 }}>
                  Traceability Inspector
                </div>
                <div style={{ fontSize: 11, color: 'var(--t3)', fontFamily: 'var(--font-mono), monospace' }}>
                  Ref: {(traceReq as any).rfp_clause_ref || traceReq.ref || traceReq.id}
                  {traceReq.page_number ? ` · Page ${traceReq.page_number}` : ''}
                </div>
              </div>
              <button className="btn btn-icon btn-g" onClick={() => setTraceReqId(null)}>
                <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Modal body — two-column: info left, PDF right */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '320px 1fr',
              gap: 0,
              flex: 1,
              overflow: 'hidden',
              minHeight: 0,
            }}>
              {/* Left column: text info */}
              <div style={{
                padding: 20,
                borderRight: '1px solid var(--border)',
                overflowY: 'auto',
                display: 'flex',
                flexDirection: 'column',
                gap: 16,
              }}>
                <div>
                  <div style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--t3)', marginBottom: 6 }}>
                    Extracted Requirement
                  </div>
                  <div style={{
                    fontSize: 13, lineHeight: 1.7, color: 'var(--t1)', fontStyle: 'italic',
                    background: 'var(--bg)', borderRadius: 'var(--r)', padding: '10px 12px',
                    border: '1px solid var(--border)',
                  }}>
                    {(traceReq as any).normalised_intent || traceReq.normalised || traceReq.raw_text}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--t3)', marginBottom: 6 }}>
                    Source Text (RFP Passage)
                  </div>
                  <div style={{
                    fontSize: 12, lineHeight: 1.75, color: 'var(--t1)',
                    background: '#FFFBEB', borderRadius: 'var(--r)', padding: '10px 12px',
                    border: '1px solid #FDE68A',
                  }}>
                    {traceReq.raw_text}
                  </div>
                </div>

                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <StatusBadge status={traceReq.category} size="badge" />
                  <StatusBadge status={traceReq.criticality} size="badge" />
                  {traceReq.page_number && (
                    <span style={{ fontSize: 11, fontFamily: 'var(--font-mono), monospace', color: 'var(--t3)', background: 'var(--bg)', padding: '2px 8px', borderRadius: 100, border: '1px solid var(--border)' }}>
                      p.{traceReq.page_number}
                    </span>
                  )}
                </div>

                {!traceFileUrl && (
                  <div style={{ fontSize: 12, color: 'var(--t3)', fontStyle: 'italic' }}>
                    No source PDF available — rfp_document_id not set for this requirement.
                  </div>
                )}
              </div>

              {/* Right column: PDF viewer */}
              <div style={{ overflowY: 'auto', padding: 16, background: '#E8E7E2' }}>
                {traceFileUrl ? (
                  <PdfErrorBoundary
                    fallback={
                      <div>
                        <div style={{ fontSize: 12, color: 'var(--t3)', marginBottom: 8 }}>
                          PDF module failed to load. Using browser fallback.
                        </div>
                        <iframe
                          src={`${traceFileUrl}#page=${tracePageNumber}&view=FitH`}
                          title="Trace PDF preview"
                          style={{
                            width: '100%', height: '68vh',
                            border: '1px solid var(--border)', borderRadius: 'var(--r)',
                          }}
                        />
                      </div>
                    }
                  >
                    <TracePdfViewer
                      fileUrl={traceFileUrl}
                      pageNumber={tracePageNumber}
                      bbox={traceBbox}
                    />
                  </PdfErrorBoundary>
                ) : (
                  <div style={{
                    height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 13, color: 'var(--t3)', textAlign: 'center', padding: 32,
                  }}>
                    No PDF available.<br />
                    <span style={{ fontSize: 11, marginTop: 6, display: 'block' }}>
                      The backend must set <code>rfp_document_id</code> on requirements for traceability to work.
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}