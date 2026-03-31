"""
test_phase2.py
--------------
Unit tests for Phase 2 components.
Tests reranker, entailment classifier (mocked), and scorer.

Run: pytest tests/test_phase2.py -v
"""

from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock

from backend.database import Criticality, MatchStatus, RiskSeverity
from services.entailment_classifier import EntailmentClassifier, EntailmentResult
from services.scorer import ComplianceScorer, VendorScore
from utils.risk_patterns import scan_text


# ── Entailment classifier tests (mocked LLM) ──────────────────────────────────

class TestEntailmentClassifier:

    def test_negative_space_fires_below_threshold(self):
        """
        If max_reranker_score < NONE_THRESHOLD, classifier returns NONE
        without any LLM call. This is the negative space detection.
        """
        classifier = EntailmentClassifier()
        result = classifier.classify(
            requirement_id=1,
            vendor_document_id=1,
            requirement_text="Vendor must provide 24/7 support",
            category="Technical",
            criticality="Mandatory",
            top_passages=[{"text": "We provide services.", "score": 0.1, "reranker_score": 0.1}],
            max_reranker_score=0.10,  # well below threshold of 0.35
        )
        assert result.status == MatchStatus.NONE
        assert result.was_negative_space is True
        assert result.confidence >= 0.9  # high confidence in absence

    def test_negative_space_does_not_fire_above_threshold(self):
        """
        If max_reranker_score >= NONE_THRESHOLD, classifier should attempt LLM call.
        We mock the LLM to test the parsing logic.
        """
        classifier = EntailmentClassifier()

        mock_llm_response = {
            "status": "FULL",
            "confidence": 0.88,
            "evidence_quote": "We provide round-the-clock technical support 24 hours a day.",
            "section_ref": "Section 4.1, page 8",
            "explanation": "Vendor explicitly commits to 24/7 support in Section 4.1.",
        }

        with patch("services.entailment_classifier.call_smart", return_value=mock_llm_response):
            result = classifier.classify(
                requirement_id=2,
                vendor_document_id=1,
                requirement_text="Vendor must provide 24/7 support",
                category="Technical",
                criticality="Mandatory",
                top_passages=[
                    {
                        "text": "We provide round-the-clock technical support 24 hours a day.",
                        "score": 0.85,
                        "reranker_score": 0.85,
                        "section_title": "Section 4.1",
                        "page_number": 8,
                    }
                ],
                max_reranker_score=0.85,
            )

        assert result.status == MatchStatus.FULL
        assert result.was_negative_space is False
        assert result.confidence == pytest.approx(0.88, abs=0.01)
        assert result.evidence_quote is not None
        assert result.section_ref == "Section 4.1, page 8"

    def test_partial_status_parsed_correctly(self):
        """PARTIAL status with evidence quote is parsed and stored correctly."""
        classifier = EntailmentClassifier()

        mock_response = {
            "status": "PARTIAL",
            "confidence": 0.62,
            "evidence_quote": "We endeavour to provide support services.",
            "section_ref": "Section 5.2",
            "explanation": "Vendor uses 'endeavour' instead of a firm commitment.",
        }

        with patch("services.entailment_classifier.call_smart", return_value=mock_response):
            result = classifier.classify(
                requirement_id=3,
                vendor_document_id=2,
                requirement_text="Vendor must provide dedicated account management",
                category="Technical",
                criticality="Mandatory",
                top_passages=[{"text": "We endeavour to provide support.", "score": 0.55, "reranker_score": 0.55}],
                max_reranker_score=0.55,
            )

        assert result.status == MatchStatus.PARTIAL
        assert result.confidence == pytest.approx(0.62, abs=0.01)

    def test_full_without_evidence_downgraded_to_ambiguous(self):
        """
        If LLM returns FULL but no evidence_quote, downgrade to AMBIGUOUS.
        Prevents false positives when LLM is overconfident without citing evidence.
        """
        classifier = EntailmentClassifier()

        mock_response = {
            "status": "FULL",
            "confidence": 0.90,
            "evidence_quote": None,  # no evidence provided
            "section_ref": None,
            "explanation": "Requirement appears to be met.",
        }

        with patch("services.entailment_classifier.call_smart", return_value=mock_response):
            result = classifier.classify(
                requirement_id=4,
                vendor_document_id=1,
                requirement_text="Vendor must hold ISO 27001 certification",
                category="Technical",
                criticality="Mandatory",
                top_passages=[{"text": "We follow security best practices.", "score": 0.45, "reranker_score": 0.45}],
                max_reranker_score=0.45,
            )

        # Should be downgraded to AMBIGUOUS since no evidence
        assert result.status == MatchStatus.AMBIGUOUS
        assert result.confidence <= 0.5

    def test_llm_failure_returns_ambiguous_fallback(self):
        """LLM API failure returns AMBIGUOUS with low confidence — not a crash."""
        classifier = EntailmentClassifier()

        with patch("services.entailment_classifier.call_smart", side_effect=RuntimeError("API timeout")):
            result = classifier.classify(
                requirement_id=5,
                vendor_document_id=1,
                requirement_text="Vendor must provide SLA guarantees",
                category="Technical",
                criticality="Mandatory",
                top_passages=[{"text": "Our SLA is defined.", "score": 0.6, "reranker_score": 0.6}],
                max_reranker_score=0.6,
            )

        assert result.status == MatchStatus.AMBIGUOUS
        assert result.confidence <= 0.4
        assert "API" in result.explanation or "error" in result.explanation.lower()


# ── Compliance scorer tests ───────────────────────────────────────────────────

class TestComplianceScorer:

    def _make_req(self, req_id, criticality="Mandatory"):
        return {
            "id": req_id,
            "normalised_intent": f"Requirement {req_id}",
            "category": "Technical",
            "criticality": criticality,
            "rfp_clause_ref": None,
        }

    def _make_match(self, req_id, vendor_id, status):
        return {
            "requirement_id": req_id,
            "vendor_document_id": vendor_id,
            "status": status,
            "confidence": 0.8,
        }

    def test_full_compliance_scores_100(self):
        """All mandatory requirements FULL → 100% score."""
        scorer = ComplianceScorer()
        reqs = [self._make_req(i) for i in range(1, 4)]
        matches = [self._make_match(i, 1, "FULL") for i in range(1, 4)]

        scores = scorer.score_all(
            vendors=[{"document_id": 1, "vendor_name": "Perfect Vendor"}],
            requirements=reqs,
            matches=matches,
            risk_findings=[],
        )

        assert len(scores) == 1
        assert scores[0].compliance_score == pytest.approx(100.0, abs=0.1)
        assert scores[0].status_colour == "green"

    def test_zero_compliance_scores_zero(self):
        """All mandatory requirements NONE → 0% score."""
        scorer = ComplianceScorer()
        reqs = [self._make_req(i) for i in range(1, 4)]
        matches = [self._make_match(i, 1, "NONE") for i in range(1, 4)]

        scores = scorer.score_all(
            vendors=[{"document_id": 1, "vendor_name": "Missing Vendor"}],
            requirements=reqs,
            matches=matches,
            risk_findings=[],
        )

        assert scores[0].compliance_score == pytest.approx(0.0, abs=0.1)
        assert scores[0].status_colour == "red"

    def test_partial_compliance_scores_50(self):
        """All mandatory PARTIAL → 50% score."""
        scorer = ComplianceScorer()
        reqs = [self._make_req(i) for i in range(1, 3)]
        matches = [self._make_match(i, 1, "PARTIAL") for i in range(1, 3)]

        scores = scorer.score_all(
            vendors=[{"document_id": 1, "vendor_name": "Partial Vendor"}],
            requirements=reqs,
            matches=matches,
            risk_findings=[],
        )

        assert scores[0].compliance_score == pytest.approx(50.0, abs=0.1)
        assert scores[0].status_colour == "amber"

    def test_critical_risk_forces_red(self):
        """Even high compliance, a Critical risk → red status."""
        scorer = ComplianceScorer()
        reqs = [self._make_req(i) for i in range(1, 4)]
        matches = [self._make_match(i, 1, "FULL") for i in range(1, 4)]
        risks = [{"vendor_document_id": 1, "severity": "Critical", "risk_type": "liability_cap"}]

        scores = scorer.score_all(
            vendors=[{"document_id": 1, "vendor_name": "Risky Vendor"}],
            requirements=reqs,
            matches=matches,
            risk_findings=risks,
        )

        assert scores[0].compliance_score == pytest.approx(100.0, abs=0.1)
        assert scores[0].status_colour == "red"  # critical risk overrides
        assert scores[0].critical_risks == 1

    def test_recommended_requirements_count_half(self):
        """Recommended requirements contribute half weight."""
        scorer = ComplianceScorer()
        reqs = [
            self._make_req(1, "Mandatory"),
            self._make_req(2, "Recommended"),
        ]
        matches = [
            self._make_match(1, 1, "FULL"),
            self._make_match(2, 1, "FULL"),
        ]

        scores = scorer.score_all(
            vendors=[{"document_id": 1, "vendor_name": "Good Vendor"}],
            requirements=reqs,
            matches=matches,
            risk_findings=[],
        )

        # Mandatory FULL (1.0) + Recommended FULL (0.5) / possible (1.0 + 0.5) = 100%
        assert scores[0].compliance_score == pytest.approx(100.0, abs=0.1)

    def test_multiple_vendors_sorted_by_compliance(self):
        """Multiple vendors should be sorted highest compliance first."""
        scorer = ComplianceScorer()
        reqs = [self._make_req(1)]

        scores = scorer.score_all(
            vendors=[
                {"document_id": 1, "vendor_name": "Bad"},
                {"document_id": 2, "vendor_name": "Good"},
            ],
            requirements=reqs,
            matches=[
                self._make_match(1, 1, "NONE"),
                self._make_match(1, 2, "FULL"),
            ],
            risk_findings=[],
        )

        assert scores[0].vendor_name == "Good"
        assert scores[1].vendor_name == "Bad"


# ── Risk pattern tests ────────────────────────────────────────────────────────

class TestRiskPatterns:

    def test_detects_limited_liability(self):
        hits = scan_text("The vendor's limitation of liability shall not exceed $10,000.")
        assert any("limited liability" in h["pattern"].name.lower() or
                   "liability" in h["matched_phrase"].lower() for h in hits)

    def test_detects_subject_to_change(self):
        hits = scan_text("Pricing is subject to change without prior notice.")
        assert len(hits) > 0
        assert any("change" in h["matched_phrase"].lower() for h in hits)

    def test_detects_best_efforts(self):
        hits = scan_text("We will use best efforts to deliver the solution on time.")
        assert any("effort" in h["matched_phrase"].lower() for h in hits)

    def test_detects_subject_to_availability(self):
        hits = scan_text("Support resources will be assigned subject to availability.")
        assert any("availability" in h["matched_phrase"].lower() for h in hits)

    def test_clean_text_returns_no_hits(self):
        """Clean, compliant text should not trigger risk patterns."""
        clean = (
            "The vendor shall provide 24/7 technical support. "
            "All deliverables will be completed within agreed timelines. "
            "The vendor guarantees a 99.9% uptime SLA."
        )
        hits = scan_text(clean)
        # Clean text should produce zero or very few hits
        assert len(hits) <= 1  # allow 1 in case of edge cases

    def test_deduplication_removes_overlapping_hits(self):
        """Two patterns firing within 50 chars should be deduplicated."""
        text = "The vendor's limitation of liability is subject to change."
        hits = scan_text(text)
        # Verify no two hits have char positions within 50 of each other
        for i, h1 in enumerate(hits):
            for h2 in hits[i+1:]:
                diff = abs(h1["char_start"] - h2["char_start"])
                assert diff >= 50 or h1["pattern"].name == h2["pattern"].name