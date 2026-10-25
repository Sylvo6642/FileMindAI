"""Token-aware chunking with overlap.

Why chunk at all? An embedding is one vector for a whole piece of text. Embed
a 40-page contract as one vector and its meaning gets averaged into mush; embed
~600-token pieces and each vector stays specific enough to match a query.

How it works:
1. Split every segment into sentences ("units"), remembering their source.
2. Pack units into a chunk until the next one would exceed max_tokens.
3. Start the next chunk with the last ~overlap_tokens worth of units, so a
   sentence near a boundary is never only half-represented.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

import tiktoken

from app.core.config import settings
from app.services.extraction_service import TextSegment

# text-embedding-3-small uses the cl100k_base tokenizer, so we count tokens
# exactly the way the embedding model will.
ENCODING_NAME = "cl100k_base"

_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding(ENCODING_NAME)


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text))


def make_chunk_id(file_id: str, chunk_index: int) -> str:
    """Stable ID: the same file and position always produce the same ID."""
    return f"{file_id}:{chunk_index}"


@dataclass
class Chunk:
    chunk_index: int
    text: str
    token_count: int
    page_start: int | None = None
    page_end: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    section: str | None = None


@dataclass
class _Unit:
    text: str
    tokens: int
    segment_index: int
    segment: TextSegment


def chunk_segments(
    segments: list[TextSegment],
    max_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[Chunk]:
    max_tokens = max_tokens or settings.chunk_size_tokens
    overlap_tokens = settings.chunk_overlap_tokens if overlap_tokens is None else overlap_tokens

    chunks: list[Chunk] = []
    current: list[_Unit] = []
    current_tokens = 0

    for unit in _to_units(segments, max_tokens):
        if current and current_tokens + unit.tokens > max_tokens:
            chunks.append(_build_chunk(len(chunks), current))
            current = _overlap_tail(current, overlap_tokens)
            current_tokens = sum(u.tokens for u in current)
            # If overlap + the next unit is still too big, shrink the overlap.
            while current and current_tokens + unit.tokens > max_tokens:
                current_tokens -= current.pop(0).tokens
        current.append(unit)
        current_tokens += unit.tokens

    if current:
        chunks.append(_build_chunk(len(chunks), current))
    return chunks


def _to_units(segments: list[TextSegment], max_tokens: int):
    for index, segment in enumerate(segments):
        normalized = " ".join(segment.text.split())
        for sentence in _SENTENCE_END.split(normalized):
            if not sentence:
                continue
            tokens = count_tokens(sentence)
            if tokens <= max_tokens:
                yield _Unit(sentence, tokens, index, segment)
            else:
                for piece in _split_long(sentence, max_tokens):
                    yield _Unit(piece, count_tokens(piece), index, segment)


def _split_long(text: str, max_tokens: int) -> list[str]:
    """Split an oversized sentence on word boundaries (tokens as a last resort)."""
    pieces: list[str] = []
    words: list[str] = []
    words_tokens = 0
    for word in text.split(" "):
        word_tokens = count_tokens(" " + word)
        if word_tokens > max_tokens:
            if words:
                pieces.append(" ".join(words))
                words, words_tokens = [], 0
            encoded = _encoding().encode(word)
            pieces.extend(
                _encoding().decode(encoded[i : i + max_tokens])
                for i in range(0, len(encoded), max_tokens)
            )
            continue
        if words and words_tokens + word_tokens > max_tokens:
            pieces.append(" ".join(words))
            words, words_tokens = [], 0
        words.append(word)
        words_tokens += word_tokens
    if words:
        pieces.append(" ".join(words))
    return pieces


def _overlap_tail(units: list[_Unit], overlap_tokens: int) -> list[_Unit]:
    tail: list[_Unit] = []
    total = 0
    for unit in reversed(units):
        if total + unit.tokens > overlap_tokens:
            break
        tail.insert(0, unit)
        total += unit.tokens
    return tail


def _build_chunk(chunk_index: int, units: list[_Unit]) -> Chunk:
    parts: list[str] = []
    previous_segment: int | None = None
    for unit in units:
        if previous_segment is not None:
            # Same segment -> same paragraph; new segment -> new line.
            parts.append(" " if unit.segment_index == previous_segment else "\n")
        parts.append(unit.text)
        previous_segment = unit.segment_index
    text = "".join(parts)

    segments = [unit.segment for unit in units]
    pages = [s.page for s in segments if s.page is not None]
    paragraphs = [s.paragraph for s in segments if s.paragraph is not None]
    lines = [s.line for s in segments if s.line is not None]
    sections = [s.section for s in segments if s.section]

    return Chunk(
        chunk_index=chunk_index,
        text=text,
        token_count=count_tokens(text),
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        paragraph_start=min(paragraphs) if paragraphs else None,
        paragraph_end=max(paragraphs) if paragraphs else None,
        line_start=min(lines) if lines else None,
        line_end=max(lines) if lines else None,
        section=sections[0] if sections else None,
    )
