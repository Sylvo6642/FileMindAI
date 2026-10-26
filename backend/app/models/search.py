from pydantic import BaseModel, Field


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class ExcerptOut(BaseModel):
    chunk_id: str
    chunk_index: int
    similarity: float
    location: str
    references: dict[str, int | str]
    text: str


class FileMatchOut(BaseModel):
    rank: int
    file_id: str
    filename: str
    file_type: str
    # 1 - cosine distance. A ranking signal, not a confidence percentage.
    similarity: float
    # "semantic", "keyword" or "both": which ranking found the file.
    matched_by: str
    matching_chunks: int
    excerpts: list[ExcerptOut]


class SemanticSearchResponse(BaseModel):
    query: str
    result_count: int
    results: list[FileMatchOut]
    message: str | None = None
