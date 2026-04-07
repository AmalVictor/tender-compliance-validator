'use client';
// src/app/dashboard/[projectId]/DashboardClient.tsx

import React, { useEffect, useState, useRef, useCallback } from 'react';
import { ProjectProvider, useProject } from '@/context/ProjectContext';
import { useToast } from '@/context/ToastContext';
import { Sidebar, type TabId } from '@/components/Sidebar';
import { TopNav } from '@/components/TopNav';
import { Workspace } from '@/components/Workspace';
import { ComplianceMatrix } from '@/components/ComplianceMatrix';
import { RiskHeatmap } from '@/components/RiskHeatmap';
import { RequirementsReview } from '@/components/RequirementsReview';
import { DeepDive } from '@/components/DeepDive';
import { Chatbot } from '@/components/Chatbot';
import { extractRequirements, getAuditStatus, getExportUrl, ApiError } from '../../../lib/api';
import type { AuditStatus } from '@/types';

//Slower count-up for compliance matrix KPI numbers
function CountUpSlow({ target, suffix = '' }: { target: number; suffix?: string }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    if (!target) return;
    const duration = 1600;
    const steps = 36;
    const step = target / steps;
    let current = 0;
    const interval = setInterval(() => {
      current += step;
      if (current >= target) {
        setDisplay(target);
        clearInterval(interval);
      } else {
        setDisplay(Math.round(current));
      }
    }, duration / steps);
    return () => clearInterval(interval);
  }, [target]);
  return <span style={{ animation: 'countUp .35s ease forwards' }}>{display}{suffix}</span>;
}

// ── Gap summary (derived from matrix) ────────────────────────────────────────
function GapSummaryCard({ matrix }: { matrix: any[] }) {
  const noCompliant = matrix.filter((r) => r.matches.every((m: any) => m.status === 'NONE')).length;
  const singleVendor = matrix.filter((r) => r.matches.filter((m: any) => m.status === 'FULL').length === 1 && r.requirement.criticality === 'Mandatory').length;
  const multiVendor = matrix.filter((r) => r.matches.filter((m: any) => m.status === 'FULL').length >= 2).length;

  return (
    <div className="card">
      <div className="ch">
        <div className="ct">Gap Summary</div>
        <span style={{ fontSize: 11, color: 'var(--t3)' }}>Derived from compliance matrix</span>
      </div>
      <div className="cb">
        <div className="gap-summary">
          <div className="gs-item" style={{ background: '#FEF8F8', borderColor: '#FECACA' }}>
            <div className="gs-val" style={{ color: 'var(--none)' }}><CountUpSlow target={noCompliant} /></div>
            <div className="gs-label" style={{ color: '#991B1B' }}>Mandatory requirements with <strong>no compliant vendor</strong></div>
            <div className="gs-sub">Require negotiation or disqualification</div>
          </div>
          <div className="gs-item" style={{ background: '#FFF7ED', borderColor: '#FDE68A' }}>
            <div className="gs-val" style={{ color: 'var(--part)' }}><CountUpSlow target={singleVendor} /></div>
            <div className="gs-label" style={{ color: '#92400E' }}>Mandatory reqs met by <strong>only 1 vendor</strong></div>
            <div className="gs-sub">Single-source dependency risk</div>
          </div>
          <div className="gs-item" style={{ background: '#ECFDF5', borderColor: '#A7D9D6' }}>
            <div className="gs-val" style={{ color: 'var(--full)' }}><CountUpSlow target={multiVendor} /></div>
            <div className="gs-label" style={{ color: '#065F46' }}>Requirements where <strong>2+ vendors comply</strong></div>
            <div className="gs-sub">Healthy competition — proceed on cost</div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Verdict card ──────────────────────────────────────────────────────────────
function VerdictCard({ summary, onCompare }: { summary: any; onCompare: () => void }) {
  if (!summary?.recommended_vendor) return null;
  return (
    <div className="verdict-card">
      <div className="vc-icon">
        <svg width="22" height="22" fill="none" viewBox="0 0 24 24" stroke="white" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>
      <div className="vc-body">
        <div className="vc-label">AI Award Recommendation</div>
        <div className="vc-title">
          {summary.recommended_vendor}
          <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--t2)' }}> — recommended for award</span>
        </div>
        <div className="vc-reason">
          {summary.critical_risks > 0
            ? `⚠ ${summary.critical_risks} critical risk(s) found across all vendors — review before award.`
            : 'Best compliance score with no critical risks. All mandatory requirements satisfied.'}
        </div>
      </div>
      <div className="vc-scores">
        <div className="vc-score">
          <div className="vc-score-val" style={{ color: 'var(--full)' }}><CountUpSlow target={summary.best_compliance_score} suffix="%" /></div>
          <div className="vc-score-lbl">Compliance</div>
        </div>
        <div className="vc-score">
          <div className="vc-score-val" style={{ color: 'var(--med)' }}><CountUpSlow target={summary.gap_count} /></div>
          <div className="vc-score-lbl">Gaps</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, justifyContent: 'center' }}>
          <button className="btn btn-p btn-sm" onClick={onCompare}>Compare vendors</button>
        </div>
      </div>
    </div>
  );
}

// ── Audit gate empty state ────────────────────────────────────────────────────
function AuditEmptyState({ onRunAudit }: { onRunAudit: () => void }) {
  return (
    <div className="card" style={{ padding: '48px 32px', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
      <div style={{ width: 56, height: 56, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 14, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 24 }}>
        🤖
      </div>
      <div>
        <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--t1)', marginBottom: 6 }}>No audit data yet</div>
        <div style={{ fontSize: 13, color: 'var(--t3)', lineHeight: 1.6, maxWidth: 380 }}>
          Upload your RFP and at least one vendor proposal in the Workspace, then run the compliance audit to populate this view.
        </div>
      </div>
      <button className="btn-run" onClick={onRunAudit}>
        Go to Workspace →
      </button>
    </div>
  );
}

// ── Inner dashboard ───────────────────────────────────────────────────────────
function DashboardInner({ projectId }: { projectId: string }) {
  const {
    project,
    auditResults,
    auditStatus,
    requirements,
    loadProject,
    loadAuditResults,
    loadRequirements,
    setAuditStatus,
    setAuditResults,
  } = useProject();

  const toast = useToast();
  // --- UI State with localStorage hydration ---
  const [activeTab, setActiveTab] = useState<TabId>(() => {
    if (typeof window !== 'undefined') {
      return (localStorage.getItem(`dashboard:${projectId}:activeTab`) as TabId) || 'workspace';
    }
    return 'workspace';
  });
  const [chatOpen, setChatOpen] = useState(false);
  const [deepDiveReqId, setDeepDiveReqId] = useState<string | undefined>();
  const [backendDown, setBackendDown] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Progressive disclosure state (driven by Workspace uploads + Requirements confirmation).
  const [hasRfp, setHasRfp] = useState(false);
  const [hasVendorDocs, setHasVendorDocs] = useState(false);
  const [reqsExtracted, setReqsExtracted] = useState(false);
  const [vendorDocsStale, setVendorDocsStale] = useState(false);
  const [rfpSignature, setRfpSignature] = useState<string>('');
  const [proposalsSignature, setProposalsSignature] = useState<string>('');

  // --- Initialization loading state ---
  const [isInitializing, setIsInitializing] = useState(true);

  const reqsForState = requirements.length > 0 ? requirements : (auditResults?.requirements ?? []);
  const reqCount = reqsForState.length;
  const reqsConfirmed = reqsExtracted && reqCount > 0 && reqsForState.every((r) => r.confirmed);

  // If we have audit results OR the status is complete, audit is inherently complete
  const auditComplete = !!auditResults || auditStatus?.status === 'complete';
  const auditCompleteEffective = auditComplete && !vendorDocsStale;

  const reqSignature = JSON.stringify(
    [...reqsForState]
      .sort((a, b) => String(a.id).localeCompare(String(b.id)))
      .map((r) => [r.id, r.confirmed]),
  );
  const auditReqSignatureRef = useRef<string | null>(null);
  const auditVendorDocsSignatureRef = useRef<string | null>(null);
  const auditRfpSignatureRef = useRef<string | null>(null);
  const stalePromptedRef = useRef(false);
  const vendorStalePromptedRef = useRef(false);
  const prevAuditCompleteRef = useRef(false);
  const prevRfpSignatureRef = useRef<string | null>(null);

  // Sidebar tab badges: red until all confirmed, then green.
  const reqBadgeColorClass = reqsConfirmed ? 'tcnt-g' : 'tcnt-r';

  const handleDocsChanged = useCallback((flags: {
    hasRfp: boolean;
    hasVendorDocs: boolean;
    rfpSignature: string;
    proposalsSignature: string;
  }) => {
    setHasRfp(flags.hasRfp);
    setHasVendorDocs(flags.hasVendorDocs);
    setRfpSignature(flags.rfpSignature);
    setProposalsSignature(flags.proposalsSignature);
  }, []);

  const handleExtractRequirements = useCallback(async () => {
    await extractRequirements(projectId);
    setReqsExtracted(true);
  }, [projectId]);

  // Counts for tab badges
  const gapCount = auditResults?.matrix.filter((r) => r.matches.some((m) => m.status === 'NONE')).length ?? 0;
  const riskCount = auditResults?.risks.length ?? 0;

  // When audit completes, snapshot confirmed requirements and clear stale.
  useEffect(() => {
    if (!auditComplete) {
      prevAuditCompleteRef.current = false;
      return;
    }
    if (!prevAuditCompleteRef.current) {
      auditReqSignatureRef.current = reqSignature;
      if (proposalsSignature) auditVendorDocsSignatureRef.current = proposalsSignature;
      if (rfpSignature) auditRfpSignatureRef.current = rfpSignature;
      stalePromptedRef.current = false;
      vendorStalePromptedRef.current = false;
      setVendorDocsStale(false);
    }
    prevAuditCompleteRef.current = true;
  }, [auditComplete, reqSignature, proposalsSignature, rfpSignature]);

  // Graceful re-runs: if requirements are edited after an audit completed, lock the pay-off tabs.
  useEffect(() => {
    if (!auditComplete) return;
    
    if (isInitializing || !reqSignature) return;
    if (!auditReqSignatureRef.current) return;
    if (reqSignature === auditReqSignatureRef.current) return;

    if (!stalePromptedRef.current) {
      stalePromptedRef.current = true;
      setVendorDocsStale(true);
      toast.showToast('Vendor documents are stale. Re-run Audit for new requirements.', 'warning');
    }
  }, [auditComplete, reqSignature, toast, isInitializing]);

  // If vendor documents change after audit completion, force a re-run.
  useEffect(() => {
    if (!auditComplete) return;
    
    if (isInitializing || !proposalsSignature) return;
    if (!auditVendorDocsSignatureRef.current) return;
    if (proposalsSignature === auditVendorDocsSignatureRef.current) return;

    if (!vendorStalePromptedRef.current) {
      vendorStalePromptedRef.current = true;
      setVendorDocsStale(true);
      toast.showToast('Vendor documents changed. Re-run Audit for updated proposals.', 'warning');
    }
  }, [auditComplete, proposalsSignature, toast, isInitializing]);

  // If we already have auditComplete but the vendor signature hasn't arrived yet
  // (e.g. Workspace docs load after audit results), capture the snapshot once.
  useEffect(() => {
    if (!auditComplete) return;
    if (!auditVendorDocsSignatureRef.current && proposalsSignature) {
      auditVendorDocsSignatureRef.current = proposalsSignature;
    }
    if (!auditRfpSignatureRef.current && rfpSignature) {
      auditRfpSignatureRef.current = rfpSignature;
    }
  }, [auditComplete, proposalsSignature, rfpSignature]);

  // If a new RFP is uploaded, reset the progressive-disclosure gate.
  useEffect(() => {
    if (!rfpSignature) return;
    if (prevRfpSignatureRef.current && rfpSignature !== prevRfpSignatureRef.current) {
      setReqsExtracted(false);
      if (auditComplete) setVendorDocsStale(true);
    }
    prevRfpSignatureRef.current = rfpSignature;
  }, [rfpSignature, auditComplete]);

  // ── Initial load ──────────────────────────────────────────────────────────
  useEffect(() => {
    setIsInitializing(true);
    (async () => {
      try {
        await loadProject(projectId);
      } catch (e: any) {
        if (e?.status === 0) { setBackendDown(true); toast.showError('Cannot connect to backend — demo mode'); }
        else toast.showError(e?.message ?? 'Failed to load project');
      }
      try {
        await loadAuditResults(projectId);
      } catch { }
      try {
        await loadRequirements(projectId);
      } catch { }
      try {
        const status = await getAuditStatus(projectId);
        setAuditStatus(status);
      } catch { }

      // --- Hydrate UI state from localStorage ---
      if (typeof window !== 'undefined') {
        const storedTab = localStorage.getItem(`dashboard:${projectId}:activeTab`);
        if (storedTab) setActiveTab(storedTab as TabId);
      }

      setIsInitializing(false);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // --- Hydrate reqsExtracted from requirements ---
  useEffect(() => {
    if (requirements.length > 0) {
      setReqsExtracted(true);
    }
  }, [requirements]);

  // --- Always unlock audit tabs if audit is complete and results exist ---
  useEffect(() => {
    if (auditResults && auditStatus?.status === 'complete') {
      setVendorDocsStale(false);
    }
  }, [auditResults, auditStatus]);

  // ── Poll when audit running ──────────────────────────────────────────────
  useEffect(() => {
    if (auditStatus?.status !== 'running') return;

    const poll = async () => {
      try {
        const latest: AuditStatus = await getAuditStatus(projectId);
        setAuditStatus(latest);

        if (latest.status === 'complete') {
          await loadAuditResults(projectId);
          await loadRequirements(projectId);
          toast.showSuccess('Audit complete! Results are ready.');
        } else if (latest.status === 'error') {
          toast.showError('Audit encountered an error. Check the backend logs.');
        } else {
          pollRef.current = setTimeout(poll, 2500);
        }
      } catch {
        pollRef.current = setTimeout(poll, 4000); // retry on transient network error
      }
    };

    pollRef.current = setTimeout(poll, 2500);
    return () => { if (pollRef.current) clearTimeout(pollRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditStatus?.status]);

  // ── Tab change with audit gate ────────────────────────────────────────────
  const handleTabChange = useCallback((tab: TabId) => {
    if (tab === 'reqs' && !reqsExtracted) {
      toast.showInfo('Extract requirements first.');
      return;
    }
    if (tab !== 'workspace' && tab !== 'reqs' && (!auditComplete || vendorDocsStale)) {
      toast.showInfo(vendorDocsStale ? 'Re-run audit to update results.' : 'Run the compliance audit first to unlock this view.');
      return;
    }
    setActiveTab(tab);
    if (typeof window !== 'undefined') {
      localStorage.setItem(`dashboard:${projectId}:activeTab`, tab);
    }
  }, [auditComplete, reqsExtracted, toast, vendorDocsStale, projectId]);

  // If stale flag gets raised, pull user back to Workspace.
  useEffect(() => {
    if (!vendorDocsStale) return;
    if (activeTab === 'matrix' || activeTab === 'heatmap' || activeTab === 'deepdive') {
      setActiveTab('workspace');
    }
  }, [vendorDocsStale, activeTab]);

  // ── Deep dive shortcut ────────────────────────────────────────────────────
  const handleDeepDive = useCallback((reqId: string) => {
    setDeepDiveReqId(reqId);
    setActiveTab('deepdive');
  }, []);

  // ── Export ────────────────────────────────────────────────────────────────
  const handleExport = useCallback(() => {
    if (!auditResults) { toast.showInfo('Run an audit first to generate the report.'); return; }
    window.open(getExportUrl(projectId), '_blank', 'noopener,noreferrer');
    toast.showInfo('Opening export…');
  }, [auditResults, projectId, toast]);

  const reqs = requirements.length > 0 ? requirements : (auditResults?.requirements ?? []);

  // Project sub-title: rich metadata from project object
  const projectSub = [
    project?.reference,
    project?.due_date ? `Due ${new Date(project.due_date).toLocaleDateString('en-ZA', { day: 'numeric', month: 'short', year: 'numeric' })}` : null,
    project?.contract_value,
    project?.document_count ? `${project.document_count} docs` : null,
  ].filter(Boolean).join(' · ');

  if (isInitializing) {
    return (
      <div style={{ 
        display: 'flex', 
        flexDirection: 'column', 
        alignItems: 'center', 
        justifyContent: 'center', 
        height: '80vh',
        gap: '16px',
        fontFamily: 'system-ui, -apple-system, sans-serif'
      }}>
        {/* Sleek SVG Spinner */}
        <svg 
          style={{ width: '40px', height: '40px', color: '#059669', animation: 'spin 1s linear infinite' }} 
          xmlns="http://www.w3.org/2000/svg" 
          fill="none" 
          viewBox="0 0 24 24"
        >
          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.2"></circle>
          <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        
        {/* Muted, professional text */}
        <div style={{ 
          fontSize: '15px', 
          fontWeight: 500, 
          color: '#52525B', 
          letterSpacing: '0.3px',
          animation: 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite'
        }}>
          Preparing your dashboard...
        </div>
      </div>
    );
  }

  return (
    <div className="layout">
      <Sidebar
        activeTab={activeTab}
        onTabChange={handleTabChange}
        chatOpen={chatOpen}
        onChatToggle={() => setChatOpen((v) => !v)}
      />

      <div className="main">
        <TopNav
          projectName={project?.name ?? '…'}
          projectSub={projectSub}
          summary={auditResults?.summary ?? null}
          onTabChange={handleTabChange}
          onExport={handleExport}
        />

        {/* Running banner */}
        {auditStatus?.status === 'running' && (
          <div style={{
            background: 'linear-gradient(135deg, #0C7B72, #059669)',
            color: 'white',
            padding: '8px 22px',
            fontSize: 12,
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            flexShrink: 0,
          }}>
            <span className="spin">⟳</span>
            Audit is running — results will appear automatically when complete
          </div>
        )}

        {/* Tab bar */}
        <div className="tabs">
          {[
            { id: 'workspace' as TabId, label: 'Workspace', locked: false },
            { id: 'reqs' as TabId, label: 'Requirements', locked: !reqsExtracted, cnt: reqsExtracted ? reqCount : undefined, cc: reqBadgeColorClass },
            { id: 'matrix' as TabId, label: 'Compliance Matrix', locked: !auditComplete || vendorDocsStale, cnt: gapCount > 0 ? `${gapCount} gaps` : undefined, cc: 'tcnt-r' },
            { id: 'heatmap' as TabId, label: 'Risk Heatmap', locked: !auditComplete || vendorDocsStale, cnt: riskCount > 0 ? `${riskCount} risks` : undefined, cc: 'tcnt-o' },
            { id: 'deepdive' as TabId, label: 'Deep Dive', locked: !auditComplete || vendorDocsStale },
          ].map((t) => (
            <div
              key={t.id}
              className={`tab ${activeTab === t.id ? 'on' : ''} ${t.locked ? 'locked' : ''}`}
              onClick={() => handleTabChange(t.id)}
              title={t.locked ? 'Run an audit first to unlock' : undefined}
              style={t.locked ? { opacity: .45, cursor: 'not-allowed' } : undefined}
            >
              <div className="tab-dot" />
              {t.label}
              {t.locked && <span style={{ fontSize: 10, marginLeft: 4 }}>🔒</span>}
              {!t.locked && t.cnt !== undefined && t.cnt !== 0 && (
                <span className={`tcnt ${t.cc}`}>{t.cnt}</span>
              )}
            </div>
          ))}
        </div>

        {/* Content area */}
        <div className="cr">
          <div className="scr">

            {/* Workspace */}
            <div className={`pane ${activeTab === 'workspace' ? 'on' : ''}`}>
              <Workspace
                reqsExtracted={reqsExtracted}
                reqsConfirmed={reqsConfirmed}
                auditComplete={auditCompleteEffective}
                vendorDocsStale={vendorDocsStale}
                auditResults={auditResults}
                onExtractRequirements={handleExtractRequirements}
                onDocsChanged={handleDocsChanged}
              />
            </div>

            {/* Requirements */}
            <div className={`pane ${activeTab === 'reqs' ? 'on' : ''}`}>
              <RequirementsReview requirements={reqs} />
            </div>

            {/* Compliance Matrix */}
            <div className={`pane ${activeTab === 'matrix' ? 'on' : ''}`}>
              {auditResults ? (
                <>
                  <VerdictCard summary={auditResults.summary} onCompare={() => setActiveTab('deepdive')} />
                  <GapSummaryCard matrix={auditResults.matrix} />
                  <ComplianceMatrix matrix={auditResults.matrix} onDeepDive={handleDeepDive} />
                </>
              ) : (
                <AuditEmptyState onRunAudit={() => setActiveTab('workspace')} />
              )}
            </div>

            {/* Risk Heatmap */}
            <div className={`pane ${activeTab === 'heatmap' ? 'on' : ''}`}>
              {auditResults ? (
                <RiskHeatmap heatmap={auditResults.heatmap} risks={auditResults.risks} />
              ) : (
                <AuditEmptyState onRunAudit={() => setActiveTab('workspace')} />
              )}
            </div>

            {/* Deep Dive */}
            <div className={`pane ${activeTab === 'deepdive' ? 'on' : ''}`}>
              {auditResults ? (
                <DeepDive auditResults={auditResults} initialReqId={deepDiveReqId} />
              ) : (
                <AuditEmptyState onRunAudit={() => setActiveTab('workspace')} />
              )}
            </div>

          </div>

          <Chatbot
            projectId={projectId}
            chatOpen={chatOpen}
            onClose={() => setChatOpen(false)}
            vendorNames={auditResults?.vendor_scores.map(v => v.vendor_name)}
          //onOpenPdf={(docId, page, name) => openYourPdfModal(docId, page)}
          />
        </div>
      </div>
    </div>
  );
}

// ── Exported: wraps with providers ───────────────────────────────────────────
export default function DashboardClient({ projectId }: { projectId: string }) {
  return (
    <ProjectProvider>
      <DashboardInner projectId={projectId} />
    </ProjectProvider>
  );
}