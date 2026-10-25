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


def list_documents() -> list[DocumentRecord]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    return [_to_record(row) for row in rows]


def delete_document(file_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM documents WHERE file_id = ?", (file_id,))
