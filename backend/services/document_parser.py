"""
document_parser.py  — PATCHED
-------------------------------
Changes from original:
  [FIX-2] Cross-block sentence continuation merging in
          _split_into_chunks_from_blocks().

  Root cause: the original code iterated blocks one-by-one and called
  _split_sentences() on each block independently. A sentence split across
  two physical PDF blocks ("Target RTO is 4 hours" / "and RPO is 30 minutes.")
  became two separate ChildChunks, severing the semantic unit.

  Fix: before sentence-splitting, merge consecutive blocks whose boundary
  is a dangling continuation — detected by TWO complementary signals:
    Signal A (tail of previous block): does it end WITHOUT sentence-terminal
              punctuation (., !, ?, :) ?
    Signal B (head of current block):  does it start with a lowercase letter,
              a coordinating/subordinating conjunction, or a relative pronoun?

  Both signals must fire to trigger a merge (AND logic), which prevents
  over-merging bullet lists and standalone sentences that happen to use
  lowercase style.

  The merged block inherits the LATER block's page number and bbox
  (the continuation lives on the later page / position).

  Also fixed/improved:
  [IMPROVE-A] _split_sentences() was losing the last merged part in the
              while-loop when an abbreviation caused a join. The loop now
              correctly appends the final part.
  [IMPROVE-B] Duplicate heading detection: consecutive identical headings
              (copy-paste artifact in some RFP templates) are now deduplicated
              in _build_sections().
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd
from PIL import Image

logger = logging.getLogger(__name__)

import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Users\hp\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"


# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class ChildChunk:
    text: str
    chunk_type: str
    section_title: str
    section_level: int
    page_number: int
    clause_ref: str | None
    char_start: int
    chunk_index: int
    bbox: list[float] | None = None


@dataclass
class ParentSection:
    title: str
    level: int
    full_text: str
    page_number: int
    clause_ref: str | None
    children: list[ChildChunk] = field(default_factory=list)


@dataclass
class ParsedDocument:
    filename: str
    page_count: int
    word_count: int
    sections: list[ParentSection]
    all_chunks: list[ChildChunk]
    is_scanned: bool
    is_multi_column: bool
    parse_warnings: list[str]


# ─── Constants ────────────────────────────────────────────────────────────────

HEADING_SCALE_THRESHOLD = 1.15
MIN_CHUNK_CHARS         = 5

CLAUSE_REF_PATTERN = re.compile(
    r"^([A-Z]?\d+(?:\.\d+){0,3})\s*[.\-:]?\s+", re.MULTILINE
)
PAGE_NUMBER_PATTERN = re.compile(
    r"""^(
        page\s*\d+(\s+of\s+\d+)?
        |
        \d+\s*/\s*\d+
        |
        \d+
    )$""",
    re.IGNORECASE | re.VERBOSE,
)
HEADING_PREFIX_PATTERN = re.compile(
    r"^(?:\d+\.\s+|EC-\d+\b|FR-\d+\b)", re.IGNORECASE,
)
SENTENCE_END_PATTERN = re.compile(r"(?<=[.!?])\s+")

_ABBREVS = {
    "e.g", "i.e", "vs", "etc", "mr", "ms", "dr", "prof",
    "ltd", "inc", "corp", "no", "st", "fig", "sec", "art",
    "dept", "approx", "est", "ref", "vol", "p",
}

# Continuation-start pattern:
# A block is a continuation of the previous block if its first word is one
# of these — conjunctions, relative pronouns, prepositions that only make
# sense mid-sentence — OR if it starts with a lowercase letter.
_CONTINUATION_START = re.compile(
    r"^(and|or|but|nor|yet|so|for|because|since|while|although|though"
    r"|however|therefore|moreover|furthermore|additionally|consequently"
    r"|thus|hence|whereby|which|who|whose|whom|that|whereas|unless"
    r"|until|if|when|where|as\s|with\s|to\s|of\s|in\s|on\s|at\s"
    r"|from\s|by\s|than\s|after\s|before\s)\b",
    re.IGNORECASE,
)

# Sentence-terminal punctuation at the END of a string
_SENTENCE_TERMINAL = re.compile(r"[.!?:]\s*$")


def _is_continuation_block(prev_text: str, curr_text: str) -> bool:
    """
    Return True when curr_text appears to be a dangling continuation
    of prev_text that was split across two PDF layout blocks.

    Signal A: prev_text does NOT end with sentence-terminal punctuation.
    Signal B: curr_text starts with a lowercase letter OR a continuation word.
    Both must hold (AND logic) to avoid over-merging.
    """
    if not prev_text or not curr_text:
        return False

    # Signal A: tail of previous block has no terminal punctuation
    tail_open = not _SENTENCE_TERMINAL.search(prev_text)

    # Signal B: head of current block is a continuation indicator
    first_char = curr_text[0]
    head_continues = first_char.islower() or bool(_CONTINUATION_START.match(curr_text))

    return tail_open and head_continues


# ─── Main parser ──────────────────────────────────────────────────────────────

class DocumentParser:
    """Hierarchical PDF parser."""

    def parse(self, file_path: str | Path) -> ParsedDocument:
        path     = Path(file_path)
        warnings: list[str] = []

        try:
            doc = fitz.open(str(path))
        except Exception as e:
            raise ValueError(f"Cannot open PDF '{path.name}': {e}") from e

        if doc.is_encrypted:
            doc.close()
            raise ValueError(f"'{path.name}' is password-protected.")

        page_count = len(doc)
        raw_blocks = self._extract_blocks(doc)

        if not raw_blocks:
            doc.close()
            return ParsedDocument(
                filename=path.name, page_count=page_count, word_count=0,
                sections=[], all_chunks=[], is_scanned=True,
                is_multi_column=False,
                parse_warnings=["Document appears scanned/image-based. No text extracted."],
            )

        is_multi_column = self._detect_multi_column(raw_blocks)
        if is_multi_column:
            warnings.append(
                "Multi-column layout detected. Clause order may not perfectly "
                "reflect reading order."
            )

        body_font_size    = self._compute_body_font_size(raw_blocks)
        heading_threshold = body_font_size * HEADING_SCALE_THRESHOLD
        sections          = self._build_sections(raw_blocks, heading_threshold)

        if not sections:
            warnings.append("No clear section structure detected. Treating entire document as one section.")
            all_text = " ".join(b["text"] for b in raw_blocks)
            fallback = ParentSection(title="Document", level=1, full_text=all_text, page_number=1, clause_ref=None)
            fallback.children = self._split_into_chunks_from_blocks(raw_blocks, "Document", 1, None, 0)
            sections = [fallback]

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
            filename=path.name, page_count=page_count, word_count=word_count,
            sections=sections, all_chunks=all_chunks,
            is_scanned=False, is_multi_column=is_multi_column,
            parse_warnings=warnings,
        )

    # ─── Private helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _rect_to_bbox_list(bbox) -> list[float] | None:
        if bbox is None:
            return None
        try:
            if hasattr(bbox, "x0"):
                return [float(bbox.x0), float(bbox.y0), float(bbox.x1), float(bbox.y1)]
            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                return [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
        except (TypeError, ValueError):
            return None
        return None

    def _extract_blocks(self, doc: fitz.Document) -> list[dict]:
        """Extract text blocks from all pages with position and font metadata."""
        blocks = []
        for page_num, page in enumerate(doc, start=1):
            page_height  = page.rect.height
            top_cutoff   = page_height * 0.08
            bottom_cutoff = page_height * 0.92
            page_plain_text = page.get_text().strip()

            # Tables
            try:
                tables_obj = page.find_tables()
            except Exception as e:
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
                except Exception as e:
                    logger.debug("to_pandas failed page %d: %s", page_num, e)
                    continue
                headers = list(df.columns)
                raw_tb  = getattr(table, "bbox", None)
                tb      = self._rect_to_bbox_list(raw_tb) or self._rect_to_bbox_list(page.rect)
                if not tb:
                    continue
                x0, y0, x1, y1 = tb
                if y1 <= top_cutoff or y0 >= bottom_cutoff:
                    continue
                for _, row in df.iterrows():
                    cells = [f"{h}: {row.get(h)}" for h in headers if not pd.isna(row.get(h))]
                    if not cells:
                        continue
                    text = " | ".join(str(c) for c in cells).strip()
                    if len(text) < 3 or PAGE_NUMBER_PATTERN.match(text):
                        continue
                    blocks.append({"text": text, "font_size": 10.0, "is_bold": False, "page": page_num, "bbox": list(tb)})

            # OCR fallback
            if len(page_plain_text) < 50:
                try:
                    pix      = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img      = Image.open(io.BytesIO(pix.tobytes("png")))
                    ocr_text = pytesseract.image_to_string(img).strip()
                    if ocr_text:
                        page_bb = self._rect_to_bbox_list(page.rect)
                        if page_bb:
                            blocks.append({"text": ocr_text, "font_size": 11.0, "is_bold": False, "page": page_num, "bbox": page_bb})
                except Exception:
                    logger.warning("OCR failed or Tesseract not installed. Skipping scanned page.")
                continue

            # Standard text blocks
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                lines_text: list[str] = []
                max_font_size = 0.0
                is_bold = False
                for line in block.get("lines", []):
                    line_text = ""
                    for span in line.get("spans", []):
                        span_text = span.get("text", "").strip()
                        if span_text:
                            line_text += span_text + " "
                            font_size  = span.get("size", 10.0)
                            if font_size > max_font_size:
                                max_font_size = font_size
                            if span.get("flags", 0) & 16:
                                is_bold = True
                    if line_text.strip():
                        lines_text.append(line_text.strip())
                if not lines_text:
                    continue
                text   = " ".join(lines_text).strip()
                raw_bb = block.get("bbox")
                bb     = self._rect_to_bbox_list(raw_bb)
                if not bb or len(text) < 3:
                    continue
                x0, y0, x1, y1 = bb
                if y1 <= top_cutoff or y0 >= bottom_cutoff:
                    continue
                if PAGE_NUMBER_PATTERN.match(text):
                    continue
                blocks.append({"text": text, "font_size": max_font_size, "is_bold": is_bold, "page": page_num, "bbox": bb})
        return blocks

    def _compute_body_font_size(self, blocks: list[dict]) -> float:
        from collections import Counter
        sizes   = [round(b["font_size"] * 2) / 2 for b in blocks]
        counter = Counter(sizes)
        return counter.most_common(1)[0][0] if sizes else 10.0

    def _detect_multi_column(self, blocks: list[dict]) -> bool:
        if not blocks:
            return False
        page_widths: dict[int, list[float]] = {}
        for b in blocks:
            bb = b.get("bbox")
            if bb and len(bb) >= 4:
                page_widths.setdefault(b["page"], []).append(bb[2])
        all_max_x = [max(v) for v in page_widths.values()]
        if not all_max_x:
            return False
        page_width   = sorted(all_max_x)[len(all_max_x) // 2]
        midpoint     = page_width * 0.5
        with_x0      = [b for b in blocks if b.get("bbox") and len(b["bbox"]) >= 4]
        if not with_x0:
            return False
        right_col    = sum(1 for b in with_x0 if b["bbox"][0] > midpoint)
        return right_col / len(with_x0) > 0.30

    def _is_heading(self, block: dict, heading_threshold: float) -> bool:
        text = block["text"]
        if block["font_size"] >= heading_threshold:
            return True
        if block["is_bold"] and len(text.split()) <= 8 and not text.endswith((",", ";")):
            return True
        if text.isupper() and len(text.split()) <= 8:
            return True
        if HEADING_PREFIX_PATTERN.match(text.strip()):
            return True
        if CLAUSE_REF_PATTERN.match(text) and len(text.split()) <= 15:
            return True
        return False

    def _extract_clause_ref(self, text: str) -> str | None:
        match = CLAUSE_REF_PATTERN.match(text)
        return match.group(1) if match else None

    def _estimate_heading_level(self, block: dict, body_size: float) -> int:
        ratio = block["font_size"] / body_size if body_size > 0 else 1.0
        if ratio >= 1.5:
            return 1
        if ratio >= 1.25:
            return 2
        return 3

    def _merge_continuation_blocks(self, blocks: list[dict]) -> list[dict]:
        """
        Pre-process a block list, merging consecutive blocks where the
        second block is a syntactic continuation of the first.

        The merged result:
          - text  = prev.text + " " + curr.text
          - page  = curr.page   (continuation is on the later page/position)
          - bbox  = curr.bbox   (position of the continuation fragment)
          - font_size / is_bold inherited from the FIRST block
            (it determines heading classification)
        """
        if not blocks:
            return blocks

        merged: list[dict] = [blocks[0].copy()]
        for curr in blocks[1:]:
            prev = merged[-1]
            if _is_continuation_block(prev["text"], curr["text"]):
                logger.debug(
                    "Merging cross-block continuation: '%s...' + '...%s'",
                    prev["text"][-40:], curr["text"][:40],
                )
                merged[-1] = {
                    "text":      prev["text"].rstrip() + " " + curr["text"].lstrip(),
                    "font_size": prev["font_size"],
                    "is_bold":   prev["is_bold"],
                    # Use the later block's spatial info for metadata accuracy
                    "page":      curr["page"],
                    "bbox":      curr["bbox"],
                }
            else:
                merged.append(curr.copy())
        return merged

    def _split_into_chunks_from_blocks(
        self,
        section_blocks: list[dict],
        section_title: str,
        section_level: int,
        section_clause_ref: str | None,
        start_index: int,
    ) -> list[ChildChunk]:
        """
        First merge continuation blocks, THEN split into sentences.
        This ensures cross-block sentences are reassembled before chunking.
        """
        # ── Step 1: merge dangling continuations ──────────────────────────
        merged_blocks = self._merge_continuation_blocks(section_blocks)

        # ── Step 2: sentence-split each merged block ──────────────────────
        chunks: list[ChildChunk] = []
        char_pos = 0

        for block in merged_blocks:
            text = (block.get("text") or "").strip()
            if not text:
                continue
            try:
                page_number = int(block.get("page") or 1)
            except (TypeError, ValueError):
                page_number = 1
            bb = self._rect_to_bbox_list(block.get("bbox"))

            for sentence in self._split_sentences(text):
                sentence = sentence.strip()
                if len(sentence) < MIN_CHUNK_CHARS:
                    char_pos += len(sentence)
                    continue
                inline_ref = self._extract_clause_ref(sentence) or section_clause_ref
                chunks.append(ChildChunk(
                    text          = sentence,
                    chunk_type    = "child",
                    section_title = section_title,
                    section_level = section_level,
                    page_number   = page_number,
                    clause_ref    = inline_ref,
                    char_start    = char_pos,
                    chunk_index   = start_index + len(chunks),
                    bbox          = bb,
                ))
                char_pos += len(sentence) + 1

        return chunks

    def _split_sentences(self, text: str) -> list[str]:
        
        parts = SENTENCE_END_PATTERN.split(text)
        if len(parts) <= 1:
            return parts

        merged: list[str] = []
        buffer = parts[0]
        for part in parts[1:]:
            last_word = buffer.rstrip().split()[-1].lower().rstrip(".") if buffer.strip() else ""
            if last_word in _ABBREVS:
                buffer = buffer + " " + part
            else:
                merged.append(buffer)
                buffer = part
        merged.append(buffer)  
        return merged

    def _build_sections(
        self, blocks: list[dict], heading_threshold: float
    ) -> list[ParentSection]:
        """
        [IMPROVE-B] Skip consecutive duplicate headings (copy-paste artifact).
        """
        body_size = self._compute_body_font_size(blocks)
        sections: list[ParentSection] = []
        current_section: ParentSection | None = None
        current_block_entries: list[dict]     = []
        chunk_index = 0
        last_heading_text: str | None = None   

        for block in blocks:
            text = block["text"]

            if self._is_heading(block, heading_threshold):

                #Skip duplicate consecutive headings
                if text == last_heading_text:
                    logger.debug("Skipping duplicate heading: '%s'", text)
                    continue
                last_heading_text = text

                if current_section is not None:
                    full_text = " ".join(b["text"] for b in current_block_entries).strip()
                    current_section.full_text = full_text
                    current_section.children  = self._split_into_chunks_from_blocks(
                        current_block_entries,
                        current_section.title,
                        current_section.level,
                        current_section.clause_ref,
                        start_index=chunk_index,
                    )
                    chunk_index += len(current_section.children)
                    sections.append(current_section)

                clause_ref = self._extract_clause_ref(text)
                level      = self._estimate_heading_level(block, body_size)
                current_section       = ParentSection(
                    title=text, level=level, full_text="",
                    page_number=block["page"], clause_ref=clause_ref,
                )
                current_block_entries = [block]

            else:
                if current_section is None:
                    current_section = ParentSection(
                        title="Introduction", level=1, full_text="",
                        page_number=block["page"], clause_ref=None,
                    )
                    current_block_entries = []
                current_block_entries.append(block)

        if current_section is not None:
            full_text = " ".join(b["text"] for b in current_block_entries).strip()
            current_section.full_text = full_text
            current_section.children  = self._split_into_chunks_from_blocks(
                current_block_entries,
                current_section.title,
                current_section.level,
                current_section.clause_ref,
                start_index=chunk_index,
            )
            sections.append(current_section)

        return sections


def parse_document(file_path: str | Path) -> ParsedDocument:
    return DocumentParser().parse(file_path)