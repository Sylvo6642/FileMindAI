from app.services.agent_service import AgentError
from tests.fake_anthropic import final_answer, response, tool_use


def test_agent_search_endpoint(client, upload, fake_claude):
    doc = upload("agreement_001.txt", "Software development agreement between Alpha and Beta.")
    fake_claude.messages.script = [
        response(tool_use("search_files", {"query": "software development agreement", "limit": 5}),
                 stop_reason="tool_use"),
        response(final_answer("Likely agreement_001.txt.",
                              [{"file_id": doc["file_id"], "reason": "Alpha and Beta agreement."}])),
    ]

    body = client.post("/api/search", json={"query": "Find the software development agreement"}).json()

    assert body["answer"] == "Likely agreement_001.txt."
    assert body["matches"][0]["filename"] == "agreement_001.txt"
    assert body["matches"][0]["excerpts"][0]["location"] == "line 1"
    assert body["activity"] == [{
        "tool": "search_files",
        "input": {"query": "software development agreement", "limit": 5},
        "summary": "Found 1 candidate document.",
        "is_error": False,
    }]
    assert body["tool_rounds"] == 1
    assert body["usage"] == {"input_tokens": 200, "output_tokens": 40}


def test_agent_search_without_documents_skips_claude(client, fake_claude):
    body = client.post("/api/search", json={"query": "anything"}).json()
    assert "No documents have been indexed" in body["answer"]
    assert fake_claude.messages.calls == []


def test_agent_search_validation(client):
    assert client.post("/api/search", json={"query": ""}).status_code == 422
    assert client.post("/api/search", json={"query": "   "}).status_code == 400
    assert client.post("/api/search", json={"query": "x" * 1001}).status_code == 422


def test_agent_unavailable_returns_502(client, upload, monkeypatch):
    from app.services import agent_service

    upload("a.txt", "text")

    def broken(_query):
        raise AgentError("Anthropic rejected the API key. Check ANTHROPIC_API_KEY in backend/.env.")

    monkeypatch.setattr(agent_service, "run_search_agent", broken)
    response_ = client.post("/api/search", json={"query": "anything"})

    assert response_.status_code == 502
    assert response_.json()["error"]["code"] == "assistant_unavailable"
    assert "sk-" not in response_.text
