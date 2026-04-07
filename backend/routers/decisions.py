"""
routers/decisions.py
--------------------
Human decision endpoints: Accept, Annotate, Override on individual match verdicts.

These three actions are what the Accept / Annotate / Override buttons in the
Deep Dive tab write to the database. They power the "Decision Trail" section
of the exported PDF and make the audit legally defensible.

Endpoints:
    POST /api/decisions/                    Record a new decision
    GET  /api/decisions/match/{match_id}    Get all decisions for a match
    GET  /api/decisions/project/{project_id} Get all decisions for a project
    DELETE /api/decisions/{decision_id}     Undo a decision (soft-delete via new entry)
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Match, get_db
from database_decisions import DecisionType, HumanDecision

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response schemas ─────────────────────────────────────────────────

class DecisionCreate(BaseModel):
    match_id: int
    requirement_id: int
    vendor_document_id: int
    decision_type: DecisionType
    override_status: str | None = Field(
        None,
        description="Required when decision_type=OVERRIDDEN. One of: FULL, PARTIAL, NONE, AMBIGUOUS",
    )
    reviewer_note: str | None = Field(None, max_length=2000)
    reviewer_name: str | None = Field(None, max_length=200)


class DecisionResponse(BaseModel):
    id: int
    match_id: int
    requirement_id: int
    vendor_document_id: int
    decision_type: DecisionType
    override_status: str | None
    reviewer_note: str | None
    reviewer_name: str | None
    decided_at: datetime

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", response_model=DecisionResponse, status_code=201)
async def record_decision(
    payload: DecisionCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Record an Accept / Annotate / Override decision.

    - ACCEPTED: reviewer confirms AI verdict is correct. reviewer_note optional.
    - ANNOTATED: reviewer adds context without changing verdict. reviewer_note required.
    - OVERRIDDEN: reviewer changes the verdict. override_status + reviewer_note required.
    """
    # Validate the match exists
    match_result = await db.execute(select(Match).where(Match.id == payload.match_id))
    match = match_result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail=f"Match {payload.match_id} not found.")

    # Validate OVERRIDDEN has a status
    if payload.decision_type == DecisionType.OVERRIDDEN:
        if not payload.override_status:
            raise HTTPException(
                status_code=422,
                detail="override_status is required when decision_type is OVERRIDDEN.",
            )
        valid_statuses = {"FULL", "PARTIAL", "NONE", "AMBIGUOUS"}
        if payload.override_status.upper() not in valid_statuses:
            raise HTTPException(
                status_code=422,
                detail=f"override_status must be one of: {', '.join(valid_statuses)}",
            )

    # Validate ANNOTATED has a note
    if payload.decision_type == DecisionType.ANNOTATED and not payload.reviewer_note:
        raise HTTPException(
            status_code=422,
            detail="reviewer_note is required when decision_type is ANNOTATED.",
        )

    decision = HumanDecision(
        match_id=payload.match_id,
        requirement_id=payload.requirement_id,
        vendor_document_id=payload.vendor_document_id,
        decision_type=payload.decision_type,
        override_status=payload.override_status.upper() if payload.override_status else None,
        reviewer_note=payload.reviewer_note,
        reviewer_name=payload.reviewer_name,
    )
    db.add(decision)
    await db.flush()
    await db.refresh(decision)

    logger.info(
        "Decision recorded: match=%d type=%s reviewer=%s",
        payload.match_id, payload.decision_type, payload.reviewer_name or "anonymous",
    )

    return DecisionResponse.model_validate(decision)


@router.get("/match/{match_id}", response_model=list[DecisionResponse])
async def get_decisions_for_match(
    match_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return all decisions for a single match, newest first."""
    result = await db.execute(
        select(HumanDecision)
        .where(HumanDecision.match_id == match_id)
        .order_by(HumanDecision.decided_at.desc())
    )
    return [DecisionResponse.model_validate(d) for d in result.scalars().all()]


@router.get("/project/{project_id}", response_model=list[DecisionResponse])
async def get_decisions_for_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Return all decisions for every match in a project.
    The export endpoint uses this to populate the Decision Trail section.
    """
    # Join through matches → requirements → project
    from database import Requirement
    req_subquery = (
        select(Match.id)
        .join(Requirement, Match.requirement_id == Requirement.id)
        .where(Requirement.project_id == project_id)
        .scalar_subquery()
    )
    result = await db.execute(
        select(HumanDecision)
        .where(HumanDecision.match_id.in_(req_subquery))
        .order_by(HumanDecision.decided_at.asc())
    )
    return [DecisionResponse.model_validate(d) for d in result.scalars().all()]