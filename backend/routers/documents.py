"""
routers/documents.py
--------------------
Document upload, parsing, and indexing endpoints.
Handles both RFP and vendor proposal files.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import (
    AdminCheck,
    Document,
    DocumentType,
    Project,
    Requirement,
    get_db,
)
from schemas import (
    AdminCheckResponse,
    BulkConfirmRequest,
    DocumentResponse,
    MessageResponse,
    RequirementResponse,
    RequirementUpdate,
)
from services.document_parser import parse_document
from services.proposal_indexer import ProposalIndexer
from services.requirement_extractor import check_admin_eligibility, extract_requirements

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_upload_path(project_id: int, filename: str) -> Path:
    """Build a safe upload file path."""
    upload_dir = Path(settings.UPLOAD_DIR) / str(project_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")
    return upload_dir / safe_name


# ── Upload + Parse ────────────────────────────────────────────────────────────

@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    project_id: int = Form(...),
    document_type: DocumentType = Form(...),
    vendor_name: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a PDF document (RFP or vendor proposal).
    Automatically parses the document after upload.
    For RFPs, requirements are extracted only when the user manually triggers
    the "extract requirements" endpoint (human-in-the-loop gate).
    For proposals, runs admin eligibility check.
    """
    # ── Validate project ──────────────────────────────────────────────────
    result = await db.execute(select(Project).where(Project.id == project_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")

    # ── Validate file ─────────────────────────────────────────────────────
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {settings.MAX_FILE_SIZE_MB}MB.",
        )

    # ── Save file ─────────────────────────────────────────────────────────
    file_path = _get_upload_path(project_id, file.filename)
    file_path.write_bytes(content)

    # ── Create DB record ──────────────────────────────────────────────────
    doc = Document(
        project_id=project_id,
        document_type=document_type,
        vendor_name=vendor_name if document_type == DocumentType.PROPOSAL else None,
        filename=file.filename,
        file_path=str(file_path),
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)

    # ── Parse document ────────────────────────────────────────────────────
    try:
        parsed = parse_document(file_path)
        doc.page_count = parsed.page_count
        doc.word_count = parsed.word_count
        doc.is_parsed = True

        if parsed.is_scanned:
            doc.parse_error = "Document appears to be scanned. Text extraction failed."
            logger.warning("Scanned document: %s", file.filename)
            await db.flush()
            await db.refresh(doc)
            return _doc_to_response(doc)

        # ── Proposal: index + admin check ─────────────────────────────────
        elif document_type == DocumentType.PROPOSAL:
            indexer = ProposalIndexer()
            chunk_count = indexer.index(
                parsed, 
                project_id=project_id, 
                document_id=doc.id, 
                vendor_name=doc.vendor_name or doc.filename
            )
            doc.is_indexed = True
            logger.info("Indexed %d chunks for proposal '%s'", chunk_count, file.filename)

            # Admin eligibility check
            admin_results = check_admin_eligibility(parsed)
            for check in admin_results:
                db_check = AdminCheck(
                    vendor_document_id=doc.id,
                    item_name=check.item_name,
                    status=check.status,
                    page_reference=check.page_reference,
                    matched_text=check.matched_text,
                )
                db.add(db_check)

    except ValueError as e:
        doc.parse_error = str(e)
        logger.error("Parse error for '%s': %s", file.filename, e)
    except Exception as e:
        doc.parse_error = f"Unexpected error: {e}"
        logger.exception("Unexpected parse error for '%s'", file.filename)

    await db.flush()
    await db.refresh(doc)
    return _doc_to_response(doc)


# ── List documents ────────────────────────────────────────────────────────────

@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    """List all documents for a project."""
    result = await db.execute(
        select(Document)
        .where(Document.project_id == project_id)
        .order_by(Document.uploaded_at)
    )
    docs = result.scalars().all()
    return [_doc_to_response(d) for d in docs]


# ── Requirements (human-in-the-loop) ─────────────────────────────────────────

@router.get("/{project_id}/requirements", response_model=list[RequirementResponse])
async def get_requirements(
    project_id: int,
    confirmed_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """
    Get all extracted requirements for a project.
    Set confirmed_only=true to get only human-confirmed requirements.
    """
    query = select(Requirement).where(
        Requirement.project_id == project_id,
        Requirement.is_deleted == False,
    )
    if confirmed_only:
        query = query.where(Requirement.is_confirmed == True)

    result = await db.execute(query.order_by(Requirement.criticality, Requirement.id))
    reqs = result.scalars().all()
    return [RequirementResponse.model_validate(r) for r in reqs]


@router.patch("/requirements/{requirement_id}", response_model=RequirementResponse)
async def update_requirement(
    requirement_id: int,
    payload: RequirementUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a single requirement (human-in-the-loop editing)."""
    result = await db.execute(
        select(Requirement).where(Requirement.id == requirement_id)
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail=f"Requirement {requirement_id} not found.")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(req, field, value)

    await db.flush()
    await db.refresh(req)
    return RequirementResponse.model_validate(req)


@router.post("/requirements/bulk-confirm", response_model=MessageResponse)
async def bulk_confirm_requirements(
    payload: BulkConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """Confirm (or unconfirm) multiple requirements at once."""
    result = await db.execute(
        select(Requirement).where(Requirement.id.in_(payload.requirement_ids))
    )
    reqs = result.scalars().all()

    for req in reqs:
        req.is_confirmed = payload.confirm

    updated = len(reqs)
    return MessageResponse(
        message=f"{'Confirmed' if payload.confirm else 'Unconfirmed'} {updated} requirements."
    )


# ── Admin checks ──────────────────────────────────────────────────────────────

@router.get("/{document_id}/admin-checks", response_model=list[AdminCheckResponse])
async def get_admin_checks(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get admin eligibility check results for a vendor document."""
    result = await db.execute(
        select(AdminCheck).where(AdminCheck.vendor_document_id == document_id)
    )
    checks = result.scalars().all()
    return [AdminCheckResponse.model_validate(c) for c in checks]


# ── Manual requirements extraction (human-in-the-loop gate) ────────────────

@router.post("/{project_id}/requirements/extract", response_model=MessageResponse)
async def extract_requirements_for_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Extract requirements from the latest uploaded RFP (stored as unconfirmed).

    """
    # Validate project
    proj_result = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")

    # Latest parsed RFP document
    rfp_result = await db.execute(
        select(Document)
        .where(Document.project_id == project_id, Document.document_type == DocumentType.RFP)
        .order_by(Document.uploaded_at.desc())
        .limit(1)
    )
    rfp_doc = rfp_result.scalar_one_or_none()
    if not rfp_doc:
        raise HTTPException(status_code=404, detail="No RFP document found for this project.")

    # Parse + extract
    try:
        parsed = parse_document(rfp_doc.file_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse RFP: {e}")

    if parsed.is_scanned:
        raise HTTPException(status_code=400, detail="RFP appears to be scanned; text extraction failed.")

    extracted = extract_requirements(parsed)

    
    existing_result = await db.execute(select(Requirement).where(Requirement.project_id == project_id))
    for old_req in existing_result.scalars().all():
        old_req.is_confirmed = False
        old_req.is_deleted = True

    # Reset audit completion because requirements changed.
    project.audit_complete = False

    for req in extracted:
        db_req = Requirement(
            project_id=project_id,
            rfp_document_id=rfp_doc.id,
            rfp_clause_ref=req.rfp_clause_ref,
            raw_text=req.raw_text,
            normalised_intent=req.normalised_intent,
            category=req.category,
            criticality=req.criticality,
            section_title=req.section_title,
            page_number=req.page_number,
            confidence=req.confidence_score,
            bbox=req.bbox,
            is_confirmed=False,
        )
        db.add(db_req)

    await db.flush()
    return MessageResponse(message=f"Extracted {len(extracted)} requirements.", data=None)


# ── Document file serving (used by Traceability PDF viewer) ───────────────

@router.get("/file/{document_id}")
async def get_document_file(document_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    # Stream inline so browsers embed preview (instead of forced download).
    return FileResponse(
        doc.file_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"'},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _doc_to_response(doc: Document) -> DocumentResponse:
    return DocumentResponse(
        id=doc.id,
        project_id=doc.project_id,
        document_type=doc.document_type,
        vendor_name=doc.vendor_name,
        filename=doc.filename,
        page_count=doc.page_count,
        word_count=doc.word_count,
        is_parsed=doc.is_parsed,
        is_indexed=doc.is_indexed,
        parse_error=doc.parse_error,
        uploaded_at=doc.uploaded_at,
    )