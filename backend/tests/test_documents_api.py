import pytest
import httpx
import openai

from app.core.config import settings
from app.services import document_service, metadata_service, vector_service
from tests.sample_files import make_docx, make_image_only_pdf, make_pdf

TXT = "text/plain"
PDF = "application/pdf"


def _upload(client, name: str, data: bytes, content_type: str = TXT):
    return client.post("/api/documents/upload", files={"file": (name, data, content_type)})


def _uploaded_files() -> list[str]:
    return sorted(p.name for p in settings.uploads_dir.iterdir())


def test_upload_txt_is_embedded_and_indexed(client, fake_openai):
    response = _upload(client, "notes.txt", b"Meeting notes about the AI proposal.")

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "notes.txt"
    assert body["file_type"] == "txt"
    assert body["status"] == "indexed"
    assert body["chunk_count"] == 1
    assert vector_service.count_file_vectors(body["file_id"]) == 1
    assert len(fake_openai.embeddings.calls) == 1
    assert "stored_name" not in body  # internal paths are never exposed
    assert _uploaded_files() == [f"{body['file_id']}.txt"]


def test_upload_pdf_and_docx(client):
    pdf = _upload(client, "agreement_001.pdf", make_pdf(["Software agreement.", "Fees."]), PDF)
    docx = _upload(client, "document_final.docx", make_docx([("p", "Website maintenance.")]))

    assert pdf.status_code == 201 and pdf.json()["page_count"] == 2
    assert docx.status_code == 201 and docx.json()["page_count"] is None


def test_duplicate_upload_is_rejected_even_with_new_name(client, fake_openai):
    first = _upload(client, "a.txt", b"same content").json()
    second = _upload(client, "renamed.txt", b"same content")

    assert second.status_code == 409
    error = second.json()["error"]
    assert error["code"] == "duplicate_file"
    assert error["file_id"] == first["file_id"]
    assert len(_uploaded_files()) == 1
    assert len(fake_openai.embeddings.calls) == 1  # no paid API call for the duplicate


def test_unsupported_and_invalid_uploads_store_nothing(client):
    assert _upload(client, "x.exe", b"MZ").status_code == 415
    assert _upload(client, "fake.pdf", b"not a pdf", PDF).status_code == 400
    assert _upload(client, "empty.txt", b"").status_code == 400
    assert _upload(client, "blank.txt", b"   \n  ").status_code == 422

    scanned = _upload(client, "scan.pdf", make_image_only_pdf(), PDF)
    assert scanned.status_code == 422
    assert "OCR" in scanned.json()["error"]["message"]

    assert _uploaded_files() == []
    assert client.get("/api/documents").json()["count"] == 0


def test_too_large_upload(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 1024)
    response = _upload(client, "big.txt", b"a" * 2048)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_path_traversal_filename_is_neutralised(client):
    body = _upload(client, "..\\..\\Windows\\evil.txt", b"hello").json()
    assert body["filename"] == "evil.txt"
    assert _uploaded_files() == [f"{body['file_id']}.txt"]


def test_list_and_get(client):
    created = _upload(client, "notes.txt", b"hello").json()

    listing = client.get("/api/documents").json()
    assert listing["count"] == 1
    assert listing["documents"][0]["file_id"] == created["file_id"]

    assert client.get(f"/api/documents/{created['file_id']}").json() == created


def test_invalid_and_unknown_ids(client):
    assert client.get("/api/documents/not-a-uuid").status_code == 422
    missing = client.get("/api/documents/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "document_not_found"


def test_open_returns_original_bytes(client):
    data = make_pdf(["Original content."])
    file_id = _upload(client, "contract.pdf", data, PDF).json()["file_id"]

    response = client.get(f"/api/documents/{file_id}/open")
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == PDF
    assert response.headers["content-disposition"].startswith("inline")


def test_chunk_preview(client):
    text = "\n".join(f"Line {i} of the meeting notes." for i in range(1, 400)).encode()
    file_id = _upload(client, "notes.txt", text).json()["file_id"]

    preview = client.get(f"/api/documents/{file_id}/chunks?limit=2").json()
    assert preview["total_chunks"] > 2
    assert len(preview["chunks"]) == 2
    first = preview["chunks"][0]
    assert first["chunk_id"] == f"{file_id}:0"
    assert first["line_start"] == 1


def test_embedding_failure_keeps_document_as_failed(client, fake_openai):
    fake_openai.embeddings.error = openai.APIConnectionError(request=None)

    body = _upload(client, "notes.txt", b"Notes that cannot be embedded right now.").json()

    assert body["status"] == "failed"
    assert "Could not reach OpenAI" in body["error_message"]
    assert vector_service.count_file_vectors(body["file_id"]) == 0
    assert _uploaded_files() == [f"{body['file_id']}.txt"]  # kept for a later retry


def test_reindex_recovers_a_failed_document(client, fake_openai):
    fake_openai.embeddings.error = openai.APIConnectionError(request=None)
    file_id = _upload(client, "notes.txt", b"Retry me later.").json()["file_id"]

    fake_openai.embeddings.error = None
    body = client.post(f"/api/documents/{file_id}/reindex").json()

    assert body["status"] == "indexed"
    assert body["error_message"] is None
    assert vector_service.count_file_vectors(file_id) == 1


def test_reindex_is_idempotent(client):
    text = "\n".join(f"Line {i} of the meeting notes." for i in range(1, 300)).encode()
    body = _upload(client, "notes.txt", text).json()

    client.post(f"/api/documents/{body['file_id']}/reindex")
    client.post(f"/api/documents/{body['file_id']}/reindex")

    assert vector_service.count_file_vectors(body["file_id"]) == body["chunk_count"]


def test_startup_flags_interrupted_documents(client):
    file_id = _upload(client, "notes.txt", b"Interrupted mid-way.").json()["file_id"]
    metadata_service.update_status(file_id, "processing")

    assert metadata_service.mark_unfinished_as_failed() == 1
    record = metadata_service.get_document(file_id)
    assert record.status == "failed"
    assert "Reindex" in record.error_message


def test_debug_nearest_chunks_ranks_relevant_file_first(client):
    _upload(client, "document_final.docx", make_docx([("p", "Website maintenance and annual support fees.")]))
    _upload(client, "contract_045.pdf", make_pdf(["Employee salary, leave and notice period."]), PDF)

    body = client.post("/api/debug/nearest-chunks", json={"query": "website maintenance"}).json()

    assert body["total_vectors"] == 2
    assert body["hits"][0]["filename"] == "document_final.docx"
    assert body["hits"][0]["distance"] < body["hits"][1]["distance"]


def test_debug_nearest_chunks_reports_embedding_failure(client, fake_openai):
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    fake_openai.embeddings.error = openai.AuthenticationError(
        "bad key", response=httpx.Response(401, request=request), body=None
    )
    response = client.post("/api/debug/nearest-chunks", json={"query": "anything"})
    assert response.status_code == 502
    assert "rejected the API key" in response.json()["error"]["message"]


def test_delete_removes_file_vectors_and_metadata(client):
    file_id = _upload(client, "notes.txt", b"to be deleted").json()["file_id"]
    assert vector_service.count_file_vectors(file_id) == 1

    assert client.delete(f"/api/documents/{file_id}").status_code == 204
    assert _uploaded_files() == []
    assert vector_service.count_file_vectors(file_id) == 0
    assert client.get(f"/api/documents/{file_id}").status_code == 404
    assert client.delete(f"/api/documents/{file_id}").status_code == 404
    # The same content can be uploaded again once deleted.
    assert _upload(client, "notes.txt", b"to be deleted").status_code == 201


def _estimate(client, name: str, data: bytes, content_type: str = TXT):
    return client.post("/api/documents/estimate", files={"file": (name, data, content_type)})


def test_estimate_counts_tokens_without_saving_or_calling_openai(client, fake_openai):
    text = "Annual support fees for the website maintenance contract. " * 400
    response = _estimate(client, "fees.txt", text.encode())

    assert response.status_code == 200, response.text
    body = response.json()
    preview = document_service.chunk_segments(
        document_service.extract(text.encode(), "txt").segments
    )
    assert body["chunk_count"] == len(preview) > 1
    assert body["token_count"] == sum(c.token_count for c in preview)
    assert body["estimated_cost_usd"] == pytest.approx(body["token_count"] / 1_000_000 * 0.02)
    assert body["embedding_model"] == settings.embedding_model
    assert body["duplicate_of"] is None
    # Nothing happened: no embedding call, no stored file, no library entry.
    assert fake_openai.embeddings.calls == []
    assert _uploaded_files() == []
    assert metadata_service.list_documents() == []


def test_estimate_flags_content_already_in_the_library(client):
    _upload(client, "original.txt", b"same content")

    body = _estimate(client, "renamed copy.txt", b"same content").json()

    assert body["duplicate_of"] == "original.txt"


def test_estimate_rejects_what_an_upload_would_reject(client):
    assert _estimate(client, "virus.exe", b"MZ").status_code == 415
    scanned = _estimate(client, "scan.pdf", make_image_only_pdf(), PDF)
    assert scanned.status_code == 422
    assert scanned.json()["error"]["code"] == "extraction_failed"
