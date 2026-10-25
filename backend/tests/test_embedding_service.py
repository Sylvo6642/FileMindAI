import httpx
import openai
import pytest

from app.core.config import settings
from app.services import embedding_service
from app.services.embedding_service import EmbeddingError, embed_query, embed_texts

# Captured at import time, before the autouse fixture swaps in the fake client.
_real_client = embedding_service._client

_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/embeddings")


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=_REQUEST)


def test_embeds_in_batches_and_keeps_order(fake_openai, monkeypatch):
    monkeypatch.setattr(settings, "embedding_batch_size", 2)
    texts = ["one", "two", "three", "four", "five"]

    vectors = embed_texts(texts)

    assert len(vectors) == 5
    assert [len(call["input"]) for call in fake_openai.embeddings.calls] == [2, 2, 1]
    assert all(len(v) == settings.embedding_dimensions for v in vectors)


def test_results_are_matched_by_index_not_position(fake_openai):
    fake_openai.embeddings.reverse_order = True
    vectors = embed_texts(["alpha", "beta"])
    assert vectors[0] == embed_texts(["alpha"])[0]


def test_uses_configured_model_and_dimensions(fake_openai):
    embed_query("hello")
    call = fake_openai.embeddings.calls[0]
    assert call["model"] == "text-embedding-3-small"
    assert call["dimensions"] == 1536


def test_missing_api_key_is_reported(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    _real_client.cache_clear()
    with pytest.raises(EmbeddingError, match="OPENAI_API_KEY is not configured"):
        _real_client()


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (openai.AuthenticationError("bad key", response=_response(401), body=None), "rejected the API key"),
        (openai.RateLimitError("slow down", response=_response(429), body=None), "rate limit"),
        (openai.APITimeoutError(request=_REQUEST), "timeout or network"),
        (openai.APIConnectionError(request=_REQUEST), "timeout or network"),
        (openai.InternalServerError("boom", response=_response(500), body=None), "request failed"),
    ],
)
def test_api_failures_become_friendly_errors(fake_openai, error, message):
    fake_openai.embeddings.error = error
    with pytest.raises(EmbeddingError, match=message):
        embed_texts(["anything"])
