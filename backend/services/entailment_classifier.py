"""
entailment_classifier.py  
------------------------------------

  Temporal/future-commitment detection so "we intend to obtain ISO 27001
          by Q4" is classified NONE, not PARTIAL.

  Approach (two layers so neither alone is a single point of failure):
    Layer A — System prompt: new rule #6 explicitly defines future commitments
              as NONE. LLM learns the distinction from the prompt.
    Layer B — Post-hoc regex guard in _parse_result: if the LLM still returns
              FULL or PARTIAL despite future-tense evidence, we downgrade to NONE
              and attach a clear explanation. This makes the fix deterministic
              regardless of LLM compliance.

  Also added:
   _build_prompt now annotates each passage with a
            TEMPORAL WARNING when future-tense phrases are detected, so
            the LLM has explicit in-context signal before it reasons.
   explain field now always cites both the requirement and the
            specific evidence (or lack thereof) — enforced in _parse_result.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Literal

from config import settings
from database import MatchStatus
from pydantic import BaseModel, Field, ValidationError
from utils.llm_client import acall_smart, call_smart

logger = logging.getLogger(__name__)


# ─── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class EntailmentResult:
    """Result of classifying one (requirement, vendor) pair."""
    requirement_id: int
    vendor_document_id: int
    status: MatchStatus
    confidence: float
    evidence_quote: str | None
    section_ref: str | None
    explanation: str
    reranker_score: float
    was_negative_space: bool
    bbox: list[float] | None = None


class EntailmentResponse(BaseModel):
    """Strict schema for LLM entailment output."""
    status: Literal["FULL", "PARTIAL", "NONE", "AMBIGUOUS"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_quote: str | None
    section_ref: str | None
    explanation: str


# ─── Future-tense phrase patterns ───────────────────────────────────
#
# These patterns identify evidence quotes / passages that express intent or
# planned future compliance rather than current compliance.
# The list is intentionally broad — false positives here (downgrading a
# genuinely PARTIAL to NONE) are far safer than false negatives (calling
# "we plan to comply" a PARTIAL compliance).
#
_FUTURE_COMMITMENT_PATTERNS: list[re.Pattern[str]] = [
    # Explicit future intent verbs
    re.compile(
        r"\b(intend|plan|aim|expect|hope|will\s+seek|will\s+obtain|will\s+achieve"
        r"|will\s+implement|will\s+pursue|will\s+be\s+seeking|will\s+be\s+certified"
        r"|are\s+planning|are\s+working\s+towards?|are\s+in\s+the\s+process"
        r"|is\s+in\s+the\s+process|working\s+towards?)\b",
        re.IGNORECASE,
    ),
    # Temporal phrases anchoring to a future date
    re.compile(
        r"\b(by\s+Q[1-4]|by\s+end\s+of|by\s+(January|February|March|April|May|June"
        r"|July|August|September|October|November|December)"
        r"|by\s+\d{4}|within\s+\d+\s+(months?|years?|weeks?)"
        r"|in\s+the\s+coming|in\s+the\s+near\s+future|upon\s+award)\b",
        re.IGNORECASE,
    ),
    # "currently pursuing", "currently in progress"
    re.compile(
        r"\b(currently\s+(pursuing|seeking|applying\s+for|working\s+towards?|in\s+progress"
        r"|undergoing|not\s+yet|pending))\b",
        re.IGNORECASE,
    ),
    # "not yet certified/compliant/obtained"
    re.compile(
        r"\b(not\s+yet|yet\s+to)\b",
        re.IGNORECASE,
    ),
    # Conditional on future event
    re.compile(
        r"\b(upon\s+contract\s+award|if\s+awarded|once\s+awarded|post[- ]award)\b",
        re.IGNORECASE,
    ),
]


def _contains_future_commitment(text: str | None) -> bool:
    """
    Return True if the text expresses future / planned compliance rather
    than current compliance.
    """
    if not text:
        return False
    for pattern in _FUTURE_COMMITMENT_PATTERNS:
        if pattern.search(text):
            return True
    return False


# ─── System prompt ────────────────────────────────────────────────────────────

# Rule #6 added — the LLM must treat future commitments as NONE.
_SYSTEM_PROMPT = """You are a senior legal compliance auditor specialising in government tenders and RFPs.

Your task: determine whether a vendor's proposal satisfies a specific RFP requirement AS OF TODAY.

You must return ONLY valid JSON — no markdown, no preamble, no explanation outside the JSON.

Status definitions:
- FULL: The requirement is clearly and completely addressed RIGHT NOW. The vendor makes an
  explicit, unambiguous, PRESENT-TENSE commitment with no conditions or deferral.
- PARTIAL: Some aspects of the requirement are addressed TODAY but others are unclear,
  missing, or qualified with weak language (e.g. "best efforts", "subject to availability").
  The vendor must currently have partial capability — not merely plan to acquire it.
- NONE: No current evidence found. This includes:
    (a) No relevant passage in the proposal at all.
    (b) The vendor mentions the topic ONLY in the context of future plans, intentions,
        or certifications they are working towards (e.g. "we intend to obtain ISO 27001
        by Q4", "we are currently pursuing certification", "we plan to comply upon award").
        A future commitment is NOT compliance — classify as NONE.
- AMBIGUOUS: Evidence exists but is too vague or non-committal to determine compliance
  (e.g. "we aim to provide" without any specifics or timeline).

Critical rules:
1. Base your decision ONLY on the provided passages — do not assume information not present.
2. If the vendor uses weaker language than required (e.g. "shall endeavour" vs "shall
   provide"), mark as PARTIAL — but only if they currently have partial capability.
3. An evidence_quote must be a verbatim excerpt from the passages, under 100 words.
4. section_ref should identify where in the proposal the evidence was found.
5. Your explanation must cite BOTH the requirement and the evidence (or lack thereof).
6. TEMPORAL RULE (strict): If the evidence quote contains future-tense language
   ("intend to", "plan to", "will obtain", "by Q[N]", "currently pursuing",
   "not yet certified", "upon award", etc.), you MUST classify as NONE regardless
   of whether the certification/capability is mentioned. Future intent ≠ current compliance."""


# ─── Passage annotator ────────────────────────────────────────────────────────

def _annotate_passage_for_temporality(passage_text: str) -> str:
    """
    [FIX-1 / IMPROVE] Prefix passage with a WARNING if future-commitment
    language is detected. This gives the LLM an explicit in-context signal
    before it reasons about the status.
    """
    if _contains_future_commitment(passage_text):
        return f"[⚠ TEMPORAL WARNING: This passage expresses future intent, not current compliance]\n{passage_text}"
    return passage_text


# ─── Prompt builder ───────────────────────────────────────────────────────────

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
        page    = p.get("page_number", "?")
        score   = p.get("reranker_score", p.get("score", 0))
        # Annotate each passage with temporal warning if needed
        annotated_text = _annotate_passage_for_temporality(p["text"])
        passages_text += (
            f"\n[Passage {i}] Section: {section}, Page: {page}, "
            f"Relevance score: {score:.3f}\n"
            f"{annotated_text}\n"
        )

    clause_info = f"Clause reference: {rfp_clause_ref}" if rfp_clause_ref else ""

    return f"""REQUIREMENT TO VALIDATE (must be met AS OF TODAY):
{requirement_text}
Category: {category} | Criticality: {criticality}
{clause_info}

TOP EVIDENCE PASSAGES FROM VENDOR PROPOSAL (ranked by relevance):
{passages_text}

REMINDER: If any passage uses future-tense language about this requirement,
classify as NONE — a promise to comply in the future is not current compliance.

Respond with ONLY this JSON:
{{
  "status": "FULL" | "PARTIAL" | "NONE" | "AMBIGUOUS",
  "confidence": <float 0.0 to 1.0>,
  "evidence_quote": "<verbatim quote from above passages, or null if NONE>",
  "section_ref": "<e.g. 'Section 3.2, page 7' or null>",
  "explanation": "<1-2 sentences: cite the requirement AND what the vendor said or failed to say>"
}}"""


# ─── Bbox extraction helper ────────────────────────────────────────────────────

def _extract_bbox_for_quote(
    evidence_quote: str | None, top_passages: list[dict]
) -> list[float] | None:
    if not evidence_quote or not top_passages:
        return None
    normalized_quote = evidence_quote.strip().lower()
    for passage in top_passages:
        passage_text = passage.get("text", "").lower()
        if normalized_quote in passage_text:
            bbox = passage.get("bbox")
            if bbox:
                return bbox
    return None


# ─── Main classifier ──────────────────────────────────────────────────────────

class EntailmentClassifier:
    """
    Classifies (requirement, vendor) pairs as FULL/PARTIAL/NONE/AMBIGUOUS.
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
        if top_fused_score < settings.PROBABILITY_NONE_THRESHOLD:
            logger.debug(
                "Req %d vs doc %d: NONE (top fused probability %.4f < threshold %.2f)",
                requirement_id, vendor_document_id,
                top_fused_score, settings.PROBABILITY_NONE_THRESHOLD,
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
                    f"Best fused probability ({top_fused_score:.4f}) is below "
                    f"the minimum threshold ({settings.PROBABILITY_NONE_THRESHOLD:.2f})."
                ),
                reranker_score=top_fused_score,
                was_negative_space=True,
            )

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

        return self._parse_result(
            result,
            requirement_id,
            vendor_document_id,
            float(top_passages[0].get("reranker_score", 0.0)) if top_passages else 0.0,
            top_passages,
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
        if top_fused_score < settings.PROBABILITY_NONE_THRESHOLD:
            return EntailmentResult(
                requirement_id=requirement_id,
                vendor_document_id=vendor_document_id,
                status=MatchStatus.NONE,
                confidence=0.95,
                evidence_quote=None,
                section_ref=None,
                explanation=(
                    f"No relevant passage found. Best fused probability "
                    f"({top_fused_score:.4f}) is below threshold "
                    f"({settings.PROBABILITY_NONE_THRESHOLD:.2f})."
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
                    top_passages,
                )
            except ValidationError as e:
                validation_error = e
                if attempt >= retries:
                    break
                logger.warning(
                    "Validation failed for req %d vs doc %d attempt %d/%d: %s",
                    requirement_id, vendor_document_id, attempt + 1, retries + 1, e,
                )
                prompt = (
                    f"{base_prompt}\n\nYour previous response failed validation: {e}. "
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
            "LLM validation failed after retries for req %d vs doc %d: %s",
            requirement_id, vendor_document_id, validation_error,
        )
        return EntailmentResult(
            requirement_id=requirement_id,
            vendor_document_id=vendor_document_id,
            status=MatchStatus.AMBIGUOUS,
            confidence=0.3,
            evidence_quote=None,
            section_ref=None,
            explanation="Classification failed due to invalid structured output after retries. Manual review required.",
            reranker_score=float(top_passages[0].get("reranker_score", 0.0)) if top_passages else 0.0,
            was_negative_space=False,
        )

    def _parse_result(
        self,
        raw: dict,
        requirement_id: int,
        vendor_document_id: int,
        reranker_score: float,
        top_passages: list[dict] | None = None,
    ) -> EntailmentResult:
        """Parse and validate the LLM JSON response."""

        status_str = raw.get("status", "AMBIGUOUS").upper()
        status_map = {
            "FULL": MatchStatus.FULL,
            "PARTIAL": MatchStatus.PARTIAL,
            "NONE": MatchStatus.NONE,
            "AMBIGUOUS": MatchStatus.AMBIGUOUS,
        }
        status = status_map.get(status_str, MatchStatus.AMBIGUOUS)

        try:
            confidence = float(raw.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
        except (ValueError, TypeError):
            confidence = 0.5

        evidence = raw.get("evidence_quote") or None
        if evidence and len(evidence.strip()) < 5:
            evidence = None
        if status in (MatchStatus.FULL, MatchStatus.PARTIAL) and not evidence:
            status    = MatchStatus.AMBIGUOUS
            confidence = min(confidence, 0.5)

        explanation = raw.get("explanation", "No explanation provided.").strip() or \
                      f"Classified as {status_str} with confidence {confidence:.2f}."

        # Removed Claude's aggressive FIX-1-B regex here!

        bbox = _extract_bbox_for_quote(evidence, top_passages or [])

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
            bbox=bbox,
        )


# ─── Batch classifier ─────────────────────────────────────────────────────────

class BatchEntailmentClassifier:
    """Classifies all (requirement × vendor) pairs for a project."""

    def __init__(self):
        self.classifier = EntailmentClassifier()

    def classify_all(
        self,
        requirement_vendor_pairs: list[dict],
        sleep_between: float | None = None,
    ) -> list[EntailmentResult]:
        sleep   = sleep_between if sleep_between is not None else settings.RATE_LIMIT_SLEEP
        results = []
        total   = len(requirement_vendor_pairs)
        none_count = llm_count = 0

        for i, pair in enumerate(requirement_vendor_pairs):
            result = self.classifier.classify(
                requirement_id     = pair["requirement_id"],
                vendor_document_id = pair["vendor_document_id"],
                requirement_text   = pair["requirement_text"],
                category           = pair.get("category", "Technical"),
                criticality        = pair.get("criticality", "Mandatory"),
                top_passages       = pair["top_passages"],
                top_fused_score    = pair.get("top_fused_score", pair.get("max_reranker_score", 0.0)),
                rfp_clause_ref     = pair.get("rfp_clause_ref"),
            )
            results.append(result)

            if result.was_negative_space:
                none_count += 1
            else:
                llm_count += 1
                if i < total - 1:
                    time.sleep(sleep)

            logger.info(
                "Classified %d/%d: req=%d vendor=%d → %s (conf=%.2f) %s",
                i + 1, total,
                result.requirement_id, result.vendor_document_id,
                result.status.value, result.confidence,
                "[negative space]" if result.was_negative_space else "",
            )

        logger.info(
            "Batch complete: %d total, %d negative space, %d via LLM",
            total, none_count, llm_count,
        )
        return results

    async def classify_all_async(
        self,
        requirement_vendor_pairs: list[dict],
    ) -> list[EntailmentResult]:
        tasks = [
            self.classifier.classify_async(
                requirement_id     = pair["requirement_id"],
                vendor_document_id = pair["vendor_document_id"],
                requirement_text   = pair["requirement_text"],
                category           = pair.get("category", "Technical"),
                criticality        = pair.get("criticality", "Mandatory"),
                top_passages       = pair["top_passages"],
                top_fused_score    = pair.get("top_fused_score", pair.get("max_reranker_score", 0.0)),
                rfp_clause_ref     = pair.get("rfp_clause_ref"),
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
                results.append(EntailmentResult(
                    requirement_id     = pair["requirement_id"],
                    vendor_document_id = pair["vendor_document_id"],
                    status             = MatchStatus.AMBIGUOUS,
                    confidence         = 0.3,
                    evidence_quote     = None,
                    section_ref        = None,
                    explanation        = f"Classification failed: {result}. Manual review required.",
                    reranker_score     = float(
                        pair.get("top_passages", [{}])[0].get("reranker_score", 0.0)
                    ) if pair.get("top_passages") else 0.0,
                    was_negative_space = False,
                ))
                continue
            results.append(result)
        return results