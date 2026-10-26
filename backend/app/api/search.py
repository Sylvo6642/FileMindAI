import logging
from dataclasses import asdict

from fastapi import APIRouter

from app.core.errors import ApiError
from app.models.agent import (
    ActivityStepOut,
    AgentMatchOut,
    AgentSearchRequest,
    AgentSearchResponse,
    MatchExcerptOut,
    UsageOut,
)
from app.models.search import FileMatchOut, SemanticSearchRequest, SemanticSearchResponse
from app.services import agent_service, history_service, search_service, vector_service
from app.services.agent_service import AgentError
from app.services.embedding_service import EmbeddingError

logger = logging.getLogger("filemind")

router = APIRouter(prefix="/api/search", tags=["search"])


def _clean_query(query: str) -> str:
    query = query.strip()
    if not query:
        raise ApiError(400, "empty_query", "Search query cannot be blank.")
    return query


@router.post("", response_model=AgentSearchResponse)
def agent_search(request: AgentSearchRequest) -> AgentSearchResponse:
    """Claude decides which tools to call; the backend runs them and verifies the answer."""
    query = _clean_query(request.query)

    if vector_service.count_all_vectors() == 0:
        # Nothing to search: answer directly instead of paying for an LLM call.
        return AgentSearchResponse(
            query=query,
            answer="No documents have been indexed yet. Upload some files first.",
            matches=[], activity=[], tool_rounds=0, model=None,
            usage=UsageOut(input_tokens=0, output_tokens=0),
        )

    try:
        result = agent_service.run_search_agent(query)
    except AgentError as exc:
        raise ApiError(502, "assistant_unavailable", str(exc))

    response = AgentSearchResponse(
        query=query,
        answer=result.answer,
        matches=[
            AgentMatchOut(
                file_id=m.file_id,
                filename=m.filename,
                file_type=m.file_type,
                reason=m.reason,
                similarity=m.similarity,
                excerpts=[
                    MatchExcerptOut(location=e["location"], text=e["document_text"]) for e in m.excerpts
                ],
            )
            for m in result.matches
        ],
        activity=[ActivityStepOut(**asdict(step)) for step in result.activity],
        tool_rounds=result.tool_rounds,
        model=result.model,
        usage=UsageOut(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
    )
    try:
        return history_service.save(response)
    except Exception:
        # The answer was already paid for: show it even if history can't be written.
        logger.exception("Could not save search to history")
        return response


# Retrieval only, no LLM. Useful for debugging and for measuring retrieval quality.
@router.post("/semantic", response_model=SemanticSearchResponse)
def semantic_search(request: SemanticSearchRequest) -> SemanticSearchResponse:
    query = _clean_query(request.query)

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
