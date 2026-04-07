"""
requirement_extractor.py
------------------------
Two-pass requirement extraction engine.

Architecture:
  Pass 1 (heuristic, instant, free):
    - Regex filter for obligation keywords: shall, must, required, mandatory, etc.
    - Eliminates ~80% of body text without any LLM call.

  Pass 2 (LLM, FAST_MODEL, cheap):
    - For surviving candidates, batch-classify with llama-3.1-8b-instant.
    - Produces: category, criticality, clause_ref, normalised_intent.
    - normalised_intent is the key field — it is what gets embedded into
      the vector store, not the raw clause text. Normalisation ensures that
      "The vendor shall ensure 24/7 system uptime" and "Continuous availability
      of 99.9% is mandated" produce similar embeddings.

  Human-in-the-loop:
    - All extracted requirements are stored with is_confirmed=False.
    - The Streamlit UI presents an editable table for the user to confirm,
      edit, or delete rows before the audit runs.
    - Only confirmed requirements are used in the compliance audit.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from backend.config import settings
from backend.database import Criticality, RequirementCategory
from services.document_parser import ChildChunk, ParsedDocument
from utils.llm_client import call_fast_batch

logger = logging.getLogger(__name__)


# ── Obligation keyword patterns ───────────────────────────────────────────────

# Primary obligation words 
PRIMARY_OBLIGATION = re.compile(
    r"\b(shall|must|is required to|are required to|is mandatory|"
    r"mandatory requirement|is obligatory|will be required|"
    r"no later than|to be provided|to be submitted)\b",
    re.IGNORECASE,
)

# Secondary obligation words 
SECONDARY_OBLIGATION = re.compile(
    r"\b(should|is expected to|are expected to|will ensure|"
    r"will provide|will include|must include|must demonstrate|"
    r"must have|must be able to|must not|shall not)\b",
    re.IGNORECASE,
)

# Negative patterns 
EXCLUSION_PATTERN = re.compile(
    r"\b(does not|do not|is not|are not|will not|cannot|"
    r"for example|e\.g\.|i\.e\.|such as|including but not|"
    r"note that|please note)\b",
    re.IGNORECASE,
)

# Minimum useful requirement length
MIN_REQUIREMENT_CHARS = 30


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ExtractedRequirement:
    """A single extracted and classified requirement."""
    raw_text: str
    normalised_intent: str
    category: RequirementCategory
    criticality: Criticality
    rfp_clause_ref: str | None
    section_title: str
    page_number: int
    confidence_score: float     # 0–1: how confident the LLM is in its classification
    is_primary: bool            # True if matched primary obligation keywords
    bbox: list[float] | None = None  # [x0, y0, x1, y1] PDF page coords for trace highlighting


# ── Main extractor ────────────────────────────────────────────────────────────

class RequirementExtractor:
    """
    Extracts and classifies mandatory requirements from parsed RFP documents.

    Usage:
        extractor = RequirementExtractor()
        requirements = extractor.extract(parsed_document)
    """

    def extract(self, parsed: ParsedDocument) -> list[ExtractedRequirement]:
        """
        Run the two-pass extraction pipeline.

        Returns a list of classified requirements ready for DB storage.
        """
        logger.info(
            "Starting requirement extraction on '%s' (%d chunks)",
            parsed.filename, len(parsed.all_chunks),
        )

        # ── Pass 1: Heuristic filter ──────────────────────────────────────
        candidates = self._pass1_filter(parsed.all_chunks)
        logger.info(
            "Pass 1 complete: %d/%d chunks passed obligation filter",
            len(candidates), len(parsed.all_chunks),
        )

        if not candidates:
            logger.warning("No obligation candidates found. Check the PDF content.")
            return []

        # ── Pass 2: LLM classification ────────────────────────────────────
        requirements = self._pass2_classify(candidates)
        logger.info(
            "Pass 2 complete: %d requirements extracted and classified",
            len(requirements),
        )

        return requirements

    # ── Pass 1: Heuristic filter ──────────────────────────────────────────────

    def _pass1_filter(self, chunks: list[ChildChunk]) -> list[dict]:
        """
        Filter chunks to obligation candidates.
        Returns enriched dicts with is_primary flag.
        """
        candidates = []

        for chunk in chunks:
            text = chunk.text

            # Skip very short chunks
            if len(text) < MIN_REQUIREMENT_CHARS:
                continue

            # Skip if exclusion pattern dominates
            if EXCLUSION_PATTERN.search(text):
                # Still include if it has a strong primary obligation
                if not PRIMARY_OBLIGATION.search(text):
                    continue

            is_primary = bool(PRIMARY_OBLIGATION.search(text))
            is_secondary = bool(SECONDARY_OBLIGATION.search(text))

            if is_primary or is_secondary:
                candidates.append({
                    "chunk": chunk,
                    "is_primary": is_primary,
                })

        return candidates

    # ── Pass 2: LLM classification ────────────────────────────────────────────

    def _pass2_classify(self, candidates: list[dict]) -> list[ExtractedRequirement]:
        """
        Batch-classify candidates using the fast LLM model.
        Processes in batches of BATCH_SIZE to respect rate limits.
        """
        batch_size = settings.BATCH_SIZE
        all_results: list[ExtractedRequirement] = []

        # Split into batches
        for batch_start in range(0, len(candidates), batch_size):
            batch = candidates[batch_start: batch_start + batch_size]
            prompts = [self._build_classification_prompt(c) for c in batch]

            logger.debug(
                "Classifying batch %d–%d of %d candidates",
                batch_start + 1, batch_start + len(batch), len(candidates),
            )

            try:
                results = call_fast_batch(
                    prompts,
                    system=self._system_prompt(),
                    max_tokens=512,
                )
                for candidate, result in zip(batch, results):
                    req = self._parse_llm_result(candidate, result)
                    if req is not None:
                        all_results.append(req)

            except Exception as e:
                logger.error(
                    "Batch classification failed for batch starting at %d: %s",
                    batch_start, e,
                )
                # Fallback: add candidates with minimal classification
                for candidate in batch:
                    req = self._fallback_classification(candidate)
                    all_results.append(req)

        return all_results

    def _system_prompt(self) -> str:
        return (
            "You are a legal compliance expert specialising in government tenders and RFPs. "
            "Extract and classify mandatory requirements precisely. "
            "Always respond with valid JSON only — no markdown, no preamble, no explanation."
        )

    def _build_classification_prompt(self, candidate: dict) -> str:
        chunk: ChildChunk = candidate["chunk"]
        return f"""Classify this RFP clause as a compliance requirement.

CLAUSE TEXT:
{chunk.text}

SECTION: {chunk.section_title}
CLAUSE REF: {chunk.clause_ref or "unknown"}

Respond with ONLY this JSON structure:
{{
  "category": "Technical" | "Legal" | "Financial" | "Administrative",
  "criticality": "Mandatory" | "Recommended" | "Informational",
  "clause_ref": "<extracted ref like 4.2.1 or null>",
  "normalised_intent": "<1 clear sentence: exactly what must the vendor DO or PROVIDE?>",
  "confidence": <0.0 to 1.0>,
  "is_genuine_requirement": <true | false>
}}

Rules:
- normalised_intent must be actionable (start with "Vendor must..." or "Bidder must...")
- If this is not a genuine requirement (e.g. it's explanatory text), set is_genuine_requirement=false
- confidence reflects how certain you are this is a mandatory compliance item"""

    def _parse_llm_result(
        self, candidate: dict, result: dict
    ) -> ExtractedRequirement | None:
        """Parse the LLM JSON result into an ExtractedRequirement."""
        chunk: ChildChunk = candidate["chunk"]

        # Skip if LLM says it's not a genuine requirement
        if not result.get("is_genuine_requirement", True):
            return None

        # Skip low confidence results
        confidence = float(result.get("confidence", 0.5))
        if confidence < 0.3:
            return None

        # Map category string to enum
        category_str = result.get("category", "Technical")
        try:
            category = RequirementCategory(category_str)
        except ValueError:
            category = RequirementCategory.TECHNICAL

        # Map criticality string to enum
        criticality_str = result.get("criticality", "Mandatory")
        try:
            criticality = Criticality(criticality_str)
        except ValueError:
            criticality = Criticality.MANDATORY

        normalised = result.get("normalised_intent", "").strip()
        if not normalised:
            normalised = chunk.text[:200]

        return ExtractedRequirement(
            raw_text=chunk.text,
            normalised_intent=normalised,
            category=category,
            criticality=criticality,
            rfp_clause_ref=result.get("clause_ref") or chunk.clause_ref,
            section_title=chunk.section_title,
            page_number=chunk.page_number,
            confidence_score=confidence,
            bbox=chunk.bbox,
            is_primary=candidate["is_primary"],
        )

    def _fallback_classification(self, candidate: dict) -> ExtractedRequirement:
        """Minimal classification when LLM call fails. Keeps data, marks as unclassified."""
        chunk: ChildChunk = candidate["chunk"]
        return ExtractedRequirement(
            raw_text=chunk.text,
            normalised_intent=f"Vendor must comply with: {chunk.text[:150]}",
            category=RequirementCategory.TECHNICAL,
            criticality=Criticality.MANDATORY if candidate["is_primary"] else Criticality.RECOMMENDED,
            rfp_clause_ref=chunk.clause_ref,
            section_title=chunk.section_title,
            page_number=chunk.page_number,
            confidence_score=0.4,
            bbox=chunk.bbox,
            is_primary=candidate["is_primary"],
        )


# ── Admin eligibility checker ─────────────────────────────────────────────────

# Documents typically required in public tenders (configurable)
ADMIN_CHECKLIST_ITEMS = [
    ("Tax clearance certificate", [
        r"tax clearance", r"sars certificate", r"tax compliance",
    ]),
    ("Company registration", [
        r"company registration", r"cipc", r"registration number", r"reg\.?\s*no",
    ]),
    ("VAT registration", [
        r"vat\s*(?:registration|number|no\.?|reg\.?)", r"value.added tax",
    ]),
    ("Proof of insurance", [
        r"insurance certificate", r"proof of insurance", r"liability insurance",
        r"professional indemnity",
    ]),
    ("BEE/BBBEE certificate", [
        r"b-?bbee", r"broad.based black economic", r"bee certificate",
        r"level \d+ contributor",
    ]),
    ("Signed declaration", [
        r"declaration of interest", r"signed declaration", r"conflict of interest",
    ]),
    ("Company letterhead", [
        r"company letterhead", r"official letterhead", r"on letterhead",
    ]),
    ("Bank confirmation letter", [
        r"bank(?:ers?)? confirmation", r"bank letter", r"banking details",
    ]),
    ("Audited financial statements", [
        r"audited financial", r"annual financial statements", r"auditor.s report",
    ]),
]


@dataclass
class AdminCheckResult:
    item_name: str
    status: str          # FOUND / MISSING / UNCLEAR
    page_reference: str | None
    matched_text: str | None


def check_admin_eligibility(
    parsed: ParsedDocument,
) -> list[AdminCheckResult]:
    """
    Scan a proposal for required administrative documents.
    Fast, deterministic — no LLM needed.

    Directly addresses the real-world stat that ~40% of bids are rejected
    for admin non-compliance before technical evaluation begins.
    """
    full_text = " ".join(c.text for c in parsed.all_chunks)
    full_text_lower = full_text.lower()

    # Build page-aware index for better references
    page_texts: dict[int, str] = {}
    for chunk in parsed.all_chunks:
        page_texts.setdefault(chunk.page_number, "")
        page_texts[chunk.page_number] += " " + chunk.text.lower()

    results: list[AdminCheckResult] = []

    for item_name, patterns in ADMIN_CHECKLIST_ITEMS:
        found = False
        matched_text = None
        page_ref = None

        for pattern in patterns:
            regex = re.compile(pattern, re.IGNORECASE)

            # Search full text first
            match = regex.search(full_text)
            if match:
                start = max(0, match.start() - 40)
                end = min(len(full_text), match.end() + 60)
                matched_text = full_text[start:end].strip()

                # Find the page
                for page_num, page_text in page_texts.items():
                    if regex.search(page_text):
                        page_ref = f"Page {page_num}"
                        break

                found = True
                break

        results.append(AdminCheckResult(
            item_name=item_name,
            status="FOUND" if found else "MISSING",
            page_reference=page_ref,
            matched_text=matched_text,
        ))

    found_count = sum(1 for r in results if r.status == "FOUND")
    logger.info(
        "Admin check complete: %d/%d items found for '%s'",
        found_count, len(results), parsed.filename,
    )

    return results


# ── Module-level convenience ──────────────────────────────────────────────────

def extract_requirements(parsed: ParsedDocument) -> list[ExtractedRequirement]:
    """Extract requirements from a parsed document. Module-level convenience."""
    return RequirementExtractor().extract(parsed)