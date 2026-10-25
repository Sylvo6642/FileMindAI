import openai

from tests.sample_files import make_docx, make_pdf


def _search(client, query: str, **extra):
    return client.post("/api/search/semantic", json={"query": query, **extra})


def test_search_returns_files_with_excerpts(client):
    client.post(
        "/api/documents/upload",
        files={"file": ("document_final.docx", make_docx([
            ("h", "Fees"), ("p", "Annual support fees are invoiced each April."),
        ]), "application/octet-stream")},
    )
    client.post(
        "/api/documents/upload",
        files={"file": ("contract_045.pdf", make_pdf(["Employee leave and notice period."]), "application/pdf")},
    )

    body = _search(client, "annual support fees").json()

    assert body["result_count"] == 1  # the employment contract shares no words: filtered out
    match = body["results"][0]
    assert match["filename"] == "document_final.docx"
    assert match["excerpts"][0]["location"].endswith("(section: Fees)")
    assert "Annual support fees" in match["excerpts"][0]["text"]
    assert body["message"] is None


def test_search_with_no_documents(client):
    body = _search(client, "anything").json()
    assert body["result_count"] == 0
    assert body["message"] == "No documents have been indexed yet."


def test_search_with_no_matches(client):
    client.post("/api/documents/upload", files={"file": ("cake.txt", b"chocolate cake recipe", "text/plain")})
    body = _search(client, "employment contract").json()
    assert body["results"] == []
    assert body["message"] == "No documents matched this description."


def test_search_validates_input(client):
    assert _search(client, "").status_code == 422
    assert _search(client, "   ").status_code == 400
    assert _search(client, "ok", limit=11).status_code == 422
    assert _search(client, "x" * 501).status_code == 422


def test_search_reports_embedding_failure(client, fake_openai):
    client.post("/api/documents/upload", files={"file": ("a.txt", b"some text", "text/plain")})
    fake_openai.embeddings.error = openai.APIConnectionError(request=None)

    response = _search(client, "some text")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "embedding_failed"
