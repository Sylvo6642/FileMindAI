from app.core.config import settings
from app.services import vector_service
from app.services.chunking_service import Chunk
from tests.fake_openai import fake_vector


def _vec(text: str) -> list[float]:
    return fake_vector(text, settings.embedding_dimensions)


def _store(file_id: str, filename: str, texts: list[str], **refs) -> None:
    chunks = [Chunk(chunk_index=i, text=t, token_count=5, **refs) for i, t in enumerate(texts)]
    vector_service.upsert_chunks(file_id, filename, "txt", chunks, [_vec(t) for t in texts])


def test_insert_and_count():
    _store("file-a", "a.txt", ["first chunk", "second chunk"])
    assert vector_service.count_file_vectors("file-a") == 2
    assert vector_service.count_all_vectors() == 2


def test_upsert_with_stable_ids_does_not_duplicate():
    _store("file-a", "a.txt", ["first chunk", "second chunk"])
    _store("file-a", "a.txt", ["first chunk", "second chunk"])
    assert vector_service.count_file_vectors("file-a") == 2


def test_nearest_chunk_is_returned_first():
    _store("maint", "document_final.docx", ["website maintenance and annual support fees"])
    _store("hr", "contract_045.pdf", ["employee salary leave and notice period"])

    hits = vector_service.query_chunks(_vec("website maintenance contract"), n_results=2)

    assert [h.filename for h in hits] == ["document_final.docx", "contract_045.pdf"]
    assert hits[0].distance < hits[1].distance


def test_metadata_and_references_round_trip():
    _store("file-a", "a.pdf", ["payment terms"], page_start=2, page_end=3)
    [hit] = vector_service.query_chunks(_vec("payment terms"), n_results=1)

    assert hit.chunk_id == "file-a:0"
    assert hit.metadata["page_start"] == 2 and hit.metadata["page_end"] == 3
    assert "line_start" not in hit.metadata  # None values are omitted
    assert hit.text == "payment terms"


def test_empty_collection_returns_no_hits():
    assert vector_service.query_chunks(_vec("anything"), n_results=5) == []


def test_n_results_larger_than_collection():
    _store("file-a", "a.txt", ["only one chunk"])
    assert len(vector_service.query_chunks(_vec("chunk"), n_results=50)) == 1


def test_delete_removes_only_that_file():
    _store("file-a", "a.txt", ["alpha text"])
    _store("file-b", "b.txt", ["beta text"])

    vector_service.delete_file_vectors("file-a")

    assert vector_service.count_file_vectors("file-a") == 0
    assert vector_service.count_file_vectors("file-b") == 1


def test_vectors_persist_across_client_restarts():
    _store("file-a", "a.txt", ["persisted chunk"])
    vector_service._client.cache_clear()  # simulate a fresh process opening the folder
    assert vector_service.count_file_vectors("file-a") == 1


def test_collection_name_includes_model_and_dimensions():
    assert vector_service.collection_name() == "chunks__text-embedding-3-small__1536"
