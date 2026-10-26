from typing import Any

from pydantic import BaseModel, Field


class AgentSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


class MatchExcerptOut(BaseModel):
    location: str
    text: str


class AgentMatchOut(BaseModel):
    file_id: str
    filename: str
    file_type: str
    reason: str
    # 1 - cosine distance of the best chunk. A ranking signal, not confidence.
    similarity: float | None
    excerpts: list[MatchExcerptOut]


class ActivityStepOut(BaseModel):
    tool: str
    input: dict[str, Any]
    summary: str
    is_error: bool


class UsageOut(BaseModel):
    input_tokens: int
    output_tokens: int


class AgentSearchResponse(BaseModel):
    query: str
    answer: str
    matches: list[AgentMatchOut]
    activity: list[ActivityStepOut]
    tool_rounds: int
    model: str | None
    usage: UsageOut
    # Set once the search is saved to history.
    search_id: str | None = None
    created_at: str | None = None


class SearchSummaryOut(BaseModel):
    search_id: str
    query: str
    created_at: str
    match_count: int
    usage: UsageOut


class SearchHistoryOut(BaseModel):
    count: int
    searches: list[SearchSummaryOut]
    # Over the whole history, not just the returned page.
    total_searches: int
    total_usage: UsageOut
