"""Knowledge-base search tools backed by Redis (RediSearch).

kb_search_bm25: full-text BM25 search (OR-semantics keyword query).
kb_search_vector: HNSW vector search over gemini-embedding-001 embeddings
(available only when the index was built with embeddings).

Replies are parsed via execute_command so both the classic array reply and
the Redis 8 map-style reply work regardless of redis-py version."""

import os
import re
import struct

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
KB_INDEX = "kb_idx"
DOC_PREFIX = "doc:"
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 3072

_client = redis.Redis.from_url(REDIS_URL, decode_responses=False)
_genai_client = None


def _get_genai_client():
    """Reused genai client (one connection pool, not a new one per search).

    Configured to retry Vertex rate-limit / transient errors with exponential
    backoff so embedding calls survive higher eval concurrency on one API key
    instead of failing the search outright."""
    global _genai_client
    if _genai_client is None:
        from google import genai
        from google.genai import types

        _genai_client = genai.Client(
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(
                    attempts=4, initial_delay=1.0, max_delay=20.0, exp_base=2.0,
                    jitter=0.5, http_status_codes=[429, 500, 503],
                )
            )
        )
    return _genai_client


def _embed(texts: list[str]) -> list[list[float]]:
    """Embed texts with gemini-embedding-001 via google-genai."""
    from google.genai import types

    # Reduced-dim output is unnormalized; the index uses COSINE, so that's fine.
    result = _get_genai_client().models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIM),
    )
    return [e.values for e in result.embeddings]


def _decode(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _parse_search_reply(reply) -> list[dict]:
    """Normalize an FT.SEARCH reply (array or map shape) to result dicts."""
    if isinstance(reply, dict):
        results = reply.get(b"results", reply.get("results")) or []
        out = []
        for row in results:
            attrs = row.get(b"extra_attributes", row.get("extra_attributes")) or {}
            doc = {"doc_id": _decode(row.get(b"id", row.get("id", "")))}
            doc.update({_decode(k): _decode(v) for k, v in attrs.items()})
            out.append(doc)
        return out
    out = []
    for i in range(1, len(reply) - 1, 2):
        doc = {"doc_id": _decode(reply[i])}
        fields = reply[i + 1]
        for j in range(0, len(fields) - 1, 2):
            doc[_decode(fields[j])] = _decode(fields[j + 1])
        out.append(doc)
    return out


def _strip_score(docs: list[dict]) -> list[dict]:
    for doc in docs:
        doc.pop("score", None)
    return docs


def kb_search_bm25(query: str, top_k: int = 5) -> list[dict]:
    """Full-text (BM25) search over the Rho-Bank knowledge base.

    Args:
        query: Keywords or a short phrase to search for. Matching is ranked,
            so extra keywords help rather than hurt.
        top_k: Number of documents to return.

    Returns:
        Matching documents with doc_id, title, and full content.
    """
    terms = re.findall(r"\w+", query.lower())
    if not terms:
        return []
    # OR-join: RediSearch defaults to AND, which zeroes out long queries.
    or_query = "|".join(dict.fromkeys(terms))
    reply = _client.execute_command(
        "FT.SEARCH", KB_INDEX, or_query,
        "LIMIT", "0", str(top_k),
        "RETURN", "2", "title", "content",
    )
    return _parse_search_reply(reply)


def kb_search_vector(query: str, top_k: int = 5) -> list[dict]:
    """Semantic (vector) search over the Rho-Bank knowledge base.

    Better than kb_search_bm25 when the query is a natural-language question
    rather than exact keywords.

    Args:
        query: A natural-language question or description.
        top_k: Number of documents to return.

    Returns:
        Matching documents with doc_id, title, and full content; or an error
        entry telling you to fall back to kb_search_bm25.
    """
    try:
        vector = struct.pack(f"{EMBEDDING_DIM}f", *_embed([query])[0])
        reply = _client.execute_command(
            "FT.SEARCH", KB_INDEX, f"*=>[KNN {top_k} @embedding $vec AS score]",
            "PARAMS", "2", "vec", vector,
            "SORTBY", "score",
            "LIMIT", "0", str(top_k),
            "RETURN", "3", "title", "content", "score",
            "DIALECT", "2",
        )
        return _strip_score(_parse_search_reply(reply))
    except Exception as e:
        return [
            {
                "error": f"Vector search unavailable ({type(e).__name__}). "
                "Use kb_search_bm25 with keywords instead."
            }
        ]


def _rrf_fuse(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion: merge several ranked id-lists into one score map.

    RRF is scale-free, so it combines BM25 and cosine rankings without needing
    their (incomparable) raw scores. Lower rank => higher contribution.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


def kb_search(query: str, top_k: int = 8) -> list[dict]:
    """Hybrid search over the Rho-Bank knowledge base. PREFER THIS tool.

    Runs keyword (BM25) and semantic (vector) search together and fuses them
    with Reciprocal Rank Fusion, so it is robust whether the query is exact
    keywords (e.g. an internal tool name) or a natural-language question. Each
    method catches what the other misses; fusion surfaces docs ranked well by
    either. Degrades to keyword-only if embeddings are unavailable.

    Args:
        query: Keywords or a natural-language question/description.
        top_k: Number of documents to return.

    Returns:
        Best-matching documents (doc_id, title, full content), best first.
    """
    over = max(top_k * 2, 10)
    bm = kb_search_bm25(query, top_k=over)
    vec = kb_search_vector(query, top_k=over)
    if vec and isinstance(vec[0], dict) and "error" in vec[0]:
        vec = []  # embeddings unavailable -> BM25 ranking only

    docs: dict[str, dict] = {}
    bm_ids: list[str] = []
    vec_ids: list[str] = []
    for d in bm:
        did = d.get("doc_id")
        if did:
            docs.setdefault(did, d)
            bm_ids.append(did)
    for d in vec:
        did = d.get("doc_id")
        if did:
            docs.setdefault(did, d)
            vec_ids.append(did)

    if not docs:
        return []
    fused = _rrf_fuse([bm_ids, vec_ids])
    ranked = sorted(fused, key=lambda did: -fused[did])[:top_k]
    return [docs[did] for did in ranked]
