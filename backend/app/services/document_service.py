"""Document lifecycle: ingest, index, locate, preview and delete.

Ingestion order is deliberate: everything that can fail on bad input
(validation, extraction, chunking) runs in memory *before* anything is written,
so a rejected upload never leaves a half-saved file or orphaned row behind.

Indexing (the OpenAI call) happens after the file and row are saved. If it
fails, the document is kept with status 'failed' so it can be reindexed later
without uploading again.
"""

import hashlib
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.errors import ApiError
from app.services import embedding_service, metadata_service, vector_service
from app.services.chunking_service import Chunk, chunk_segments
from app.services.embedding_service import EmbeddingError
from app.services.extraction_service import ExtractionError, extract
from app.services.metadata_service import DocumentRecord
from app.services.validation_service import sanitize_filename, validate_upload

logger = logging.getLogger("filemind")

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain; charset=utf-8",
}


@dataclass
class UploadEstimate:
    filename: str
    file_type: str
    size_bytes: int
    page_count: int | None
    chunk_count: int
    token_count: int
    estimated_cost_usd: float
    duplicate_of: str | None


def estimate_upload(raw_filename: str | None, data: bytes) -> UploadEstimate:
    """What uploading this file would cost, without saving it or calling OpenAI.

    Runs the same validation, extraction and chunking as an upload, so the token
    count is exactly what would be sent to the embedding model.
    """
    filename = sanitize_filename(raw_filename)
    file_type = validate_upload(filename, data)
    existing = metadata_service.get_document_by_hash(hashlib.sha256(data).hexdigest())
    try:
        extraction = extract(data, file_type)
    except ExtractionError as exc:
        raise ApiError(422, "extraction_failed", str(exc))
    chunks = chunk_segments(extraction.segments)
    tokens = sum(chunk.token_count for chunk in chunks)
    return UploadEstimate(
        filename=filename,
        file_type=file_type,
        size_bytes=len(data),
        page_count=extraction.page_count,
        chunk_count=len(chunks),
        token_count=tokens,
        estimated_cost_usd=tokens / 1_000_000 * settings.embedding_price_per_million,
        duplicate_of=existing.filename if existing else None,
    )


def ingest_upload(raw_filename: str | None, data: bytes) -> DocumentRecord:
    filename = sanitize_filename(raw_filename)
    file_type = validate_upload(filename, data)

    sha256 = hashlib.sha256(data).hexdigest()
    existing = metadata_service.get_document_by_hash(sha256)
    if existing:
        raise _duplicate_error(existing)

    try:
        extraction = extract(data, file_type)
    except ExtractionError as exc:
        raise ApiError(422, "extraction_failed", str(exc))
    chunks = chunk_segments(extraction.segments)

    file_id = str(uuid.uuid4())
    path = stored_path(file_id, file_type)
    path.write_bytes(data)
    try:
        record = metadata_service.insert_document(
            file_id=file_id,
            filename=filename,
            file_type=file_type,
            stored_name=path.name,
            sha256=sha256,
            size_bytes=len(data),
            status="pending",
            page_count=extraction.page_count,
            char_count=extraction.char_count,
            chunk_count=len(chunks),
            extraction_warnings=extraction.warnings,
        )
    except sqlite3.IntegrityError:
        # Two identical uploads raced past the duplicate check.
        path.unlink(missing_ok=True)
        existing = metadata_service.get_document_by_hash(sha256)
        if existing:
            raise _duplicate_error(existing)
        raise
    except Exception:
        path.unlink(missing_ok=True)
        raise

    return _index(record, chunks)


def reindex_document(record: DocumentRecord) -> DocumentRecord:
    """Rebuild a document's vectors from its stored original file."""
    if record.status == "processing":
        raise ApiError(409, "already_processing", "This document is already being indexed.")
    try:
        chunks = chunk_segments(extract(original_file(record).read_bytes(), record.file_type).segments)
    except ExtractionError as exc:
        raise ApiError(422, "extraction_failed", str(exc))
    return _index(record, chunks)


def _index(record: DocumentRecord, chunks: list[Chunk]) -> DocumentRecord:
    """Embed chunks and store vectors. Always ends in 'indexed' or 'failed'."""
    metadata_service.update_status(record.file_id, "processing", chunk_count=len(chunks))
    try:
        # Clear leftovers from any earlier, partial attempt before writing.
        vector_service.delete_file_vectors(record.file_id)
        embeddings = embedding_service.embed_texts([chunk.text for chunk in chunks])
        vector_service.upsert_chunks(
            record.file_id, record.filename, record.file_type, chunks, embeddings
        )
    except Exception as exc:
        if isinstance(exc, EmbeddingError):
            message = str(exc)
        else:
            logger.exception("Indexing failed for %s", record.file_id)
            message = "Indexing failed because of an internal error."
        try:
            vector_service.delete_file_vectors(record.file_id)
        except Exception:
            logger.exception("Could not clean up vectors for %s", record.file_id)
        return metadata_service.update_status(record.file_id, "failed", message)

    return metadata_service.update_status(record.file_id, "indexed")


def get_document_or_404(file_id: str) -> DocumentRecord:
    record = metadata_service.get_document(file_id)
    if record is None:
        raise ApiError(404, "document_not_found", "Document not found.")
    return record


def stored_path(file_id: str, file_type: str) -> Path:
    """Build the on-disk path from a validated UUID, never from user input."""
    uploads = settings.uploads_dir.resolve()
    path = (uploads / f"{uuid.UUID(file_id)}.{file_type}").resolve()
    if not path.is_relative_to(uploads):
        raise ApiError(400, "invalid_path", "Invalid file location.")
    return path


def original_file(record: DocumentRecord) -> Path:
    path = stored_path(record.file_id, record.file_type)
    if not path.is_file():
        raise ApiError(404, "file_missing", "The original file is missing from storage.")
    return path


def preview_chunks(record: DocumentRecord) -> list[Chunk]:
    """Re-extract and re-chunk a stored file (learning/debug aid)."""
    data = original_file(record).read_bytes()
    return chunk_segments(extract(data, record.file_type).segments)


def delete_document(record: DocumentRecord) -> None:
    """Delete file, vectors, then metadata.

    Each step is safe to repeat, so if one fails the user can simply delete
    again and the remaining steps complete. The SQLite row goes last: while it
    exists, the document is still visible and can be retried.
    """
    path = stored_path(record.file_id, record.file_type)
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        # Windows locks files that are open in another program (e.g. Word).
        raise ApiError(
            409, "file_in_use", "The file is open in another program. Close it and try again."
        )
    vector_service.delete_file_vectors(record.file_id)
    metadata_service.delete_document(record.file_id)


def _duplicate_error(existing: DocumentRecord) -> ApiError:
    return ApiError(
        409,
        "duplicate_file",
        f"This file was already uploaded as '{existing.filename}'.",
        file_id=existing.file_id,
    )
