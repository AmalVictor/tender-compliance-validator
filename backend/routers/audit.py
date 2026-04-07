"""
routers/audit.py
----------------
Full audit orchestration endpoints.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import (
    AdminCheck,
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

    # Admin checks
    admin_result = await db.execute(
        select(AdminCheck).where(
            AdminCheck.vendor_document_id.in_([p.id for p in proposals])
        )
    )
    admin_checks = admin_result.scalars().all()

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
            "id": m.id,
            "requirement_id": m.requirement_id,
            "vendor_document_id": m.vendor_document_id,
            "status": m.status.value,
            "confidence": m.confidence,
            "evidence_quote": m.evidence_quote,
            "section_ref": m.section_ref,
            "explanation": m.explanation,
            "reranker_score": m.reranker_score,
            "page_number": m.page_number,
            "bbox": json.loads(m.bbox) if isinstance(m.bbox, str) else m.bbox,
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
        "admin_checks": [
            {
                "id": a.id,
                "vendor_document_id": a.vendor_document_id,
                "item_name": a.item_name,
                "status": a.status.value if hasattr(a.status, 'value') else a.status,
                "page_reference": a.page_reference,
                "matched_text": a.matched_text,
            }
            for a in admin_checks
        ] if admin_checks else [],
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
                "id": match.id if match else None,
                "vendor_document_id": prop.id,
                "vendor_name": prop.vendor_name or prop.filename,
                "status": match.status.value if match else "PENDING",
                "confidence": round(match.confidence or 0, 2) if match else None,
                "evidence_quote": match.evidence_quote if match else None,
                "section_ref": match.section_ref if match else None,
                "explanation": match.explanation if match else None,
            })
        matrix.append({
            "requirement": {  
                "id": req.id,
                "raw_text": req.raw_text,
                "normalised": req.normalised_intent or req.raw_text,
                "rfp_clause_ref": req.rfp_clause_ref,
                "category": req.category.value,
                "criticality": req.criticality.value,
                "section_title": req.section_title,
                "page_number": req.page_number,
            },
            "matches": vendor_results,
        })
    return matrix

# ── Export PDF report ──────────────────────────────────────────────────────────
 
@router.get("/export/{project_id}", response_class=FileResponse)
async def export_audit_report(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate and download a professional PDF audit report.
 
    The PDF includes:
    - Cover page with traffic-light vendor scores
    - Executive summary table per vendor
    - Colour-coded compliance matrix (rows=requirements, columns=vendors)
    - Risk findings sorted by severity
    - Administrative eligibility check results
    - Methodology note (2 paragraphs)
    
    Takes ~2 seconds to generate.
    """
    # ── Load all data ──────────────────────────────────────────────────────────
    proj_result = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")
 
    if not project.audit_complete:
        raise HTTPException(
            status_code=400,
            detail="Audit not complete. Run POST /api/audit/run/{project_id} first.",
        )
 
    req_result = await db.execute(
        select(Requirement).where(
            Requirement.project_id == project_id,
            Requirement.is_confirmed == True,
            Requirement.is_deleted == False,
        ).order_by(Requirement.criticality, Requirement.id)
    )
    requirements = req_result.scalars().all()
 
    prop_result = await db.execute(
        select(Document).where(
            Document.project_id == project_id,
            Document.document_type == DocumentType.PROPOSAL,
        )
    )
    proposals = prop_result.scalars().all()
 
    if not proposals:
        raise HTTPException(status_code=404, detail="No proposals found.")
 
    proposal_ids = [p.id for p in proposals]
 
    match_result = await db.execute(
        select(Match).where(Match.vendor_document_id.in_(proposal_ids))
    )
    matches = match_result.scalars().all()
 
    risk_result = await db.execute(
        select(RiskFinding).where(RiskFinding.vendor_document_id.in_(proposal_ids))
    )
    risk_findings = risk_result.scalars().all()
 
    admin_result = await db.execute(
        select(AdminCheck).where(AdminCheck.vendor_document_id.in_(proposal_ids))
    )
    admin_checks = admin_result.scalars().all()
 
    # ── Build dicts for report generator ──────────────────────────────────────
    req_dicts = [
        {
            "id": r.id,
            "normalised_intent": r.normalised_intent or r.raw_text,
            "raw_text": r.raw_text,
            "category": r.category.value,
            "criticality": r.criticality.value,
            "rfp_clause_ref": r.rfp_clause_ref,
        }
        for r in requirements
    ]
 
    match_dicts = [
        {
            "id": m.id,
            "requirement_id": m.requirement_id,
            "vendor_document_id": m.vendor_document_id,
            "status": m.status.value,
            "confidence": m.confidence,
            "evidence_quote": m.evidence_quote,
            "section_ref": m.section_ref,
            "explanation": m.explanation,
            "reranker_score": m.reranker_score,
            "page_number": m.page_number,
            "bbox": json.loads(m.bbox) if isinstance(m.bbox, str) else m.bbox,
        }
        for m in matches
    ]
 
    risk_dicts = [
        {
            "vendor_document_id": r.vendor_document_id,
            "risk_type": r.risk_type.value,
            "severity": r.severity.value,
            "matched_phrase": r.matched_phrase,
            "impact_explanation": r.impact_explanation,
            "section_ref": r.section_ref,
            "page_number": r.page_number,
            "rfp_clause_ref": r.rfp_clause_ref,
            "confirmed_by_llm": r.confirmed_by_llm,
            "pattern_name": getattr(r, "pattern_name", r.risk_type.value),
        }
        for r in risk_findings
    ]
 
    admin_dicts = [
        {
            "vendor_document_id": a.vendor_document_id,
            "item_name": a.item_name,
            "status": a.status,
            "page_reference": a.page_reference,
            "matched_text": a.matched_text,
        }
        for a in admin_checks
    ] if admin_checks else []
 
    vendor_list = [
        {"document_id": p.id, "vendor_name": p.vendor_name or p.filename}
        for p in proposals
    ]
 
    vendor_scores = ComplianceScorer().score_all(
        vendors=vendor_list,
        requirements=req_dicts,
        matches=match_dicts,
        risk_findings=risk_dicts,
    )
 
    vendor_score_dicts = [
        {
            "vendor_document_id": s.vendor_document_id,
            "vendor_name": s.vendor_name,
            "compliance_score": s.compliance_score,
            "risk_score": s.risk_score,
            "status_colour": s.status_colour,
            "mandatory_full": s.mandatory_full,
            "mandatory_partial": s.mandatory_partial,
            "mandatory_none": s.mandatory_none,
            "mandatory_ambiguous": s.mandatory_ambiguous,
            "critical_risks": s.critical_risks,
            "high_risks": s.high_risks,
        }
        for s in vendor_scores
    ]
 
    # ── Generate PDF in temp file ──────────────────────────────────────────────
    os.makedirs("reports", exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in project.name)
    output_path = f"reports/{safe_name}_audit_report.pdf"
 
    # Load human decisions for the decision trail section
    try:
        from backend.database_decisions import HumanDecision
        from sqlalchemy import select as sa_select
        decision_result = await db.execute(
            sa_select(HumanDecision)
            .where(HumanDecision.vendor_document_id.in_(proposal_ids))
            .order_by(HumanDecision.decided_at.asc())
        )
        raw_decisions = decision_result.scalars().all()
        decision_dicts = [
            {
                "match_id": d.match_id,
                "requirement_id": d.requirement_id,
                "vendor_document_id": d.vendor_document_id,
                "decision_type": d.decision_type.value,
                "override_status": d.override_status,
                "reviewer_note": d.reviewer_note,
                "reviewer_name": d.reviewer_name,
                "decided_at": d.decided_at.isoformat() if d.decided_at else None,
            }
            for d in raw_decisions
        ]
    except Exception as e:
        logger.warning("Could not load decisions for PDF: %s", e)
        decision_dicts = []
 
    try:
        from services.report_generator import ReportGenerator
        pdf_path = await asyncio.to_thread(
            ReportGenerator().generate,
            project_name=project.name,
            vendor_scores=vendor_score_dicts,
            requirements=req_dicts,
            matches=match_dicts,
            risk_findings=risk_dicts,
            admin_checks=admin_dicts or None,
            decisions=decision_dicts or None,
            output_path=output_path,
        )
    except Exception as e:
        logger.exception("Report generation failed for project %d: %s", project_id, e)
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")
 
    filename = f"{safe_name}_audit_report.pdf"
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
 