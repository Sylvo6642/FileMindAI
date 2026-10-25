"""Learning/debug endpoints that expose the raw retrieval layer.

/nearest-chunks shows exactly what the vector database returns for a query:
individual chunks, ranked by cosine distance, with no grouping by file. The
real search (Stage 4) builds on this.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.errors import ApiError
from app.services import consistency_service, embedding_service, vector_service
from app.services.embedding_service import EmbeddingError

router = APIRouter(prefix="/api/debug", tags=["debug"])


class NearestChunksRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    n: int = Field(default=8, ge=1, le=20)


class ChunkHitOut(BaseModel):
    rank: int
    chunk_id: str
    filename: str
    chunk_index: int
    distance: float
    references: dict[str, int | str]
    excerpt: str


class NearestChunksResponse(BaseModel):
    query: str
    embedding_dimensions: int
    total_vectors: int
    hits: list[ChunkHitOut]


_REFERENCE_KEYS = (
    "page_start", "page_end", "paragraph_start", "paragraph_end", "line_start", "line_end", "section",
)


class ConsistencyOut(BaseModel):
    ok: bool
    documents: int
    vectors: int
    orphan_files: list[str]
    orphan_vectors: dict[str, int]
    missing_files: list[str]
    vector_mismatches: dict[str, dict[str, int]]


@router.get("/consistency", response_model=ConsistencyOut)
def consistency() -> ConsistencyOut:
    """Read-only report: do SQLite, uploads/ and ChromaDB agree? (Repair runs at startup.)"""
    report = consistency_service.check()
    return ConsistencyOut(ok=report.ok, **vars(report))


@router.post("/nearest-chunks", response_model=NearestChunksResponse)
def nearest_chunks(request: NearestChunksRequest) -> NearestChunksResponse:
    try:
        query_vector = embedding_service.embed_query(request.query)
    except EmbeddingError as exc:
        raise ApiError(502, "embedding_failed", str(exc))

    hits = vector_service.query_chunks(query_vector, request.n)
    return NearestChunksResponse(
        query=request.query,
        embedding_dimensions=len(query_vector),
        total_vectors=vector_service.count_all_vectors(),
        hits=[
            ChunkHitOut(
                rank=rank,
                chunk_id=hit.chunk_id,
                filename=hit.filename,
                chunk_index=hit.chunk_index,
                distance=round(hit.distance, 4),
                references={k: hit.metadata[k] for k in _REFERENCE_KEYS if k in hit.metadata},
                excerpt=hit.text[:300],
            )
            for rank, hit in enumerate(hits, start=1)
        ],
    )
