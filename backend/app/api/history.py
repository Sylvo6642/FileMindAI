import uuid

from fastapi import APIRouter, Query, Response, status

from app.core.errors import ApiError
from app.models.agent import AgentSearchResponse, SearchHistoryOut, SearchSummaryOut, UsageOut
from app.services import history_service

router = APIRouter(prefix="/api/searches", tags=["history"])


@router.get("", response_model=SearchHistoryOut)
def list_searches(limit: int = Query(default=50, ge=1, le=200)) -> SearchHistoryOut:
    searches = history_service.list_recent(limit)
    totals = history_service.totals()
    return SearchHistoryOut(
        count=len(searches),
        searches=[
            SearchSummaryOut(
                search_id=s.search_id,
                query=s.query,
                created_at=s.created_at,
                match_count=s.match_count,
                usage=UsageOut(input_tokens=s.input_tokens, output_tokens=s.output_tokens),
            )
            for s in searches
        ],
        total_searches=totals.searches,
        total_usage=UsageOut(input_tokens=totals.input_tokens, output_tokens=totals.output_tokens),
    )


@router.get("/{search_id}", response_model=AgentSearchResponse)
def get_search(search_id: uuid.UUID) -> AgentSearchResponse:
    """The saved answer, exactly as it was shown: no new Claude call."""
    saved = history_service.get(str(search_id))
    if saved is None:
        raise ApiError(404, "search_not_found", "This search is no longer in the history.")
    return saved


@router.delete("/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_search(search_id: uuid.UUID) -> Response:
    if not history_service.delete(str(search_id)):
        raise ApiError(404, "search_not_found", "This search is no longer in the history.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("")
def clear_searches() -> dict[str, int]:
    return {"deleted": history_service.clear()}
