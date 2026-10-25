import httpx2
import anthropic
import pytest

from app.core.config import settings
from app.services.agent_service import AgentError, run_search_agent
from tests.fake_anthropic import final_answer, response, text, thinking, tool_use

AGREEMENT = "Software development agreement between Alpha Technologies and Beta Solutions."
NOTES = "Meeting notes: approved an advance payment of 50,000 rupees to Omega Printing."


def _tool_results(call: dict) -> list[dict]:
    """The tool_result blocks the agent sent in the last user message of a call."""
    return [b for b in call["messages"][-1]["content"] if b.get("type") == "tool_result"]


def test_search_then_answer(upload, fake_claude):
    doc = upload("agreement_001.txt", AGREEMENT)
    upload("notes.txt", NOTES)
    fake_claude.messages.script = [
        response(thinking(), tool_use("search_files", {"query": "software development agreement", "limit": 5}),
                 stop_reason="tool_use"),
        response(thinking(), final_answer(
            "The software development agreement is agreement_001.txt.",
            [{"file_id": doc["file_id"], "reason": "Agreement between Alpha Technologies and Beta Solutions."}],
        )),
    ]

    result = run_search_agent("Find the software development agreement")

    assert result.answer.startswith("The software development agreement")
    assert [m.filename for m in result.matches] == ["agreement_001.txt"]
    assert result.matches[0].excerpts[0]["document_text"].startswith("Software development")
    # The notes file shares no words with the query, so retrieval filters it out.
    assert [(s.tool, s.summary) for s in result.activity] == [("search_files", "Found 1 candidate document.")]
    assert result.tool_rounds == 1
    assert result.input_tokens == 200 and result.output_tokens == 40


def test_request_shape_sent_to_claude(upload, fake_claude):
    upload("a.txt", AGREEMENT)
    fake_claude.messages.script = [response(final_answer("Nothing found.", []))]

    run_search_agent("find something")

    call = fake_claude.messages.calls[0]
    assert call["model"] == settings.anthropic_model
    assert [t["name"] for t in call["tools"]] == ["search_files", "inspect_file"]
    assert call["tool_choice"] == {"type": "auto"}
    assert call["output_config"]["effort"] == settings.agent_effort
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "untrusted data" in call["system"]
    assert "temperature" not in call  # Haiku 5.5 rejects sampling parameters


def test_assistant_turns_are_appended_unmodified(upload, fake_claude):
    upload("a.txt", AGREEMENT)
    first = response(thinking(), text("Let me search."),
                     tool_use("search_files", {"query": "agreement", "limit": 5}), stop_reason="tool_use")
    fake_claude.messages.script = [first, response(final_answer("Done.", []))]

    run_search_agent("find the agreement")

    second_call = fake_claude.messages.calls[1]
    assert second_call["messages"][1] == {"role": "assistant", "content": first.content}


def test_search_inspect_then_answer(upload, fake_claude):
    doc = upload("notes.txt", NOTES)

    def inspect_first_result(request):
        # Read the file_id from the search result the agent sent back.
        import json
        search_payload = json.loads(_tool_results({"messages": request["messages"]})[0]["content"])
        file_id = search_payload["results"][0]["file_id"]
        return response(tool_use("inspect_file", {"file_id": file_id}), stop_reason="tool_use")

    fake_claude.messages.script = [
        response(tool_use("search_files", {"query": "payment of 50000 rupees", "limit": 5}), stop_reason="tool_use"),
        inspect_first_result,
        response(final_answer("notes.txt records the 50,000 rupee payment.",
                              [{"file_id": doc["file_id"], "reason": "Advance payment of 50,000 rupees."}])),
    ]

    result = run_search_agent("Find the document about a payment of 50000 rupees")

    assert [s.tool for s in result.activity] == ["search_files", "inspect_file"]
    assert result.activity[1].summary == "Inspected notes.txt."
    assert result.tool_rounds == 2
    assert result.matches[0].file_id == doc["file_id"]


def test_parallel_tool_calls_are_answered_in_one_message(upload, fake_claude):
    a = upload("a.txt", AGREEMENT)
    b = upload("b.txt", NOTES)
    fake_claude.messages.script = [
        response(tool_use("inspect_file", {"file_id": a["file_id"]}),
                 tool_use("inspect_file", {"file_id": b["file_id"]}), stop_reason="tool_use"),
        response(final_answer("Checked both.", [])),
    ]

    run_search_agent("compare")

    results = _tool_results(fake_claude.messages.calls[1])
    assert len(results) == 2
    ids = [blk.id for blk in fake_claude.messages.calls[1]["messages"][1]["content"]]
    assert [r["tool_use_id"] for r in results] == ids


def test_tool_errors_are_returned_to_claude_not_raised(upload, fake_claude):
    upload("a.txt", AGREEMENT)
    fake_claude.messages.script = [
        response(tool_use("inspect_file", {"file_id": "not-a-uuid"}), stop_reason="tool_use"),
        response(final_answer("I could not inspect that file.", [])),
    ]

    result = run_search_agent("inspect something")

    [tool_result] = _tool_results(fake_claude.messages.calls[1])
    assert tool_result["is_error"] is True
    assert result.activity[0].is_error is True
    assert result.answer == "I could not inspect that file."


def test_invented_file_ids_are_discarded(upload, fake_claude):
    real = upload("a.txt", AGREEMENT)
    never_returned = upload("secret.txt", "chocolate cake recipe")
    fake_claude.messages.script = [
        response(tool_use("search_files", {"query": "software agreement", "limit": 5}), stop_reason="tool_use"),
        response(final_answer("Two matches.", [
            {"file_id": real["file_id"], "reason": "Real match."},
            {"file_id": "11111111-1111-1111-1111-111111111111", "reason": "Made up."},
            {"file_id": never_returned["file_id"], "reason": "Exists, but no tool returned it."},
            {"file_id": real["file_id"], "reason": "Duplicate."},
        ])),
    ]

    result = run_search_agent("find the agreement")

    assert [m.file_id for m in result.matches] == [real["file_id"]]
    assert len(result.discarded_file_ids) == 3


def test_tool_round_limit_forces_a_final_answer(upload, fake_claude):
    upload("a.txt", AGREEMENT)
    rounds = settings.agent_max_tool_rounds
    fake_claude.messages.script = [
        response(tool_use("search_files", {"query": f"attempt {i}", "limit": 5}), stop_reason="tool_use")
        for i in range(rounds)
    ] + [response(final_answer("Best effort answer.", []))]

    result = run_search_agent("keep searching forever")

    calls = fake_claude.messages.calls
    assert len(calls) == rounds + 1
    assert all(c["tool_choice"] == {"type": "auto"} for c in calls[:-1])
    assert calls[-1]["tool_choice"] == {"type": "none"}
    assert calls[-1]["messages"][-1]["content"][-1]["text"].startswith("Tool limit reached")
    assert result.tool_rounds == rounds
    assert result.answer == "Best effort answer."


def test_no_matches_answer(upload, fake_claude):
    upload("cake.txt", "chocolate cake recipe")
    fake_claude.messages.script = [
        response(tool_use("search_files", {"query": "employment contract", "limit": 5}), stop_reason="tool_use"),
        response(final_answer("I could not find any employment contract.", [])),
    ]

    result = run_search_agent("find my employment contract")

    assert result.matches == []
    assert "could not find" in result.answer


@pytest.mark.parametrize(
    ("stop_reason", "expected"),
    [("refusal", "can't help"), ("max_tokens", "cut off")],
)
def test_unusual_stop_reasons(upload, fake_claude, stop_reason, expected):
    upload("a.txt", AGREEMENT)
    fake_claude.messages.script = [response(text("partial"), stop_reason=stop_reason)]

    result = run_search_agent("anything")

    assert expected in result.answer
    assert result.matches == []


def test_non_json_final_text_is_shown_as_is(upload, fake_claude):
    upload("a.txt", AGREEMENT)
    fake_claude.messages.script = [response(text("Plain text answer."))]
    assert run_search_agent("anything").answer == "Plain text answer."


_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (anthropic.AuthenticationError("bad", response=httpx2.Response(401, request=_REQUEST), body=None), "rejected the API key"),
        (anthropic.NotFoundError("no model", response=httpx2.Response(404, request=_REQUEST), body=None), "not found"),
        (anthropic.RateLimitError("slow", response=httpx2.Response(429, request=_REQUEST), body=None), "rate limit"),
        (anthropic.APIConnectionError(request=_REQUEST), "Could not reach Anthropic"),
        (anthropic.InternalServerError("boom", response=httpx2.Response(500, request=_REQUEST), body=None), "(500)"),
    ],
)
def test_api_failures_become_agent_errors(upload, fake_claude, error, message):
    upload("a.txt", AGREEMENT)
    fake_claude.messages.error = error
    with pytest.raises(AgentError, match=message):
        run_search_agent("anything")
