'use client';
// src/components/Workspace.tsx


import React, { useState, useEffect, useRef } from 'react';
import type { TenderDocument, AuditStatus, AuditResults } from '@/types';
import { getDocuments, uploadDocument, runAudit, ApiError, getExportUrl } from '../lib/api';
import { useProject } from '@/context/ProjectContext';
import { useToast } from '@/context/ToastContext';

const PIPELINE_STEPS = [
  { label: 'RFP\nUploaded', icon: '📄' },
  { label: 'Reqs\nExtracted', icon: '🔍' },
  { label: 'Reqs\nConfirmed', icon: '✅' },
  { label: 'Proposals\nIndexed', icon: '📁' },
  { label: 'Audit\nComplete', icon: '🤖' },
  { label: 'Report\nReady', icon: '📊' },
];

// 5-step console messages with timing ──────────────────────────────────
const AUDIT_CONSOLE_MESSAGES = [
  { text: 'Parsing RFP clauses', pct: 12 },
  { text: 'Embedding requirements into vector store', pct: 30 },
  { text: 'Scoring vendor proposals', pct: 55 },
  { text: 'Running risk analysis', pct: 78 },
  { text: 'Finalizing compliance matrix', pct: 94 },
];
const CONSOLE_STEP_MS = [0, 3500, 7500, 12000, 17000] as const;

function pipelineStepsFromAuditStatus(
  status: AuditStatus | null,
  hasRfp: boolean,
  reqsExtracted: boolean,
  reqsConfirmed: boolean,
  proposalsIndexed: boolean,
  auditComplete: boolean,
  vendorDocsStale: boolean,
) {
  const auditDone = auditComplete && !vendorDocsStale;
  const doneFlags = [hasRfp, reqsExtracted, reqsConfirmed, proposalsIndexed, auditDone, auditDone];
  return PIPELINE_STEPS.map((s, i) => {
    const isDone = doneFlags[i];
    if (isDone) return { ...s, status: 'done' as const };
    const firstUndone = doneFlags.findIndex((d) => !d);
    const active = i === firstUndone;
    return { ...s, status: (active ? 'active' : 'pending') as 'done' | 'active' | 'pending' };
  });
}

// ── Admin helpers ─────────────────────────────────────────────────

const ADMIN_CHECK_ITEMS = [
  'Tax Clearance', 'B-BBEE Certificate', 'Insurance Proof',
  'CIPC Registration', 'VAT Registration', 'Signed Declaration',
];

interface AdminCheckSummary {
  item_name: string;
  missingVendors: string[];
  foundCount: number;
  totalVendors: number;
}

function buildAdminCheckSummary(
  adminChecks: AuditResults['admin_checks'],
  vendorScores: AuditResults['vendor_scores'],
): AdminCheckSummary[] {
  const vendorById: Record<string, string> = {};
  vendorScores.forEach((v) => { vendorById[String(v.vendor_document_id)] = v.vendor_name; });
  const totalVendors = vendorScores.length;
  const norm = (s: string) => s.toLowerCase().replace(/[-\s]/g, '');
  return ADMIN_CHECK_ITEMS.map((itemName) => {
    const itemChecks = adminChecks.filter((c) => norm(c.item_name) === norm(itemName));
    const missingVendors = Array.from(new Set(
      itemChecks
        .filter((c) => c.status.toUpperCase() === 'MISSING')
        .map((c) => vendorById[String(c.vendor_document_id)] ?? `Vendor ${c.vendor_document_id}`)
    ));
    const foundCount = itemChecks.filter((c) => c.status.toUpperCase() === 'FOUND').length;
    return { item_name: itemName, missingVendors, foundCount, totalVendors };
  });
}

function AdminPreScreeningCard({ auditResults, projectId }: { auditResults: AuditResults; projectId: string }) {
  console.debug('[AdminCheck] admin_checks:', auditResults.admin_checks);
  console.debug('[AdminCheck] vendor_scores:', auditResults.vendor_scores);
  const summary = buildAdminCheckSummary(auditResults.admin_checks, auditResults.vendor_scores);
  const totalMissing = summary.filter((s) => s.missingVendors.length > 0).length;
  return (
    <div className="card">
      <div className="ch" style={{ alignItems: 'flex-start' }}>
        <div>
          <div className="ct">Administrative Pre-screening</div>
          <div style={{ fontSize: 12, color: 'var(--t3)', marginTop: 2 }}>Required documents checked across all proposals</div>
        </div>
        {totalMissing > 0 ? (
          <span style={{ fontSize: 12, fontWeight: 700, padding: '3px 10px', borderRadius: 20, background: '#FEF2F2', color: '#B91C1C', border: '1px solid #FECACA', flexShrink: 0 }}>
            {totalMissing} Item{totalMissing > 1 ? 's' : ''} Missing
          </span>
        ) : (
          <span style={{ fontSize: 12, fontWeight: 700, padding: '3px 10px', borderRadius: 20, background: '#F0FDF4', color: '#166534', border: '1px solid #BBF7D0', flexShrink: 0 }}>
            ✓ All Clear
          </span>
        )}
      </div>
      <div className="cb">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
          {summary.map((item) => {
            const hasMissing = item.missingVendors.length > 0;
            return (
              <div key={item.item_name} style={{ padding: '12px 14px', borderRadius: 'var(--r)', border: `1px solid ${hasMissing ? '#FECACA' : 'var(--border)'}`, background: hasMissing ? '#FEF2F2' : 'var(--bg)', transition: 'all .2s ease' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: hasMissing ? '#B91C1C' : 'var(--ac)' }}>{hasMissing ? '✗' : '✓'}</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: hasMissing ? '#B91C1C' : 'var(--ac)' }}>{item.item_name}</span>
                </div>
                {hasMissing ? (
                  <div style={{ fontSize: 11, color: '#B91C1C', lineHeight: 1.5 }}>
                    {item.missingVendors.map((v, i) => <div key={`${v}-${i}`}>{v} — missing</div>)}
                  </div>
                ) : (
                  <div style={{ fontSize: 11, color: 'var(--t3)' }}>All {item.totalVendors} vendor{item.totalVendors !== 1 ? 's' : ''}</div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// Extract Requirements skeleton ────────────────────────────────────────
function ExtractSkeleton() {
  return (
    <div className="extract-skeleton">
      {[1, 2, 3].map((i) => (
        <div key={i} className="extract-skeleton-row" style={{ animationDelay: `${i * 0.08}s` }}>
          <div style={{ width: '70%', animationDelay: `${i * 0.08 + 0.0}s` }} />
          <div style={{ animationDelay: `${i * 0.08 + 0.1}s` }} />
          <div style={{ width: '60%', animationDelay: `${i * 0.08 + 0.2}s` }} />
          <div style={{ width: '50%', animationDelay: `${i * 0.08 + 0.3}s` }} />
        </div>
      ))}
      <div style={{ padding: '8px 16px', fontSize: 11, color: 'var(--t3)', fontStyle: 'italic' }}>
        Extracting and normalising requirements…
      </div>
    </div>
  );
}

// [MOTION] Report generation modal — pure UI, no logic change
const REPORT_STEPS = [
  'Compiling compliance matrix',
  'Analyzing risk findings',
  'Building methodology note',
  'Finalizing PDF export',
];

function ReportGenerationModal({ onComplete }: { onComplete: () => void }) {
  const [stepIndex, setStepIndex] = React.useState(0);
  const [done, setDone] = React.useState(false);

  React.useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    REPORT_STEPS.forEach((_, i) => {
      timers.push(setTimeout(() => setStepIndex(i), i * 900));
    });
    timers.push(setTimeout(() => {
      setDone(true);
      setTimeout(onComplete, 600);
    }, REPORT_STEPS.length * 900));
    return () => timers.forEach(clearTimeout);
  }, [onComplete]);

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: 'rgba(0,0,0,.4)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      // [MOTION] backdrop entrance
      animation: 'overlayIn .2s ease forwards',
    }}>
      <div style={{
        background: 'var(--surface)', borderRadius: 16,
        padding: '32px 36px', width: 380, boxShadow: 'var(--sh3)',
        // [MOTION] panel pop-in
        animation: 'popIn .28s cubic-bezier(0.34,1.4,0.64,1) forwards',
      }}>
        <div style={{
          width: 56, height: 56, borderRadius: 14,
          background: done ? 'var(--full-bg)' : 'var(--ac-bg)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          margin: '0 auto 20px',
          transition: 'background .4s ease',
          boxShadow: done ? '0 0 0 0 transparent' : '0 4px 18px rgba(12,123,114,.2)',
          animation: done ? 'none' : 'glowPulse 1.6s ease infinite',
        }}>
          {done ? (
            <span style={{ fontSize: 28, animation: 'checkBounce .4s cubic-bezier(0.34,1.4,0.64,1) forwards' }}>✓</span>
          ) : (
            <svg width="26" height="26" fill="none" viewBox="0 0 24 24" stroke="var(--ac)" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
            </svg>
          )}
        </div>

        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>
            {done ? 'Report Ready' : 'Generating Report...'}
          </div>
          <div style={{ fontSize: 12, color: 'var(--t3)' }}>
            {done ? 'Your download will start automatically' : 'This takes a few seconds'}
          </div>
        </div>

        <div style={{ height: 4, background: 'var(--bg2)', borderRadius: 2, overflow: 'hidden', marginBottom: 20 }}>
          <div style={{
            height: '100%',
            width: done ? '100%' : `${((stepIndex + 1) / REPORT_STEPS.length) * 100}%`,
            background: done ? 'var(--full)' : 'var(--ac)',
            borderRadius: 2,
            transition: 'width .6s var(--ease-out), background .4s ease',
          }} />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {REPORT_STEPS.map((step, i) => {
            const isComplete = i < stepIndex || done;
            const isActive = i === stepIndex && !done;
            return (
              <div key={step} style={{
                display: 'flex', alignItems: 'center', gap: 10,
                animation: 'fadeUp .18s ease both',
                animationDelay: `${i * 0.06}s`,
              }}>
                <div style={{
                  width: 20, height: 20, borderRadius: '50%', flexShrink: 0,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: isComplete ? 'var(--full-bg)' : isActive ? 'var(--ac-bg)' : 'var(--bg2)',
                  border: `1.5px solid ${isComplete ? 'var(--full)' : isActive ? 'var(--ac)' : 'var(--border)'}`,
                  transition: 'all .3s ease',
                }}>
                  {isComplete && (
                    <span style={{ fontSize: 11, color: 'var(--full)', animation: 'stepTick .3s forwards' }}>✓</span>
                  )}
                  {isActive && (
                    <div style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--ac)', animation: 'pulseDot 1s ease infinite' }} />
                  )}
                </div>
                <span style={{
                  fontSize: 13,
                  color: isComplete ? 'var(--t2)' : isActive ? 'var(--t1)' : 'var(--t3)',
                  fontWeight: isActive ? 600 : 400,
                  transition: 'color .25s ease, font-weight .25s ease',
                }}>
                  {step}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Props & Component ─────────────────────────────────────────────────────────

interface WorkspaceProps {
  reqsExtracted: boolean;
  reqsConfirmed: boolean;
  auditComplete: boolean;
  vendorDocsStale: boolean;
  auditResults?: AuditResults | null;
  onExtractRequirements: () => void | Promise<void>;
  onDocsChanged?: (flags: {
    hasRfp: boolean;
    hasVendorDocs: boolean;
    rfpSignature: string;
    proposalsSignature: string;
  }) => void;
}

export function Workspace({
  reqsExtracted, reqsConfirmed, auditComplete, vendorDocsStale,
  auditResults, onExtractRequirements, onDocsChanged,
}: WorkspaceProps) {
  const { project, auditStatus, setAuditStatus, loadAuditResults, loadRequirements } = useProject();
  const toast = useToast();

  // ── All original state (unchanged) ──────────────────────────────────────────
  const [documents, setDocuments] = useState<TenderDocument[]>([]);
  const [uploading, setUploading] = useState(false);
  const [runLoad, setRunLoad] = useState(false);
  const [extractLoad, setExtractLoad] = useState(false);
  const [auditConsoleStep, setAuditConsoleStep] = useState(0);   // presentation only
  const [vendorModal, setVendorModal] = useState(false);
  // [MOTION] report generation modal state
  const [showReportModal, setShowReportModal] = React.useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [vendorName, setVendorName] = useState('');
  const rfpInputRef = useRef<HTMLInputElement>(null);
  const proposalInputRef = useRef<HTMLInputElement>(null);
  // NEW: refs for console step timers so we can clear on unmount
  const consoleTimers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    if (!project?.id) return;
    getDocuments(project.id)
      .then(setDocuments)
      .catch((e) => { if (e instanceof ApiError && !e.isNotFound) toast.showError(e.message); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  const rfps = documents.filter((d) => d.document_type === 'RFP');
  const proposals = documents.filter((d) => d.document_type === 'PROPOSAL');
  const isRunning = auditStatus?.status === 'running';
  const hasRfp = rfps.length > 0;
  const hasVendorDocs = proposals.length > 0;
  const proposalsIndexed = hasVendorDocs && proposals.every((p) => p.is_indexed);
  const rfpSignature = rfps.map((d) => String(d.id)).sort().join(',');
  const proposalsSignature = proposals.map((p) => String(p.id)).sort().join(',');

  useEffect(() => {
    onDocsChanged?.({ hasRfp, hasVendorDocs, rfpSignature, proposalsSignature });
  }, [hasRfp, hasVendorDocs, rfpSignature, proposalsSignature, onDocsChanged]);

  // ── NEW: Multi-step console — cycles all 5 steps via chained timeouts ───────
  useEffect(() => {
    const auditRunningUI = runLoad || isRunning;
    // Clear any existing timers
    consoleTimers.current.forEach(clearTimeout);
    consoleTimers.current = [];

    if (!auditRunningUI) {
      setAuditConsoleStep(0);
      return;
    }

    setAuditConsoleStep(0);
    // Schedule steps 1–4 (step 0 is already shown)
    CONSOLE_STEP_MS.forEach((ms, i) => {
      if (i === 0) return; // step 0 shown immediately
      const t = setTimeout(() => setAuditConsoleStep(i), ms);
      consoleTimers.current.push(t);
    });

    return () => {
      consoleTimers.current.forEach(clearTimeout);
      consoleTimers.current = [];
    };
  }, [runLoad, isRunning]);

  // ── All original handlers (unchanged) ────────────────────────────────────────

  async function handleRfpUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file || !project) return;
    setUploading(true);
    toast.showInfo(`Uploading ${file.name}…`);
    try {
      const doc = await uploadDocument(project.id, file, 'rfp');
      setDocuments((prev) => [...prev.filter((d) => d.document_type !== 'RFP'), doc]);
      toast.showSuccess(`RFP "${file.name}" uploaded.`);
      toast.showInfo('Click "Extract Requirements" to generate the human review list.');
    } catch (err) {
      const msg = err instanceof ApiError ? (err.isNetworkError ? 'Backend offline' : err.message) : 'Upload failed';
      toast.showError(msg);
    } finally {
      setUploading(false);
    }
  }

  async function handleExtractRequirements() {
    if (!project || extractLoad) return;
    setExtractLoad(true);
    try {
      await onExtractRequirements();
      await loadRequirements(project.id);
      toast.showSuccess('Requirements extracted — review them below.');
    } catch (err) {
      toast.showError(err instanceof ApiError ? err.message : 'Failed to extract requirements');
    } finally {
      setExtractLoad(false);
    }
  }

  async function handleProposalFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setPendingFile(file);
    setVendorName('');
    setVendorModal(true);
  }

  async function submitProposal(e: React.FormEvent) {
    e.preventDefault();
    if (!pendingFile || !project || !vendorName.trim()) return;
    setVendorModal(false);
    setUploading(true);
    toast.showInfo(`Uploading ${pendingFile.name}…`);
    try {
      const doc = await uploadDocument(project.id, pendingFile, 'proposal', vendorName.trim());
      setDocuments((prev) => [...prev, doc]);
      toast.showSuccess(`Proposal for "${vendorName.trim()}" uploaded`);
    } catch (err) {
      const msg = err instanceof ApiError ? (err.isNetworkError ? 'Backend offline' : err.message) : 'Upload failed';
      toast.showError(msg);
    } finally {
      setUploading(false);
      setPendingFile(null);
    }
  }

  async function handleRunAudit() {
    if (!project) return;
    if (!hasRfp) { toast.showError('Upload an RFP document first'); return; }
    if (!reqsExtracted) { toast.showError('Extract requirements first'); return; }
    if (!reqsConfirmed) { toast.showError('Confirm all requirements before running the audit'); return; }
    if (proposals.length < 1) { toast.showError('Upload at least one vendor proposal first'); return; }
    setRunLoad(true);
    try {
      await runAudit(project.id);
      const runningStatus: AuditStatus = {
        project_id: project.id,
        status: 'running',
        steps: PIPELINE_STEPS.map((s, i) => ({
          ...s,
          status: (i < 4 ? 'done' : i === 4 ? 'active' : 'pending') as 'done' | 'active' | 'pending',
        })),
      };
      setAuditStatus(runningStatus);
      toast.showInfo('Audit started — results will appear automatically when complete');
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Failed to start audit';
      toast.showError(msg);
    } finally {
      setRunLoad(false);
    }
  }

  const steps = pipelineStepsFromAuditStatus(
    auditStatus, hasRfp, reqsExtracted, reqsConfirmed,
    proposalsIndexed, auditComplete, vendorDocsStale,
  );

  const showAdminCard =
    auditComplete && !vendorDocsStale && !!auditResults && auditResults.admin_checks.length > 0;

  // NEW: console data helpers
  const auditRunningUI = runLoad || isRunning;
  const safeStep = Math.min(auditConsoleStep, AUDIT_CONSOLE_MESSAGES.length - 1);
  const consolePct = AUDIT_CONSOLE_MESSAGES[safeStep].pct;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24, width: '100%' }}>

      {/* ── Pipeline card ──────────────────────────────────────────────────── */}
      <div className="card">
        <div className="ch">
          <div className="ct">Audit Pipeline</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {auditStatus?.status === 'complete' && (
              <span style={{ fontSize: 11, color: 'var(--full)', fontWeight: 600 }}>✓ Last audit complete</span>
            )}

            {/* Extract Requirements button */}
            {hasRfp && !reqsExtracted && (
              <button
                className="btn btn-p btn-sm"
                onClick={handleExtractRequirements}
                disabled={extractLoad || uploading || isRunning}
              >
                {extractLoad ? (
                  <><span className="spin">⟳</span> Extracting…</>
                ) : (
                  <>
                    <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l2.5-2.5m-2.5 2.5l-2.5-2.5m2.5 2.5l2.5 2.5m-2.5-2.5l-2.5 2.5" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Extract Requirements
                  </>
                )}
              </button>
            )}

            {/* Run Audit button — adds .is-running class when running */}
            <button
              className={`btn-run${auditRunningUI ? ' is-running' : ''}`}
              onClick={handleRunAudit}
              disabled={runLoad || isRunning || !hasRfp || !reqsExtracted || !reqsConfirmed || !hasVendorDocs}
              title={
                !hasRfp ? 'Upload an RFP first'
                  : !reqsExtracted ? 'Extract requirements first'
                    : !reqsConfirmed ? 'Confirm all requirements first'
                      : !hasVendorDocs ? 'Upload at least one vendor proposal first'
                        : undefined
              }
            >
              {auditRunningUI ? (
                <><span className="spin">⟳</span> {isRunning ? 'Running…' : 'Starting…'}</>
              ) : (
                <>
                  <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.986V5.653z" />
                  </svg>
                  {vendorDocsStale ? 'Re-run Audit for new requirements' : 'Run Compliance Audit'}
                </>
              )}
            </button>
          </div>
        </div>

        <div className="cb" style={{ padding: '14px 18px' }}>

          {/* ── NEW: Multi-step audit console ─────────────────────────────── */}
          {auditRunningUI && (
            <div className="audit-console">
              <div className="audit-console-head">
                <div className="audit-console-icon">🤖</div>
                <div>
                  <div className="audit-console-title">Audit Console</div>
                  {/* key on safeStep forces React to remount the element,
                      which re-triggers the stepIn CSS animation on each message change */}
                  <div
                    className="audit-console-step"
                    key={safeStep}
                  >
                    {AUDIT_CONSOLE_MESSAGES[safeStep].text}
                    <span className="audit-console-dots">
                      <span /><span /><span />
                    </span>
                  </div>
                </div>
              </div>

              {/* Progress bar — driven by the step's pct value */}
              <div className="audit-console-progress-track">
                <div
                  className="audit-console-progress-fill"
                  style={{ width: `${consolePct}%` }}
                />
              </div>
            </div>
          )}

          {/* Pipeline steps */}
          <div className="pipeline">
            {steps.map((step, i) => (
              <div key={i} className={`pip-step ${step.status}`}>
                <div className="pip-icon">{step.status === 'done' ? '✓' : step.icon}</div>
                <div className="pip-label">{step.label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Documents grid ──────────────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>

        {/* RFP card */}
        <div className="card">
          <div className="ch">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div className="ct">1. Master RFP Document</div>
            </div>
            {rfps.length > 0 && (
              <button className="btn btn-g btn-sm" onClick={() => rfpInputRef.current?.click()} disabled={uploading}>
                Replace
              </button>
            )}
          </div>
          <div className="cb" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

            {/* ── NEW: Show skeleton while extracting ── */}
            {extractLoad && <ExtractSkeleton />}

            {!extractLoad && rfps.length === 0 && (
              <div
                /* NEW: upload-zone-uploading adds animated border pulse */
                className={uploading ? 'upload-zone-uploading' : ''}
                style={{ padding: '32px 20px', textAlign: 'center', border: '1.5px dashed var(--border-s)', borderRadius: 'var(--r)', background: 'var(--bg)', cursor: 'pointer', transition: 'all .2s' }}
                onClick={() => rfpInputRef.current?.click()}
                onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--ac)'; (e.currentTarget as HTMLDivElement).style.background = 'var(--ac-bg)'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = uploading ? 'var(--ac)' : 'var(--border-s)'; (e.currentTarget as HTMLDivElement).style.background = 'var(--bg)'; }}
              >
                <div style={{ fontSize: 24, marginBottom: 8 }}>📄</div>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Upload RFP Document</div>
                <div style={{ fontSize: 12, color: 'var(--t3)' }}>PDF or DOCX · Up to 50 MB</div>
                <div style={{ marginTop: 14 }}>
                  <button className="btn btn-p btn-sm" disabled={uploading} onClick={(e) => { e.stopPropagation(); rfpInputRef.current?.click(); }}>
                    {uploading ? <><span className="spin">⟳</span> Uploading…</> : 'Choose file'}
                  </button>
                </div>
              </div>
            )}

            {!extractLoad && rfps.length > 0 && rfps.map((r) => (
              <div key={r.id} className="doc-row fade-up" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderRadius: 'var(--r)', border: '1px solid var(--border)', background: 'var(--bg)' }}>
                <div style={{ width: 34, height: 34, background: '#FEF2F2', color: '#DC2626', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 11, flexShrink: 0 }}>
                  PDF
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.filename}</div>
                  <div style={{ fontSize: 11, color: 'var(--t3)', fontFamily: 'var(--font-mono), monospace' }}>
                    {r.page_count ? `${r.page_count} pages` : '–'} · {new Date(r.uploaded_at).toLocaleDateString()}
                    {r.is_indexed && <span style={{ color: 'var(--full)', marginLeft: 6 }}>✓ Indexed</span>}
                  </div>
                </div>
                <span className="bd bd-blue" style={{ flexShrink: 0 }}>Baseline Set</span>
              </div>
            ))}
          </div>
        </div>

        {/* Proposals card */}
        <div className="card">
          <div className="ch">
            <div className="ct">2. Vendor Proposals</div>
            <span style={{ fontSize: 11, color: 'var(--t3)' }}>{proposals.length} uploaded</span>
          </div>
          <div className="cb" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {proposals.map((p, i) => {
              const COLORS = ['#6366F1', '#10B981', '#F59E0B', '#EC4899', '#8B5CF6'];
              const vendorBadge =
                auditComplete && !vendorDocsStale
                  ? { cls: 'bd bd-full', label: 'Audited' }
                  : vendorDocsStale
                    ? { cls: 'bd bd-stale', label: 'Stale' }
                    : { cls: 'bd bd-yellow', label: 'Needs Audit' };
              return (
                <div key={p.id} className="fade-up" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderRadius: 'var(--r)', border: '1px solid var(--border)', background: 'var(--bg)', animationDelay: `${i * 0.04}s` }}>
                  <div style={{ width: 9, height: 9, borderRadius: '50%', background: COLORS[i % COLORS.length], flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{p.vendor_name ?? 'Vendor'}</div>
                    <div style={{ fontSize: 11, color: 'var(--t3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.filename}</div>
                  </div>
                  {p.is_indexed && <span style={{ fontSize: 10, color: 'var(--full)', fontWeight: 600 }}>✓</span>}
                  <span className={vendorBadge.cls} style={{ flexShrink: 0 }}>{vendorBadge.label}</span>
                </div>
              );
            })}

            {/* Add proposal drop zone */}
            <div
              /* NEW: animated border when uploading */
              className={uploading ? 'upload-zone-uploading' : ''}
              onClick={() => proposalInputRef.current?.click()}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--ac)'; (e.currentTarget as HTMLDivElement).style.background = 'var(--ac-bg)'; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = uploading ? 'var(--ac)' : 'var(--border-s)'; (e.currentTarget as HTMLDivElement).style.background = 'var(--bg)'; }}
              style={
                isRunning || uploading
                  ? { pointerEvents: 'none', opacity: 0.6, padding: '24px 20px', textAlign: 'center', border: '1.5px dashed var(--border-s)', borderRadius: 'var(--r2)', background: 'var(--bg)', marginTop: proposals.length > 0 ? 8 : 0 }
                  : { padding: '24px 20px', textAlign: 'center', border: '1.5px dashed var(--border-s)', borderRadius: 'var(--r2)', background: 'var(--bg)', cursor: 'pointer', transition: 'all .2s', marginTop: proposals.length > 0 ? 8 : 0 }
              }
            >
              <div style={{ width: 40, height: 40, background: 'rgba(0,0,0,.06)', borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 10px' }}>
                <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="var(--ac)" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Add Vendor Proposal</div>
              <div style={{ fontSize: 12, color: 'var(--t3)' }}>Upload multiple PDFs at once</div>
            </div>
          </div>
        </div>
      </div>

      {/* Post-audit section */}
      {auditComplete && !vendorDocsStale && project && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, animation: 'fadeUp .25s ease' }}>
          {auditResults && auditResults.admin_checks.length > 0 ? (
            <AdminPreScreeningCard auditResults={auditResults} projectId={project.id} />
          ) : (
            <div style={{ padding: '12px 16px', background: 'var(--ac-bg)', borderRadius: 'var(--r)', border: '1px solid rgba(12,123,114,.2)', fontSize: 12, color: '#0A5954' }}>
              <strong>Admin pre-screening:</strong> Re-upload vendor proposals to enable automatic document checks.
            </div>
          )}

          <div
            role="button"
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, padding: '18px 24px', borderRadius: 'var(--r)', background: '#0C7B72', textDecoration: 'none', cursor: 'pointer', transition: 'box-shadow .2s ease, transform .18s ease' }}
            onClick={() => setShowReportModal(true)}
            onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.boxShadow = '0 8px 24px rgba(12,123,114,.4)'; (e.currentTarget as HTMLDivElement).style.transform = 'translateY(-1px)'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.boxShadow = 'none'; (e.currentTarget as HTMLDivElement).style.transform = 'none'; }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <div style={{ width: 40, height: 40, borderRadius: 10, background: 'rgba(255,255,255,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="white" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                </svg>
              </div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'white', marginBottom: 3 }}>Export Audit Report</div>
                <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.7)' }}>Cover page · Compliance matrix · Risk findings · Methodology note</div>
              </div>
            </div>
            <div style={{ padding: '9px 20px', borderRadius: 8, background: 'white', color: '#0C7B72', fontSize: 13, fontWeight: 700, flexShrink: 0, whiteSpace: 'nowrap' }}>
              Download Report
            </div>
          </div>
        </div>
      )}

      {proposals.length > 0 && !auditComplete && (
        <div style={{ padding: '12px 16px', background: 'var(--ac-bg)', borderRadius: 'var(--r)', border: '1px solid rgba(12,123,114,.2)', fontSize: 12, color: '#0A5954' }}>
          <strong>Admin pre-screening:</strong> Once the audit runs, TenderAI automatically checks all proposals for required documents (B-BBEE certificate, tax clearance, VAT registration, signed declaration).
        </div>
      )}

      {/* [MOTION] Report generation modal */}
      {showReportModal && project && (
        <ReportGenerationModal
          onComplete={() => {
            // [MOTION] actual download fires after animation completes
            window.open(getExportUrl(project.id), '_blank', 'noopener,noreferrer');
            setShowReportModal(false);
          }}
        />
      )}

      {/* Hidden file inputs */}
      <input ref={rfpInputRef} type="file" accept=".pdf,.docx" style={{ display: 'none' }} onChange={handleRfpUpload} />
      <input ref={proposalInputRef} type="file" accept=".pdf,.docx" style={{ display: 'none' }} onChange={handleProposalFileChange} />

      {/* ── Vendor name modal with pop-in entrance ─────────────────────── */}
      {vendorModal && (
        <>
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.4)', zIndex: 600, animation: 'overlayIn .2s ease' }} onClick={() => setVendorModal(false)} />
          {/* NEW: pop-in class for spring entrance */}
          <div className="pop-in" style={{ position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', background: 'var(--surface)', borderRadius: 14, padding: 0, width: 'min(420px,90vw)', boxShadow: 'var(--sh3)', zIndex: 601, overflow: 'hidden' }}>
            <div style={{ padding: '18px 20px', borderBottom: '1px solid var(--border)', fontSize: 15, fontWeight: 700 }}>
              Vendor Information
            </div>
            <form onSubmit={submitProposal} style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ fontSize: 13, color: 'var(--t2)', lineHeight: 1.6 }}>
                Enter the vendor name exactly as you want it to appear in the compliance matrix and audit report.
              </div>
              {pendingFile && (
                <div style={{ fontSize: 12, color: 'var(--t3)', fontFamily: 'var(--font-mono)', padding: '6px 10px', background: 'var(--bg)', borderRadius: 'var(--r)', border: '1px solid var(--border)' }}>
                  📄 {pendingFile.name}
                </div>
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--t2)' }}>
                  Vendor name <span style={{ color: 'var(--none)' }}>*</span>
                </label>
                <input
                  type="text"
                  autoFocus
                  value={vendorName}
                  onChange={(e) => setVendorName(e.target.value)}
                  placeholder="e.g. Nexus Systems Pty Ltd"
                  style={{ padding: '9px 12px', borderRadius: 'var(--r)', border: '1px solid var(--border-s)', fontFamily: 'inherit', fontSize: 13, outline: 'none', transition: 'border-color .15s, box-shadow .15s' }}
                  onFocus={(e) => { e.target.style.borderColor = 'var(--ac)'; e.target.style.boxShadow = '0 0 0 3px rgba(12,123,114,.1)'; }}
                  onBlur={(e) => { e.target.style.borderColor = 'var(--border-s)'; e.target.style.boxShadow = 'none'; }}
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                <button type="button" className="btn btn-g" onClick={() => setVendorModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-p" disabled={!vendorName.trim() || uploading}>Upload proposal</button>
              </div>
            </form>
          </div>
        </>
      )}
    </div>
  );
}