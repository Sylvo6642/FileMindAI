"""CRUD for document metadata in SQLite."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.database import connect


@dataclass
class DocumentRecord:
    file_id: str
    filename: str
    file_type: str
    stored_name: str
    sha256: str
    size_bytes: int
    status: str
    page_count: int | None
    char_count: int
    chunk_count: int
    extraction_warnings: list[str]
    error_message: str | None
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_record(row: sqlite3.Row) -> DocumentRecord:
    data = dict(row)
    data["extraction_warnings"] = json.loads(data["extraction_warnings"])
    return DocumentRecord(**data)


def insert_document(
    *,
    file_id: str,
    filename: str,
    file_type: str,
    stored_name: str,
    sha256: str,
    size_bytes: int,
    status: str,
    page_count: int | None,
    char_count: int,
    chunk_count: int,
    extraction_warnings: list[str],
) -> DocumentRecord:
    now = _now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO documents (
                file_id, filename, file_type, stored_name, sha256, size_bytes, status,
                page_count, char_count, chunk_count, extraction_warnings, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id, filename, file_type, stored_name, sha256, size_bytes, status,
                page_count, char_count, chunk_count, json.dumps(extraction_warnings), now, now,
            ),
        )
    record = get_document(file_id)
    assert record is not None
    return record


def get_document(file_id: str) -> DocumentRecord | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE file_id = ?", (file_id,)).fetchone()
    return _to_record(row) if row else None


def get_document_by_hash(sha256: str) -> DocumentRecord | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE sha256 = ?", (sha256,)).fetchone()
    return _to_record(row) if row else None


def get_documents_by_ids(file_ids: list[str]) -> dict[str, DocumentRecord]:
    if not file_ids:
        return {}
    placeholders = ", ".join("?" for _ in file_ids)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM documents WHERE file_id IN ({placeholders})", file_ids
        ).fetchall()
    return {row["file_id"]: _to_record(row) for row in rows}


def list_documents() -> list[DocumentRecord]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    return [_to_record(row) for row in rows]


def update_status(
    file_id: str,
    status: str,
    error_message: str | None = None,
    chunk_count: int | None = None,
) -> DocumentRecord:
    with connect() as conn:
        conn.execute(
            """
            UPDATE documents
            SET status = ?, error_message = ?, chunk_count = COALESCE(?, chunk_count), updated_at = ?
            WHERE file_id = ?
            """,
            (status, error_message, chunk_count, _now(), file_id),
        )
    record = get_document(file_id)
    assert record is not None
    return record


def mark_unfinished_as_failed() -> int:
    """At startup, anything still pending/processing was interrupted by a shutdown."""
    with connect() as conn:
        cursor = conn.execute(
            """
            UPDATE documents
            SET status = 'failed',
                error_message = 'Indexing did not finish (the server stopped). Reindex to retry.',
                updated_at = ?
            WHERE status IN ('pending', 'processing')
            """,
            (_now(),),
        )
        return cursor.rowcount


def delete_document(file_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM documents WHERE file_id = ?", (file_id,))
