"""Turn text into vectors with OpenAI text-embedding-3-small.

An embedding is a list of numbers (1536 here) that places a piece of text in a
"meaning space": texts about similar things land close together, even when they
share no words. "website upkeep contract" and "maintenance agreement for our
site" get nearby vectors; "employee leave policy" lands far away.
"""

from functools import lru_cache

import openai
from openai import OpenAI

from app.core.config import settings


class EmbeddingError(Exception):
    """A user-presentable reason why embeddings could not be generated."""


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    if not settings.openai_api_key:
        raise EmbeddingError("OPENAI_API_KEY is not configured in backend/.env.")
    # The SDK retries timeouts, 429s and 5xx errors with exponential backoff.
    return OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed many texts, sending them in batches to save round trips."""
    vectors: list[list[float]] = []
    size = settings.embedding_batch_size
    for start in range(0, len(texts), size):
        vectors.extend(_embed_batch(texts[start : start + size]))
    return vectors


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def _embed_batch(batch: list[str]) -> list[list[float]]:
    try:
        response = _client().embeddings.create(
            model=settings.embedding_model,
            input=batch,
            dimensions=settings.embedding_dimensions,
        )
    except openai.AuthenticationError:
        raise EmbeddingError("OpenAI rejected the API key. Check OPENAI_API_KEY in backend/.env.")
    except openai.RateLimitError:
        raise EmbeddingError(
            "OpenAI rate limit reached or the account has no remaining quota. Check billing, then retry."
        )
    except (openai.APITimeoutError, openai.APIConnectionError):
        raise EmbeddingError("Could not reach OpenAI (timeout or network error). Try again.")
    except openai.APIError as exc:
        raise EmbeddingError(f"OpenAI embedding request failed ({type(exc).__name__}).")

    # Results carry an index; sort so vector i always belongs to text i.
    data = sorted(response.data, key=lambda item: item.index)
    if len(data) != len(batch):
        raise EmbeddingError("OpenAI returned an unexpected number of embeddings.")
    return [item.embedding for item in data]
