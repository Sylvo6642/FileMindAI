from app.services import history_service
from tests.fake_anthropic import final_answer, response, tool_use


def _search(client, fake_claude, file_id: str, query: str) -> dict:
    fake_claude.messages.script = [
        response(tool_use("search_files", {"query": query, "limit": 5}), stop_reason="tool_use"),
        response(final_answer("Likely agreement.txt.", [{"file_id": file_id, "reason": "Matches."}])),
    ]
    result = client.post("/api/search", json={"query": query})
    assert result.status_code == 200, result.text
    return result.json()


def test_answered_searches_are_saved_and_listed_newest_first(client, upload, fake_claude):
    doc = upload("agreement.txt", "Software development agreement between Alpha and Beta.")

    first = _search(client, fake_claude, doc["file_id"], "software agreement")
    second = _search(client, fake_claude, doc["file_id"], "Alpha and Beta contract")

    assert first["search_id"] and first["created_at"]
    history = client.get("/api/searches").json()
    assert [s["query"] for s in history["searches"]] == ["Alpha and Beta contract", "software agreement"]
    assert history["searches"][0] == {
        "search_id": second["search_id"],
        "query": "Alpha and Beta contract",
        "created_at": second["created_at"],
        "match_count": 1,
        "usage": {"input_tokens": 200, "output_tokens": 40},
    }
    assert history["total_searches"] == 2
    assert history["total_usage"] == {"input_tokens": 400, "output_tokens": 80}


def test_reopening_a_saved_search_returns_the_stored_answer_without_claude(client, upload, fake_claude):
    doc = upload("agreement.txt", "Software development agreement between Alpha and Beta.")
    original = _search(client, fake_claude, doc["file_id"], "software agreement")
    calls_before = len(fake_claude.messages.calls)

    reopened = client.get(f"/api/searches/{original['search_id']}").json()

    assert reopened == original
    assert len(fake_claude.messages.calls) == calls_before


def test_delete_one_and_clear_all(client, upload, fake_claude):
    doc = upload("agreement.txt", "Software development agreement.")
    keep = _search(client, fake_claude, doc["file_id"], "first")
    drop = _search(client, fake_claude, doc["file_id"], "second")

    assert client.delete(f"/api/searches/{drop['search_id']}").status_code == 204
    assert client.get(f"/api/searches/{drop['search_id']}").status_code == 404
    assert client.delete(f"/api/searches/{drop['search_id']}").status_code == 404
    assert [s["search_id"] for s in client.get("/api/searches").json()["searches"]] == [keep["search_id"]]

    assert client.delete("/api/searches").json() == {"deleted": 1}
    history = client.get("/api/searches").json()
    assert history["searches"] == [] and history["total_searches"] == 0


def test_searches_that_never_reached_claude_are_not_saved(client):
    client.post("/api/search", json={"query": "anything"})  # empty library: answered without Claude

    assert client.get("/api/searches").json()["total_searches"] == 0


def test_a_history_failure_still_returns_the_answer(client, upload, fake_claude, monkeypatch):
    doc = upload("agreement.txt", "Software development agreement.")

    def broken(_response):
        raise OSError("disk full")

    monkeypatch.setattr(history_service, "save", broken)
    body = _search(client, fake_claude, doc["file_id"], "software agreement")

    assert body["answer"] == "Likely agreement.txt."
    assert body["search_id"] is None


def test_invalid_ids_and_limits_are_rejected(client):
    assert client.get("/api/searches/not-a-uuid").status_code == 422
    assert client.get("/api/searches?limit=0").status_code == 422
    assert client.get("/api/searches?limit=500").status_code == 422
