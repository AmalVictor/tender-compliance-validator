// src/types/index.ts
// All types aligned with FastAPI backend response shapes.

export type ComplianceStatus = 'FULL' | 'PARTIAL' | 'NONE' | 'AMBIGUOUS' | 'PENDING';
export type RiskSeverity = 'Critical' | 'High' | 'Medium' | 'Low';
export type RequirementCategory = 'Technical' | 'Legal' | 'Financial' | 'Administrative';
export type RequirementCriticality = 'Mandatory' | 'Recommended' | 'Informational';
export type DocumentType = 'RFP' | 'PROPOSAL';
export type AuditStatusType = 'complete' | 'running' | 'pending' | 'error';

// ── Projects ──────────────────────────────────────────────────────────────────
export interface Project {
  id: string;
  name: string;
  description?: string;
  reference?: string;
  due_date?: string;           // ISO date string "2025-04-15"
  contract_value?: string;     // e.g. "R 42.8M" — user-supplied string
  client_department?: string;  // e.g. "Dept. of Health"
  created_at: string;
  audit_complete: boolean;
  audit_status: AuditStatusType;
  document_count: number;
  requirement_count: number;
  vendor_count: number;
  best_compliance_score?: number;
}

// ── Documents ─────────────────────────────────────────────────────────────────
export interface TenderDocument {
  id: string;
  project_id: string;
  doc_type: 'rfp' | 'proposal';
  document_type: DocumentType;
  filename: string;
  vendor_name?: string;
  page_count?: number;
  word_count?: number;
  is_parsed: boolean;
  is_indexed: boolean;
  parse_error?: string;
  uploaded_at: string;
}

export interface AdminCheck {
  id: string;
  vendor_document_id: string;
  item_name: string;
  status: 'FOUND' | 'MISSING';
  page_reference?: string;
  matched_text?: string;
}

// ── Requirements ──────────────────────────────────────────────────────────────
export interface Requirement {
  id: string;
  project_id: string;
  rfp_clause_ref?: string;
  ref?: string;
  raw_text: string;
  normalised?: string;
  normalised_intent?: string;
  category: RequirementCategory;
  criticality: RequirementCriticality;
  section_title?: string;
  page_number?: number;
  confidence?: number;
  bbox?: number[] | null;
  rfp_document_id?: string | null;
  confirmed: boolean;
  is_confirmed?: boolean;
  is_deleted?: boolean;
}

// ── Audit ─────────────────────────────────────────────────────────────────────
export interface VendorMatch {
  id?: number | null;
  vendor_name: string;
  vendor_document_id: string;
  status: ComplianceStatus;
  confidence: number;             // 0–1
  evidence?: string;
  evidence_quote?: string;
  section_ref?: string;
  explanation?: string;
  bbox?: number[] | null;
}

export interface MatrixRow {
  requirement: Requirement;
  matches: VendorMatch[];
}

export interface RiskFinding {
  id: string;
  vendor_name: string;
  vendor_document_id: string;
  risk_type: string;
  severity: RiskSeverity;
  phrase: string;
  matched_phrase?: string;
  impact: string;
  impact_explanation?: string;
  section_ref?: string;
  page: number;
  page_number?: number;
  rfp_clause_ref?: string;
  confirmed_by_llm: boolean;
  recommended_action?: string;
  vendor_color?: string;
}

export interface RiskHeatmapCell {
  vendor_name: string;
  vendor_color: string;
  vendor_document_id: string;
  liability_cap: RiskSeverity | null;
  price_scope: RiskSeverity | null;
  obligation: RiskSeverity | null;
  ip_data: RiskSeverity | null;
  exit: RiskSeverity | null;
}

export interface VendorScore {
  vendor_document_id: string;
  vendor_name: string;
  compliance_score: number;     // 0–100
  risk_score: number;
  status_colour: 'green' | 'amber' | 'red';
  mandatory_full: number;
  mandatory_partial: number;
  mandatory_none: number;
  critical_risks: number;
  high_risks: number;
  vendor_color?: string;
}

export interface AuditSummary {
  best_compliance_score: number;
  critical_risks: number;
  gap_count: number;
  vendor_count: number;
  recommended_vendor?: string;
}

export interface AuditResults {
  project_id: string;
  project_name: string;
  summary: AuditSummary;
  vendor_scores: VendorScore[];
  matrix: MatrixRow[];
  heatmap: RiskHeatmapCell[];
  risks: RiskFinding[];
  requirements: Requirement[];
  admin_checks: AdminCheck[];
}

// ── Audit Status / Pipeline ───────────────────────────────────────────────────
export interface PipelineStep {
  label: string;
  icon: string;
  status: 'done' | 'active' | 'pending';
}

export interface AuditStatus {
  project_id: string;
  status: AuditStatusType;
  steps: PipelineStep[];
  pipeline_stages?: {
    rfp_uploaded?: boolean;
    rfp_parsed?: boolean;
    requirements_extracted?: boolean;
    requirements_confirmed?: boolean;
    proposals_uploaded?: boolean;
    proposals_indexed?: boolean;
    audit_complete?: boolean;
  };
}

// ── Chat ──────────────────────────────────────────────────────────────────────
export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  citation?: string;
}

// ── UI Only ───────────────────────────────────────────────────────────────────
export interface RiskDrawerState {
  open: boolean;
  vendor: string;
  severity: string;
  title: string;
  source: string;
  analysis: string;
  action: string;
}

export interface ToastMessage {
  id: string;
  message: string;
  type: 'success' | 'error' | 'info' | 'warning';
}