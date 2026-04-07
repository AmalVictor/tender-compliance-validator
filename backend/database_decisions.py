"""
database_decisions.py
---------------------
HumanDecision table for Accept / Annotate / Override actions.

Why a separate table instead of columns on Match:
  - A single match can have multiple decisions over time (override → re-override → accepted)
  - We want a full audit log of every human action, not just the latest
  - This keeps the Match table unchanged (no migration of existing data)
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class DecisionType(str, enum.Enum):
    """Types of human decisions on AI classifications."""
    ACCEPTED   = "ACCEPTED"    # reviewer agrees with AI verdict
    ANNOTATED  = "ANNOTATED"   # reviewer adds a note but keeps AI verdict
    OVERRIDDEN = "OVERRIDDEN"  # reviewer changes the AI verdict


class HumanDecision(Base):
    """
    Records every human Accept / Annotate / Override action on a Match.

    The latest decision for a (match_id) is the canonical human verdict.
    All previous decisions are retained for audit purposes.
    """
    __tablename__ = "human_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ─ The AI classification this decision relates to ────────────────────────
    match_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ─ Denormalised for easy querying ─────────────────────────────────────────
    requirement_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    vendor_document_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # ─ The action type ───────────────────────────────────────────────────────
    decision_type: Mapped[DecisionType] = mapped_column(
        Enum(DecisionType), nullable=False
    )

    # ─ For OVERRIDDEN: the new status the reviewer has set ────────────────────
    # NULL for ACCEPTED and ANNOTATED
    override_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ─ Reviewer's note ───────────────────────────────────────────────────────
    # Required for ANNOTATED and OVERRIDDEN, optional for ACCEPTED
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ─ Who made the decision ────────────────────────────────────────────────────
    # Passed from frontend, not auth-gated for now
    reviewer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ─ Timestamp ────────────────────────────────────────────────────────────
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<HumanDecision match={self.match_id} "
            f"type={self.decision_type} override={self.override_status}>"
        )
