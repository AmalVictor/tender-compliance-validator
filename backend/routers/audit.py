"""
routers/audit.py
----------------
Full audit orchestration endpoints.
Replaces the Phase 1 stub with real pipeline execution.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import (
    Document,
    DocumentType,
    Match,
    Project,
    Requirement,
    RiskFinding,
    get_db,
)
from backend.schemas import AuditResultsResponse, MessageResponse, VendorComplianceScore
from services.audit_orchestrator import AuditOrchestrator
from services.scorer import ComplianceScorer

logger = logging.getLogger(__name__)
router = APIRouter()

# Track running audits to prevent duplicates
_running_audits: set[int] = set()


# ── Pipeline status ────────────────────────────────────────────────────────────

@router.get("/status/{project_id}")
async def get_audit_status(
    project_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return current pipeline status and counts for a project."""

    proj_result = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")

    rfp_result = await db.execute(
        select(Document).where(
            Document.project_id == project_id,
            Document.document_type == DocumentType.RFP,
        )
    )
    rfps = rfp_result.scalars().all()

    prop_result = await db.execute(
        select(Document).where(
            Document.project_id == project_id,
            Document.document_type == DocumentType.PROPOSAL,
        )
    )
    proposals = prop_result.scalars().all()

    req_result = await db.execute(
        select(Requirement).where(
            Requirement.project_id == project_id,
            Requirement.is_deleted == False,
        )
    )
    all_reqs = req_result.scalars().all()
    confirmed = [r for r in all_reqs if r.is_confirmed]

    match_result = await db.execute(
        select(Match).where(
            Match.vendor_document_id.in_([p.id for p in proposals])
        )
    )
    matches = match_result.scalars().all()

    return {
        "project_id": project_id,
        "project_name": project.name,
        "is_running": project_id in _running_audits,
        "pipeline_stages": {
            "rfp_uploaded":              len(rfps) > 0,
            "rfp_parsed":                any(r.is_parsed for r in rfps),
            "requirements_extracted":    len(all_reqs) > 0,
            "requirements_confirmed":    len(confirmed) > 0,
            "proposals_uploaded":        len(proposals) > 0,
            "proposals_indexed":         all(p.is_indexed for p in proposals) if proposals else False,
            "audit_complete":            project.audit_complete,
        },
        "counts": {
            "rfps":                    len(rfps),
            "proposals":               len(proposals),
            "total_requirements":      len(all_reqs),
            "confirmed_requirements":  len(confirmed),
            "proposals_indexed":       sum(1 for p in proposals if p.is_indexed),
            "matches_computed":        len(matches),
        },
        "vendors": [
            {
                "document_id":  p.id,
                "vendor_name":  p.vendor_name or p.filename,
                "is_parsed":    p.is_parsed,
                "is_indexed":   p.is_indexed,
                "parse_error":  p.parse_error,
            }
            for p in proposals
        ],
    }


# ── Run audit ──────────────────────────────────────────────────────────────────

@router.post("/run/{project_id}", response_model=MessageResponse)
async def run_audit(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger the full compliance audit pipeline.

    Runs synchronously (waits for completion) for the hackathon demo.
    For large RFPs (50+ requirements × 3 vendors), expect 3–8 minutes.
    Pre-run and cache results the night before your demo.
    """
    if project_id in _running_audits:
        raise HTTPException(
            status_code=409,
            detail=f"Audit already running for project {project_id}. Please wait.",
        )

    # Validate project exists
    proj_result = await db.execute(select(Project).where(Project.id == project_id))
    if not proj_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")

    _running_audits.add(project_id)
    try:
        orchestrator = AuditOrchestrator(db)
        result = await orchestrator.run(project_id)
    except Exception as e:
        logger.exception("Audit failed for project %d: %s", project_id, e)
        raise HTTPException(status_code=500, detail=f"Audit failed: {e}")
    finally:
        _running_audits.discard(project_id)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return MessageResponse(
        message=(
            f"Audit complete. {result['vendors_audited']} vendors audited, "
            f"{result['requirements_checked']} requirements checked."
        ),
        data=result,
    )


# ── Get results ────────────────────────────────────────────────────────────────

@router.get("/results/{project_id}")
async def get_audit_results(
    project_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Get full audit results for a project.
    Returns compliance matrix, risk findings, and vendor scores.
    """
    # Requirements
    req_result = await db.execute(
        select(Requirement).where(
            Requirement.project_id == project_id,
            Requirement.is_confirmed == True,
            Requirement.is_deleted == False,
        ).order_by(Requirement.criticality, Requirement.id)
    )
    requirements = req_result.scalars().all()

    # Proposals
    prop_result = await db.execute(
        select(Document).where(
            Document.project_id == project_id,
            Document.document_type == DocumentType.PROPOSAL,
        )
    )
    proposals = prop_result.scalars().all()

    if not proposals:
        raise HTTPException(status_code=404, detail="No proposals found for this project.")

    # Matches
    match_result = await db.execute(
        select(Match).where(
            Match.vendor_document_id.in_([p.id for p in proposals])
        )
    )
    matches = match_result.scalars().all()

    # Risk findings
    risk_result = await db.execute(
        select(RiskFinding).where(
            RiskFinding.vendor_document_id.in_([p.id for p in proposals])
        )
    )
    risk_findings = risk_result.scalars().all()

    # Compute scores
    req_dicts = [
        {
            "id": r.id,
            "raw_text": r.raw_text,
            "normalised_intent": r.normalised_intent or r.raw_text,
            "category": r.category.value,
            "criticality": r.criticality.value,
            "rfp_clause_ref": r.rfp_clause_ref,
        }
        for r in requirements
    ]

    match_dicts = [
        {
            "requirement_id": m.requirement_id,
            "vendor_document_id": m.vendor_document_id,
            "status": m.status.value,
            "confidence": m.confidence,
            "evidence_quote": m.evidence_quote,
            "section_ref": m.section_ref,
            "explanation": m.explanation,
            "reranker_score": m.reranker_score,
        }
        for m in matches
    ]

    risk_dicts = [
        {
            "id": r.id,
            "vendor_document_id": r.vendor_document_id,
            "risk_type": r.risk_type.value,
            "severity": r.severity.value,
            "matched_phrase": r.matched_phrase,
            "context_text": r.context_text,
            "impact_explanation": r.impact_explanation,
            "section_ref": r.section_ref,
            "page_number": r.page_number,
            "rfp_clause_ref": r.rfp_clause_ref,
            "confirmed_by_llm": r.confirmed_by_llm,
        }
        for r in risk_findings
    ]

    vendor_list = [
        {
            "document_id": p.id,
            "vendor_name": p.vendor_name or p.filename,
        }
        for p in proposals
    ]

    vendor_scores = ComplianceScorer().score_all(
        vendors=vendor_list,
        requirements=req_dicts,
        matches=match_dicts,
        risk_findings=risk_dicts,
    )

    return {
        "project_id": project_id,
        "requirements": req_dicts,
        "vendors": [
            {
                "document_id": p.id,
                "vendor_name": p.vendor_name or p.filename,
                "compliance_score": next(
                    (s.compliance_score for s in vendor_scores if s.vendor_document_id == p.id),
                    None,
                ),
                "risk_score": next(
                    (s.risk_score for s in vendor_scores if s.vendor_document_id == p.id),
                    None,
                ),
                "status_colour": next(
                    (s.status_colour for s in vendor_scores if s.vendor_document_id == p.id),
                    "amber",
                ),
                "mandatory_full": next(
                    (s.mandatory_full for s in vendor_scores if s.vendor_document_id == p.id),
                    0,
                ),
                "mandatory_none": next(
                    (s.mandatory_none for s in vendor_scores if s.vendor_document_id == p.id),
                    0,
                ),
                "critical_risks": next(
                    (s.critical_risks for s in vendor_scores if s.vendor_document_id == p.id),
                    0,
                ),
            }
            for p in proposals
        ],
        "compliance_matrix": _build_matrix(requirements, proposals, matches),
        "risk_findings": risk_dicts,
        "match_details": match_dicts,
    }


def _build_matrix(
    requirements,
    proposals,
    matches,
) -> list[dict]:
    """
    Build the compliance matrix: for each requirement, show each vendor's status.
    Structure: [{requirement_id, requirement_text, vendor_results: [{vendor_id, status, confidence, explanation}]}]
    """
    # Build quick lookup: (req_id, vendor_id) -> match
    match_lookup = {
        (m.requirement_id, m.vendor_document_id): m
        for m in matches
    }

    matrix = []
    for req in requirements:
        vendor_results = []
        for prop in proposals:
            match = match_lookup.get((req.id, prop.id))
            vendor_results.append({
                "vendor_document_id": prop.id,
                "vendor_name": prop.vendor_name or prop.filename,
                "status": match.status.value if match else "PENDING",
                "confidence": round(match.confidence or 0, 2) if match else None,
                "evidence_quote": match.evidence_quote if match else None,
                "section_ref": match.section_ref if match else None,
                "explanation": match.explanation if match else None,
            })
        matrix.append({
            "requirement_id": req.id,
            "rfp_clause_ref": req.rfp_clause_ref,
            "requirement_text": req.normalised_intent or req.raw_text,
            "category": req.category.value,
            "criticality": req.criticality.value,
            "vendor_results": vendor_results,
        })
    return matrix