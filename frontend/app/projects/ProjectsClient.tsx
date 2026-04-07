'use client';
// src/app/projects/ProjectsClient.tsx

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getProjects, createProject, deleteProject, ApiError } from '../../lib/api';
import { useToast } from '../../context/ToastContext';
import type { Project } from '../../types';
import styles from './projects.module.css';

// ─── Status config ────────────────────────────────────────────────────────────
const STATUS_COLORS: Record<string, string> = {
  complete: 'var(--full)',
  running: 'var(--med)',
  pending: 'var(--t3)',
  error: 'var(--none)',
};
const STATUS_LABELS: Record<string, string> = {
  complete: 'Audit complete',
  running: 'Audit running…',
  pending: 'Awaiting documents',
  error: 'Audit error',
};

// ─── Demo fallback data ───────────────────────────────────────────────────────
const DEMO_PROJECTS: Project[] = [
  {
    id: 'demo-1',
    name: 'Dept. of Health — ICT Infrastructure Tender 2025',
    description: 'Comprehensive ICT infrastructure services including data centres, networking, and managed security.',
    reference: 'DOH-ICT-2025-004',
    due_date: '2025-04-15',
    contract_value: 'R 42.8M',
    client_department: 'Department of Health',
    created_at: '2025-03-20T09:00:00Z',
    audit_complete: true,
    audit_status: 'complete',
    document_count: 4,
    requirement_count: 10,
    vendor_count: 3,
    best_compliance_score: 92,
  },
  {
    id: 'demo-2',
    name: 'SAPS Vehicle Fleet Management RFQ 2024',
    reference: 'SAPS-VFM-2024-011',
    due_date: '2024-11-30',
    contract_value: 'R 18.2M',
    client_department: 'South African Police Service',
    created_at: '2024-10-01T08:30:00Z',
    audit_complete: true,
    audit_status: 'complete',
    document_count: 6,
    requirement_count: 14,
    vendor_count: 5,
    best_compliance_score: 78,
  },
  {
    id: 'demo-3',
    name: 'ESKOM IT Services Renewal 2025',
    reference: 'EKM-IT-2025-003',
    due_date: '2025-06-01',
    contract_value: 'R 67.5M',
    client_department: 'Eskom Holdings SOC',
    created_at: '2025-04-01T11:00:00Z',
    audit_complete: false,
    audit_status: 'running',
    document_count: 2,
    requirement_count: 0,
    vendor_count: 0,
    best_compliance_score: 0,
  },
];

// ─── Form shape ───────────────────────────────────────────────────────────────
interface CreateProjectForm {
  name: string;
  description: string;
  reference: string;
  client_department: string;
  due_date: string;
  contract_value: string;
}
const EMPTY_FORM: CreateProjectForm = {
  name: '', description: '', reference: '',
  client_department: '', due_date: '', contract_value: '',
};

// ─── Compliance ring SVG ──────────────────────────────────────────────────────
// Pure SVG arc — no library. Shows audit score at a glance.
function ComplianceRing({ score, status }: { score: number; status: string }) {
  const r = 18;
  const stroke = 3.5;
  const norm = r - stroke / 2;
  const circ = 2 * Math.PI * norm;
  // Only render ring when audit is complete and score is meaningful
  const hasSore = status === 'complete' && score > 0;
  const dash = hasSore ? (score / 100) * circ : 0;
  const color = score >= 80 ? 'var(--full)' : score >= 60 ? 'var(--med)' : 'var(--none)';

  return (
    <div className={styles.ringWrap} title={hasSore ? `Best compliance: ${score}%` : undefined}>
      <svg width={r * 2} height={r * 2} style={{ transform: 'rotate(-90deg)' }}>
        {/* Track */}
        <circle cx={r} cy={r} r={norm} fill="none" stroke="var(--border-s)" strokeWidth={stroke} />
        {/* Arc — only when there's data */}
        {hasSore && (
          <circle
            cx={r} cy={r} r={norm}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeDasharray={`${dash} ${circ}`}
            strokeLinecap="round"
            className={styles.ringArc}
          />
        )}
      </svg>
      <span className={styles.ringLabel} style={{ color: hasSore ? color : 'var(--t3)' }}>
        {hasSore ? `${score}%` : '—'}
      </span>
    </div>
  );
}

// ─── Status dot (with pulse for running) ─────────────────────────────────────
function StatusDot({ status }: { status: string }) {
  return (
    <span
      className={`${styles.statusDot} ${status === 'running' ? styles.statusDotRunning : ''}`}
      style={{ background: STATUS_COLORS[status] ?? 'var(--t3)' }}
      title={STATUS_LABELS[status]}
    />
  );
}

// ─── Empty state ──────────────────────────────────────────────────────────────
function EmptyState({ onNew }: { onNew: () => void }) {
  return (
    <div className={styles.emptyState}>
      {/* Pulsing document stack illustration — pure SVG */}
      <div className={styles.emptyIllustration}>
        <svg width="80" height="80" viewBox="0 0 80 80" fill="none" aria-hidden>
          {/* Back sheet */}
          <rect className={styles.emptyDoc3} x="18" y="22" width="44" height="54" rx="5"
            fill="#E5F5F3" stroke="#A7D9D6" strokeWidth="1.5" />
          {/* Mid sheet */}
          <rect className={styles.emptyDoc2} x="12" y="16" width="44" height="54" rx="5"
            fill="#F4F3EF" stroke="var(--border-s)" strokeWidth="1.5" />
          {/* Front sheet */}
          <rect className={styles.emptyDoc1} x="6" y="10" width="44" height="54" rx="5"
            fill="white" stroke="var(--border-s)" strokeWidth="1.5" />
          {/* Lines on front sheet */}
          <rect x="13" y="22" width="26" height="3" rx="1.5" fill="var(--border-s)" />
          <rect x="13" y="29" width="20" height="3" rx="1.5" fill="var(--border-s)" />
          <rect x="13" y="36" width="24" height="3" rx="1.5" fill="var(--border-s)" />
          {/* Spark/star — the AI indicator */}
          <circle cx="62" cy="18" r="10" fill="var(--ac-bg)" stroke="#A7D9D6" strokeWidth="1.5" />
          <text x="62" y="22" textAnchor="middle" fontSize="11" fill="var(--ac)">✦</text>
        </svg>
      </div>
      <div className={styles.emptyTitle}>No projects yet</div>
      <div className={styles.emptySub}>
        Create your first tender project to start uploading RFPs and running compliance audits.
      </div>
      <button className={styles.emptyBtn} onClick={onNew}>
        <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
        Create first project
      </button>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function ProjectsClient() {
  const router = useRouter();
  const toast = useToast();

  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [mounted, setMounted] = useState(false); // drives entrance animation
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState<CreateProjectForm>(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [formErrors, setFormErrors] = useState<Partial<CreateProjectForm>>({});
  const [backendDown, setBackendDown] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  useEffect(() => {
    getProjects()
      .then((data) => { setProjects(data); setLoading(false); })
      .catch((err) => {
        if (err instanceof ApiError && err.isNetworkError) {
          setBackendDown(true);
          setProjects(DEMO_PROJECTS);
          toast.showInfo('Backend offline — showing demo projects');
        } else {
          toast.showError(err.message);
        }
        setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Trigger entrance animation on the frame after first paint
  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);

  // ── Form helpers ────────────────────────────────────────────────────────────
  function validateForm(): boolean {
    const errs: Partial<CreateProjectForm> = {};
    if (!form.name.trim()) errs.name = 'Project name is required';
    if (form.due_date && isNaN(new Date(form.due_date).getTime()))
      errs.due_date = 'Invalid date format';
    setFormErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!validateForm()) return;
    setCreating(true);
    try {
      const proj = await createProject({
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        reference: form.reference.trim() || undefined,
        client_department: form.client_department.trim() || undefined,
        due_date: form.due_date || undefined,
        contract_value: form.contract_value.trim() || undefined,
      });
      toast.showSuccess(`Project "${proj.name}" created`);
      setShowNew(false);
      setForm(EMPTY_FORM);
      router.push(`/dashboard/${proj.id}`);
    } catch (err) {
      const msg = err instanceof ApiError
        ? (err.isNetworkError ? 'Backend offline — start FastAPI on port 8000' : err.message)
        : 'Failed to create project';
      toast.showError(msg);
      if (err instanceof ApiError && err.isNetworkError) {
        router.push('/dashboard/demo-1');
      }
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string) {
    setDeleteConfirm(null);
    try {
      await deleteProject(id);
      setProjects((prev) => prev.filter((p) => p.id !== id));
      toast.showSuccess('Project deleted');
    } catch (err) {
      toast.showError(err instanceof ApiError ? err.message : 'Failed to delete project');
    }
  }

  function update(field: keyof CreateProjectForm, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
    if (formErrors[field]) setFormErrors((prev) => ({ ...prev, [field]: undefined }));
  }

  // ── Derived summary stats ───────────────────────────────────────────────────
  const totalVendors = projects.reduce((s, p) => s + (p.vendor_count ?? 0), 0);
  const completeCount = projects.filter((p) => p.audit_status === 'complete').length;
  const runningCount = projects.filter((p) => p.audit_status === 'running').length;

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className={styles.root}>

      {/* ── Hero header with mesh gradient ─────────────────────────────── */}
      <header className={styles.hero}>
        {/* Decorative SVG grid pattern — absolutely positioned, pointer-events none */}
        <svg className={styles.heroGrid} aria-hidden width="100%" height="100%"
          xmlns="http://www.w3.org/2000/svg">
          <defs>
            <pattern id="pg" width="32" height="32" patternUnits="userSpaceOnUse">
              <path d="M 32 0 L 0 0 0 32" fill="none" stroke="rgba(12,123,114,0.07)" strokeWidth="1" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#pg)" />
        </svg>

        <div className={styles.heroInner}>
          <div className={styles.heroBrand}>
            <div className={styles.heroLogo}>TA</div>
            <span className={styles.heroBrandName}>TenderAI</span>
          </div>

          {/* Summary stats row */}
          {!loading && projects.length > 0 && (
            <div className={`${styles.heroStats} ${mounted ? styles.heroStatsVisible : ''}`}>
              <div className={styles.heroStat}>
                <div className={styles.heroStatVal}>{projects.length}</div>
                <div className={styles.heroStatLbl}>Projects</div>
              </div>
              <div className={styles.heroStatDivider} />
              <div className={styles.heroStat}>
                <div className={styles.heroStatVal} style={{ color: 'var(--full)' }}>{completeCount}</div>
                <div className={styles.heroStatLbl}>Audited</div>
              </div>
              <div className={styles.heroStatDivider} />
              <div className={styles.heroStat}>
                <div className={styles.heroStatVal}>{totalVendors}</div>
                <div className={styles.heroStatLbl}>Total vendors</div>
              </div>
              {runningCount > 0 && (
                <>
                  <div className={styles.heroStatDivider} />
                  <div className={styles.heroStat}>
                    <div className={styles.heroStatVal} style={{ color: 'var(--med)', display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span className={styles.runningPulse} />
                      {runningCount}
                    </div>
                    <div className={styles.heroStatLbl}>Running now</div>
                  </div>
                </>
              )}
            </div>
          )}

          <button
            className={styles.newBtn}
            onClick={() => { setShowNew(true); setForm(EMPTY_FORM); setFormErrors({}); }}
          >
            <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            New Project
          </button>
        </div>
      </header>

      <main className={styles.main}>
        {backendDown && (
          <div className={styles.warningBanner}>
            <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
            Backend unreachable — showing demo data. Start FastAPI at{' '}
            <code>http://localhost:8000</code>
          </div>
        )}

        <div className={styles.pageHeader}>
          <h1 className={styles.title}>Projects</h1>
          <p className={styles.sub}>Select a tender project to open its compliance dashboard</p>
        </div>

        {/* ── Loading skeletons ─────────────────────────────────────────── */}
        {loading ? (
          <div className={styles.grid}>
            {[1, 2, 3].map((i) => (
              <div key={i} className={styles.skeletonCard}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
                  <div className={`${styles.skLine} skeleton`} style={{ width: 36, height: 36, borderRadius: 9 }} />
                  <div className={`${styles.skLine} skeleton`} style={{ width: 36, height: 36, borderRadius: '50%' }} />
                </div>
                <div className={`${styles.skLine} skeleton`} style={{ width: '75%', height: 16, marginBottom: 10 }} />
                <div className={`${styles.skLine} skeleton`} style={{ width: '48%', height: 11, marginBottom: 6 }} />
                <div className={`${styles.skLine} skeleton`} style={{ width: '32%', height: 11 }} />
              </div>
            ))}
          </div>
        ) : projects.length === 0 ? (
          /* ── Empty state ─────────────────────────────────────────────── */
          <EmptyState onNew={() => { setShowNew(true); setForm(EMPTY_FORM); setFormErrors({}); }} />
        ) : (
          /* ── Project grid ────────────────────────────────────────────── */
          <div className={styles.grid}>
            {projects.map((p, i) => (
              <div
                key={p.id}
                className={`${styles.projectCard} ${mounted ? styles.projectCardVisible : ''}`}
                style={{ '--card-delay': `${i * 60}ms` } as React.CSSProperties}
                onClick={() => router.push(`/dashboard/${p.id}`)}
              >
                {/* Card top row: icon + ring + status + delete */}
                <div className={styles.cardTop}>
                  <div className={styles.projectIcon}>
                    <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                    </svg>
                  </div>

                  {/* Right cluster: ring + status dot + delete */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <ComplianceRing
                      score={(p as any).best_compliance_score ?? 0}
                      status={p.audit_status}
                    />
                    <StatusDot status={p.audit_status} />
                    <button
                      className={styles.deleteBtn}
                      onClick={(e) => { e.stopPropagation(); setDeleteConfirm(p.id); }}
                      title="Delete project"
                    >
                      <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                </div>

                <div className={styles.projectName}>{p.name}</div>

                {p.description && (
                  <div className={styles.projectDesc}>{p.description}</div>
                )}

                <div className={styles.projectMeta}>
                  {p.reference && <span className={styles.metaRef}>{p.reference}</span>}
                  {p.reference && p.contract_value && <span className={styles.metaSep}>·</span>}
                  {p.contract_value && <span>{p.contract_value}</span>}
                  {p.due_date && (
                    <>
                      <span className={styles.metaSep}>·</span>
                      <span>Due {new Date(p.due_date).toLocaleDateString('en-ZA', { day: 'numeric', month: 'short', year: 'numeric' })}</span>
                    </>
                  )}
                </div>

                <div className={styles.projectFooter}>
                  <span className={styles.auditStatus} style={{ color: STATUS_COLORS[p.audit_status] }}>
                    {STATUS_LABELS[p.audit_status]}
                  </span>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {(p.vendor_count ?? 0) > 0 && (
                      <span className={styles.vendorCount}>{p.vendor_count} vendors</span>
                    )}
                    {(p.requirement_count ?? 0) > 0 && (
                      <span className={styles.vendorCount}>{p.requirement_count} reqs</span>
                    )}
                  </div>
                </div>

                {/* Subtle hover-reveal border accent at card bottom */}
                <div className={styles.cardAccent} />
              </div>
            ))}

            {/* New project card */}
            <button
              className={styles.newCard}
              onClick={() => { setShowNew(true); setForm(EMPTY_FORM); setFormErrors({}); }}
            >
              <div className={styles.newCardIcon}>
                <svg width="22" height="22" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
              </div>
              <div className={styles.newCardLabel}>New project</div>
            </button>
          </div>
        )}
      </main>

      {/* ── Delete confirmation modal ──────────────────────────────────── */}
      {deleteConfirm && (
        <>
          <div className={styles.modalOverlay} onClick={() => setDeleteConfirm(null)} />
          <div className={styles.modal} style={{ maxWidth: 380 }}>
            <div className={styles.modalHead}>
              <h3 className={styles.modalTitle}>Delete project?</h3>
            </div>
            <div style={{ padding: '16px 20px', fontSize: 13, color: 'var(--t2)', lineHeight: 1.6 }}>
              This will permanently delete the project and all associated documents, requirements, and audit results. This action cannot be undone.
            </div>
            <div className={styles.modalFoot}>
              <button className="btn btn-g" onClick={() => setDeleteConfirm(null)}>Cancel</button>
              <button className="btn btn-p" style={{ background: 'var(--none)' }} onClick={() => handleDelete(deleteConfirm)}>
                Delete
              </button>
            </div>
          </div>
        </>
      )}

      {/* ── New project modal ──────────────────────────────────────────── */}
      {showNew && (
        <>
          <div className={styles.modalOverlay} onClick={() => setShowNew(false)} />
          <div className={styles.modal}>
            <div className={styles.modalHead}>
              <h3 className={styles.modalTitle}>Create new project</h3>
              <button className="btn btn-icon btn-g" onClick={() => setShowNew(false)}>
                <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <form className={styles.modalForm} onSubmit={handleCreate} noValidate>
              <div className={styles.field}>
                <label className={styles.label}>
                  Project name <span style={{ color: 'var(--none)' }}>*</span>
                </label>
                <input
                  className={`${styles.input} ${formErrors.name ? styles.inputError : ''}`}
                  placeholder="e.g. Dept. of Health — ICT Infrastructure Tender 2025"
                  value={form.name}
                  onChange={(e) => update('name', e.target.value)}
                  autoFocus
                />
                {formErrors.name && <div className={styles.fieldError}>{formErrors.name}</div>}
              </div>

              <div className={styles.formRow}>
                <div className={styles.field}>
                  <label className={styles.label}>Reference number</label>
                  <input className={styles.input} placeholder="DOH-ICT-2025-004"
                    value={form.reference} onChange={(e) => update('reference', e.target.value)} />
                </div>
                <div className={styles.field}>
                  <label className={styles.label}>Client department</label>
                  <input className={styles.input} placeholder="Dept. of Health"
                    value={form.client_department} onChange={(e) => update('client_department', e.target.value)} />
                </div>
              </div>

              <div className={styles.formRow}>
                <div className={styles.field}>
                  <label className={styles.label}>Due date</label>
                  <input type="date"
                    className={`${styles.input} ${formErrors.due_date ? styles.inputError : ''}`}
                    value={form.due_date} onChange={(e) => update('due_date', e.target.value)} />
                  {formErrors.due_date && <div className={styles.fieldError}>{formErrors.due_date}</div>}
                </div>
                <div className={styles.field}>
                  <label className={styles.label}>Contract value</label>
                  <input className={styles.input} placeholder="R 42.8M"
                    value={form.contract_value} onChange={(e) => update('contract_value', e.target.value)} />
                </div>
              </div>

              <div className={styles.field}>
                <label className={styles.label}>
                  Description <span style={{ color: 'var(--t3)' }}>(optional)</span>
                </label>
                <textarea className={styles.textarea} placeholder="Brief description of the tender scope…"
                  value={form.description} onChange={(e) => update('description', e.target.value)} rows={2} />
              </div>

              <div className={styles.modalFoot}>
                <button type="button" className="btn btn-g" onClick={() => setShowNew(false)}>Cancel</button>
                <button type="submit" className="btn btn-p" disabled={creating || !form.name.trim()}>
                  {creating ? <><span className="spin">⟳</span> Creating…</> : 'Create project →'}
                </button>
              </div>
            </form>
          </div>
        </>
      )}
    </div>
  );
}