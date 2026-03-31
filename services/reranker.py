"""
reranker.py
-----------
Stage 2 retrieval: cross-encoder reranking.

Architecture decision: why two stages?
  Stage 1 (bi-encoder): fast ANN search, retrieves top-20 candidates.
    Weakness: bi-encoders encode query and passage INDEPENDENTLY, so they
    miss semantic equivalences like "round-the-clock" == "24/7 support".

  Stage 2 (cross-encoder): scores each (query, passage) PAIR jointly.
    The model sees both texts simultaneously, enabling deep interaction.
    This is what catches paraphrase matches that Stage 1 misses.
    Cost: ~20× slower per call, but only runs on top-20 not all chunks.

Design document quote:
  "Stage 1 alone vs Stage 1+2 accuracy improvement: ~35% on
   paraphrase-heavy requirements" — benchmark this with test_retriever.py.
"""

from __future__ import annotations

import logging
import os

from sentence_transformers import CrossEncoder

from backend.config import settings

logger = logging.getLogger(__name__)

# ── Model singleton ───────────────────────────────────────────────────────────

_cross_encoder: CrossEncoder | None = None


def get_cross_encoder() -> CrossEncoder:
    global _cross_encoder
    if _cross_encoder is None:
        os.makedirs(settings.HF_HOME, exist_ok=True)
        logger.info("Loading cross-encoder model (first run downloads ~80MB)...")
        _cross_encoder = CrossEncoder(
            "cross-encoder/ms-marco-MiniLM-L-6-v2",
            max_length=512,
            # Store in same cache dir as bi-encoder
        )
        logger.info("Cross-encoder ready.")
    return _cross_encoder


# ── Reranker ──────────────────────────────────────────────────────────────────

class Reranker:
    """
    Reranks Stage 1 retrieval candidates using a cross-encoder model.

    Usage:
        reranker = Reranker()
        top5 = reranker.rerank(query, candidates, top_k=5)
    """

    def __init__(self):
        self.model = get_cross_encoder()

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int | None = None,
    ) -> list[dict]:
        """
        Rerank Stage 1 candidates by cross-encoder score.

        Args:
            query:      The requirement text (normalised_intent preferred).
            candidates: Output from ProposalIndexer.retrieve_with_keyword_boost().
            top_k:      How many to return. Defaults to settings.TOP_K_RERANK (5).

        Returns:
            Top-k candidates sorted by cross-encoder score (descending).
            Each result gains a 'reranker_score' field.
        """
        top_k = top_k or settings.TOP_K_RERANK

        if not candidates:
            return []

        # Build (query, passage) pairs for the cross-encoder
        pairs = [(query, c["text"]) for c in candidates]

        # Score all pairs — cross-encoder sees both texts simultaneously
        scores = self.model.predict(pairs, show_progress_bar=False)

        # Attach scores to candidates
        scored = []
        for candidate, score in zip(candidates, scores):
            enriched = dict(candidate)
            enriched["reranker_score"] = float(score)
            scored.append(enriched)

        # Reciprocal Rank Fusion (RRF): combines bi-encoder and cross-encoder ranks.
        # rank starts at 1, with constant 60 (common robust default).
        k = 60.0
        def _chunk_key(c: dict) -> tuple:
            return (
                c.get("text", ""),
                c.get("section_title", ""),
                c.get("page_number", 0),
                c.get("clause_ref", ""),
            )

        bi_rank_map = {_chunk_key(c): idx + 1 for idx, c in enumerate(candidates)}
        cross_sorted = sorted(scored, key=lambda x: x["reranker_score"], reverse=True)
        cross_rank_map = {_chunk_key(c): idx + 1 for idx, c in enumerate(cross_sorted)}

        for item in scored:
            key = _chunk_key(item)
            bi_rank = bi_rank_map.get(key, len(candidates) + 1)
            cross_rank = cross_rank_map.get(key, len(candidates) + 1)
            item["rrf_score"] = (1.0 / (k + bi_rank)) + (1.0 / (k + cross_rank))

        # Sort by fused score first, then cross-encoder as tie-breaker
        scored.sort(
            key=lambda x: (x.get("rrf_score", 0.0), x["reranker_score"]),
            reverse=True,
        )

        logger.debug(
            "Reranked %d candidates → top RRF: %.4f, top CE: %.4f",
            len(scored),
            scored[0]["rrf_score"] if scored else 0,
            scored[0]["reranker_score"] if scored else 0,
        )

        return scored[:top_k]

    def max_score(self, candidates: list[dict]) -> float:
        """Return the highest reranker_score in a candidate list."""
        if not candidates:
            return 0.0
        scores = [c.get("reranker_score", 0.0) for c in candidates]
        return max(scores)

    def top_fused_score(self, candidates: list[dict]) -> float:
        """Return highest fused RRF score from reranked candidates."""
        if not candidates:
            return 0.0
        scores = [float(c.get("rrf_score", 0.0)) for c in candidates]
        return max(scores)


# ── Module-level convenience ──────────────────────────────────────────────────

def rerank(query: str, candidates: list[dict], top_k: int | None = None) -> list[dict]:
    """Module-level convenience wrapper."""
    return Reranker().rerank(query, candidates, top_k)