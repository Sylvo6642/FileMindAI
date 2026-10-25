from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import consistency_service, metadata_service, vector_service

ORPHAN = "11111111-2222-3333-4444-555555555555.txt"


def test_fresh_library_is_consistent(client, upload):
    upload("notes.txt", "Payment of 50000 rupees.")
    upload("plan.txt", "Website maintenance plan.")

    report = consistency_service.check()

    assert report.ok
    assert (report.documents, report.vectors) == (2, 2)


def test_orphan_file_is_removed_but_foreign_files_are_left_alone(client):
    (settings.uploads_dir / ORPHAN).write_text("left behind")
    (settings.uploads_dir / "readme.md").write_text("not ours")

    assert consistency_service.check().orphan_files == [ORPHAN]
    consistency_service.repair()

    assert sorted(p.name for p in settings.uploads_dir.iterdir()) == ["readme.md"]
    assert consistency_service.check().ok


def test_vectors_without_a_row_are_removed(client, upload):
    file_id = upload("notes.txt", "Payment of 50000 rupees.")["file_id"]
    metadata_service.delete_document(file_id)  # row gone, vectors left behind

    assert consistency_service.check().orphan_vectors == {file_id: 1}
    consistency_service.repair()

    assert vector_service.count_file_vectors(file_id) == 0


def test_missing_original_marks_document_failed_and_hides_it_from_search(client, upload):
    record = upload("notes.txt", "Payment of 50000 rupees.")
    (settings.uploads_dir / f"{record['file_id']}.txt").unlink()

    assert consistency_service.check().missing_files == [record["file_id"]]
    consistency_service.repair()

    repaired = metadata_service.get_document(record["file_id"])
    assert repaired.status == "failed"
    assert "missing" in repaired.error_message
    assert vector_service.count_file_vectors(record["file_id"]) == 0
    assert consistency_service.check().missing_files == [record["file_id"]]  # still reported


def test_partial_vectors_mark_document_failed_and_reindex_fixes_it(client, upload):
    file_id = upload("notes.txt", "Payment of 50000 rupees.")["file_id"]
    vector_service.delete_file_vectors(file_id)

    assert consistency_service.check().vector_mismatches == {file_id: {"expected": 1, "stored": 0}}
    consistency_service.repair()
    assert metadata_service.get_document(file_id).status == "failed"

    assert client.post(f"/api/documents/{file_id}/reindex").json()["status"] == "indexed"
    assert consistency_service.check().ok


def test_startup_runs_repair(client):
    (settings.uploads_dir / ORPHAN).write_text("left behind")

    with TestClient(app):  # a second startup
        pass

    assert not (settings.uploads_dir / ORPHAN).exists()


def test_consistency_endpoint(client, upload):
    upload("notes.txt", "Payment of 50000 rupees.")
    (settings.uploads_dir / ORPHAN).write_text("left behind")

    body = client.get("/api/debug/consistency").json()

    assert body["ok"] is False
    assert body["orphan_files"] == [ORPHAN]
    assert (body["documents"], body["vectors"]) == (1, 1)
