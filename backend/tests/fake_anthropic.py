"""A scripted stand-in for the Anthropic Messages API.

Each test queues the responses "Claude" should give, then inspects what the
agent sent. This tests our loop logic exactly, offline, and for free.
"""

import itertools
import json
from types import SimpleNamespace

_ids = itertools.count(1)


def thinking():
    # Haiku 5.5 returns thinking blocks with empty text by default.
    return SimpleNamespace(type="thinking", thinking="", signature="sig")


def text(value: str):
    return SimpleNamespace(type="text", text=value)


def tool_use(name: str, tool_input: dict):
    return SimpleNamespace(type="tool_use", id=f"toolu_{next(_ids)}", name=name, input=tool_input)


def final_answer(answer: str, matches: list[dict]):
    return text(json.dumps({"answer": answer, "matches": matches}))


def response(*content, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        content=list(content),
        stop_reason=stop_reason,
        model="claude-haiku-5-5",
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
    )


class FakeMessages:
    def __init__(self) -> None:
        self.script: list = []
        self.calls: list[dict] = []
        self.error: Exception | None = None

    def create(self, **kwargs):
        # Snapshot the message list: the agent keeps appending to the same list.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        if self.error:
            raise self.error
        if not self.script:
            raise AssertionError("Claude was called more times than the test scripted")
        next_item = self.script.pop(0)
        return next_item(kwargs) if callable(next_item) else next_item


class FakeAnthropic:
    def __init__(self) -> None:
        self.messages = FakeMessages()
