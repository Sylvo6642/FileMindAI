"""SQLite connection and schema.

SQLite holds the *metadata* about each file (name, hash, status...) and the
search history. The vectors themselves live in ChromaDB.
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

-- Search history. The full answer is kept as JSON so an old search can be shown
-- again without calling Claude; token counts are columns so totals are cheap.
CREATE TABLE IF NOT EXISTS searches (
    search_id     TEXT PRIMARY KEY,
    query         TEXT NOT NULL,
    response_json TEXT NOT NULL,
    match_count   INTEGER NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    model         TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_searches_created_at ON searches (created_at);
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
