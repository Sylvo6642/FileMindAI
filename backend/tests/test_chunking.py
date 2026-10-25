from app.services.chunking_service import chunk_segments, count_tokens, make_chunk_id
from app.services.extraction_service import TextSegment


def _sentences(n: int, prefix: str = "Sentence") -> str:
    return " ".join(f"{prefix} number {i} talks about software contracts." for i in range(n))


def test_short_text_is_a_single_chunk():
    chunks = chunk_segments([TextSegment("A short note.", line=1)], max_tokens=600)
    assert len(chunks) == 1
    assert chunks[0].text == "A short note."
    assert (chunks[0].line_start, chunks[0].line_end) == (1, 1)


def test_long_text_is_split_within_token_budget():
    chunks = chunk_segments([TextSegment(_sentences(200), page=1)], max_tokens=100, overlap_tokens=20)

    assert len(chunks) > 5
    for chunk in chunks:
        # Joining sentences can add a token or two, hence "approximately".
        assert chunk.token_count <= 105
        assert chunk.token_count == count_tokens(chunk.text)


def test_consecutive_chunks_overlap():
    chunks = chunk_segments([TextSegment(_sentences(60))], max_tokens=100, overlap_tokens=30)

    for previous, current in zip(chunks, chunks[1:]):
        last_sentence = previous.text.split(". ")[-1]
        assert last_sentence in current.text


def test_no_overlap_when_disabled():
    chunks = chunk_segments([TextSegment(_sentences(60))], max_tokens=100, overlap_tokens=0)
    joined = " ".join(c.text for c in chunks)
    assert joined.count("number 7 talks") == 1


def test_chunk_indexes_are_sequential():
    chunks = chunk_segments([TextSegment(_sentences(80))], max_tokens=100, overlap_tokens=20)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_page_ranges_are_preserved():
    segments = [TextSegment(_sentences(5, f"Page{p}"), page=p) for p in range(1, 6)]
    chunks = chunk_segments(segments, max_tokens=120, overlap_tokens=0)

    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 5
    for chunk in chunks:
        for page in range(1, 6):
            if f"Page{page} " in chunk.text:
                assert chunk.page_start <= page <= chunk.page_end


def test_docx_section_and_paragraph_range_are_preserved():
    segments = [
        TextSegment("Fees are due annually.", paragraph=4, section="Payment Terms"),
        TextSegment("Late fees apply.", paragraph=5, section="Payment Terms"),
    ]
    [chunk] = chunk_segments(segments, max_tokens=600)
    assert (chunk.paragraph_start, chunk.paragraph_end, chunk.section) == (4, 5, "Payment Terms")
    assert chunk.text == "Fees are due annually.\nLate fees apply."


def test_oversized_sentence_without_punctuation_is_split():
    giant = "word " * 1000  # one "sentence" far larger than the budget
    chunks = chunk_segments([TextSegment(giant)], max_tokens=100, overlap_tokens=0)
    assert len(chunks) >= 10
    assert all(c.token_count <= 105 for c in chunks)


def test_chunk_ids_are_stable():
    assert make_chunk_id("abc", 3) == "abc:3"
    assert make_chunk_id("abc", 3) == make_chunk_id("abc", 3)
