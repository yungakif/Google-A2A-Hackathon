"""Reciprocal Rank Fusion — merge several ranked id lists into one ranking."""

from typing import Optional


def reciprocal_rank_fusion(
    rankings: list[list[str]], k: int = 60, top_k: Optional[int] = None
) -> list[str]:
    """Combine ranked id lists by RRF: score(id) = sum 1/(k + rank), rank from 1.

    Ids absent from a list contribute nothing for it. Returns ids by descending
    fused score; ties broken by first appearance (deterministic)."""
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    order = 0
    for ranking in rankings:
        for rank, _id in enumerate(ranking, start=1):
            scores[_id] = scores.get(_id, 0.0) + 1.0 / (k + rank)
            if _id not in first_seen:
                first_seen[_id] = order
                order += 1
    ranked = sorted(scores, key=lambda i: (-scores[i], first_seen[i]))
    return ranked[:top_k] if top_k is not None else ranked
