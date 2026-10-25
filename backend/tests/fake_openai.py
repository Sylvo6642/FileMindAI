"""An offline stand-in for the OpenAI embeddings API.

It builds "bag of words" vectors: each word is hashed to a position and
counted, then the vector is normalised. Texts sharing words point in similar
directions, which is a crude version of what real embeddings do with meaning.
"""

import hashlib
import math
import re
from types import SimpleNamespace

_WORD = re.compile(r"[a-z0-9]+")


def fake_vector(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for word in _WORD.findall(text.lower()):
        position = int(hashlib.md5(word.encode()).hexdigest(), 16) % dimensions
        vector[position] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class FakeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.error: Exception | None = None
        self.reverse_order = False

    def create(self, *, model: str, input: list[str], dimensions: int, **_):
        self.calls.append({"model": model, "input": list(input), "dimensions": dimensions})
        if self.error:
            raise self.error
        data = [
            SimpleNamespace(index=i, embedding=fake_vector(text, dimensions))
            for i, text in enumerate(input)
        ]
        if self.reverse_order:
            data.reverse()
        return SimpleNamespace(data=data)


class FakeOpenAI:
    def __init__(self) -> None:
        self.embeddings = FakeEmbeddings()
