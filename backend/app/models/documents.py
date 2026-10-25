from typing import Literal

from pydantic import BaseModel

DocumentStatus = Literal["pending", "processing", "indexed", "failed"]


class DocumentOut(BaseModel):
    file_id: str
    filename: str
    file_type: str
    size_bytes: int
    sha256: str
    status: DocumentStatus
    page_count: int | None
    char_count: int
    chunk_count: int
    warnings: list[str]
    error_message: str | None
    created_at: str
    updated_at: str


class DocumentListOut(BaseModel):
    count: int
    documents: list[DocumentOut]


class ChunkOut(BaseModel):
    chunk_id: str
    chunk_index: int
    token_count: int
    page_start: int | None
    page_end: int | None
    paragraph_start: int | None
    paragraph_end: int | None
    line_start: int | None
    line_end: int | None
    section: str | None
    text: str


class ChunkPreviewOut(BaseModel):
    file_id: str
    filename: str
    total_chunks: int
    chunks: list[ChunkOut]
