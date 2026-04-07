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
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from rank_bm25 import BM25Okapi
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


def _bbox_from_metadata(meta: dict) -> list[float] | None:
    """Parse bbox JSON string from Chroma metadata (lists are not supported natively)."""
    raw = meta.get("bbox")
    if raw is None or raw == "":
        return None
    try:
        if isinstance(raw, str):
            parsed = json.loads(raw)
            if isinstance(parsed, list) and len(parsed) >= 4:
                return [float(parsed[0]), float(parsed[1]), float(parsed[2]), float(parsed[3])]
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return None


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
        vendor_name: str,
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
            metadatas = []
            for c in batch:
                meta = {
                    "document_id": document_id,
                    "project_id": project_id,
                    "vendor_name": vendor_name,
                    "section_title": c.section_title,
                    "page_number": c.page_number,
                    "clause_ref": c.clause_ref or "",
                    "section_level": c.section_level,
                    "chunk_index": c.chunk_index,
                    "technical_terms": json.dumps(extract_technical_terms(c.text)),
                }
                if c.bbox is not None and len(c.bbox) >= 4:
                    meta["bbox"] = json.dumps(c.bbox)
                metadatas.append(meta)

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
                "bbox": _bbox_from_metadata(meta),
            })

        return candidates

    def retrieve_hybrid(
        self,
        query_text: str,
        project_id: int,
        document_id: int,
        top_k: int | None = None,
    ) -> list[dict]:
        """
        Stage 1 hybrid retrieval: Sparse BM25 + Dense vector search + RRF fusion.
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

        # 1) Fetch all chunks in this collection for BM25 sparse retrieval
        raw = collection.get(include=["documents", "metadatas"])
        all_docs = raw.get("documents") or []
        all_meta = raw.get("metadatas") or []
        if not all_docs:
            return []

        # 2) Sparse BM25 ranking
        tokenized_corpus = [doc.lower().split() for doc in all_docs]
        bm25 = BM25Okapi(tokenized_corpus)
        query_tokens = query_text.lower().split()
        bm25_scores = bm25.get_scores(query_tokens)

        bm25_ranked_idx = sorted(
            range(len(all_docs)),
            key=lambda i: float(bm25_scores[i]),
            reverse=True,
        )
        bm25_rank_map = {idx: rank + 1 for rank, idx in enumerate(bm25_ranked_idx)}

        # 3) Dense vector ranking (bi-encoder via ChromaDB ANN)
        query_embedding = self.encoder.encode(
            query_text,
            normalize_embeddings=True,
        ).tolist()
        dense = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(len(all_docs), collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        dense_score_map: dict[tuple[str, int, str], float] = {}
        dense_rank_map: dict[tuple[str, int, str], int] = {}
        dense_results = list(
            zip(
                dense.get("documents", [[]])[0],
                dense.get("metadatas", [[]])[0],
                dense.get("distances", [[]])[0],
            )
        )
        for rank, (text, meta, distance) in enumerate(dense_results, start=1):
            key = (
                text,
                int(meta.get("page_number", 0)),
                str(meta.get("clause_ref", "")),
            )
            similarity = 1.0 - (float(distance) / 2.0)
            dense_score_map[key] = round(similarity, 4)
            dense_rank_map[key] = rank

        # 4) Retrieval-stage RRF fusion across BM25 + dense ranks
        k = 60.0
        fused: list[dict] = []
        for idx, (text, meta) in enumerate(zip(all_docs, all_meta)):
            key = (
                text,
                int(meta.get("page_number", 0)),
                str(meta.get("clause_ref", "")),
            )
            bm25_rank = bm25_rank_map.get(idx, len(all_docs) + 1)
            dense_rank = dense_rank_map.get(key, len(all_docs) + 1)
            retrieval_rrf = (1.0 / (k + bm25_rank)) + (1.0 / (k + dense_rank))

            fused.append({
                "text": text,
                # keep dense score shape expected downstream; default to 0 when missing
                "score": float(dense_score_map.get(key, 0.0)),
                "metadata": meta,
                "section_title": meta.get("section_title", ""),
                "page_number": meta.get("page_number", 0),
                "clause_ref": meta.get("clause_ref", ""),
                "technical_terms": json.loads(meta.get("technical_terms", "[]")),
                "bbox": _bbox_from_metadata(meta),
                "retrieval_rrf": retrieval_rrf,
            })

        fused.sort(key=lambda x: float(x.get("retrieval_rrf", 0.0)), reverse=True)
        return fused[:top_k]

    # Backward-compatible alias for legacy callers/tests.
    def retrieve_with_keyword_boost(
        self,
        query_text: str,
        project_id: int,
        document_id: int,
        top_k: int | None = None,
    ) -> list[dict]:
        return self.retrieve_hybrid(query_text, project_id, document_id, top_k)

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
    vendor_name: str,
) -> int:
    """Index a parsed document. Module-level convenience."""
    return ProposalIndexer().index(parsed, project_id, document_id, vendor_name)