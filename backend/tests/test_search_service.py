import uuid

import pytest

from app.core.config import settings
from app.core.database import init_db
from app.services import metadata_service, vector_service
from app.services.chunking_service import Chunk
from app.services.search_service import best_passage, format_location, search_files
from tests.fake_openai import fake_vector


@pytest.fixture(autouse=True)
def database():
    init_db()


def _index_file(filename: str, texts: list[str], status: str = "indexed", with_row: bool = True) -> str:
    """Store a file's chunks directly, bypassing upload, for precise control."""
    file_id = str(uuid.uuid4())
    if with_row:
        metadata_service.insert_document(
            file_id=file_id, filename=filename, file_type="txt", stored_name=f"{file_id}.txt",
            sha256=file_id, size_bytes=1, status=status, page_count=None,
            char_count=sum(map(len, texts)), chunk_count=len(texts), extraction_warnings=[],
        )
    chunks = [
        Chunk(chunk_index=i, text=t, token_count=10, line_start=i * 10 + 1, line_end=i * 10 + 9)
        for i, t in enumerate(texts)
    ]
    vectors = [fake_vector(t, settings.embedding_dimensions) for t in texts]
    vector_service.upsert_chunks(file_id, filename, "txt", chunks, vectors)
    return file_id


def test_chunks_from_one_file_are_grouped_into_one_result():
    _index_file("agreement.txt", [
        "software development agreement",
        "software development fees",
        "software development warranty",
    ])
    _index_file("other.txt", ["software notes"])

    results = search_files("software development", limit=5)

    assert [r.filename for r in results] == ["agreement.txt", "other.txt"]
    assert results[0].matching_chunks == 3
    assert len({r.file_id for r in results}) == len(results)


def test_files_are_ranked_by_their_best_chunk():
    _index_file("weak.txt", ["website", "website hosting"])
    _index_file("strong.txt", ["unrelated filler words", "website maintenance contract"])

    results = search_files("website maintenance contract", limit=5)

    assert results[0].filename == "strong.txt"
    assert results[0].similarity > results[1].similarity
    assert [r.rank for r in results] == [1, 2]


def test_limit_bounds_the_number_of_files():
    for i in range(6):
        _index_file(f"file{i}.txt", [f"invoice payment number {i}"])
    assert len(search_files("invoice payment", limit=3)) == 3


def test_unrelated_chunks_are_dropped():
    _index_file("cake.txt", ["chocolate cake recipe"])
    assert search_files("employment notice period", limit=5) == []


def test_orphaned_and_unindexed_vectors_are_ignored():
    _index_file("orphan.txt", ["website maintenance"], with_row=False)
    _index_file("failed.txt", ["website maintenance"], status="failed")
    good = _index_file("good.txt", ["website maintenance"])

    assert [r.file_id for r in search_files("website maintenance", limit=5)] == [good]


def test_one_long_file_cannot_crowd_out_other_candidates():
    # 30 near-identical chunks: more than the initial pool of limit * 8 = 16.
    _index_file("long.txt", [f"annual support fees section {i}" for i in range(30)])
    _index_file("short.txt", ["annual support"])

    results = search_files("annual support fees", limit=2)

    assert {r.filename for r in results} == {"long.txt", "short.txt"}


def test_excerpts_are_bounded_and_referenced():
    _index_file("long.txt", [f"payment terms clause {i}" for i in range(6)])

    [match] = search_files("payment terms", limit=1)

    assert len(match.excerpts) == settings.search_excerpts_per_file
    first = match.excerpts[0]
    assert first.location.startswith("lines ")
    assert first.references["line_start"] >= 1
    assert len(first.text) <= settings.search_excerpt_chars + 4


def test_best_passage_finds_the_relevant_sentence():
    text = (
        "Office move: the team moves to the 4th floor. "
        "Vendor payment: approved an advance payment of ₹50,000 to Omega Printing. "
        "Laptop refresh: six laptops are out of warranty."
    )
    passage = best_passage(text, "payment of 50000 rupees", max_chars=90)
    assert "₹50,000" in passage


def test_best_passage_falls_back_to_the_start():
    text = "First sentence here. Second sentence here."
    assert best_passage(text, "zzz", max_chars=25).startswith("First sentence here.")


@pytest.mark.parametrize(
    ("refs", "expected"),
    [
        ({"page_start": 2, "page_end": 2}, "page 2"),
        ({"page_start": 1, "page_end": 4}, "pages 1-4"),
        ({"line_start": 3, "line_end": 9}, "lines 3-9"),
        ({"paragraph_start": 4, "paragraph_end": 6, "section": "Fees"}, "paragraphs 4-6 (section: Fees)"),
        ({}, "unknown location"),
    ],
)
def test_format_location(refs, expected):
    assert format_location(refs) == expected
