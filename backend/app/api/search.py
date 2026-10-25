from dataclasses import asdict

from fastapi import APIRouter

from app.core.errors import ApiError
from app.models.search import FileMatchOut, SemanticSearchRequest, SemanticSearchResponse
from app.services import search_service, vector_service
from app.services.embedding_service import EmbeddingError

router = APIRouter(prefix="/api/search", tags=["search"])


# Retrieval only, no LLM. Stage 5 adds POST /api/search, where Claude calls
# this same search as a tool and reasons about the results.
@router.post("/semantic", response_model=SemanticSearchResponse)
def semantic_search(request: SemanticSearchRequest) -> SemanticSearchResponse:
    query = request.query.strip()
    if not query:
        raise ApiError(400, "empty_query", "Search query cannot be blank.")

    if vector_service.count_all_vectors() == 0:
        return SemanticSearchResponse(
            query=query, result_count=0, results=[], message="No documents have been indexed yet."
        )

    try:
        matches = search_service.search_files(query, request.limit)
    except EmbeddingError as exc:
        raise ApiError(502, "embedding_failed", str(exc))

    return SemanticSearchResponse(
        query=query,
        result_count=len(matches),
        results=[FileMatchOut(**asdict(match)) for match in matches],
        message=None if matches else "No documents matched this description.",
    )
