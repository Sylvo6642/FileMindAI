import pytest

from app.core.config import settings
from app.services import lexical_service, search_service, vector_service
from app.services.lexical_service import tokenize


@pytest.mark.parametrize(
    ("query", "document", "shared"),
    [
        ("50000 rupees", "an advance payment of ₹50,000", "50000"),
        ("32 lakh", "estimated budget is INR 32,00,000", "3200000"),
        ("1.5 crore", "valued at 1,50,00,000", "15000000"),
        ("total 1,23,900", "Total due INR 123900", "123900"),
        ("annual support fee", "annual support fees", "fee"),
        ("functional requirement", "Schedule A - functional requirements", "requirement"),
    ],
)
def test_number_and_plural_forms_meet(query, document, shared):
    assert shared in set(tokenize(query)) & set(tokenize(document))


def test_stopwords_and_short_words_are_dropped_but_numbers_kept():
    assert tokenize("Find the file with a 4 in it") == ["4"]


def test_rare_terms_outrank_common_ones(client, upload):
    upload("a.txt", "Contract for office cleaning. Payment terms apply.")
    upload("b.txt", "Contract for catering. Payment of 50,000 approved.")
    upload("c.txt", "Contract for security guards. Payment monthly.")

    hits = lexical_service.search("contract payment 50000")

    assert [hit.file_id for hit in hits][0] == search_service.search_files("catering")[0].file_id
    assert len(hits) == 3  # every chunk shares "contract", but b wins on the rare amount


def test_index_follows_uploads_and_deletes(client, upload):
    assert lexical_service.search("pickle") == []
    file_id = upload("recipe.txt", "Mango pickle recipe")["file_id"]
    assert [hit.file_id for hit in lexical_service.search("pickle")] == [file_id]

    client.delete(f"/api/documents/{file_id}")
    assert lexical_service.search("pickle") == []


def test_hybrid_finds_an_exact_amount_vector_search_misses(client, upload, monkeypatch):
    # The fake embedder splits "50,000" into "50" and "000", so the vector for
    # "50000" shares nothing with it, just like real embeddings struggle here.
    note = upload("notes.txt", "Vendor update: advance of ₹50,000 approved for Omega Printing.")
    upload("other.txt", "Rupees and payment schedules for the rupees payment plan.")

    monkeypatch.setattr(settings, "search_mode", "vector")
    assert note["file_id"] not in [m.file_id for m in search_service.search_files("payment of 50000 rupees")]

    monkeypatch.setattr(settings, "search_mode", "hybrid")
    matches = search_service.search_files("payment of 50000 rupees")
    found = {m.file_id: m for m in matches}
    assert found[note["file_id"]].matched_by == "keyword"
    assert "50,000" in found[note["file_id"]].excerpts[0].text
    assert 0.0 <= found[note["file_id"]].similarity <= 1.0  # real cosine, computed on demand


def test_file_found_both_ways_is_marked_both(client, upload):
    record = upload("plan.txt", "Website maintenance plan with annual support fees.")

    [match] = search_service.search_files("website maintenance")

    assert match.file_id == record["file_id"]
    assert match.matched_by == "both"


def test_keyword_hits_for_deleted_or_failed_files_are_ignored(client, upload):
    record = upload("notes.txt", "Advance of ₹50,000 approved.")
    vector_service.delete_file_vectors(record["file_id"])

    assert search_service.search_files("50000") == []
