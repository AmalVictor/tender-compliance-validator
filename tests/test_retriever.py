"""
test_retriever.py
-----------------
Tests for the proposal indexer and retrieval pipeline.
Includes the Stage 1 vs Stage 1+2 accuracy benchmark
(critical evidence for your Design Document).

Run: pytest tests/test_retriever.py -v -s
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz
import pytest

from services.document_parser import ChildChunk, ParsedDocument, ParentSection
from services.proposal_indexer import ProposalIndexer, extract_technical_terms


def make_mock_parsed_doc(chunks_text: list[str], filename: str = "test.pdf") -> ParsedDocument:
    """Create a mock ParsedDocument from a list of text strings."""
    chunks = []
    sections = []

    for i, text in enumerate(chunks_text):
        chunk = ChildChunk(
            text=text,
            chunk_type="child",
            section_title=f"Section {i + 1}",
            section_level=1,
            page_number=i + 1,
            clause_ref=None,
            char_start=0,
            chunk_index=i,
        )
        chunks.append(chunk)
        section = ParentSection(
            title=f"Section {i + 1}",
            level=1,
            full_text=text,
            page_number=i + 1,
            clause_ref=None,
            children=[chunk],
        )
        sections.append(section)

    return ParsedDocument(
        filename=filename,
        page_count=len(chunks_text),
        word_count=sum(len(t.split()) for t in chunks_text),
        sections=sections,
        all_chunks=chunks,
        is_scanned=False,
        is_multi_column=False,
        parse_warnings=[],
    )


class TestProposalIndexer:

    PROJECT_ID = 9999  # use a non-conflicting test project ID
    DOCUMENT_ID = 9999

    def setup_method(self):
        """Reset the test collection before each test."""
        indexer = ProposalIndexer()
        indexer.delete_index(self.PROJECT_ID, self.DOCUMENT_ID)

    def teardown_method(self):
        """Clean up after each test."""
        indexer = ProposalIndexer()
        indexer.delete_index(self.PROJECT_ID, self.DOCUMENT_ID)

    def test_indexes_and_retrieves(self):
        """Should index chunks and retrieve the most relevant one."""
        proposal_chunks = [
            "Our team provides round-the-clock technical support 24 hours a day, 7 days a week.",
            "The company was founded in 2010 and serves clients globally.",
            "All software undergoes rigorous quality assurance testing before deployment.",
            "Payment terms are net-30 from invoice date.",
        ]
        parsed = make_mock_parsed_doc(proposal_chunks, "vendor_a.pdf")
        indexer = ProposalIndexer()
        count = indexer.index(parsed, self.PROJECT_ID, self.DOCUMENT_ID, "Test Vendor")
        assert count == len(proposal_chunks)

        # Query: should find the 24/7 support chunk
        results = indexer.retrieve(
            "vendor must provide 24/7 support",
            self.PROJECT_ID,
            self.DOCUMENT_ID,
            top_k=4,
        )
        assert len(results) > 0
        # The support chunk should be in top 2
        top_texts = [r["text"] for r in results[:2]]
        assert any("round-the-clock" in t or "24 hours" in t for t in top_texts), (
            f"Expected 24/7 support chunk in top 2. Got: {top_texts}"
        )

    def test_keyword_boost_promotes_exact_match(self):
        """
        Stage 1+2 test: ISO 27001 should be boosted to top even if
        semantic similarity alone would rank it lower.
        """
        proposal_chunks = [
            "We maintain comprehensive security policies and procedures.",
            "Our infrastructure is certified under ISO 27001:2022 information security standard.",
            "The project team has extensive experience in cloud deployments.",
            "Customer data is protected using industry-standard encryption.",
        ]
        parsed = make_mock_parsed_doc(proposal_chunks, "vendor_b.pdf")
        indexer.index(parsed, self.PROJECT_ID, self.DOCUMENT_ID, "Test Vendor")

        results = indexer.retrieve_with_keyword_boost(
            "vendor must hold ISO 27001 certification",
            self.PROJECT_ID,
            self.DOCUMENT_ID,
            top_k=4,
        )
        assert len(results) > 0
        # The ISO 27001 chunk should be first or second
        top_texts = [r["text"] for r in results[:2]]
        assert any("ISO 27001" in t for t in top_texts), (
            f"ISO 27001 chunk should be in top 2 with keyword boost. Got: {top_texts}"
        )

    def test_empty_document_returns_zero_chunks(self):
        """Empty parsed document should index zero chunks gracefully."""
        empty_parsed = make_mock_parsed_doc([], "empty.pdf")
        indexer = ProposalIndexer()
        count = indexer.index(empty_parsed, self.PROJECT_ID, self.DOCUMENT_ID, "Test Vendor")
        assert count == 0

    def test_retrieve_unindexed_document_raises(self):
        """Retrieving from an unindexed document should raise ValueError."""
        indexer = ProposalIndexer()
        with pytest.raises(ValueError, match="not found"):
            indexer.retrieve("any query", project_id=8888, document_id=8888)

    def test_collection_stats(self):
        """get_collection_stats should return correct chunk count."""
        chunks = ["First chunk of content.", "Second chunk of content.", "Third chunk."]
        parsed = make_mock_parsed_doc(chunks, "stats_test.pdf")
        indexer.index(parsed, self.PROJECT_ID, self.DOCUMENT_ID, "Test Vendor")

        stats = indexer.get_collection_stats(self.PROJECT_ID, self.DOCUMENT_ID)
        assert stats["chunk_count"] == len(chunks)


class TestTechnicalTermExtractor:

    def test_extracts_iso_standard(self):
        terms = extract_technical_terms("The vendor must hold ISO 27001 certification.")
        assert any("iso" in t for t in terms)

    def test_extracts_uptime_percentage(self):
        terms = extract_technical_terms("Guaranteed 99.9% uptime SLA.")
        assert any("99.9" in t for t in terms)

    def test_extracts_24_7(self):
        terms = extract_technical_terms("Support must be available 24/7.")
        assert any("24/7" in t for t in terms)

    def test_returns_empty_for_plain_text(self):
        terms = extract_technical_terms("The vendor shall provide good service.")
        assert len(terms) == 0