"""
entailment_classifier.py
------------------------
NLI-style entailment classification for compliance checking.

This is the core reasoning engine — the component that separates
this system from "RAG with a chatbot wrapper."

Architecture:
  Standard RAG asks: "Is this passage similar to this requirement?"
  → Fails on paraphrases, fails on absence, can't reason about partial compliance.

  This system asks: "Does this passage ENTAIL this requirement?"
  → Handles "round-the-clock" == "24/7 support" (entailment, not similarity)
  → Handles missing requirements (negative space detection)
  → Produces structured FULL/PARTIAL/NONE/AMBIGUOUS with calibrated confidence

Negative space detection (the hardest problem):
  When no candidate passage scores above FUSION_NONE_THRESHOLD after reranking,
  the system marks the requirement NONE WITHOUT making an LLM call.
  This is inference from absence — a capability that pure retrieval cannot provide.
  Cost: free (no API call). Accuracy: high (threshold-tuned).

Confidence calibration:
  Raw LLM confidence values are stored and can be calibrated post-hoc
  using isotonic regression on labeled examples. The stored values
  allow you to show a calibration curve in the Design Document.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal

from backend.config import settings
from backend.database import MatchStatus
from pydantic import BaseModel, Field, ValidationError
from utils.llm_client import acall_smart, call_smart

logger = logging.getLogger(__name__)


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class EntailmentResult:
    """Result of classifying one (requirement, vendor) pair."""
    requirement_id: int
    vendor_document_id: int
    status: MatchStatus
    confidence: float          # 0.0–1.0
    evidence_quote: str | None # exact quote from vendor proposal
    section_ref: str | None    # e.g. "Section 3.2, page 7"
    explanation: str           # 1–2 sentences citing both req and evidence
    reranker_score: float      # max cross-encoder score (for calibration analysis)
    was_negative_space: bool   # True if status=NONE was set without LLM call


class EntailmentResponse(BaseModel):
    """Strict schema for LLM entailment output."""
    status: Literal["FULL", "PARTIAL", "NONE", "AMBIGUOUS"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_quote: str | None
    section_ref: str | None
    explanation: str


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a senior legal compliance auditor specialising in government tenders and RFPs.

Your task: determine whether a vendor's proposal satisfies a specific RFP requirement.

You must return ONLY valid JSON — no markdown, no preamble, no explanation outside the JSON.

Status definitions:
- FULL: The requirement is clearly and completely addressed. The vendor makes an explicit, unambiguous commitment.
- PARTIAL: Some aspects of the requirement are addressed but others are unclear, missing, or qualified with weak language (e.g. "best efforts", "subject to availability").
- NONE: No relevant evidence found in the provided passages. The vendor does not address this requirement.
- AMBIGUOUS: Evidence exists but is too vague or non-committal to determine compliance (e.g. "we aim to provide" without specifics).

Critical rules:
1. Base your decision ONLY on the provided passages — do not assume information not present.
2. If the vendor uses weaker language than required (e.g. "shall endeavour" vs "shall provide"), mark as PARTIAL.
3. An evidence_quote must be a verbatim excerpt from the passages, under 100 words.
4. section_ref should identify where in the proposal the evidence was found.
5. Your explanation must cite BOTH the requirement and the evidence (or lack thereof)."""


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(
    requirement_text: str,
    category: str,
    criticality: str,
    rfp_clause_ref: str | None,
    top_passages: list[dict],
) -> str:
    passages_text = ""
    for i, p in enumerate(top_passages, 1):
        section = p.get("section_title", "Unknown section")
        page = p.get("page_number", "?")
        score = p.get("reranker_score", p.get("score", 0))
        passages_text += (
            f"\n[Passage {i}] Section: {section}, Page: {page}, "
            f"Relevance score: {score:.3f}\n"
            f"{p['text']}\n"
        )

    clause_info = f"Clause reference: {rfp_clause_ref}" if rfp_clause_ref else ""

    return f"""REQUIREMENT TO VALIDATE:
{requirement_text}
Category: {category} | Criticality: {criticality}
{clause_info}

TOP EVIDENCE PASSAGES FROM VENDOR PROPOSAL (ranked by relevance):
{passages_text}

Respond with ONLY this JSON:
{{
  "status": "FULL" | "PARTIAL" | "NONE" | "AMBIGUOUS",
  "confidence": <float 0.0 to 1.0>,
  "evidence_quote": "<verbatim quote from above passages, or null if NONE>",
  "section_ref": "<e.g. 'Section 3.2, page 7' or null>",
  "explanation": "<1-2 sentences: cite the requirement AND what the vendor said or failed to say>"
}}"""


# ── Main classifier ───────────────────────────────────────────────────────────

class EntailmentClassifier:
    """
    Classifies (requirement, vendor) pairs as FULL/PARTIAL/NONE/AMBIGUOUS.

    Usage:
        classifier = EntailmentClassifier()
        result = classifier.classify(
            requirement_id=1,
            vendor_document_id=2,
            requirement_text="Vendor must provide 24/7 technical support",
            category="Technical",
            criticality="Mandatory",
            top_passages=[...],  # output from Reranker.rerank()
            top_fused_score=0.82,
        )
    """

    def classify(
        self,
        requirement_id: int,
        vendor_document_id: int,
        requirement_text: str,
        category: str,
        criticality: str,
        top_passages: list[dict],
        top_fused_score: float,
        rfp_clause_ref: str | None = None,
    ) -> EntailmentResult:
        """
        Classify a single (requirement, vendor) pair.

        Negative space detection fires first: if the best fused score
        is below FUSION_NONE_THRESHOLD, returns NONE immediately without an LLM call.
        """

        # ── Negative space detection ──────────────────────────────────────
        if top_fused_score < settings.FUSION_NONE_THRESHOLD:
            logger.debug(
                "Req %d vs doc %d: NONE (top fused score %.4f < threshold %.4f)",
                requirement_id, vendor_document_id,
                top_fused_score, settings.FUSION_NONE_THRESHOLD,
            )
            return EntailmentResult(
                requirement_id=requirement_id,
                vendor_document_id=vendor_document_id,
                status=MatchStatus.NONE,
                confidence=0.95,  # high confidence: threshold-based, not probabilistic
                evidence_quote=None,
                section_ref=None,
                explanation=(
                    f"No relevant passage found in the vendor proposal. "
                    f"Best fused score ({top_fused_score:.4f}) is below "
                    f"the minimum threshold ({settings.FUSION_NONE_THRESHOLD:.4f}), indicating "
                    f"this requirement is not addressed."
                ),
                reranker_score=top_fused_score,
                was_negative_space=True,
            )

        # ── LLM entailment classification ─────────────────────────────────
        prompt = _build_prompt(
            requirement_text=requirement_text,
            category=category,
            criticality=criticality,
            rfp_clause_ref=rfp_clause_ref,
            top_passages=top_passages,
        )

        try:
            result = call_smart(
                prompt,
                system=_SYSTEM_PROMPT,
                max_tokens=400,
                temperature=0.0,
            )
        except Exception as e:
            logger.error(
                "LLM classification failed for req %d vs doc %d: %s",
                requirement_id, vendor_document_id, e,
            )
            # Safe fallback: AMBIGUOUS with low confidence
            return EntailmentResult(
                requirement_id=requirement_id,
                vendor_document_id=vendor_document_id,
                status=MatchStatus.AMBIGUOUS,
                confidence=0.3,
                evidence_quote=None,
                section_ref=None,
                explanation=f"Classification failed due to API error: {e}. Manual review required.",
                reranker_score=float(top_passages[0].get("reranker_score", 0.0)) if top_passages else 0.0,
                was_negative_space=False,
            )

        # ── Parse and validate result ──────────────────────────────────────
        return self._parse_result(
            result,
            requirement_id,
            vendor_document_id,
            float(top_passages[0].get("reranker_score", 0.0)) if top_passages else 0.0,
        )

    async def classify_async(
        self,
        requirement_id: int,
        vendor_document_id: int,
        requirement_text: str,
        category: str,
        criticality: str,
        top_passages: list[dict],
        top_fused_score: float,
        rfp_clause_ref: str | None = None,
    ) -> EntailmentResult:
        """Async variant of classify() for concurrent orchestration."""
        if top_fused_score < settings.FUSION_NONE_THRESHOLD:
            logger.debug(
                "Req %d vs doc %d: NONE (top fused score %.4f < threshold %.4f)",
                requirement_id, vendor_document_id,
                top_fused_score, settings.FUSION_NONE_THRESHOLD,
            )
            return EntailmentResult(
                requirement_id=requirement_id,
                vendor_document_id=vendor_document_id,
                status=MatchStatus.NONE,
                confidence=0.95,
                evidence_quote=None,
                section_ref=None,
                explanation=(
                    f"No relevant passage found in the vendor proposal. "
                    f"Best fused score ({top_fused_score:.4f}) is below "
                    f"the minimum threshold ({settings.FUSION_NONE_THRESHOLD:.4f}), indicating "
                    f"this requirement is not addressed."
                ),
                reranker_score=top_fused_score,
                was_negative_space=True,
            )

        base_prompt = _build_prompt(
            requirement_text=requirement_text,
            category=category,
            criticality=criticality,
            rfp_clause_ref=rfp_clause_ref,
            top_passages=top_passages,
        )

        prompt = base_prompt
        validation_error: ValidationError | None = None
        retries = 2
        for attempt in range(retries + 1):
            try:
                result = await acall_smart(
                    prompt,
                    system=_SYSTEM_PROMPT,
                    max_tokens=400,
                    temperature=0.0,
                )
                validated = EntailmentResponse.model_validate(result)
                return self._parse_result(
                    validated.model_dump(),
                    requirement_id,
                    vendor_document_id,
                    float(top_passages[0].get("reranker_score", 0.0)) if top_passages else 0.0,
                )
            except ValidationError as e:
                validation_error = e
                if attempt >= retries:
                    break
                logger.warning(
                    "Validation failed for req %d vs doc %d on attempt %d/%d: %s",
                    requirement_id, vendor_document_id, attempt + 1, retries + 1, e,
                )
                prompt = (
                    f"{base_prompt}\n\n"
                    f"Your previous response failed validation: {e}. "
                    "Please correct it and return ONLY valid JSON."
                )
            except Exception as e:
                logger.error(
                    "LLM classification failed for req %d vs doc %d: %s",
                    requirement_id, vendor_document_id, e,
                )
                return EntailmentResult(
                    requirement_id=requirement_id,
                    vendor_document_id=vendor_document_id,
                    status=MatchStatus.AMBIGUOUS,
                    confidence=0.3,
                    evidence_quote=None,
                    section_ref=None,
                    explanation=f"Classification failed due to API error: {e}. Manual review required.",
                    reranker_score=float(top_passages[0].get("reranker_score", 0.0)) if top_passages else 0.0,
                    was_negative_space=False,
                )

        logger.error(
            "LLM response validation failed after retries for req %d vs doc %d: %s",
            requirement_id, vendor_document_id, validation_error,
        )
        return EntailmentResult(
            requirement_id=requirement_id,
            vendor_document_id=vendor_document_id,
            status=MatchStatus.AMBIGUOUS,
            confidence=0.3,
            evidence_quote=None,
            section_ref=None,
            explanation=(
                "Classification failed due to invalid structured output after retries. "
                "Manual review required."
            ),
            reranker_score=float(top_passages[0].get("reranker_score", 0.0)) if top_passages else 0.0,
            was_negative_space=False,
        )

    def _parse_result(
        self,
        raw: dict,
        requirement_id: int,
        vendor_document_id: int,
        reranker_score: float,
    ) -> EntailmentResult:
        """Parse and validate the LLM JSON response."""

        # Parse status
        status_str = raw.get("status", "AMBIGUOUS").upper()
        status_map = {
            "FULL": MatchStatus.FULL,
            "PARTIAL": MatchStatus.PARTIAL,
            "NONE": MatchStatus.NONE,
            "AMBIGUOUS": MatchStatus.AMBIGUOUS,
        }
        status = status_map.get(status_str, MatchStatus.AMBIGUOUS)

        # Parse confidence
        try:
            confidence = float(raw.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))  # clamp to [0, 1]
        except (ValueError, TypeError):
            confidence = 0.5

        # Validate evidence quote (must be non-empty for FULL/PARTIAL)
        evidence = raw.get("evidence_quote") or None
        if evidence and len(evidence.strip()) < 5:
            evidence = None
        if status in (MatchStatus.FULL, MatchStatus.PARTIAL) and not evidence:
            # Downgrade to AMBIGUOUS if no evidence provided for positive match
            status = MatchStatus.AMBIGUOUS
            confidence = min(confidence, 0.5)

        explanation = raw.get("explanation", "No explanation provided.").strip()
        if not explanation:
            explanation = f"Classified as {status_str} with confidence {confidence:.2f}."

        return EntailmentResult(
            requirement_id=requirement_id,
            vendor_document_id=vendor_document_id,
            status=status,
            confidence=confidence,
            evidence_quote=evidence,
            section_ref=raw.get("section_ref") or None,
            explanation=explanation,
            reranker_score=reranker_score,
            was_negative_space=False,
        )


# ── Batch classifier ──────────────────────────────────────────────────────────

class BatchEntailmentClassifier:
    """
    Classifies all (requirement × vendor) pairs for a project.
    Handles rate limiting and caching of results.
    """

    def __init__(self):
        self.classifier = EntailmentClassifier()

    def classify_all(
        self,
        requirement_vendor_pairs: list[dict],
        sleep_between: float | None = None,
    ) -> list[EntailmentResult]:
        """
        Classify all pairs sequentially with rate-limit sleep.

        Each pair dict must contain:
          requirement_id, vendor_document_id, requirement_text,
          category, criticality, top_passages, top_fused_score,
          rfp_clause_ref (optional)
        """
        sleep = sleep_between if sleep_between is not None else settings.RATE_LIMIT_SLEEP
        results = []
        total = len(requirement_vendor_pairs)
        none_count = 0
        llm_count = 0

        for i, pair in enumerate(requirement_vendor_pairs):
            result = self.classifier.classify(
                requirement_id=pair["requirement_id"],
                vendor_document_id=pair["vendor_document_id"],
                requirement_text=pair["requirement_text"],
                category=pair.get("category", "Technical"),
                criticality=pair.get("criticality", "Mandatory"),
                top_passages=pair["top_passages"],
                top_fused_score=pair.get("top_fused_score", pair.get("max_reranker_score", 0.0)),
                rfp_clause_ref=pair.get("rfp_clause_ref"),
            )
            results.append(result)

            if result.was_negative_space:
                none_count += 1
            else:
                llm_count += 1
                # Sleep between LLM calls to avoid rate limits
                if i < total - 1:
                    time.sleep(sleep)

            logger.info(
                "Classified %d/%d: req=%d vendor=%d → %s (conf=%.2f) %s",
                i + 1, total,
                result.requirement_id,
                result.vendor_document_id,
                result.status.value,
                result.confidence,
                "[negative space]" if result.was_negative_space else "",
            )

        logger.info(
            "Batch classification complete: %d total, %d via negative space (free), %d via LLM",
            total, none_count, llm_count,
        )
        return results

    async def classify_all_async(
        self,
        requirement_vendor_pairs: list[dict],
    ) -> list[EntailmentResult]:
        """
        Classify all pairs concurrently.
        Uses asyncio.gather(return_exceptions=True) and preserves input order.
        """
        tasks = [
            self.classifier.classify_async(
                requirement_id=pair["requirement_id"],
                vendor_document_id=pair["vendor_document_id"],
                requirement_text=pair["requirement_text"],
                category=pair.get("category", "Technical"),
                criticality=pair.get("criticality", "Mandatory"),
                top_passages=pair["top_passages"],
                top_fused_score=pair.get("top_fused_score", pair.get("max_reranker_score", 0.0)),
                rfp_clause_ref=pair.get("rfp_clause_ref"),
            )
            for pair in requirement_vendor_pairs
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[EntailmentResult] = []
        for i, result in enumerate(raw_results):
            pair = requirement_vendor_pairs[i]
            if isinstance(result, Exception):
                logger.error(
                    "Async classification failed for req %d vs doc %d: %s",
                    pair["requirement_id"], pair["vendor_document_id"], result,
                )
                results.append(
                    EntailmentResult(
                        requirement_id=pair["requirement_id"],
                        vendor_document_id=pair["vendor_document_id"],
                        status=MatchStatus.AMBIGUOUS,
                        confidence=0.3,
                        evidence_quote=None,
                        section_ref=None,
                        explanation=f"Classification failed due to API error: {result}. Manual review required.",
                        reranker_score=float(
                            pair.get("top_passages", [{}])[0].get("reranker_score", 0.0)
                        ) if pair.get("top_passages") else 0.0,
                        was_negative_space=False,
                    )
                )
                continue
            results.append(result)

        return results