"""Semantic file search: from a natural-language query to a ranked list of files.

The vector database returns *chunks*. Users want *files*. So:
1. Embed the query with the same model used for the documents.
2. Fetch a pool of nearest chunks (more than we need, since many may share a file).
3. Drop chunks that are too far away to be plausible matches.
4. Group the remaining chunks by file. A file's score is its BEST chunk:
   one highly relevant clause in a 40-page contract should not be averaged away.
5. Rank files, keep the top `limit`, and attach short excerpts with references.

In "hybrid" mode (the default) a keyword ranking (BM25, see lexical_service)
is merged in with Reciprocal Rank Fusion: each file scores 1/(k + rank) in
every ranking it appears in, and the scores are summed. RRF only uses ranks,
so the two very different score scales never have to be compared. A file
found only by keywords (an exact amount, a rare name) can now be returned
even when its meaning-similarity is low.

Similarity here is 1 - cosine distance. It is a relative ranking signal, not a
confidence percentage: 0.6 means "closer than 0.4", not "60% sure".
"""

import re
from dataclasses import dataclass, field

from app.core.config import settings
from app.services import embedding_service, lexical_service, metadata_service, vector_service
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
    # Which ranking found the file: "semantic", "keyword" or "both".
    matched_by: str = "semantic"


def search_files(
    query: str, limit: int = 5, query_vector: list[float] | None = None
) -> list[FileMatch]:
    if query_vector is None:
        query_vector = embedding_service.embed_query(query)
    hits = _nearest_chunks_covering_files(query_vector, limit)

    plausible = [hit for hit in hits if hit.distance <= settings.search_max_distance]
    by_file: dict[str, list[ChunkHit]] = {}
    for hit in plausible:  # hits arrive sorted best-first
        by_file.setdefault(hit.file_id, []).append(hit)
    semantic_order = sorted(by_file, key=lambda f: (by_file[f][0].distance, -len(by_file[f])))

    keyword_order: list[str] = []
    if settings.search_mode == "hybrid":
        keyword_order = _add_keyword_hits(query, query_vector, by_file)

    # Ignore vectors whose document no longer exists or is not fully indexed.
    records = metadata_service.get_documents_by_ids(list(by_file))
    indexed = {f for f in by_file if f in records and records[f].status == "indexed"}

    scores: dict[str, float] = {}
    for order in (semantic_order, keyword_order):
        for rank, file_id in enumerate((f for f in order if f in indexed), start=1):
            scores[file_id] = scores.get(file_id, 0.0) + 1 / (settings.search_rrf_k + rank)
    best_distance = {f: min(hit.distance for hit in by_file[f]) for f in indexed}
    ranked = sorted(indexed, key=lambda f: (-scores[f], best_distance[f]))

    semantic, keyword = set(semantic_order), set(keyword_order)
    matches = []
    for rank, file_id in enumerate(ranked[:limit], start=1):
        record, file_hits = records[file_id], by_file[file_id]
        matches.append(
            FileMatch(
                rank=rank,
                file_id=record.file_id,
                filename=record.filename,
                file_type=record.file_type,
                similarity=round(1.0 - best_distance[file_id], 3),
                matching_chunks=len(file_hits),
                excerpts=[
                    _excerpt(hit, query) for hit in file_hits[: settings.search_excerpts_per_file]
                ],
                matched_by=(
                    "both" if file_id in semantic and file_id in keyword
                    else "keyword" if file_id in keyword else "semantic"
                ),
            )
        )
    return matches


def _add_keyword_hits(
    query: str, query_vector: list[float], by_file: dict[str, list[ChunkHit]]
) -> list[str]:
    """Merge each file's best keyword chunk into by_file; return files in keyword order."""
    best_chunk: dict[str, str] = {}
    for hit in lexical_service.search(query, limit=MAX_POOL):  # best first
        best_chunk.setdefault(hit.file_id, hit.chunk_id)

    known = {hit.chunk_id for file_hits in by_file.values() for hit in file_hits}
    fetched = {
        hit.chunk_id: hit
        for hit in vector_service.get_chunks(
            [chunk_id for chunk_id in best_chunk.values() if chunk_id not in known], query_vector
        )
    }
    for file_id, chunk_id in best_chunk.items():
        if chunk_id in fetched:
            # Shown right after the best semantic excerpt, so both reasons are visible.
            file_hits = by_file.setdefault(file_id, [])
            file_hits.insert(min(1, len(file_hits)), fetched[chunk_id])
    return [file_id for file_id in best_chunk if file_id in by_file]


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
