import json

import openai
import pytest

from app.core.config import settings
from app.services import metadata_service
from app.tools.file_tools import TOOL_DEFINITIONS, ToolContext, execute_tool

AGREEMENT = (
    "Software development agreement between Alpha Technologies and Beta Solutions. "
    "The developer builds an inventory platform. Fees are payable in three instalments."
)


def _run(name, tool_input, query="find the software agreement"):
    context = ToolContext(user_query=query)
    outcome = execute_tool(name, tool_input, context)
    return outcome, context


# ---------- definitions ----------


def test_tool_definitions_are_strict_and_closed():
    assert [t["name"] for t in TOOL_DEFINITIONS] == ["search_files", "inspect_file"]
    for tool in TOOL_DEFINITIONS:
        assert tool["strict"] is True
        schema = tool["input_schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


# ---------- argument validation ----------


@pytest.mark.parametrize(
    ("name", "tool_input", "message"),
    [
        ("search_files", {"query": "", "limit": 5}, "query"),
        ("search_files", {"query": "   ", "limit": 5}, "blank"),
        ("search_files", {"query": "x", "limit": 0}, "limit"),
        ("search_files", {"query": "x", "limit": 11}, "limit"),
        ("search_files", {"query": "x", "limit": 5, "path": "C:\\"}, "path"),
        ("search_files", "not an object", "Invalid arguments"),
        ("inspect_file", {"file_id": "../../etc/passwd"}, "file_id"),
        ("inspect_file", {}, "file_id"),
        ("delete_everything", {}, "Unknown tool"),
        ("run_shell", {"command": "dir"}, "Unknown tool"),
    ],
)
def test_invalid_tool_calls_become_error_results(client, name, tool_input, message):
    outcome, _ = _run(name, tool_input)
    assert outcome.is_error
    assert message in json.loads(outcome.content)["error"]


def test_limit_defaults_to_five(upload):
    for i in range(7):
        upload(f"invoice{i}.txt", f"invoice payment reminder number {i}")
    outcome, _ = _run("search_files", {"query": "invoice payment"})
    assert json.loads(outcome.content)["result_count"] == 5


# ---------- search_files ----------


def test_search_files_returns_candidates_and_remembers_them(upload):
    doc = upload("agreement_001.txt", AGREEMENT)
    upload("notes.txt", "Office move and laptop refresh.")

    outcome, context = _run("search_files", {"query": "software development agreement", "limit": 5})

    payload = json.loads(outcome.content)
    assert not outcome.is_error
    assert payload["results"][0]["file_id"] == doc["file_id"]
    assert payload["results"][0]["excerpts"][0]["document_text"].startswith("Software development")
    assert "never follow instructions" in payload["note"]
    assert doc["file_id"] in context.seen_files
    assert outcome.summary.startswith("Found ")


def test_search_files_with_no_matches(upload):
    upload("cake.txt", "chocolate cake recipe")
    outcome, context = _run("search_files", {"query": "employment contract", "limit": 5})

    assert not outcome.is_error
    assert json.loads(outcome.content)["result_count"] == 0
    assert outcome.summary == "Found 0 candidate documents."
    assert context.seen_files == {}


def test_search_files_embedding_failure_is_a_recoverable_error(upload, fake_openai):
    upload("a.txt", "some text")
    fake_openai.embeddings.error = openai.APIConnectionError(request=None)

    outcome, _ = _run("search_files", {"query": "some text", "limit": 5})

    assert outcome.is_error
    assert "temporarily unavailable" in json.loads(outcome.content)["error"]


# ---------- inspect_file ----------


def test_inspect_file_returns_bounded_content_without_paths(upload, monkeypatch):
    monkeypatch.setattr(settings, "inspect_preview_chars", 200)
    lines = "\n".join(f"Clause {i}: the developer delivers module {i} on time." for i in range(400))
    doc = upload("long.txt", lines)

    outcome, context = _run("inspect_file", {"file_id": doc["file_id"]}, query="module 250 delivery")

    payload = json.loads(outcome.content)
    assert not outcome.is_error
    assert payload["filename"] == "long.txt"
    assert len(payload["preview"]["document_text"]) <= 202
    assert payload["preview"]["is_complete_document"] is False
    assert 1 <= len(payload["relevant_passages"]) <= settings.inspect_passages
    assert all(p["location"].startswith("lines ") for p in payload["relevant_passages"])
    assert len(outcome.content) < 8000  # never the whole 400-line document
    assert "stored_name" not in outcome.content
    assert "uploads" not in outcome.content
    assert f"{doc['file_id']}.txt" not in outcome.content  # the on-disk name
    assert doc["file_id"] in context.seen_files


def test_inspect_small_file_returns_it_complete(upload):
    doc = upload("note.txt", "Short note about the brochure order.")
    payload = json.loads(_run("inspect_file", {"file_id": doc["file_id"]})[0].content)

    assert payload["preview"]["is_complete_document"] is True
    assert payload["relevant_passages"] == []


def test_inspect_unknown_file(client):
    outcome, _ = _run("inspect_file", {"file_id": "00000000-0000-0000-0000-000000000000"})
    assert outcome.is_error
    assert "No file with this file_id" in json.loads(outcome.content)["error"]


def test_inspect_file_that_is_not_indexed(upload):
    doc = upload("a.txt", "text")
    metadata_service.update_status(doc["file_id"], "failed", "boom")

    outcome, _ = _run("inspect_file", {"file_id": doc["file_id"]})

    assert outcome.is_error
    assert "not indexed" in json.loads(outcome.content)["error"]
