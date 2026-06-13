"""Knowledge-base search tools backed by Redis (RediSearch).

kb_search: one hybrid tool — runs BM25 (OR-semantics keyword) and HNSW vector
search over gemini-embedding-001 chunk embeddings, then fuses them with
Reciprocal Rank Fusion. Vector search is skipped gracefully if the index has no
embeddings (BM25-only).

Replies are parsed via execute_command so both the classic array reply and
the Redis 8 map-style reply work regardless of redis-py version."""

import os
import re
import struct

import redis

from fusion import reciprocal_rank_fusion

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
KB_INDEX = "kb_idx"
DOC_PREFIX = "doc:"
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 3072

_client = redis.Redis.from_url(REDIS_URL, decode_responses=False)
_genai_client = None


def _get_genai_client():
    """Reused genai client (one connection pool, not a new one per search)."""
    global _genai_client
    if _genai_client is None:
        from google import genai

        _genai_client = genai.Client()
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


def _search_bm25(query: str, top_k: int) -> list[dict]:
    terms = re.findall(r"\w+", query.lower())
    if not terms:
        return []
    # OR-join: RediSearch defaults to AND, which zeroes out long queries.
    or_query = "|".join(dict.fromkeys(terms))
    reply = _client.execute_command(
        "FT.SEARCH", KB_INDEX, or_query,
        "LIMIT", "0", str(top_k),
        "RETURN", "3", "title", "section", "content",
    )
    return _parse_search_reply(reply)


def _search_vector(query: str, top_k: int) -> list[dict]:
    vector = struct.pack(f"{EMBEDDING_DIM}f", *_embed([query])[0])
    reply = _client.execute_command(
        "FT.SEARCH", KB_INDEX, f"*=>[KNN {top_k} @embedding $vec AS score]",
        "PARAMS", "2", "vec", vector,
        "SORTBY", "score",
        "LIMIT", "0", str(top_k),
        "RETURN", "4", "title", "section", "content", "score",
        "DIALECT", "2",
    )
    return _strip_score(_parse_search_reply(reply))


def _parent_doc_id(key: str) -> str:
    base = key[len(DOC_PREFIX):] if key.startswith(DOC_PREFIX) else key
    return base.split("#")[0]


def kb_search(query: str, top_k: int = 5) -> list[dict]:
    """Search the Rho-Bank knowledge base and return the most relevant sections.

    Runs keyword (BM25) and semantic (vector) search together and fuses the
    results, so you get the best of both with one call. Use this for any policy
    question, procedure, eligibility rule, or scenario guidance.

    Args:
        query: A natural-language question or keywords. Extra context helps.
        top_k: Number of sections to return.

    Returns:
        Matching sections, each with doc_id, title, section (heading), and content.
    """
    pool = max(top_k * 2, 10)
    bm25 = _search_bm25(query, pool)
    try:
        vector = _search_vector(query, pool)
    except Exception:
        vector = []

    field_map: dict[str, dict] = {}
    for d in bm25 + vector:
        field_map.setdefault(d["doc_id"], d)

    rankings = [[d["doc_id"] for d in bm25]]
    if vector:
        rankings.append([d["doc_id"] for d in vector])
    fused = reciprocal_rank_fusion(rankings, top_k=top_k)

    results = []
    for key in fused:
        d = field_map.get(key, {})
        results.append({
            "doc_id": _parent_doc_id(key),
            "title": d.get("title", ""),
            "section": d.get("section", ""),
            "content": d.get("content", ""),
        })
    return results
