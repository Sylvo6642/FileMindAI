"""SQLite connection and schema.

SQLite holds the *metadata* about each file (name, hash, status...).
The vectors themselves will live in ChromaDB from Stage 3 onwards.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from app.core.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    file_id             TEXT PRIMARY KEY,
    filename            TEXT NOT NULL,
    file_type           TEXT NOT NULL,
    stored_name         TEXT NOT NULL,
    sha256              TEXT NOT NULL UNIQUE,
    size_bytes          INTEGER NOT NULL,
    status              TEXT NOT NULL
                        CHECK (status IN ('pending', 'processing', 'indexed', 'failed')),
    page_count          INTEGER,
    char_count          INTEGER NOT NULL,
    chunk_count         INTEGER NOT NULL,
    extraction_warnings TEXT NOT NULL DEFAULT '[]',
    error_message       TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a short-lived connection; commit on success, roll back on error."""
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
