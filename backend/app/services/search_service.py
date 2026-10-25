"""Semantic file search: from a natural-language query to a ranked list of files.

The vector database returns *chunks*. Users want *files*. So:
1. Embed the query with the same model used for the documents.
2. Fetch a pool of nearest chunks (more than we need, since many may share a file).
3. Drop chunks that are too far away to be plausible matches.
4. Group the remaining chunks by file. A file's score is its BEST chunk:
   one highly relevant clause in a 40-page contract should not be averaged away.
5. Rank files, keep the top `limit`, and attach short excerpts with references.

Similarity here is 1 - cosine distance. It is a relative ranking signal, not a
confidence percentage: 0.6 means "closer than 0.4", not "60% sure".
"""

import re
from dataclasses import dataclass, field

from app.core.config import settings
from app.services import embedding_service, metadata_service, vector_service
from app.services.vector_service import ChunkHit

MAX_POOL = 200

_WORD = re.compile(r"\w+")
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+|\n+")
_STOPWORDS = {
    "the", "and", "for", "with", "about", "find", "where", "document", "documents", "file",
    "files", "that", "this", "from", "are", "was", "which", "locate", "show", "related",
    "mentioning", "between", "dont", "remember", "its", "filename", "what", "who", "any",
}


@dataclass
class Excerpt:
    chunk_id: str
    chunk_index: int
    similarity: float
    location: str
    references: dict[str, int | str]
    text: str


@dataclass
class FileMatch:
    rank: int
    file_id: str
    filename: str
    file_type: str
    similarity: float
    matching_chunks: int
    excerpts: list[Excerpt] = field(default_factory=list)


def search_files(query: str, limit: int = 5) -> list[FileMatch]:
    query_vector = embedding_service.embed_query(query)
    hits = _nearest_chunks_covering_files(query_vector, limit)

    plausible = [hit for hit in hits if hit.distance <= settings.search_max_distance]
    by_file: dict[str, list[ChunkHit]] = {}
    for hit in plausible:  # hits arrive sorted best-first
        by_file.setdefault(hit.file_id, []).append(hit)

    # Ignore vectors whose document no longer exists or is not fully indexed.
    records = metadata_service.get_documents_by_ids(list(by_file))
    ranked = sorted(
        (file_hits for file_id, file_hits in by_file.items()
         if file_id in records and records[file_id].status == "indexed"),
        key=lambda file_hits: (file_hits[0].distance, -len(file_hits)),
    )

    matches = []
    for rank, file_hits in enumerate(ranked[:limit], start=1):
        record = records[file_hits[0].file_id]
        matches.append(
            FileMatch(
                rank=rank,
                file_id=record.file_id,
                filename=record.filename,
                file_type=record.file_type,
                similarity=_similarity(file_hits[0]),
                matching_chunks=len(file_hits),
                excerpts=[
                    _excerpt(hit, query) for hit in file_hits[: settings.search_excerpts_per_file]
                ],
            )
        )
    return matches


def _nearest_chunks_covering_files(query_vector: list[float], limit: int) -> list[ChunkHit]:
    """Grow the chunk pool until it spans `limit` files (or runs out).

    Without this, one long document could fill the whole pool with its own
    chunks and push every other candidate file out of the results.
    """
    total = vector_service.count_all_vectors()
    pool = min(limit * 8, MAX_POOL)
    while True:
        hits = vector_service.query_chunks(query_vector, pool)
        distinct_files = len({hit.file_id for hit in hits})
        if distinct_files >= limit or pool >= total or pool >= MAX_POOL:
            return hits
        pool = min(pool * 2, MAX_POOL)


def _similarity(hit: ChunkHit) -> float:
    return round(1.0 - hit.distance, 3)


def _excerpt(hit: ChunkHit, query: str) -> Excerpt:
    references = {
        key: hit.metadata[key]
        for key in (
            "page_start", "page_end", "paragraph_start", "paragraph_end",
            "line_start", "line_end", "section",
        )
        if key in hit.metadata
    }
    return Excerpt(
        chunk_id=hit.chunk_id,
        chunk_index=hit.chunk_index,
        similarity=_similarity(hit),
        location=format_location(references),
        references=references,
        text=best_passage(hit.text, query, settings.search_excerpt_chars),
    )


def format_location(refs: dict[str, int | str]) -> str:
    """Human-readable source reference, e.g. 'pages 2-3' or 'lines 4-9'."""
    def span(start_key: str, end_key: str, singular: str, plural: str) -> str | None:
        start, end = refs.get(start_key), refs.get(end_key)
        if start is None:
            return None
        return f"{singular} {start}" if start == end or end is None else f"{plural} {start}-{end}"

    parts = [
        span("page_start", "page_end", "page", "pages"),
        span("paragraph_start", "paragraph_end", "paragraph", "paragraphs"),
        span("line_start", "line_end", "line", "lines"),
    ]
    location = ", ".join(part for part in parts if part)
    if refs.get("section"):
        location = f"{location} (section: {refs['section']})" if location else f"section: {refs['section']}"
    return location or "unknown location"


def _terms(text: str) -> set[str]:
    # "50,000" and "50000" should match, so digit groups are joined first.
    normalized = re.sub(r"(?<=\d)[,.](?=\d{2,3}\b)", "", text.lower())
    return {w for w in _WORD.findall(normalized) if len(w) > 2 and w not in _STOPWORDS}


def best_passage(text: str, query: str, max_chars: int) -> str:
    """Pick the sentence that shares the most words with the query, plus neighbours.

    Retrieval already decided this chunk is relevant by meaning; this only
    chooses which part of it to show. Falls back to the chunk's start.
    """
    sentences = [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]
    if not sentences:
        return ""
    query_terms = _terms(query)
    scores = [len(query_terms & _terms(sentence)) for sentence in sentences]
    best = max(range(len(sentences)), key=lambda i: scores[i]) if any(scores) else 0

    start = end = best
    passage = sentences[best]
    # Grow around the best sentence while there is room.
    while True:
        grew = False
        if end + 1 < len(sentences) and len(passage) + len(sentences[end + 1]) + 1 <= max_chars:
            end += 1
            passage = f"{passage} {sentences[end]}"
            grew = True
        if start > 0 and len(passage) + len(sentences[start - 1]) + 1 <= max_chars:
            start -= 1
            passage = f"{sentences[start]} {passage}"
            grew = True
        if not grew:
            break

    if len(passage) > max_chars:
        passage = passage[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    prefix = "… " if start > 0 else ""
    suffix = " …" if end < len(sentences) - 1 and not passage.endswith("…") else ""
    return f"{prefix}{passage}{suffix}"
