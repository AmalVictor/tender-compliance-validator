"""
risk_patterns.py
----------------
Deterministic regex pattern library for risk detection.

This is the first layer of the hybrid risk engine:
  Layer 1 (this file): Fast, zero-cost regex scan → candidates
  Layer 2 (risk_detector.py): LLM evaluation of candidates → confirmed findings

Design choice: regex first, LLM second.
  - Regex is deterministic and auditable — you can show exactly which pattern
    fired and why. This matters in a legal/compliance context.
  - LLM is probabilistic but handles nuance and context.
  - Together: precision from LLM, recall and speed from regex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.database import RiskSeverity, RiskType


@dataclass
class RiskPattern:
    """A single risk pattern definition."""
    name: str
    pattern: re.Pattern
    risk_type: RiskType
    default_severity: RiskSeverity
    description: str


# ── Risk pattern definitions ──────────────────────────────────────────────────
# Each pattern catches a class of risky language in vendor proposals.
# Severity defaults are overridden by the LLM evaluation layer.

RISK_PATTERNS: list[RiskPattern] = [

    # Liability limitations
    RiskPattern(
        name="Limited liability",
        pattern=re.compile(
            r"\b(limit(?:ed|ation|s)? of liability|liability.{0,20}cap(?:ped)?|"
            r"in no event.{0,30}liable|maximum liability|aggregate liability)\b",
            re.IGNORECASE,
        ),
        risk_type=RiskType.LIABILITY_CAP,
        default_severity=RiskSeverity.HIGH,
        description="Vendor attempts to cap or limit their financial liability.",
    ),

    RiskPattern(
        name="No consequential damages",
        pattern=re.compile(
            r"\b(no consequential|no indirect|no incidental|no special damages|"
            r"excludes.{0,20}(?:consequential|indirect|punitive))\b",
            re.IGNORECASE,
        ),
        risk_type=RiskType.LIABILITY_CAP,
        default_severity=RiskSeverity.HIGH,
        description="Vendor excludes consequential or indirect damages from liability.",
    ),

    # Subject to change
    RiskPattern(
        name="Subject to change",
        pattern=re.compile(
            r"\b(subject to change|may be modified|may be updated|"
            r"reserves the right to change|at our discretion|"
            r"without prior notice)\b",
            re.IGNORECASE,
        ),
        risk_type=RiskType.SCOPE_CREEP,
        default_severity=RiskSeverity.MEDIUM,
        description="Vendor reserves right to change terms or deliverables unilaterally.",
    ),

    # Additional fees
    RiskPattern(
        name="Additional fees",
        pattern=re.compile(
            r"\b(additional fees? may apply|additional charges?|"
            r"at additional cost|extra charges?|surcharge|"
            r"subject to additional pricing|fees? are subject to)\b",
            re.IGNORECASE,
        ),
        risk_type=RiskType.PRICE_CHANGE,
        default_severity=RiskSeverity.MEDIUM,
        description="Vendor indicates costs beyond quoted price may be incurred.",
    ),

    RiskPattern(
        name="Price escalation",
        pattern=re.compile(
            r"\b(price.{0,20}escalat|cost.{0,20}escalat|inflation.{0,20}adjust|"
            r"CPI.{0,20}adjust|annually.{0,20}increas|rate card.{0,20}change)\b",
            re.IGNORECASE,
        ),
        risk_type=RiskType.PRICE_CHANGE,
        default_severity=RiskSeverity.MEDIUM,
        description="Vendor includes price escalation clauses.",
    ),

    # Vague/weak commitments
    RiskPattern(
        name="Best efforts only",
        pattern=re.compile(
            r"\b(best efforts?|reasonable efforts?|commercially reasonable|"
            r"endeavour to|shall endeavour|will endeavour|attempt to)\b",
            re.IGNORECASE,
        ),
        risk_type=RiskType.OBLIGATION_WEAKENING,
        default_severity=RiskSeverity.MEDIUM,
        description=(
            "Vendor uses 'best efforts' language instead of firm commitments. "
            "Courts treat this as a lower standard than 'shall' language."
        ),
    ),

    RiskPattern(
        name="Subject to availability",
        pattern=re.compile(
            r"\b(subject to availability|as available|where available|"
            r"depending on availability|resource permitting|"
            r"subject to resource availability)\b",
            re.IGNORECASE,
        ),
        risk_type=RiskType.OBLIGATION_WEAKENING,
        default_severity=RiskSeverity.HIGH,
        description="Vendor qualifies delivery with availability caveats — undermines SLA.",
    ),

    RiskPattern(
        name="Pending approval",
        pattern=re.compile(
            r"\b(pending(?:.{0,20})approval|subject to.{0,20}approval|"
            r"pending.{0,20}confirmation|conditional(?:.{0,20})on|"
            r"subject to.{0,20}review)\b",
            re.IGNORECASE,
        ),
        risk_type=RiskType.OBLIGATION_WEAKENING,
        default_severity=RiskSeverity.MEDIUM,
        description="Commitments are conditional on internal approvals not yet obtained.",
    ),

    # Exit/termination clauses
    RiskPattern(
        name="Unilateral termination",
        pattern=re.compile(
            r"\b(terminate.{0,30}(?:at will|without cause|for convenience)|"
            r"right to terminate|may terminate.{0,20}notice|"
            r"termination for convenience)\b",
            re.IGNORECASE,
        ),
        risk_type=RiskType.EXIT_CLAUSE,
        default_severity=RiskSeverity.HIGH,
        description="Vendor retains right to terminate contract without cause.",
    ),

    RiskPattern(
        name="Force majeure overreach",
        pattern=re.compile(
            r"\b(force majeure|act of god|beyond.{0,20}reasonable control|"
            r"unforeseeable circumstances|extraordinary events?)\b",
            re.IGNORECASE,
        ),
        risk_type=RiskType.EXIT_CLAUSE,
        default_severity=RiskSeverity.LOW,
        description="Force majeure clause — standard but should not be overly broad.",
    ),

    # Time and materials risk
    RiskPattern(
        name="Time and materials",
        pattern=re.compile(
            r"\b(time and materials?|T&M|time[- ]and[- ]materials?|"
            r"cost[- ]plus|actual costs? plus)\b",
            re.IGNORECASE,
        ),
        risk_type=RiskType.PRICE_CHANGE,
        default_severity=RiskSeverity.MEDIUM,
        description=(
            "T&M pricing model creates open-ended cost exposure. "
            "RFPs typically require fixed-price commitments."
        ),
    ),

    # Intellectual property risks
    RiskPattern(
        name="IP retention by vendor",
        pattern=re.compile(
            r"\b(vendor.{0,30}retains?.{0,20}(?:IP|intellectual property|ownership)|"
            r"all IP.{0,20}remain.{0,20}(?:with|owned by) vendor|"
            r"intellectual property.{0,20}not transfer)\b",
            re.IGNORECASE,
        ),
        risk_type=RiskType.OBLIGATION_WEAKENING,
        default_severity=RiskSeverity.CRITICAL,
        description="Vendor retains IP ownership — deliverables may not belong to buyer.",
    ),

    # Vague performance
    RiskPattern(
        name="Vague performance obligation",
        pattern=re.compile(
            r"\b(as deemed appropriate|at our sole discretion|"
            r"in our judgment|as we see fit|may.{0,20}decide not to|"
            r"industry standard.{0,20}(?:support|service))\b",
            re.IGNORECASE,
        ),
        risk_type=RiskType.VAGUE_COMMITMENT,
        default_severity=RiskSeverity.MEDIUM,
        description="Vendor uses vague discretionary language for key obligations.",
    ),
]

# ── Pattern lookup by name ────────────────────────────────────────────────────

PATTERN_BY_NAME: dict[str, RiskPattern] = {p.name: p for p in RISK_PATTERNS}


def scan_text(text: str) -> list[dict]:
    """
    Scan text against all risk patterns.

    Returns a list of matches: {pattern, matched_phrase, start, end, context}
    Context includes 150 chars before and after the match for LLM evaluation.
    """
    hits = []
    for risk_pattern in RISK_PATTERNS:
        for match in risk_pattern.pattern.finditer(text):
            start = match.start()
            end = match.end()

            # Extract context window (3 sentences each side approx.)
            ctx_start = max(0, start - 200)
            ctx_end = min(len(text), end + 200)
            context = text[ctx_start:ctx_end].strip()

            hits.append({
                "pattern": risk_pattern,
                "matched_phrase": match.group().strip(),
                "char_start": start,
                "char_end": end,
                "context": context,
            })

    # Deduplicate overlapping matches from different patterns
    hits = _deduplicate_hits(hits)
    return hits


def _deduplicate_hits(hits: list[dict]) -> list[dict]:
    """
    Remove hits that overlap with a higher-severity hit in the same region.
    Keeps the highest-severity match when two patterns fire within 50 chars.
    """
    severity_rank = {
        RiskSeverity.CRITICAL: 4,
        RiskSeverity.HIGH: 3,
        RiskSeverity.MEDIUM: 2,
        RiskSeverity.LOW: 1,
    }

    unique = []
    for hit in hits:
        overlapping = False
        for existing in unique:
            # Check if hits overlap (within 50 chars of each other)
            if abs(hit["char_start"] - existing["char_start"]) < 50:
                # Keep the higher severity one
                hit_rank = severity_rank.get(hit["pattern"].default_severity, 0)
                existing_rank = severity_rank.get(existing["pattern"].default_severity, 0)
                if hit_rank > existing_rank:
                    unique.remove(existing)
                    unique.append(hit)
                overlapping = True
                break
        if not overlapping:
            unique.append(hit)

    return unique