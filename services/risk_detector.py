"""
risk_detector.py
----------------
Hybrid risk detection engine: regex pattern layer + LLM evaluation layer.

Layer 1 (regex — deterministic, instant, free):
  Scans vendor proposals for known risky phrases using the pattern library
  in utils/risk_patterns.py. Every hit is auditable: you can show exactly
  which regex fired and why. Fast: completes in milliseconds per document.

Layer 2 (LLM — contextual, smart, cheap):
  For each regex hit, sends the surrounding context + the relevant RFP
  obligation to Haiku. The LLM determines:
    - Whether the hit is a genuine risk in this context
    - Severity (Low/Medium/High/Critical)
    - Risk type (liability_cap, scope_creep, price_change, etc.)
    - A 1-sentence impact explanation citing the specific RFP clause

Why not LLM-only?
  LLMs miss risks that don't fit their training distribution. Regex
  patterns for "subject to availability", "limited liability", "best
  efforts only" are precise, never hallucinate, and run instantly.
  The LLM layer adds nuance — the regex layer adds recall.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from backend.config import settings
from backend.database import RiskSeverity, RiskType
from utils.llm_client import call_fast
from utils.risk_patterns import RiskPattern, scan_text

logger = logging.getLogger(__name__)


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class RiskFindingResult:
    """A confirmed risk finding from a vendor proposal."""
    vendor_document_id: int
    risk_type: RiskType
    severity: RiskSeverity
    matched_phrase: str
    context_text: str
    impact_explanation: str
    section_ref: str | None
    page_number: int | None
    rfp_clause_ref: str | None
    confirmed_by_llm: bool
    pattern_name: str


# ── System prompt ─────────────────────────────────────────────────────────────

_RISK_SYSTEM_PROMPT = """You are a legal risk analyst specialising in government procurement contracts.

Assess whether a flagged clause in a vendor proposal creates a genuine risk for the buyer.

Return ONLY valid JSON — no markdown, no preamble."""


# ── Risk detector ─────────────────────────────────────────────────────────────

class RiskDetector:
    """
    Detects legal and commercial risks in vendor proposals.

    Usage:
        detector = RiskDetector()
        findings = detector.detect(
            vendor_document_id=2,
            full_text="...",      # complete proposal text
            chunks=[...],         # parsed chunks with page metadata
            rfp_requirements=[...] # confirmed RFP requirements for context
        )
    """

    def detect(
        self,
        vendor_document_id: int,
        full_text: str,
        chunks: list[dict],
        rfp_requirements: list[dict] | None = None,
        sleep_between: float | None = None,
    ) -> list[RiskFindingResult]:
        """
        Run the full risk detection pipeline for one vendor proposal.

        Returns list of confirmed risk findings.
        """
        sleep = sleep_between if sleep_between is not None else settings.RATE_LIMIT_SLEEP

        # ── Layer 1: Regex scan ───────────────────────────────────────────
        raw_hits = scan_text(full_text)
        logger.info(
            "Risk scan for doc %d: %d regex hits found",
            vendor_document_id, len(raw_hits),
        )

        if not raw_hits:
            return []

        # Build page-aware lookup for better section references
        page_index = self._build_page_index(chunks)

        # ── Layer 2: LLM evaluation ───────────────────────────────────────
        findings: list[RiskFindingResult] = []

        for i, hit in enumerate(raw_hits):
            pattern: RiskPattern = hit["pattern"]
            matched_phrase: str = hit["matched_phrase"]
            context: str = hit["context"]

            # Find page reference
            page_num, section_ref = self._find_location(
                hit["char_start"], full_text, page_index
            )

            # Find related RFP requirement if available
            related_rfp = self._find_related_rfp(
                context, rfp_requirements or []
            )

            # LLM evaluation
            try:
                llm_result = self._evaluate_with_llm(
                    matched_phrase=matched_phrase,
                    context=context,
                    default_severity=pattern.default_severity,
                    default_type=pattern.risk_type,
                    related_rfp=related_rfp,
                )
                confirmed = True
            except Exception as e:
                logger.warning(
                    "LLM risk evaluation failed for '%s': %s. Using regex defaults.",
                    matched_phrase, e,
                )
                llm_result = {
                    "confirmed": True,
                    "severity": pattern.default_severity.value,
                    "risk_type": pattern.risk_type.value,
                    "impact": pattern.description,
                }
                confirmed = False

            # Skip if LLM says this is not a genuine risk in context
            if not llm_result.get("confirmed", True):
                logger.debug(
                    "LLM rejected risk hit '%s' as not genuine in context",
                    matched_phrase,
                )
                continue

            # Parse severity
            severity_str = llm_result.get("severity", pattern.default_severity.value)
            try:
                severity = RiskSeverity(severity_str)
            except ValueError:
                severity = pattern.default_severity

            # Parse risk type
            risk_type_str = llm_result.get("risk_type", pattern.risk_type.value)
            try:
                risk_type = RiskType(risk_type_str)
            except ValueError:
                risk_type = pattern.risk_type

            findings.append(RiskFindingResult(
                vendor_document_id=vendor_document_id,
                risk_type=risk_type,
                severity=severity,
                matched_phrase=matched_phrase,
                context_text=context[:500],  # truncate for storage
                impact_explanation=llm_result.get("impact", pattern.description),
                section_ref=section_ref,
                page_number=page_num,
                rfp_clause_ref=related_rfp.get("rfp_clause_ref") if related_rfp else None,
                confirmed_by_llm=confirmed,
                pattern_name=pattern.name,
            ))

            # Rate limit sleep between LLM calls
            if i < len(raw_hits) - 1:
                time.sleep(sleep)

        logger.info(
            "Risk detection complete for doc %d: %d findings confirmed from %d hits",
            vendor_document_id, len(findings), len(raw_hits),
        )
        return findings

    # ── LLM evaluation ────────────────────────────────────────────────────────

    def _evaluate_with_llm(
        self,
        matched_phrase: str,
        context: str,
        default_severity: RiskSeverity,
        default_type: RiskType,
        related_rfp: dict | None,
    ) -> dict:
        """Evaluate a regex hit using the LLM for contextual confirmation."""

        rfp_context = ""
        if related_rfp:
            rfp_context = f"\nRELATED RFP OBLIGATION:\n{related_rfp.get('normalised_intent', '')}"

        prompt = f"""A risk pattern was flagged in a vendor proposal.

FLAGGED PHRASE: "{matched_phrase}"

SURROUNDING CONTEXT:
{context}
{rfp_context}

Assess this risk. Return ONLY this JSON:
{{
  "confirmed": true | false,
  "severity": "Low" | "Medium" | "High" | "Critical",
  "risk_type": "liability_cap" | "scope_creep" | "price_change" | "obligation_weakening" | "exit_clause" | "vague_commitment",
  "impact": "<1 sentence: what could go wrong for the buyer? Cite the specific obligation it undermines if possible>"
}}

Rules:
- confirmed=false ONLY if the phrase is clearly benign in this context (e.g. "best efforts" in a non-committal section)
- severity=Critical if this could void the contract or cause major financial loss
- severity=High if this significantly weakens a mandatory obligation
- impact must reference what the buyer loses, not just describe the phrase"""

        return call_fast(
            prompt,
            system=_RISK_SYSTEM_PROMPT,
            max_tokens=200,
            temperature=0.05,
        )

    # ── Location helpers ──────────────────────────────────────────────────────

    def _build_page_index(self, chunks: list[dict]) -> list[dict]:
        """Build a sorted list of (char_start, page_num, section_title) from chunks."""
        index = []
        char_pos = 0
        for chunk in chunks:
            text = chunk.get("text", "")
            index.append({
                "char_start": char_pos,
                "char_end": char_pos + len(text),
                "page_number": chunk.get("page_number", 1),
                "section_title": chunk.get("section_title", ""),
            })
            char_pos += len(text) + 1
        return sorted(index, key=lambda x: x["char_start"])

    def _find_location(
        self,
        char_pos: int,
        full_text: str,
        page_index: list[dict],
    ) -> tuple[int | None, str | None]:
        """Find page number and section title for a character position."""
        for entry in reversed(page_index):
            if char_pos >= entry["char_start"]:
                page = entry["page_number"]
                section = entry["section_title"]
                ref = f"{section}, page {page}" if section else f"Page {page}"
                return page, ref
        return None, None

    def _find_related_rfp(
        self,
        context: str,
        rfp_requirements: list[dict],
    ) -> dict | None:
        """
        Find the RFP requirement most related to this risk context.
        Simple keyword overlap — good enough for providing LLM context.
        """
        if not rfp_requirements:
            return None

        context_words = set(context.lower().split())
        best_score = 0
        best_req = None

        for req in rfp_requirements:
            req_text = (req.get("normalised_intent") or req.get("raw_text", "")).lower()
            req_words = set(req_text.split())
            overlap = len(context_words & req_words)
            if overlap > best_score:
                best_score = overlap
                best_req = req

        return best_req if best_score >= 3 else None


# ── Module-level convenience ──────────────────────────────────────────────────

def detect_risks(
    vendor_document_id: int,
    full_text: str,
    chunks: list[dict],
    rfp_requirements: list[dict] | None = None,
) -> list[RiskFindingResult]:
    """Module-level convenience wrapper."""
    return RiskDetector().detect(
        vendor_document_id=vendor_document_id,
        full_text=full_text,
        chunks=chunks,
        rfp_requirements=rfp_requirements,
    )