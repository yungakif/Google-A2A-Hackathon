"""Split KB documents into section chunks for finer-grained retrieval.

Pure functions, no I/O — so ingest.py and precompute_embeddings.py share one
deterministic chunking definition (chunk ids MUST match between them)."""

import re

MAX_CHUNK_CHARS = 1500
_HEADING_RE = re.compile(r"^#{1,6}\s+\S.*$", re.MULTILINE)


def _split_oversized(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split text longer than `limit` on blank-line (paragraph) boundaries."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        if current and len(current) + len(para) + 2 > limit:
            parts.append(current.strip())
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current.strip():
        parts.append(current.strip())
    return parts or [text]


def chunk_document(doc: dict) -> list[dict]:
    """Split one KB doc ({id,title,content}) into section chunks.

    Each chunk: {id, doc_id, title, section, content}, id == f"{doc_id}#{n}".
    Splits on markdown headings; preamble before the first heading is its own
    chunk; no headings -> one chunk; oversized sections split on paragraphs."""
    doc_id = doc["id"]
    title = doc.get("title", "")
    content = doc.get("content") or ""

    matches = list(_HEADING_RE.finditer(content))
    raw: list[tuple[str, str]] = []  # (heading, body)
    if not matches:
        raw.append(("", content.strip()))
    else:
        if matches[0].start() > 0:
            pre = content[: matches[0].start()].strip()
            if pre:
                raw.append(("", pre))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            block = content[m.start():end]
            first_line = block.splitlines()[0]
            heading = first_line.lstrip("#").strip()
            body = block[len(first_line):].strip()
            raw.append((heading, body))

    chunks: list[dict] = []
    n = 0
    for heading, body in raw:
        if not heading and not body:
            continue
        for piece in (_split_oversized(body) if body else [""]):
            chunks.append({
                "id": f"{doc_id}#{n}",
                "doc_id": doc_id,
                "title": title,
                "section": heading,
                "content": piece,
            })
            n += 1
    if not chunks:
        chunks.append({"id": f"{doc_id}#0", "doc_id": doc_id, "title": title, "section": "", "content": ""})
    return chunks


def embed_text(chunk: dict) -> str:
    """Text used to embed a chunk: title + section heading + body (skip blanks)."""
    return "\n".join(p for p in (chunk.get("title", ""), chunk.get("section", ""), chunk.get("content", "")) if p)
