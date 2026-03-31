"""
schemas.py
----------
Pydantic v2 request and response schemas for all API endpoints.
Kept separate from ORM models to allow independent evolution.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.database import (
    Criticality,
    DocumentType,
    MatchStatus,
    RequirementCategory,
    RiskSeverity,
    RiskType,
)


# ── Shared config ─────────────────────────────────────────────────────────────

class OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Project ───────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class ProjectResponse(OrmBase):
    id: int
    name: str
    description: str | None
    created_at: datetime
    audit_complete: bool
    document_count: int = 0
    requirement_count: int = 0


# ── Document ──────────────────────────────────────────────────────────────────

class DocumentResponse(OrmBase):
    id: int
    project_id: int
    document_type: DocumentType
    vendor_name: str | None
    filename: str
    page_count: int | None
    word_count: int | None
    is_parsed: bool
    is_indexed: bool
    parse_error: str | None
    uploaded_at: datetime


# ── Requirement ───────────────────────────────────────────────────────────────

class RequirementUpdate(BaseModel):
    """Payload for human-in-the-loop confirmation/editing."""
    normalised_intent: str | None = None
    category: RequirementCategory | None = None
    criticality: Criticality | None = None
    rfp_clause_ref: str | None = None
    is_confirmed: bool | None = None
    is_deleted: bool | None = None


class RequirementResponse(OrmBase):
    id: int
    project_id: int
    rfp_clause_ref: str | None
    raw_text: str
    normalised_intent: str | None
    category: RequirementCategory
    criticality: Criticality
    section_title: str | None
    page_number: int | None
    is_confirmed: bool
    is_deleted: bool
    created_at: datetime


class BulkConfirmRequest(BaseModel):
    """Confirm all extracted requirements at once (after human review)."""
    requirement_ids: list[int]
    confirm: bool = True


# ── Match ─────────────────────────────────────────────────────────────────────

class MatchResponse(OrmBase):
    id: int
    requirement_id: int
    vendor_document_id: int
    status: MatchStatus
    confidence: float | None
    evidence_quote: str | None
    section_ref: str | None
    explanation: str | None
    reranker_score: float | None


# ── Risk ──────────────────────────────────────────────────────────────────────

class RiskFindingResponse(OrmBase):
    id: int
    vendor_document_id: int
    risk_type: RiskType
    severity: RiskSeverity
    matched_phrase: str
    context_text: str | None
    impact_explanation: str | None
    section_ref: str | None
    page_number: int | None
    rfp_clause_ref: str | None
    confirmed_by_llm: bool


# ── Admin check ───────────────────────────────────────────────────────────────

class AdminCheckResponse(OrmBase):
    id: int
    vendor_document_id: int
    item_name: str
    status: str
    page_reference: str | None
    matched_text: str | None


# ── Audit results ─────────────────────────────────────────────────────────────

class VendorComplianceScore(BaseModel):
    vendor_document_id: int
    vendor_name: str
    compliance_score: float = Field(..., ge=0.0, le=100.0)
    risk_score: float = Field(..., ge=0.0)
    status_colour: str  # green / amber / red
    mandatory_met: int
    mandatory_partial: int
    mandatory_missing: int
    total_requirements: int
    critical_risks: int
    high_risks: int


class AuditResultsResponse(BaseModel):
    project_id: int
    project_name: str
    vendor_scores: list[VendorComplianceScore]
    requirements: list[RequirementResponse]
    matches: list[MatchResponse]
    risk_findings: list[RiskFindingResponse]
    admin_checks: list[AdminCheckResponse]


# ── API responses ─────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str
    data: Any | None = None


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None