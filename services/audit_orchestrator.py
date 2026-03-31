"""
audit_orchestrator.py
---------------------
Orchestrates the full compliance audit pipeline for a project.

Pipeline:
  1. Load confirmed requirements from DB
  2. For each vendor proposal:
     a. Load proposal text from file
     b. For each requirement:
        i.  Stage 1: bi-encoder retrieval (top-20)
        ii. Stage 2: cross-encoder reranking (top-5)
        iii. Entailment classification (FULL/PARTIAL/NONE/AMBIGUOUS)
     c. Risk detection (regex + LLM)
     d. Scoring (compliance % + risk score)
  3. Save all results to DB
  4. Mark project audit_complete = True

This is a synchronous pipeline run in a background thread from FastAPI.
For a hackathon, running in a thread is fine. For production, use Celery.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import (
    Document,
    DocumentType,
    Match,
    MatchStatus,
    Project,
    Requirement,
    RiskFinding,
)
from services.document_parser import parse_document
from services.entailment_classifier import BatchEntailmentClassifier
from services.proposal_indexer import ProposalIndexer
from services.reranker import Reranker
from services.risk_detector import RiskDetector
from services.scorer import ComplianceScorer

logger = logging.getLogger(__name__)


class AuditOrchestrator:
    """
    Runs the full compliance audit pipeline for a project.
    Call run() from an async context — it handles DB operations directly.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.indexer = ProposalIndexer()
        self.reranker = Reranker()
        self.classifier = BatchEntailmentClassifier()
        self.risk_detector = RiskDetector()
        self.scorer = ComplianceScorer()

    async def _process_requirement_for_vendor(
        self,
        project_id: int,
        proposal_id: int,
        req: Requirement,
    ) -> dict:
        """Process retrieval + reranking for one requirement/vendor pair."""
        query_text = req.normalised_intent or req.raw_text

        try:
            candidates = await asyncio.to_thread(
                self.indexer.retrieve_with_keyword_boost,
                query_text,
                project_id,
                proposal_id,
                settings.TOP_K_RETRIEVAL,
            )
        except Exception as e:
            logger.warning(
                "Retrieval failed for req %d vendor %d: %s",
                req.id, proposal_id, e,
            )
            candidates = []

        best_s1 = max((float(c.get("score", 0.0)) for c in candidates), default=0.0)

        if candidates:
            top_passages = await asyncio.to_thread(
                self.reranker.rerank,
                query_text,
                candidates,
                settings.TOP_K_RERANK,
            )
            max_score = await asyncio.to_thread(self.reranker.max_score, top_passages)
            top_fused_score = await asyncio.to_thread(
                self.reranker.top_fused_score, top_passages
            )
        else:
            top_passages = []
            max_score = 0.0
            top_fused_score = 0.0

        return {
            "pair": {
                "requirement_id": req.id,
                "vendor_document_id": proposal_id,
                "requirement_text": query_text,
                "category": req.category.value,
                "criticality": req.criticality.value,
                "rfp_clause_ref": req.rfp_clause_ref,
                "top_passages": top_passages,
                "max_reranker_score": max_score,
                "top_fused_score": top_fused_score,
            },
            "best_s1": best_s1,
        }

    async def run(self, project_id: int) -> dict:
        """
        Run the full audit pipeline.
        Returns a summary dict with scores and counts.
        """
        logger.info("Starting audit for project %d", project_id)

        # ── Load confirmed requirements ────────────────────────────────────
        req_result = await self.db.execute(
            select(Requirement).where(
                Requirement.project_id == project_id,
                Requirement.is_confirmed == True,
                Requirement.is_deleted == False,
            )
        )
        requirements = req_result.scalars().all()

        if not requirements:
            return {
                "error": "No confirmed requirements found. "
                         "Please confirm requirements before running audit."
            }

        logger.info("Loaded %d confirmed requirements", len(requirements))

        # ── Load vendor proposals ──────────────────────────────────────────
        doc_result = await self.db.execute(
            select(Document).where(
                Document.project_id == project_id,
                Document.document_type == DocumentType.PROPOSAL,
                Document.is_indexed == True,
            )
        )
        proposals = doc_result.scalars().all()

        if not proposals:
            return {
                "error": "No indexed vendor proposals found. "
                         "Please upload and process vendor proposals first."
            }

        logger.info("Found %d vendor proposals to audit", len(proposals))

        # ── Delete existing match/risk results (allow re-running) ──────────
        for prop in proposals:
            await self.db.execute(
                Match.__table__.delete().where(
                    Match.vendor_document_id == prop.id
                )
            )
            await self.db.execute(
                RiskFinding.__table__.delete().where(
                    RiskFinding.vendor_document_id == prop.id
                )
            )
        await self.db.flush()

        # ── Requirements as dicts for processing ───────────────────────────
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

        all_vendor_results = []

        # ── Process each vendor proposal ───────────────────────────────────
        for proposal in proposals:
            logger.info(
                "Auditing vendor: %s (doc_id=%d)",
                proposal.vendor_name, proposal.id,
            )

            # Build classification pairs for this vendor (concurrently)
            pairs = []
            best_s1_by_requirement: dict[int, float] = {}
            req_tasks = [
                self._process_requirement_for_vendor(project_id, proposal.id, req)
                for req in requirements
            ]
            req_results = await asyncio.gather(*req_tasks, return_exceptions=True)

            for idx, item in enumerate(req_results):
                req = requirements[idx]
                if isinstance(item, Exception):
                    logger.error(
                        "Requirement pipeline failed for req %d vendor %d: %s",
                        req.id, proposal.id, item,
                    )
                    best_s1_by_requirement[req.id] = 0.0
                    pairs.append({
                        "requirement_id": req.id,
                        "vendor_document_id": proposal.id,
                        "requirement_text": req.normalised_intent or req.raw_text,
                        "category": req.category.value,
                        "criticality": req.criticality.value,
                        "rfp_clause_ref": req.rfp_clause_ref,
                        "top_passages": [],
                        "max_reranker_score": 0.0,
                        "top_fused_score": 0.0,
                    })
                    continue

                best_s1_by_requirement[item["pair"]["requirement_id"]] = item["best_s1"]
                pairs.append(item["pair"])

            # Run entailment classification
            entailment_results = await self.classifier.classify_all_async(pairs)

            # Save match results to DB
            for result in entailment_results:
                match = Match(
                    requirement_id=result.requirement_id,
                    vendor_document_id=result.vendor_document_id,
                    status=result.status,
                    confidence=result.confidence,
                    evidence_quote=result.evidence_quote,
                    section_ref=result.section_ref,
                    explanation=result.explanation,
                    retriever_score=best_s1_by_requirement.get(result.requirement_id, 0.0),
                    reranker_score=result.reranker_score,
                )
                self.db.add(match)

            await self.db.flush()

            # ── Risk detection ─────────────────────────────────────────────
            try:
                proposal_text, proposal_chunks = await asyncio.to_thread(
                    self._load_proposal_text, proposal.file_path, project_id, proposal.id
                )
                risk_results = await asyncio.to_thread(
                    self.risk_detector.detect,
                    proposal.id,
                    proposal_text,
                    proposal_chunks,
                    req_dicts,
                )

                for finding in risk_results:
                    db_finding = RiskFinding(
                        vendor_document_id=finding.vendor_document_id,
                        risk_type=finding.risk_type,
                        severity=finding.severity,
                        matched_phrase=finding.matched_phrase,
                        context_text=finding.context_text,
                        impact_explanation=finding.impact_explanation,
                        section_ref=finding.section_ref,
                        page_number=finding.page_number,
                        rfp_clause_ref=finding.rfp_clause_ref,
                        confirmed_by_llm=finding.confirmed_by_llm,
                    )
                    self.db.add(db_finding)

                await self.db.flush()

            except Exception as e:
                logger.error(
                    "Risk detection failed for vendor %s: %s",
                    proposal.vendor_name, e,
                )

            all_vendor_results.append({
                "document_id": proposal.id,
                "vendor_name": proposal.vendor_name or proposal.filename,
                "match_count": len(entailment_results),
            })

        # ── Compute scores ─────────────────────────────────────────────────
        # Reload matches and findings from DB for scoring
        all_matches = []
        all_risk_findings = []

        for proposal in proposals:
            m_result = await self.db.execute(
                select(Match).where(Match.vendor_document_id == proposal.id)
            )
            for m in m_result.scalars().all():
                all_matches.append({
                    "requirement_id": m.requirement_id,
                    "vendor_document_id": m.vendor_document_id,
                    "status": m.status.value,
                    "confidence": m.confidence,
                })

            r_result = await self.db.execute(
                select(RiskFinding).where(RiskFinding.vendor_document_id == proposal.id)
            )
            for r in r_result.scalars().all():
                all_risk_findings.append({
                    "vendor_document_id": r.vendor_document_id,
                    "severity": r.severity.value,
                    "risk_type": r.risk_type.value,
                })

        vendor_scores = self.scorer.score_all(
            vendors=all_vendor_results,
            requirements=req_dicts,
            matches=all_matches,
            risk_findings=all_risk_findings,
        )

        # ── Mark project complete ──────────────────────────────────────────
        proj_result = await self.db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = proj_result.scalar_one_or_none()
        if project:
            project.audit_complete = True

        await self.db.flush()

        logger.info(
            "Audit complete for project %d: %d vendors scored",
            project_id, len(vendor_scores),
        )

        return {
            "project_id": project_id,
            "vendors_audited": len(proposals),
            "requirements_checked": len(requirements),
            "vendor_scores": [
                {
                    "vendor_name": s.vendor_name,
                    "compliance_score": s.compliance_score,
                    "risk_score": s.risk_score,
                    "status_colour": s.status_colour,
                    "mandatory_full": s.mandatory_full,
                    "mandatory_partial": s.mandatory_partial,
                    "mandatory_none": s.mandatory_none,
                    "critical_risks": s.critical_risks,
                    "high_risks": s.high_risks,
                }
                for s in vendor_scores
            ],
        }

    def _load_proposal_text(
        self,
        file_path: str,
        project_id: int,
        document_id: int,
    ) -> tuple[str, list[dict]]:
        """Load proposal text by re-parsing the file."""
        parsed = parse_document(Path(file_path))
        full_text = " ".join(c.text for c in parsed.all_chunks)
        chunks = [
            {
                "text": c.text,
                "page_number": c.page_number,
                "section_title": c.section_title,
            }
            for c in parsed.all_chunks
        ]
        return full_text, chunks