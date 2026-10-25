import uuid
from dataclasses import asdict

from fastapi import APIRouter, Query, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.errors import ApiError
from app.models.documents import ChunkOut, ChunkPreviewOut, DocumentListOut, DocumentOut
from app.services import document_service, metadata_service
from app.services.chunking_service import make_chunk_id
from app.services.metadata_service import DocumentRecord

router = APIRouter(prefix="/api/documents", tags=["documents"])

_READ_BLOCK = 1024 * 1024


def _to_out(record: DocumentRecord) -> DocumentOut:
    return DocumentOut(
        file_id=record.file_id,
        filename=record.filename,
        file_type=record.file_type,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        status=record.status,
        page_count=record.page_count,
        char_count=record.char_count,
        chunk_count=record.chunk_count,
        warnings=record.extraction_warnings,
        error_message=record.error_message,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


async def _read_limited(file: UploadFile) -> bytes:
    """Read the upload in blocks and stop as soon as it passes the size limit."""
    data = bytearray()
    while block := await file.read(_READ_BLOCK):
        data.extend(block)
        if len(data) > settings.max_upload_bytes:
            limit_mb = settings.max_upload_bytes // (1024 * 1024)
            raise ApiError(413, "file_too_large", f"File exceeds the {limit_mb} MB limit.")
    return bytes(data)


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile) -> DocumentOut:
    data = await _read_limited(file)
    # Extraction and OpenAI calls are slow and blocking: run them off the event loop.
    record = await run_in_threadpool(document_service.ingest_upload, file.filename, data)
    return _to_out(record)


@router.get("", response_model=DocumentListOut)
def list_documents() -> DocumentListOut:
    documents = [_to_out(r) for r in metadata_service.list_documents()]
    return DocumentListOut(count=len(documents), documents=documents)


# file_id is typed as UUID, so anything else (like "../../secret") is rejected with 422.
@router.get("/{file_id}", response_model=DocumentOut)
def get_document(file_id: uuid.UUID) -> DocumentOut:
    return _to_out(document_service.get_document_or_404(str(file_id)))


@router.get("/{file_id}/open")
def open_document(file_id: uuid.UUID) -> FileResponse:
    record = document_service.get_document_or_404(str(file_id))
    return FileResponse(
        document_service.original_file(record),
        media_type=document_service.MEDIA_TYPES[record.file_type],
        filename=record.filename,
        content_disposition_type="inline",
    )


@router.get("/{file_id}/chunks", response_model=ChunkPreviewOut, tags=["debug"])
def preview_chunks(
    file_id: uuid.UUID, limit: int = Query(10, ge=1, le=100)
) -> ChunkPreviewOut:
    record = document_service.get_document_or_404(str(file_id))
    chunks = document_service.preview_chunks(record)
    return ChunkPreviewOut(
        file_id=record.file_id,
        filename=record.filename,
        total_chunks=len(chunks),
        chunks=[
            ChunkOut(chunk_id=make_chunk_id(record.file_id, c.chunk_index), **asdict(c))
            for c in chunks[:limit]
        ],
    )


@router.post("/{file_id}/reindex", response_model=DocumentOut)
def reindex_document(file_id: uuid.UUID) -> DocumentOut:
    record = document_service.get_document_or_404(str(file_id))
    return _to_out(document_service.reindex_document(record))


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(file_id: uuid.UUID) -> Response:
    record = document_service.get_document_or_404(str(file_id))
    document_service.delete_document(record)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
