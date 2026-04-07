"""
scorer.py
---------
Compliance scoring engine.

Scoring formula (Design Document justification):
  ComplianceScore = weighted_sum(requirement_scores) / max_possible × 100

  Weight by criticality × status:
    Mandatory + FULL     = 1.0
    Mandatory + PARTIAL  = 0.5
    Mandatory + AMBIGUOUS = 0.3
    Mandatory + NONE     = 0.0
    Recommended + FULL   = 0.5  (half weight)
    Recommended + PARTIAL = 0.25
    Recommended + NONE   = 0.0
    Informational        = 0.0  (not scored)

  RiskScore = Σ(severity_weight × finding_count)
    Critical = 4, High = 3, Medium = 2, Low = 1

  Status colour:
    Green:  compliance >= 75% AND no Critical risks AND ≤ 1 High risk
    Amber:  compliance >= 50% OR (compliance >= 75% with risks)
    Red:    compliance < 50% OR any Critical risk
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.database import Criticality, MatchStatus, RiskSeverity

logger = logging.getLogger(__name__)


# ── Weight tables ─────────────────────────────────────────────────────────────

STATUS_WEIGHTS: dict[tuple[Criticality, MatchStatus], float] = {
    (Criticality.MANDATORY, MatchStatus.FULL):       1.0,
    (Criticality.MANDATORY, MatchStatus.PARTIAL):    0.5,
    (Criticality.MANDATORY, MatchStatus.AMBIGUOUS):  0.3,
    (Criticality.MANDATORY, MatchStatus.NONE):       0.0,
    (Criticality.MANDATORY, MatchStatus.PENDING):    0.0,
    (Criticality.RECOMMENDED, MatchStatus.FULL):     0.5,
    (Criticality.RECOMMENDED, MatchStatus.PARTIAL):  0.25,
    (Criticality.RECOMMENDED, MatchStatus.AMBIGUOUS):0.15,
    (Criticality.RECOMMENDED, MatchStatus.NONE):     0.0,
    (Criticality.RECOMMENDED, MatchStatus.PENDING):  0.0,
    (Criticality.INFORMATIONAL, MatchStatus.FULL):   0.0,
    (Criticality.INFORMATIONAL, MatchStatus.PARTIAL):0.0,
    (Criticality.INFORMATIONAL, MatchStatus.NONE):   0.0,
    (Criticality.INFORMATIONAL, MatchStatus.AMBIGUOUS):0.0,
    (Criticality.INFORMATIONAL, MatchStatus.PENDING):0.0,
}

MAX_WEIGHTS: dict[Criticality, float] = {
    Criticality.MANDATORY:    1.0,
    Criticality.RECOMMENDED:  0.5,
    Criticality.INFORMATIONAL:0.0,
}

SEVERITY_WEIGHTS: dict[RiskSeverity, float] = {
    RiskSeverity.CRITICAL: 4.0,
    RiskSeverity.HIGH:     3.0,
    RiskSeverity.MEDIUM:   2.0,
    RiskSeverity.LOW:      1.0,
}


# ── Score result ──────────────────────────────────────────────────────────────

@dataclass
class VendorScore:
    vendor_document_id: int
    vendor_name: str
    compliance_score: float          # 0–100
    risk_score: float                # weighted sum of risk findings
    status_colour: str               # green / amber / red
    mandatory_full: int
    mandatory_partial: int
    mandatory_none: int
    mandatory_ambiguous: int
    recommended_full: int
    total_requirements: int
    critical_risks: int
    high_risks: int
    medium_risks: int
    low_risks: int
    total_risks: int
    breakdown: dict = field(default_factory=dict)


# ── Scorer ────────────────────────────────────────────────────────────────────

class ComplianceScorer:
    """
    Computes compliance and risk scores for each vendor.

    Usage:
        scorer = ComplianceScorer()
        scores = scorer.score_all(
            vendors=[{"document_id": 2, "vendor_name": "Acme Corp"}],
            matches=[...],      # list of Match ORM objects or dicts
            risk_findings=[...] # list of RiskFinding ORM objects or dicts
        )
    """

    def score_all(
        self,
        vendors: list[dict],
        requirements: list[dict],
        matches: list[dict],
        risk_findings: list[dict],
    ) -> list[VendorScore]:
        """Score all vendors and return sorted list (highest compliance first)."""
        scores = []
        for vendor in vendors:
            doc_id = vendor["document_id"]
            vendor_matches = [m for m in matches if m["vendor_document_id"] == doc_id]
            vendor_risks = [r for r in risk_findings if r["vendor_document_id"] == doc_id]
            score = self._score_vendor(
                vendor_document_id=doc_id,
                vendor_name=vendor.get("vendor_name", f"Vendor {doc_id}"),
                requirements=requirements,
                matches=vendor_matches,
                risk_findings=vendor_risks,
            )
            scores.append(score)
            logger.info(
                "Scored vendor '%s': compliance=%.1f%% risk=%.1f colour=%s",
                score.vendor_name,
                score.compliance_score,
                score.risk_score,
                score.status_colour,
            )

        # Sort: highest compliance first, then lowest risk
        scores.sort(key=lambda s: (-s.compliance_score, s.risk_score))
        return scores

    def _score_vendor(
        self,
        vendor_document_id: int,
        vendor_name: str,
        requirements: list[dict],
        matches: list[dict],
        risk_findings: list[dict],
    ) -> VendorScore:
        """Compute score for a single vendor."""

        # Build match lookup: requirement_id → match
        match_lookup: dict[int, dict] = {
            m["requirement_id"]: m for m in matches
        }

        # Compliance scoring
        earned = 0.0
        possible = 0.0
        mandatory_full = mandatory_partial = mandatory_none = mandatory_ambiguous = 0
        recommended_full = 0

        for req in requirements:
            req_id = req["id"]
            criticality_str = req.get("criticality", "Mandatory")
            try:
                criticality = Criticality(criticality_str)
            except ValueError:
                criticality = Criticality.MANDATORY

            max_w = MAX_WEIGHTS.get(criticality, 0.0)
            possible += max_w

            match = match_lookup.get(req_id)
            if match:
                status_str = match.get("status", "NONE")
                try:
                    status = MatchStatus(status_str)
                except ValueError:
                    status = MatchStatus.NONE
            else:
                status = MatchStatus.NONE

            weight = STATUS_WEIGHTS.get((criticality, status), 0.0)
            earned += weight

            # Counters for breakdown
            if criticality == Criticality.MANDATORY:
                if status == MatchStatus.FULL:
                    mandatory_full += 1
                elif status == MatchStatus.PARTIAL:
                    mandatory_partial += 1
                elif status == MatchStatus.AMBIGUOUS:
                    mandatory_ambiguous += 1
                else:
                    mandatory_none += 1
            elif criticality == Criticality.RECOMMENDED and status == MatchStatus.FULL:
                recommended_full += 1

        compliance_score = (earned / possible * 100) if possible > 0 else 0.0
        compliance_score = round(compliance_score, 1)

        # Risk scoring
        critical_risks = sum(1 for r in risk_findings if r.get("severity") == RiskSeverity.CRITICAL.value or r.get("severity") == "Critical")
        high_risks = sum(1 for r in risk_findings if r.get("severity") in (RiskSeverity.HIGH.value, "High"))
        medium_risks = sum(1 for r in risk_findings if r.get("severity") in (RiskSeverity.MEDIUM.value, "Medium"))
        low_risks = sum(1 for r in risk_findings if r.get("severity") in (RiskSeverity.LOW.value, "Low"))

        risk_score = (
            critical_risks * SEVERITY_WEIGHTS[RiskSeverity.CRITICAL]
            + high_risks * SEVERITY_WEIGHTS[RiskSeverity.HIGH]
            + medium_risks * SEVERITY_WEIGHTS[RiskSeverity.MEDIUM]
            + low_risks * SEVERITY_WEIGHTS[RiskSeverity.LOW]
        )

        # Status colour
        status_colour = self._compute_colour(
            compliance_score, critical_risks, high_risks
        )

        return VendorScore(
            vendor_document_id=vendor_document_id,
            vendor_name=vendor_name,
            compliance_score=compliance_score,
            risk_score=round(risk_score, 1),
            status_colour=status_colour,
            mandatory_full=mandatory_full,
            mandatory_partial=mandatory_partial,
            mandatory_none=mandatory_none,
            mandatory_ambiguous=mandatory_ambiguous,
            recommended_full=recommended_full,
            total_requirements=len(requirements),
            critical_risks=critical_risks,
            high_risks=high_risks,
            medium_risks=medium_risks,
            low_risks=low_risks,
            total_risks=len(risk_findings),
            breakdown={
                "earned_weight": round(earned, 2),
                "possible_weight": round(possible, 2),
                "match_count": len(matches),
            },
        )

    def _compute_colour(
        self,
        compliance: float,
        critical_risks: int,
        high_risks: int,
    ) -> str:
        """Determine traffic-light colour from scores."""
        if critical_risks > 0 or compliance < 50:
            return "red"
        if compliance >= 75 and critical_risks == 0 and high_risks <= 1:
            return "green"
        return "amber"


# ── Module-level convenience ──────────────────────────────────────────────────

def score_vendors(
    vendors: list[dict],
    requirements: list[dict],
    matches: list[dict],
    risk_findings: list[dict],
) -> list[VendorScore]:
    """Module-level convenience wrapper."""
    return ComplianceScorer().score_all(vendors, requirements, matches, risk_findings)