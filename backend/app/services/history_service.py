"""Search history in SQLite: save each answered search, list, reopen and delete.

Reopening a saved search returns the stored answer, so it costs nothing. Saved
answers contain excerpts of documents; they live in backend/data like
everything else and are removed with the search.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.database import connect
from app.models.agent import AgentSearchResponse


@dataclass
class SearchSummary:
    search_id: str
    query: str
    created_at: str
    match_count: int
    input_tokens: int
    output_tokens: int


@dataclass
class HistoryTotals:
    searches: int
    input_tokens: int
    output_tokens: int


def save(response: AgentSearchResponse) -> AgentSearchResponse:
    """Store an answered search and return it with its id and timestamp."""
    saved = response.model_copy(
        update={"search_id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat()}
    )
    with connect() as conn:
        conn.execute(
            """INSERT INTO searches (search_id, query, response_json, match_count,
                                     input_tokens, output_tokens, model, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                saved.search_id,
                saved.query,
                saved.model_dump_json(),
                len(saved.matches),
                saved.usage.input_tokens,
                saved.usage.output_tokens,
                saved.model,
                saved.created_at,
            ),
        )
    return saved


def list_recent(limit: int) -> list[SearchSummary]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT search_id, query, created_at, match_count, input_tokens, output_tokens
               FROM searches ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [SearchSummary(**dict(row)) for row in rows]


def totals() -> HistoryTotals:
    with connect() as conn:
        row = conn.execute(
            """SELECT COUNT(*), COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0)
               FROM searches"""
        ).fetchone()
    return HistoryTotals(searches=row[0], input_tokens=row[1], output_tokens=row[2])


def get(search_id: str) -> AgentSearchResponse | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT response_json FROM searches WHERE search_id = ?", (search_id,)
        ).fetchone()
    return AgentSearchResponse.model_validate_json(row["response_json"]) if row else None


def delete(search_id: str) -> bool:
    with connect() as conn:
        cursor = conn.execute("DELETE FROM searches WHERE search_id = ?", (search_id,))
    return cursor.rowcount > 0


def clear() -> int:
    with connect() as conn:
        cursor = conn.execute("DELETE FROM searches")
    return cursor.rowcount
