from app.core.config import settings
from tests.sample_files import make_docx, make_image_only_pdf, make_pdf

TXT = "text/plain"
PDF = "application/pdf"


def _upload(client, name: str, data: bytes, content_type: str = TXT):
    return client.post("/api/documents/upload", files={"file": (name, data, content_type)})


def _uploaded_files() -> list[str]:
    return sorted(p.name for p in settings.uploads_dir.iterdir())


def test_upload_txt_creates_pending_document(client):
    response = _upload(client, "notes.txt", b"Meeting notes about the AI proposal.")

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "notes.txt"
    assert body["file_type"] == "txt"
    assert body["status"] == "pending"
    assert body["chunk_count"] == 1
    assert "stored_name" not in body  # internal paths are never exposed
    assert _uploaded_files() == [f"{body['file_id']}.txt"]


def test_upload_pdf_and_docx(client):
    pdf = _upload(client, "agreement_001.pdf", make_pdf(["Software agreement.", "Fees."]), PDF)
    docx = _upload(client, "document_final.docx", make_docx([("p", "Website maintenance.")]))

    assert pdf.status_code == 201 and pdf.json()["page_count"] == 2
    assert docx.status_code == 201 and docx.json()["page_count"] is None


def test_duplicate_upload_is_rejected_even_with_new_name(client):
    first = _upload(client, "a.txt", b"same content").json()
    second = _upload(client, "renamed.txt", b"same content")

    assert second.status_code == 409
    error = second.json()["error"]
    assert error["code"] == "duplicate_file"
    assert error["file_id"] == first["file_id"]
    assert len(_uploaded_files()) == 1


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


def test_delete_removes_file_and_metadata(client):
    file_id = _upload(client, "notes.txt", b"to be deleted").json()["file_id"]

    assert client.delete(f"/api/documents/{file_id}").status_code == 204
    assert _uploaded_files() == []
    assert client.get(f"/api/documents/{file_id}").status_code == 404
    assert client.delete(f"/api/documents/{file_id}").status_code == 404
    # The same content can be uploaded again once deleted.
    assert _upload(client, "notes.txt", b"to be deleted").status_code == 201
