"""
database.py
-----------
SQLAlchemy 2.0 async ORM models and session management.
Single source of truth for all database interactions.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from backend.config import settings


# ── Engine & session factory ──────────────────────────────────────────────────

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_tables() -> None:
    """Create all tables on startup (idempotent)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── Base ──────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Enums ─────────────────────────────────────────────────────────────────────

class DocumentType(str, enum.Enum):
    RFP = "RFP"
    PROPOSAL = "PROPOSAL"


class RequirementCategory(str, enum.Enum):
    TECHNICAL = "Technical"
    LEGAL = "Legal"
    FINANCIAL = "Financial"
    ADMINISTRATIVE = "Administrative"


class Criticality(str, enum.Enum):
    MANDATORY = "Mandatory"
    RECOMMENDED = "Recommended"
    INFORMATIONAL = "Informational"


class MatchStatus(str, enum.Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    NONE = "NONE"
    AMBIGUOUS = "AMBIGUOUS"
    PENDING = "PENDING"


class RiskSeverity(str, enum.Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class RiskType(str, enum.Enum):
    LIABILITY_CAP = "liability_cap"
    SCOPE_CREEP = "scope_creep"
    PRICE_CHANGE = "price_change"
    OBLIGATION_WEAKENING = "obligation_weakening"
    EXIT_CLAUSE = "exit_clause"
    VAGUE_COMMITMENT = "vague_commitment"


# ── Models ────────────────────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    audit_complete: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="project", cascade="all, delete-orphan"
    )
    requirements: Mapped[list["Requirement"]] = relationship(
        "Requirement", back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} name={self.name!r}>"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType), nullable=False
    )
    vendor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_parsed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_indexed: Mapped[bool] = mapped_column(Boolean, default=False)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="documents")
    matches: Mapped[list["Match"]] = relationship(
        "Match", back_populates="vendor_document", cascade="all, delete-orphan"
    )
    risk_findings: Mapped[list["RiskFinding"]] = relationship(
        "RiskFinding", back_populates="vendor_document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} type={self.document_type} vendor={self.vendor_name!r}>"


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    rfp_clause_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalised_intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[RequirementCategory] = mapped_column(
        Enum(RequirementCategory), nullable=False, default=RequirementCategory.TECHNICAL
    )
    criticality: Mapped[Criticality] = mapped_column(
        Enum(Criticality), nullable=False, default=Criticality.MANDATORY
    )
    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="requirements")
    matches: Mapped[list["Match"]] = relationship(
        "Match", back_populates="requirement", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Requirement id={self.id} cat={self.category} crit={self.criticality}>"


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    requirement_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False
    )
    vendor_document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus), nullable=False, default=MatchStatus.PENDING
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    retriever_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reranker_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    requirement: Mapped["Requirement"] = relationship(
        "Requirement", back_populates="matches"
    )
    vendor_document: Mapped["Document"] = relationship(
        "Document", back_populates="matches"
    )

    def __repr__(self) -> str:
        return f"<Match req={self.requirement_id} vendor={self.vendor_document_id} status={self.status}>"


class RiskFinding(Base):
    __tablename__ = "risk_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vendor_document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    risk_type: Mapped[RiskType] = mapped_column(Enum(RiskType), nullable=False)
    severity: Mapped[RiskSeverity] = mapped_column(Enum(RiskSeverity), nullable=False)
    matched_phrase: Mapped[str] = mapped_column(String(500), nullable=False)
    context_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rfp_clause_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confirmed_by_llm: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    vendor_document: Mapped["Document"] = relationship(
        "Document", back_populates="risk_findings"
    )

    def __repr__(self) -> str:
        return f"<RiskFinding id={self.id} type={self.risk_type} severity={self.severity}>"


class AdminCheck(Base):
    __tablename__ = "admin_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vendor_document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # FOUND / MISSING / UNCLEAR
    page_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    matched_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )