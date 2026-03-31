"""
proposal_indexer.py
-------------------
Embeds and indexes vendor proposal chunks into ChromaDB.

Architecture decision: Local sentence-transformers over API embeddings
  - all-MiniLM-L6-v2 runs entirely on-device after first download (~80MB).
  - Zero cost per embedding call.
  - Sufficient quality for the bi-encoder retrieval stage (Stage 1).
  - The cross-encoder reranker (Stage 2) compensates for any retrieval gaps.

Collection naming: one ChromaDB collection per (project_id, document_id).
This allows parallel indexing of multiple vendors and clean deletion.

Keyword index: maintained in-memory for the current session + persisted
to SQLite as a JSON blob. Used to boost exact-match hits for technical
terms (certification names, uptime numbers, standards like ISO 27001).
"""

from __future__ import annotations

import json
import logging
import os
import re
from math import fsum
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

from backend.config import settings
from services.document_parser import ChildChunk, ParsedDocument

logger = logging.getLogger(__name__)

# ── Model singleton (loaded once, reused) ─────────────────────────────────────

_bi_encoder: SentenceTransformer | None = None


def get_bi_encoder() -> SentenceTransformer:
    global _bi_encoder
    if _bi_encoder is None:
        os.makedirs(settings.HF_HOME, exist_ok=True)
        logger.info("Loading bi-encoder model (first run downloads ~80MB)...")
        _bi_encoder = SentenceTransformer(
            "all-MiniLM-L6-v2",
            cache_folder=settings.HF_HOME,
        )
        logger.info("Bi-encoder ready.")
    return _bi_encoder


# ── ChromaDB client singleton ─────────────────────────────────────────────────

_chroma_client: chromadb.PersistentClient | None = None


def get_chroma_client() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _chroma_client


# ── Collection naming ─────────────────────────────────────────────────────────

def collection_name(project_id: int, document_id: int) -> str:
    return f"proj{project_id}_doc{document_id}"


# ── Technical term extractor (for keyword boost) ──────────────────────────────

# Patterns for terms that should be exact-matched (not just semantically matched)
TECHNICAL_TERM_PATTERNS = [
    re.compile(r"\bISO\s*\d+(?::\d+)?(?:\s*[-–]\d+)?\b"),      # ISO 27001, ISO 9001:2015
    re.compile(r"\bSOC\s*[12]\b"),                               # SOC 2
    re.compile(r"\b\d{1,3}(?:\.\d+)?\s*%\s*(?:uptime|availability)\b", re.IGNORECASE),
    re.compile(r"\b(?:24[/x]7|round.the.clock|always.on)\b", re.IGNORECASE),
    re.compile(r"\bPCI[- ]DSS\b", re.IGNORECASE),
    re.compile(r"\bGDPR\b"),
    re.compile(r"\bHIPAA\b"),
    re.compile(r"\bNIST\b"),
    re.compile(r"\bR\s*\d[\d,. ]+\b"),                          # Rand amounts
    re.compile(r"\$\s*\d[\d,. ]+\b"),                           # Dollar amounts
    re.compile(r"\b\d+\s*(?:days?|weeks?|months?|hours?)\b", re.IGNORECASE),
    re.compile(r"\b(?:positive|negative)\s*net\s*worth\b", re.IGNORECASE),
    re.compile(r"\bINR\s*\d[\d,. ]*(?:crore|lakh)?\b", re.IGNORECASE),
    re.compile(r"\bover\s*\d+\s*years?\s*experience\b", re.IGNORECASE),
]


def extract_technical_terms(text: str) -> list[str]:
    """Extract technical terms that should be exact-matched."""
    terms = []
    for pattern in TECHNICAL_TERM_PATTERNS:
        for match in pattern.finditer(text):
            term = match.group().strip().lower()
            if term not in terms:
                terms.append(term)
    return terms


# ── Main indexer ──────────────────────────────────────────────────────────────

class ProposalIndexer:
    """
    Embeds and indexes vendor proposal chunks into ChromaDB.

    Usage:
        indexer = ProposalIndexer()
        indexer.index(parsed_doc, project_id=1, document_id=2)
        results = indexer.retrieve("must provide 24/7 support", project_id=1, doc_id=2)
    """

    def __init__(self):
        self.encoder = get_bi_encoder()
        self.client = get_chroma_client()

    def index(
        self,
        parsed: ParsedDocument,
        project_id: int,
        document_id: int,
        batch_size: int = 64,
    ) -> int:
        """
        Embed all child chunks and store in ChromaDB.

        Returns the number of chunks indexed.
        Idempotent: deletes and recreates collection if it already exists.
        """
        coll_name = collection_name(project_id, document_id)

        # Delete existing collection (allows re-indexing)
        try:
            self.client.delete_collection(coll_name)
            logger.debug("Deleted existing collection '%s'", coll_name)
        except Exception:
            pass

        collection = self.client.create_collection(
            name=coll_name,
            metadata={"hnsw:space": "cosine"},
        )

        chunks = parsed.all_chunks
        if not chunks:
            logger.warning(
                "No chunks to index for document_id=%d (is_scanned=%s)",
                document_id, parsed.is_scanned,
            )
            return 0

        logger.info(
            "Indexing %d chunks for document_id=%d...", len(chunks), document_id
        )

        # Process in batches for memory efficiency
        indexed = 0
        for start in range(0, len(chunks), batch_size):
            batch: list[ChildChunk] = chunks[start: start + batch_size]
            texts = [c.text for c in batch]
            embeddings = self.encoder.encode(
                texts,
                show_progress_bar=False,
                normalize_embeddings=True,
            ).tolist()

            ids = [f"doc{document_id}_chunk{c.chunk_index}" for c in batch]
            metadatas = [
                {
                    "document_id": document_id,
                    "project_id": project_id,
                    "section_title": c.section_title,
                    "page_number": c.page_number,
                    "clause_ref": c.clause_ref or "",
                    "section_level": c.section_level,
                    "chunk_index": c.chunk_index,
                    "technical_terms": json.dumps(extract_technical_terms(c.text)),
                }
                for c in batch
            ]

            collection.add(
                documents=texts,
                embeddings=embeddings,
                ids=ids,
                metadatas=metadatas,
            )
            indexed += len(batch)
            logger.debug("Indexed batch %d–%d", start + 1, start + len(batch))

        logger.info(
            "Indexing complete: %d chunks in collection '%s'", indexed, coll_name
        )
        return indexed

    def retrieve(
        self,
        query_text: str,
        project_id: int,
        document_id: int,
        top_k: int | None = None,
    ) -> list[dict]:
        """
        Stage 1 retrieval: bi-encoder ANN search.

        Returns top_k results sorted by cosine similarity (descending).
        Each result: {text, score, metadata, id}

        The cross-encoder reranker (Stage 2) should be applied to these results
        before passing to the entailment classifier.
        """
        top_k = top_k or settings.TOP_K_RETRIEVAL
        coll_name = collection_name(project_id, document_id)

        try:
            collection = self.client.get_collection(coll_name)
        except Exception as e:
            raise ValueError(
                f"Collection '{coll_name}' not found. "
                f"Has document {document_id} been indexed? Error: {e}"
            ) from e

        # Embed the query
        query_embedding = self.encoder.encode(
            query_text,
            normalize_embeddings=True,
        ).tolist()

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        if not results["documents"] or not results["documents"][0]:
            return []

        candidates = []
        for text, meta, distance in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # Convert to similarity: 1 - (distance / 2) for cosine
            similarity = 1.0 - (distance / 2.0)
            candidates.append({
                "text": text,
                "score": round(similarity, 4),
                "metadata": meta,
                "section_title": meta.get("section_title", ""),
                "page_number": meta.get("page_number", 0),
                "clause_ref": meta.get("clause_ref", ""),
                "technical_terms": json.loads(meta.get("technical_terms", "[]")),
            })

        return candidates

    def retrieve_with_keyword_boost(
        self,
        query_text: str,
        project_id: int,
        document_id: int,
        top_k: int | None = None,
    ) -> list[dict]:
        """
        Stage 1 retrieval with keyword boost.

        After ANN retrieval:
        1. Extract technical terms from the query.
        2. Scan collection for chunks containing those exact terms.
        3. Promote exact-match hits to the top of the results list.

        This prevents ISO 27001 requirement from being matched only
        semantically when the vendor's document contains the exact string.
        """
        top_k = top_k or settings.TOP_K_RETRIEVAL

        # Get ANN results
        ann_results = self.retrieve(query_text, project_id, document_id, top_k)

        # Extract technical terms from query
        query_terms = extract_technical_terms(query_text)
        if not query_terms:
            return ann_results  # No boost needed

        min_semantic_score = 0.40
        keyword_boost = 0.05

        # Find which ANN results contain exact technical term matches
        boosted_ids = set()
        for result in ann_results:
            chunk_terms = result.get("technical_terms", [])
            semantic_ok = float(result.get("score", 0.0)) >= min_semantic_score
            if semantic_ok and any(qt in chunk_terms for qt in query_terms):
                boosted_ids.add(id(result))

        if not boosted_ids:
            # Terms not found in ANN results — try a direct collection scan
            # for exact matches (only for short term lists to avoid slowness)
            if len(query_terms) <= 3:
                direct_matches = self._exact_term_search(
                    query_terms,
                    query_text,
                    project_id,
                    document_id,
                    min_semantic_score=min_semantic_score,
                )
                # Deduplicate with ANN results (by text)
                ann_texts = {r["text"] for r in ann_results}
                new_matches = [r for r in direct_matches if r["text"] not in ann_texts]
                if new_matches:
                    # Add exact semantic matches with a small boost
                    for r in new_matches:
                        r["boosted"] = True
                        r["score"] = min(1.0, float(r.get("score", 0.0)) + keyword_boost)
                    combined = new_matches + ann_results
                    combined.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
                    return combined[:top_k]

        # Apply a bounded score boost only to semantically relevant exact matches.
        for r in ann_results:
            if id(r) in boosted_ids:
                r["boosted"] = True
                r["score"] = min(1.0, float(r.get("score", 0.0)) + keyword_boost)
            else:
                r["boosted"] = False

        ann_results.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
        return ann_results[:top_k]

    def _exact_term_search(
        self,
        terms: list[str],
        query_text: str,
        project_id: int,
        document_id: int,
        min_semantic_score: float = 0.40,
    ) -> list[dict]:
        """
        Exact term matching using ChromaDB document filters, guarded by semantic relevance.
        """
        coll_name = collection_name(project_id, document_id)
        try:
            collection = self.client.get_collection(coll_name)
        except Exception:
            return []

        # Semantic guardrail: only keep exact matches that are still reasonably relevant.
        query_embedding = self.encoder.encode(
            query_text,
            normalize_embeddings=True,
        ).tolist()

        results = []
        seen_texts: set[str] = set()
        for term in terms:
            try:
                matches = collection.get(
                    where_document={"$contains": term},
                    include=["documents", "metadatas"],
                )
                documents = matches.get("documents") or []
                metadatas = matches.get("metadatas") or []
                for text, meta in zip(documents, metadatas):
                    if not text:
                        continue
                    if text in seen_texts:
                        continue
                    doc_embedding = self.encoder.encode(
                        text,
                        normalize_embeddings=True,
                    ).tolist()
                    semantic_similarity = fsum(
                        float(a) * float(b) for a, b in zip(query_embedding, doc_embedding)
                    )
                    if semantic_similarity < min_semantic_score:
                        continue
                    seen_texts.add(text)
                    results.append({
                        "text": text,
                        "score": round(float(semantic_similarity), 4),
                        "metadata": meta,
                        "section_title": meta.get("section_title", ""),
                        "page_number": meta.get("page_number", 0),
                        "clause_ref": meta.get("clause_ref", ""),
                        "technical_terms": json.loads(meta.get("technical_terms", "[]")),
                    })
            except Exception as e:
                logger.debug("Exact where_document search failed for term '%s': %s", term, e)

        return results

    def delete_index(self, project_id: int, document_id: int) -> None:
        """Delete a document's vector index (e.g. when document is removed)."""
        coll_name = collection_name(project_id, document_id)
        try:
            self.client.delete_collection(coll_name)
            logger.info("Deleted collection '%s'", coll_name)
        except Exception as e:
            logger.warning("Could not delete collection '%s': %s", coll_name, e)

    def get_collection_stats(self, project_id: int, document_id: int) -> dict:
        """Return basic stats about an indexed collection."""
        coll_name = collection_name(project_id, document_id)
        try:
            collection = self.client.get_collection(coll_name)
            return {"collection": coll_name, "chunk_count": collection.count()}
        except Exception:
            return {"collection": coll_name, "chunk_count": 0, "error": "Not found"}


# ── Module-level convenience ──────────────────────────────────────────────────

def index_document(
    parsed: ParsedDocument,
    project_id: int,
    document_id: int,
) -> int:
    """Index a parsed document. Module-level convenience."""
    return ProposalIndexer().index(parsed, project_id, document_id)