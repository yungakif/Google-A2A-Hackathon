from chunking import chunk_document, embed_text


def test_splits_on_headings():
    doc = {"id": "doc_x", "title": "T", "content": "## A\nalpha body\n\n## B\nbeta body"}
    chunks = chunk_document(doc)
    assert [c["id"] for c in chunks] == ["doc_x#0", "doc_x#1"]
    assert chunks[0]["section"] == "A"
    assert "alpha body" in chunks[0]["content"]
    assert chunks[0]["doc_id"] == "doc_x"
    assert chunks[1]["section"] == "B"


def test_no_headings_single_chunk():
    doc = {"id": "d", "title": "T", "content": "just text, no headings"}
    chunks = chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0]["id"] == "d#0"
    assert chunks[0]["section"] == ""
    assert "just text" in chunks[0]["content"]


def test_preamble_before_first_heading():
    doc = {"id": "d", "title": "T", "content": "intro line\n\n## Sec\nbody"}
    chunks = chunk_document(doc)
    assert chunks[0]["section"] == ""           # preamble chunk
    assert "intro line" in chunks[0]["content"]
    assert chunks[1]["section"] == "Sec"
    assert "body" in chunks[1]["content"]


def test_oversized_section_is_split():
    big = "\n\n".join(["paragraph number %d here" % i for i in range(400)])
    doc = {"id": "d", "title": "T", "content": "## Big\n" + big}
    chunks = chunk_document(doc)
    assert len(chunks) > 1
    assert all(len(c["content"]) <= 1600 for c in chunks)


def test_embed_text_combines_fields():
    assert embed_text({"title": "T", "section": "S", "content": "C"}) == "T\nS\nC"
    assert embed_text({"title": "T", "section": "", "content": "C"}) == "T\nC"
