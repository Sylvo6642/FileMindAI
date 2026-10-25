"""Document lifecycle: ingest, locate, preview and delete.

Ingestion order is deliberate: everything that can fail on bad input
(validation, extraction, chunking) runs in memory *before* anything is written,
so a rejected upload never leaves a half-saved file or orphaned row behind.
"""

import hashlib
import sqlite3
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.errors import ApiError
from app.services import metadata_service
from app.services.chunking_service import Chunk, chunk_segments
from app.services.extraction_service import ExtractionError, extract
from app.services.metadata_service import DocumentRecord
from app.services.validation_service import sanitize_filename, validate_upload

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain; charset=utf-8",
}


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
        # 'pending' = text extracted and chunked, waiting for embeddings (Stage 3).
        return metadata_service.insert_document(
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
    path = stored_path(record.file_id, record.file_type)
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        # Windows locks files that are open in another program (e.g. Word).
        raise ApiError(
            409, "file_in_use", "The file is open in another program. Close it and try again."
        )
    metadata_service.delete_document(record.file_id)


def _duplicate_error(existing: DocumentRecord) -> ApiError:
    return ApiError(
        409,
        "duplicate_file",
        f"This file was already uploaded as '{existing.filename}'.",
        file_id=existing.file_id,
    )
