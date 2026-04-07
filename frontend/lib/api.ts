// src/lib/api.ts
// Complete FastAPI backend client. Every endpoint wired up. All errors surface cleanly.


import type {
  Project,
  TenderDocument,
  Requirement,
  AuditResults,
  AuditStatus,
  AdminCheck,
  ChatMessage,
  VendorScore,
  MatrixRow,
  RiskFinding,
  RiskHeatmapCell,
  AuditSummary,
  VendorMatch,
  RiskSeverity,
  ComplianceStatus,
  RequirementCategory,
  RequirementCriticality,
} from '@/types';


const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api';


// Deterministic vendor colours assigned by index so they're stable across renders
const VENDOR_COLORS = ['#6366F1', '#10B981', '#F59E0B', '#EC4899', '#8B5CF6', '#14B8A6'];

// ── Error class ───────────────────────────────────────────────────────────────
export class ApiError extends Error {
  constructor(
    public readonly status: number,  // 0 = network unreachable
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  get isNetworkError() { return this.status === 0; }
  get isNotFound() { return this.status === 404; }
  get isServerError() { return this.status >= 500; }
}

// ── Core fetch wrapper ────────────────────────────────────────────────────────
async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json', ...init?.headers },
      ...init,
    });
  } catch {
    throw new ApiError(0, 'Cannot connect to backend. Is FastAPI running on port 8000?');
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? body.message ?? detail;
    } catch { /* ignore parse error */ }
    throw new ApiError(res.status, detail);
  }

  // 204 No Content
  if (res.status === 204) return undefined as unknown as T;
  return res.json() as Promise<T>;
}

// ── Multipart upload wrapper ──────────────────────────────────────────────────
async function upload<T>(path: string, fd: FormData): Promise<T> {
  let res: Response;
  try {
    
    res = await fetch(`${BASE}${path}`, { method: 'POST', body: fd });
  } catch {
    throw new ApiError(0, 'Cannot connect to backend.');
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? body.message ?? detail;
    } catch { /* ignore */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

// ══════════════════════════════════════════════════════════════════════════════
//  PROJECTS
// ══════════════════════════════════════════════════════════════════════════════

export function getProjects(): Promise<Project[]> {
  return req<Project[]>('/projects');
}

export function getProject(id: string): Promise<Project> {
  return req<Project>(`/projects/${id}`);
}

export function createProject(data: {
  name: string;
  description?: string;
  reference?: string;
  due_date?: string;
  contract_value?: string;
  client_department?: string;
}): Promise<Project> {
  return req<Project>('/projects', { method: 'POST', body: JSON.stringify(data) });
}

export function deleteProject(id: string): Promise<{ message: string }> {
  return req<{ message: string }>(`/projects/${id}`, { method: 'DELETE' });
}

// ══════════════════════════════════════════════════════════════════════════════
//  DOCUMENTS
// ══════════════════════════════════════════════════════════════════════════════

export function getDocuments(projectId: string): Promise<TenderDocument[]> {
  return req<TenderDocument[]>(`/documents?project_id=${projectId}`);
}

export function uploadDocument(
  projectId: string,
  file: File,
  type: 'rfp' | 'proposal',
  vendorName?: string,
): Promise<TenderDocument> {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('project_id', projectId);
  fd.append('document_type', type.toUpperCase());
  if (vendorName) fd.append('vendor_name', vendorName);
  return upload<TenderDocument>('/documents/upload', fd);
}

export function extractRequirements(
  projectId: string,
): Promise<{ message: string }> {
  return req<{ message: string }>(`/documents/${projectId}/requirements/extract`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

export function getDocumentFileUrl(documentId: string): string {
  return `${BASE}/documents/file/${documentId}`;
}

export function getAdminChecks(documentId: string): Promise<AdminCheck[]> {
  return req<AdminCheck[]>(`/documents/${documentId}/admin-checks`);
}

// ══════════════════════════════════════════════════════════════════════════════
//  REQUIREMENTS
// ══════════════════════════════════════════════════════════════════════════════

export function getRequirements(
  projectId: string,
  confirmedOnly = false,
): Promise<Requirement[]> {
  return req<any[]>(
    `/documents/${projectId}/requirements?confirmed_only=${confirmedOnly}`,
  ).then((rawReqs) => rawReqs.map((r) => ({
    id: String(r.id),
    project_id: projectId,
    rfp_clause_ref: r.rfp_clause_ref as string | undefined,
    ref: (r.rfp_clause_ref ?? r.id) as string,
    raw_text: (r.raw_text as string) ?? '',
    normalised: (r.normalised_intent ?? r.raw_text ?? '') as string,
    normalised_intent: r.normalised_intent as string | undefined,
    category: cap((r.category as string) ?? 'technical') as RequirementCategory,
    criticality: cap((r.criticality as string) ?? 'mandatory') as RequirementCriticality,
    section_title: r.section_title as string | undefined,
    page_number: r.page_number as number | undefined,
    confidence: (r.confidence as number | null | undefined) ?? 0,
    bbox: (r.bbox as number[] | null | undefined) ?? null,
    rfp_document_id: (r.rfp_document_id as number | null | undefined) != null
      ? String(r.rfp_document_id)
      : null,
    confirmed: (r.is_confirmed ?? r.confirmed ?? false) as boolean,
    is_confirmed: (r.is_confirmed ?? false) as boolean,
    is_deleted: (r.is_deleted ?? false) as boolean,
  })));
}

export function patchRequirement(
  id: string,
  data: Partial<Requirement>,
): Promise<Requirement> {
  return req<Requirement>(`/documents/requirements/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export function bulkConfirmRequirements(
  ids: string[],
  confirm = true,
): Promise<{ message: string }> {
  return req<{ message: string }>('/documents/requirements/bulk-confirm', {
    method: 'POST',
    body: JSON.stringify({ requirement_ids: ids, confirm }),
  });
}

// ══════════════════════════════════════════════════════════════════════════════
//  AUDIT
// ══════════════════════════════════════════════════════════════════════════════

export async function getAuditStatus(projectId: string): Promise<AuditStatus> {
  const raw = await req<any>(`/audit/status/${projectId}`);
  const stages = raw.pipeline_stages || {};
  const isRunning = raw.is_running;
  const isComplete = stages.audit_complete;

  const PIPELINE_STEPS = [
    { label: 'RFP\nUploaded', icon: '📄', done: stages.rfp_uploaded },
    { label: 'Reqs\nExtracted', icon: '🔍', done: stages.requirements_extracted },
    { label: 'Reqs\nConfirmed', icon: '✅', done: stages.requirements_confirmed },
    { label: 'Proposals\nIndexed', icon: '📁', done: stages.proposals_indexed },
    { label: 'Audit\nComplete', icon: '🤖', done: stages.audit_complete },
    { label: 'Report\nReady', icon: '📊', done: stages.audit_complete },
  ];

  const steps = PIPELINE_STEPS.map((s, i) => {
    let status: 'done' | 'active' | 'pending' = 'pending';
    if (s.done) {
      status = 'done';
    } else if (isRunning) {
      const firstUndone = PIPELINE_STEPS.findIndex(x => !x.done);
      if (firstUndone === i) status = 'active';
    }
    return { label: s.label, icon: s.icon, status };
  });

  return {
    project_id: raw.project_id,
    status: isComplete ? 'complete' : (isRunning ? 'running' : (raw.pipeline_stages?.audit_complete === false && Object.values(raw.pipeline_stages).some(v => v === true)) ? 'pending' : (raw.counts?.rfps === 0 ? 'pending' : 'error')),
    steps: steps as any,
    pipeline_stages: stages,
  };
}

export function runAudit(projectId: string): Promise<{ message: string }> {
  return req<{ message: string }>(`/audit/run/${projectId}`, { method: 'POST' });
}

// Raw results as returned by the API (before transform)
export function getRawAuditResults(projectId: string): Promise<unknown> {
  return req<unknown>(`/audit/results/${projectId}`);
}

/** URL for the PDF report download — open in new tab */
export function getExportUrl(projectId: string): string {
  return `${BASE}/audit/export/${projectId}`;
}

// ══════════════════════════════════════════════════════════════════════════════
//  DECISIONS (Accept / Annotate / Override)
// ══════════════════════════════════════════════════════════════════════════════

export interface HumanDecisionPayload {
  match_id: number;
  requirement_id: number;
  vendor_document_id: number;
  decision_type: 'ACCEPTED' | 'ANNOTATED' | 'OVERRIDDEN';
  override_status?: 'FULL' | 'PARTIAL' | 'NONE' | 'AMBIGUOUS';
  reviewer_note?: string;
  reviewer_name?: string;
}

export interface HumanDecisionResponse {
  id: number;
  match_id: number;
  requirement_id: number;
  vendor_document_id: number;
  decision_type: string;
  override_status: string | null;
  reviewer_note: string | null;
  reviewer_name: string | null;
  decided_at: string;
}

/** Record an Accept / Annotate / Override decision on a match */
export function recordDecision(payload: HumanDecisionPayload): Promise<HumanDecisionResponse> {
  return req<HumanDecisionResponse>('/decisions/', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** Get all decisions (history) for a specific match */
export function getDecisionHistory(matchId: number): Promise<HumanDecisionResponse[]> {
  return req<HumanDecisionResponse[]>(`/decisions/match/${matchId}`);
}

/** Get all decisions for every match in a project (used by export) */
export function getProjectDecisions(projectId: string): Promise<HumanDecisionResponse[]> {
  return req<HumanDecisionResponse[]>(`/decisions/project/${projectId}`);
}

/** Load decisions from backend by project ID - returns mapped by requirement_id-vendor_document_id */
export function getDecisionsByProject(projectId: string): Promise<HumanDecisionResponse[]> {
  return req<HumanDecisionResponse[]>(`/decisions/project/${projectId}`);
}

// ══════════════════════════════════════════════════════════════════════════════
//  DATA TRANSFORM — raw FastAPI → frontend types
// ══════════════════════════════════════════════════════════════════════════════

const SEV_ORDER: Record<RiskSeverity, number> = { Critical: 0, High: 1, Medium: 2, Low: 3 };

function cap(s: string): string {
  if (!s) return s;
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
}

/** Handles both 0–1 and 0–100 scales returned by different backend versions */
function normaliseScore(s: number | null | undefined): number {
  if (s == null) return 0;
  if (s > 1.0) return Math.min(100, Math.round(s));
  return Math.min(100, Math.round(s * 100));
}

/**
 * Transform raw FastAPI audit results into the shape our components expect.
 * This is the critical bridge between backend and frontend data shapes.
 * All field access is defensive — backend may omit optional fields.
 */
export function transformAuditResults(raw: Record<string, unknown>, projectId: string): AuditResults {
  // Backend may return either { vendor_scores, matches } or older { vendors, match_details } shapes.
  const vendorScoresRaw = (raw.vendor_scores ?? raw.vendors ?? []) as Record<string, unknown>[];
  const rawRequirements: Record<string, unknown>[] = (raw.requirements as Record<string, unknown>[]) ?? [];
  const rawMatches: Record<string, unknown>[] = (raw.matches ?? raw.match_details ?? []) as Record<string, unknown>[];
  const rawRisks: Record<string, unknown>[] = (raw.risk_findings as Record<string, unknown>[]) ?? [];

  // Assign stable colours to vendors by position
  const vendorColorMap: Record<string, string> = {};
  vendorScoresRaw.forEach((vs, i) => {
    if (typeof vs.vendor_name === 'string') {
      vendorColorMap[vs.vendor_name] = VENDOR_COLORS[i % VENDOR_COLORS.length];
    }
  });

  // vendor_document_id → vendor_name lookup
  const docIdToName: Record<string, string> = {};
  vendorScoresRaw.forEach((vs) => {
    const docId = (vs as any).vendor_document_id ?? (vs as any).document_id;
    if (docId != null && typeof (vs as any).vendor_name === 'string') {
      docIdToName[String(docId)] = (vs as any).vendor_name;
    }
  });

  // Transform requirements
  const requirements: Requirement[] = rawRequirements.map((r) => ({
    id: String(r.id),
    project_id: projectId,
    rfp_clause_ref: r.rfp_clause_ref as string | undefined,
    ref: (r.rfp_clause_ref ?? r.id) as string,
    raw_text: (r.raw_text as string) ?? '',
    normalised: (r.normalised_intent ?? r.raw_text ?? '') as string,
    normalised_intent: r.normalised_intent as string | undefined,
    category: cap((r.category as string) ?? 'technical') as RequirementCategory,
    criticality: cap((r.criticality as string) ?? 'mandatory') as RequirementCriticality,
    section_title: r.section_title as string | undefined,
    page_number: r.page_number as number | undefined,
    confirmed: (r.is_confirmed ?? r.confirmed ?? false) as boolean,
    is_confirmed: (r.is_confirmed ?? false) as boolean,
    is_deleted: (r.is_deleted ?? false) as boolean,
  }));

  // Build compliance matrix
  const matrix: MatrixRow[] = requirements.map((req) => {
    const reqMatches = rawMatches
      .filter((m) => String(m.requirement_id) === req.id)
      .map((m): VendorMatch => ({
        id: Number(m.id),
        vendor_name: docIdToName[String(m.vendor_document_id)] ?? `Vendor ${m.vendor_document_id}`,
        vendor_document_id: String(m.vendor_document_id),
        status: (m.status as ComplianceStatus) ?? 'NONE',
        confidence: (m.confidence as number) ?? 0,
        evidence: (m.evidence_quote ?? '') as string,
        evidence_quote: m.evidence_quote as string | undefined,
        section_ref: m.section_ref as string | undefined,
        explanation: m.explanation as string | undefined,
        bbox: (m.bbox as number[] | null | undefined) ?? null,
      }));
    return { requirement: req, matches: reqMatches };
  });

  // Transform risks
  const risks: RiskFinding[] = rawRisks.map((r) => {
    const vendorName = docIdToName[String(r.vendor_document_id)] ?? `Vendor ${r.vendor_document_id}`;
    return {
      id: String(r.id),
      vendor_name: vendorName,
      vendor_document_id: String(r.vendor_document_id),
      risk_type: (r.risk_type as string) ?? '',
      severity: cap((r.severity as string) ?? 'medium') as RiskSeverity,
      phrase: (r.matched_phrase as string) ?? '',
      matched_phrase: r.matched_phrase as string | undefined,
      impact: (r.impact_explanation ?? '') as string,
      impact_explanation: r.impact_explanation as string | undefined,
      section_ref: r.section_ref as string | undefined,
      page: (r.page_number as number) ?? 0,
      page_number: r.page_number as number | undefined,
      rfp_clause_ref: r.rfp_clause_ref as string | undefined,
      confirmed_by_llm: (r.confirmed_by_llm as boolean) ?? false,
      recommended_action: r.recommended_action as string | undefined,
      vendor_color: vendorColorMap[vendorName] ?? '#888',
    };
  });

  // Build heatmap from risks
  const RISK_TYPE_COLS: Record<string, keyof RiskHeatmapCell> = {
    // Liability Cap column
    'liability_cap': 'liability_cap',
    'LIABILITY_CAP': 'liability_cap',
    // Price / Scope column
    'price_change': 'price_scope',
    'PRICE_CHANGE': 'price_scope',
    'scope_creep': 'price_scope',
    'SCOPE_CREEP': 'price_scope',
    'PRICE_RISK': 'price_scope',
    // Obligations column
    'obligation_weakening': 'obligation',
    'OBLIGATION_WEAKENING': 'obligation',
    'vague_commitment': 'obligation',
    'VAGUE_COMMITMENT': 'obligation',
    // IP / Data column  (no dedicated enum yet — catch-all for future types)
    'data_privacy': 'ip_data',
    'DATA_PRIVACY': 'ip_data',
    'ip_ownership': 'ip_data',
    'IP_OWNERSHIP': 'ip_data',
    // Exit Term column
    'exit_clause': 'exit',
    'EXIT_CLAUSE': 'exit',
    'termination': 'exit',
    'TERMINATION': 'exit',
  };

  const heatmap: RiskHeatmapCell[] = vendorScoresRaw.map((vs, i) => {
    const vName = (vs as any).vendor_name as string;
    const docId = (vs as any).vendor_document_id ?? (vs as any).document_id;
    const cell: RiskHeatmapCell = {
      vendor_name: vName,
      vendor_color: VENDOR_COLORS[i % VENDOR_COLORS.length],
      vendor_document_id: String(docId),
      liability_cap: null,
      price_scope: null,
      obligation: null,
      ip_data: null,
      exit: null,
    };
    risks
      .filter((r) => r.vendor_name === vName)
      .forEach((r) => {
        const col = RISK_TYPE_COLS[r.risk_type.toUpperCase().replace(/ /g, '_')];
        if (col) {
          const existing = cell[col] as RiskSeverity | null;
          if (!existing || SEV_ORDER[r.severity] < SEV_ORDER[existing]) {
            (cell as unknown as Record<string, RiskSeverity | null>)[col] = r.severity;
          }
        }
      });
    return cell;
  });

  // Transform vendor scores
  const scores: VendorScore[] = vendorScoresRaw.map((vs, i) => {
    const v: any = vs;
    const docId = v.vendor_document_id ?? v.document_id;
    return {
      vendor_document_id: String(docId),
      vendor_name: v.vendor_name as string,
      compliance_score: normaliseScore(v.compliance_score as number),
      risk_score: (v.risk_score as number) ?? 0,
      status_colour: (v.status_colour as VendorScore['status_colour']) ?? 'amber',
      mandatory_full: (v.mandatory_full as number) ?? 0,
      mandatory_partial: (v.mandatory_partial as number) ?? 0,
      mandatory_none: (v.mandatory_none as number) ?? 0,
      critical_risks: (v.critical_risks as number) ?? 0,
      high_risks: (v.high_risks as number) ?? 0,
      vendor_color: VENDOR_COLORS[i % VENDOR_COLORS.length],
    } satisfies VendorScore;
  });

  // Derive summary
  const bestScore = scores.reduce((max, s) => Math.max(max, s.compliance_score), 0);
  // "Crit. Risks" KPI is High + Critical risks across all vendors.
  const critRisks = risks.filter((r) => r.severity === 'High' || r.severity === 'Critical').length;
  const gapCount = matrix.filter((row) => row.matches.some((m) => m.status === 'NONE')).length;
  // "AI Award Recommendation": prefer the vendor with the fewest critical risks,
  // then the highest compliance score (always pick a vendor if any exist).
  const recommendedVendor = scores
    .slice()
    .sort((a, b) => (a.critical_risks - b.critical_risks) || (b.compliance_score - a.compliance_score))[0]?.vendor_name;

  const summary: AuditSummary = {
    best_compliance_score: bestScore,
    critical_risks: critRisks,
    gap_count: gapCount,
    vendor_count: scores.length,
    recommended_vendor: recommendedVendor,
  };

  // Admin checks
  const adminChecks: AdminCheck[] = ((raw.admin_checks as Record<string, unknown>[]) ?? []).map((a) => ({
    id: String(a.id),
    vendor_document_id: String(a.vendor_document_id),
    item_name: (a.item_name as string) ?? '',
    status: ((a.status as string) ?? 'MISSING').toUpperCase() as 'FOUND' | 'MISSING',
    page_reference: a.page_reference as string | undefined,
    matched_text: a.matched_text as string | undefined,
  }));

  return {
    project_id: projectId,
    project_name: (raw.project_name as string) ?? '',
    summary,
    vendor_scores: scores,
    matrix,
    heatmap,
    risks,
    requirements,
    admin_checks: adminChecks,
  };
}

// ── Polling utility ───────────────────────────────────────────────────────────
/** Poll audit status until complete or error. Returns final status. */
export async function pollAuditUntilDone(
  projectId: string,
  onUpdate: (status: AuditStatus) => void,
  intervalMs = 2000,
  maxAttempts = 60,
): Promise<AuditStatus> {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const tick = async () => {
      attempts++;
      try {
        const status = await getAuditStatus(projectId);
        onUpdate(status);
        if (status.status === 'complete' || status.status === 'error') {
          resolve(status);
        } else if (attempts >= maxAttempts) {
          reject(new ApiError(0, 'Audit polling timed out after 2 minutes.'));
        } else {
          setTimeout(tick, intervalMs);
        }
      } catch (err) {
        reject(err);
      }
    };
    tick();
  });
}

// ── Type re-export so callers don't need a separate import ────────────────────
export type { ComplianceStatus } from '@/types';