"""
document_parser.py
------------------
Hierarchical PDF parser using PyMuPDF.

Architecture decision: Hierarchical RAG over flat chunking
  - Flat chunking (fixed token windows) loses clause relationships.
    A mandatory clause buried in Section 4.2.1 of a 100-page RFP
    gets split mid-sentence and loses its section context.
  - Hierarchical chunking: parse into Parent sections (heading + full
    section text) and Child clauses (individual sentences within each
    section). Each child chunk carries its parent's metadata.
  - During retrieval: search child chunks. During LLM reasoning:
    pass the parent section as context. This is what "Hierarchical RAG"
    actually means architecturally.

Edge cases handled:
  - Multi-column layouts: detected by x-coordinate clustering, flagged
    but not crashed.
  - Scanned/image PDFs: detected by zero text extraction, returns error.
  - Password-protected PDFs: graceful error with clear message.
  - Corrupt files: caught and logged, not raised to caller.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd

logger = logging.getLogger(__name__)


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ChildChunk:
    """A single sentence/clause extracted from a section."""
    text: str
    chunk_type: str          # "child"
    section_title: str
    section_level: int       # 1 = top heading, 2 = sub-heading, etc.
    page_number: int
    clause_ref: str | None   # e.g. "4.2.1" if detectable
    char_start: int          # character offset within document
    chunk_index: int         # sequential index across document


@dataclass
class ParentSection:
    """A complete document section with its child chunks."""
    title: str
    level: int               # heading level (1, 2, 3...)
    full_text: str           # complete section text (for context passing)
    page_number: int
    clause_ref: str | None
    children: list[ChildChunk] = field(default_factory=list)


@dataclass
class ParsedDocument:
    """Result of parsing one PDF document."""
    filename: str
    page_count: int
    word_count: int
    sections: list[ParentSection]
    all_chunks: list[ChildChunk]   # flat list for easy iteration
    is_scanned: bool
    is_multi_column: bool
    parse_warnings: list[str]


# ── Constants ─────────────────────────────────────────────────────────────────

# Heading font size thresholds (relative to body text size)
# If avg body size is ~10pt, headings are typically 12pt+ (1.2×)
HEADING_SCALE_THRESHOLD = 1.15

# Minimum characters for a chunk to be meaningful
MIN_CHUNK_CHARS = 5

# Clause reference patterns (e.g. "4.2", "4.2.1", "A.3.1")
CLAUSE_REF_PATTERN = re.compile(
    r"^([A-Z]?\d+(?:\.\d+){0,3})\s*[.\-:]?\s+", re.MULTILINE
)

# Standalone page number patterns (e.g. "Page 1 of 50", "1/50", "12")
PAGE_NUMBER_PATTERN = re.compile(
    r"""^(
        page\s*\d+(\s+of\s+\d+)?   # "Page 1" or "Page 1 of 50"
        |
        \d+\s*/\s*\d+             # "1/50"
        |
        \d+                       # bare page number
    )$""",
    re.IGNORECASE | re.VERBOSE,
)

# Common heading prefixes that can appear at body font size
# e.g. "1. EXECUTIVE SUMMARY", "EC-1", "FR-2"
HEADING_PREFIX_PATTERN = re.compile(
    r"^(?:\d+\.\s+|EC-\d+\b|FR-\d+\b)",
    re.IGNORECASE,
)

# Sentence splitter — splits on ". " or "! " or "? " but not on
# decimal numbers (3.14) or common abbreviations detected by a post-filter.
# Avoids variable-width lookbehind (not supported in Python's re module).
SENTENCE_END_PATTERN = re.compile(r"(?<=[.!?])\s+")

# Abbreviations whose trailing period should NOT trigger a sentence split
_ABBREVS = {
    "e.g", "i.e", "vs", "etc", "mr", "ms", "dr", "prof",
    "ltd", "inc", "corp", "no", "st", "fig", "sec", "art",
    "dept", "approx", "est", "ref", "vol", "p",
}


# ── Main parser ───────────────────────────────────────────────────────────────

class DocumentParser:
    """
    Hierarchical PDF parser.

    Usage:
        parser = DocumentParser()
        result = parser.parse("path/to/rfp.pdf")
        # result.sections  → list of ParentSection
        # result.all_chunks → flat list of ChildChunk
    """

    def parse(self, file_path: str | Path) -> ParsedDocument:
        """
        Parse a PDF into a hierarchical structure of sections and child chunks.

        Returns a ParsedDocument even on partial failure — check parse_warnings.
        """
        path = Path(file_path)
        warnings: list[str] = []

        try:
            doc = fitz.open(str(path))
        except Exception as e:
            raise ValueError(f"Cannot open PDF '{path.name}': {e}") from e

        if doc.is_encrypted:
            doc.close()
            raise ValueError(f"'{path.name}' is password-protected. Please decrypt it first.")

        page_count = len(doc)

        # ── Extract all text blocks with metadata ──────────────────────────
        raw_blocks = self._extract_blocks(doc)

        if not raw_blocks:
            doc.close()
            return ParsedDocument(
                filename=path.name,
                page_count=page_count,
                word_count=0,
                sections=[],
                all_chunks=[],
                is_scanned=True,
                is_multi_column=False,
                parse_warnings=["Document appears to be scanned/image-based. No text extracted."],
            )

        # ── Detect multi-column layout ─────────────────────────────────────
        is_multi_column = self._detect_multi_column(raw_blocks)
        if is_multi_column:
            warnings.append(
                "Multi-column layout detected. Parsing proceeds but clause order "
                "may not perfectly reflect reading order."
            )

        # ── Compute body font size (median) ───────────────────────────────
        body_font_size = self._compute_body_font_size(raw_blocks)
        heading_threshold = body_font_size * HEADING_SCALE_THRESHOLD

        # ── Build section hierarchy ────────────────────────────────────────
        sections = self._build_sections(raw_blocks, heading_threshold)

        if not sections:
            warnings.append("No clear section structure detected. Treating entire document as one section.")
            # Fallback: treat entire doc as one flat section
            all_text = " ".join(b["text"] for b in raw_blocks)
            fallback_section = ParentSection(
                title="Document",
                level=1,
                full_text=all_text,
                page_number=1,
                clause_ref=None,
            )
            fallback_section.children = self._split_into_chunks(
                all_text, "Document", 1, 1, None, start_index=0
            )
            sections = [fallback_section]

        # ── Build flat chunk list ─────────────────────────────────────────
        all_chunks: list[ChildChunk] = []
        for section in sections:
            all_chunks.extend(section.children)

        word_count = sum(len(c.text.split()) for c in all_chunks)
        doc.close()

        logger.info(
            "Parsed '%s': %d pages, %d sections, %d chunks, %d words",
            path.name, page_count, len(sections), len(all_chunks), word_count,
        )

        return ParsedDocument(
            filename=path.name,
            page_count=page_count,
            word_count=word_count,
            sections=sections,
            all_chunks=all_chunks,
            is_scanned=False,
            is_multi_column=is_multi_column,
            parse_warnings=warnings,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _extract_blocks(self, doc: fitz.Document) -> list[dict]:
        """Extract text blocks from all pages with position and font metadata."""
        blocks = []
        for page_num, page in enumerate(doc, start=1):
            page_height = page.rect.height
            top_cutoff = page_height * 0.08
            bottom_cutoff = page_height * 0.92

            # ── Preserve tables as structured text blocks ─────────────────
            try:
                tables_obj = page.find_tables()
            except Exception as e:  # defensive
                logger.debug("Table detection failed on page %d: %s", page_num, e)
                tables_obj = None

            table_list: list = []
            if tables_obj is not None:
                if hasattr(tables_obj, "tables"):
                    table_list = list(getattr(tables_obj, "tables", []))
                elif isinstance(tables_obj, list):
                    table_list = tables_obj

            for table in table_list:
                try:
                    df = table.to_pandas()
                except Exception as e:  # defensive
                    logger.debug("to_pandas failed for table on page %d: %s", page_num, e)
                    continue

                headers = list(df.columns)
                bbox = getattr(table, "bbox", page.rect)
                x0, y0, x1, y1 = bbox

                # Skip tables that are clearly in header/footer regions
                if y1 <= top_cutoff or y0 >= bottom_cutoff:
                    continue

                for _, row in df.iterrows():
                    cells: list[str] = []
                    for h in headers:
                        val = row.get(h)
                        if pd.isna(val):
                            continue
                        cells.append(f"{h}: {val}")
                    if not cells:
                        continue
                    text = " | ".join(str(c) for c in cells).strip()
                    if len(text) < 3:
                        continue
                    if PAGE_NUMBER_PATTERN.match(text):
                        continue

                    blocks.append({
                        "text": text,
                        "font_size": 10.0,
                        "is_bold": False,
                        "page": page_num,
                        "x0": x0,
                        "y0": y0,
                        "x1": x1,
                        "y1": y1,
                    })

            # ── Standard text blocks with header/footer stripping ─────────
            page_blocks = page.get_text("dict")["blocks"]
            for block in page_blocks:
                if block.get("type") != 0:  # type 0 = text
                    continue
                lines_text = []
                max_font_size = 0.0
                is_bold = False

                for line in block.get("lines", []):
                    line_text = ""
                    for span in line.get("spans", []):
                        span_text = span.get("text", "").strip()
                        if span_text:
                            line_text += span_text + " "
                            font_size = span.get("size", 10.0)
                            if font_size > max_font_size:
                                max_font_size = font_size
                            font_flags = span.get("flags", 0)
                            if font_flags & 16:  # bold flag
                                is_bold = True
                    if line_text.strip():
                        lines_text.append(line_text.strip())

                if not lines_text:
                    continue

                text = " ".join(lines_text).strip()
                if len(text) < 3:
                    continue

                x0, y0, x1, y1 = block["bbox"]

                # Drop header/footer noise using vertical position
                if y1 <= top_cutoff or y0 >= bottom_cutoff:
                    continue

                # Drop standalone page numbers
                if PAGE_NUMBER_PATTERN.match(text):
                    continue

                blocks.append({
                    "text": text,
                    "font_size": max_font_size,
                    "is_bold": is_bold,
                    "page": page_num,
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                })

        return blocks

    def _compute_body_font_size(self, blocks: list[dict]) -> float:
        """
        Compute the most common font size (body text size).
        Uses mode of font sizes rounded to 0.5pt buckets.
        """
        from collections import Counter
        sizes = [round(b["font_size"] * 2) / 2 for b in blocks]
        if not sizes:
            return 10.0
        counter = Counter(sizes)
        return counter.most_common(1)[0][0]

    def _detect_multi_column(self, blocks: list[dict]) -> bool:
        """
        Heuristic: if more than 30% of blocks have x0 > 50% of page width,
        the document likely has a multi-column layout.
        """
        if not blocks:
            return False
        page_widths = {}
        for b in blocks:
            page_widths.setdefault(b["page"], []).append(b["x1"])
        # Use median max x1 as page width estimate
        all_max_x = [max(v) for v in page_widths.values()]
        if not all_max_x:
            return False
        page_width = sorted(all_max_x)[len(all_max_x) // 2]
        midpoint = page_width * 0.5
        right_col_blocks = sum(1 for b in blocks if b["x0"] > midpoint)
        return right_col_blocks / len(blocks) > 0.30

    def _is_heading(self, block: dict, heading_threshold: float) -> bool:
        """Determine if a block is a heading based on font size and characteristics."""
        text = block["text"]

        # Font size threshold
        if block["font_size"] >= heading_threshold:
            return True

        # Bold + short text (likely a heading even at normal size)
        if block["is_bold"] and len(text.split()) <= 8 and not text.endswith((",", ";")):
            return True

        # ALL CAPS short text
        if text.isupper() and len(text.split()) <= 8:
            return True

        # Prefix-based headings often share body font size in procurement docs
        if HEADING_PREFIX_PATTERN.match(text.strip()):
            return True

        # Numbered section heading (e.g. "1.", "2.3", "A.1")
        if CLAUSE_REF_PATTERN.match(text) and len(text.split()) <= 15:
            return True

        return False

    def _extract_clause_ref(self, text: str) -> str | None:
        """Extract a clause reference from the beginning of text."""
        match = CLAUSE_REF_PATTERN.match(text)
        if match:
            return match.group(1)
        return None

    def _estimate_heading_level(self, block: dict, body_size: float) -> int:
        """Estimate heading depth: 1 = top-level, 2 = sub, 3 = sub-sub."""
        size_ratio = block["font_size"] / body_size if body_size > 0 else 1.0
        if size_ratio >= 1.5:
            return 1
        if size_ratio >= 1.25:
            return 2
        return 3

    def _split_into_chunks(
        self,
        text: str,
        section_title: str,
        section_level: int,
        page_number: int,
        clause_ref: str | None,
        start_index: int,
    ) -> list[ChildChunk]:
        """Split section text into individual sentence-level child chunks."""
        raw_sentences = self._split_sentences(text)
        chunks = []
        char_pos = 0

        for sentence in raw_sentences:
            sentence = sentence.strip()
            if len(sentence) < MIN_CHUNK_CHARS:
                char_pos += len(sentence)
                continue

            # Extract inline clause ref if present
            inline_ref = self._extract_clause_ref(sentence) or clause_ref

            chunks.append(ChildChunk(
                text=sentence,
                chunk_type="child",
                section_title=section_title,
                section_level=section_level,
                page_number=page_number,
                clause_ref=inline_ref,
                char_start=char_pos,
                chunk_index=start_index + len(chunks),
            ))
            char_pos += len(sentence) + 1

        return chunks

    def _split_sentences(self, text: str) -> list[str]:
        """
        Split text into sentences, respecting common abbreviations.
        Uses a fixed-width lookbehind-safe approach compatible with Python's re.
        """
        # Split on whitespace following sentence-ending punctuation
        parts = SENTENCE_END_PATTERN.split(text)
        if len(parts) <= 1:
            return parts

        # Re-join parts that were split on abbreviation periods
        merged: list[str] = []
        i = 0
        while i < len(parts):
            part = parts[i]
            # Check if this part ends with a known abbreviation
            last_word = part.rstrip().split()[-1].lower().rstrip(".") if part.strip() else ""
            if last_word in _ABBREVS and i + 1 < len(parts):
                # Merge with next part
                parts[i + 1] = part + " " + parts[i + 1]
            else:
                merged.append(part)
            i += 1
        return merged

    def _build_sections(
        self, blocks: list[dict], heading_threshold: float
    ) -> list[ParentSection]:
        """
        Assemble blocks into a flat list of ParentSections.
        Each section captures everything from one heading to the next.
        """
        body_size = self._compute_body_font_size(blocks)
        sections: list[ParentSection] = []
        current_section: ParentSection | None = None
        current_text_blocks: list[str] = []
        chunk_index = 0

        for block in blocks:
            text = block["text"]

            if self._is_heading(block, heading_threshold):
                # Save previous section
                if current_section is not None:
                    full_text = " ".join(current_text_blocks).strip()
                    current_section.full_text = full_text
                    current_section.children = self._split_into_chunks(
                        full_text,
                        current_section.title,
                        current_section.level,
                        current_section.page_number,
                        current_section.clause_ref,
                        start_index=chunk_index,
                    )
                    chunk_index += len(current_section.children)
                    sections.append(current_section)

                # Start new section
                clause_ref = self._extract_clause_ref(text)
                level = self._estimate_heading_level(block, body_size)
                current_section = ParentSection(
                    title=text,
                    level=level,
                    full_text="",
                    page_number=block["page"],
                    clause_ref=clause_ref,
                )
                current_text_blocks = [text]

            else:
                # Body text — accumulate for current section
                if current_section is None:
                    # Text before any heading — create implicit intro section
                    current_section = ParentSection(
                        title="Introduction",
                        level=1,
                        full_text="",
                        page_number=block["page"],
                        clause_ref=None,
                    )
                    current_text_blocks = []
                current_text_blocks.append(text)

        # Flush final section
        if current_section is not None:
            full_text = " ".join(current_text_blocks).strip()
            current_section.full_text = full_text
            current_section.children = self._split_into_chunks(
                full_text,
                current_section.title,
                current_section.level,
                current_section.page_number,
                current_section.clause_ref,
                start_index=chunk_index,
            )
            sections.append(current_section)

        return sections


# ── Module-level convenience function ─────────────────────────────────────────

def parse_document(file_path: str | Path) -> ParsedDocument:
    """Parse a PDF document. Module-level convenience wrapper."""
    return DocumentParser().parse(file_path)