"""Keyword search (BM25) over chunk text, the second half of hybrid search.

Embeddings capture meaning but are weak at exact tokens. Measured in Stage 8:
"payment of 50000 rupees" missed a note saying "₹50,000", and "32 lakh"
missed "INR 32,00,000". BM25 is the classic keyword ranking formula: a chunk
scores higher when it contains rare query terms, more often, relative to its
length. Numbers are normalised first so the forms above become the same token.

The index lives in memory and is rebuilt only when the vectors change. That
is fine for a personal library (thousands of chunks); a large multi-user
system would use a persistent full-text index such as SQLite FTS5 instead.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.core.config import settings
from app.services import vector_service

# Standard BM25 parameters: k1 caps how much repeating a term helps,
# b controls how strongly long chunks are penalised.
K1 = 1.5
B = 0.75

_WORD = re.compile(r"\w+")
_DIGIT_GROUP = re.compile(r"(?<=\d),(?=\d{2,3}\b)")  # 1,23,900 / 50,000 -> 123900 / 50000
_INDIAN_UNIT = re.compile(r"\b(\d+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?)\b")
_UNIT_VALUE = {"lakh": 100_000, "lac": 100_000, "crore": 10_000_000}

STOPWORDS = {
    "a", "about", "all", "an", "and", "any", "anything", "are", "as", "at", "be", "between", "by",
    "can", "document", "documents", "does", "file", "files", "find", "for", "from", "get", "had",
    "has", "have", "how", "i", "in", "into", "is", "it", "its", "list", "listing", "locate", "me",
    "mention", "mentioning", "mentions", "my", "need", "of", "on", "or", "our", "paper", "please",
    "related", "show", "that", "the", "their", "there", "this", "to", "was", "we", "what", "where",
    "which", "who", "with", "you", "your",
}


@dataclass
class KeywordHit:
    chunk_id: str
    file_id: str
    score: float


def _expand_unit(match: re.Match) -> str:
    unit = match.group(2).rstrip("s")
    value = round(float(match.group(1)) * _UNIT_VALUE[unit])
    return f"{value} {unit}"


def _stem(word: str) -> str:
    # Deliberately tiny: just enough for "fees"/"fee" and "requirements"/"requirement".
    if word.isdigit() or len(word) <= 3:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    text = _INDIAN_UNIT.sub(_expand_unit, _DIGIT_GROUP.sub("", text.lower()))
    return [
        _stem(word)
        for word in _WORD.findall(text)
        if word not in STOPWORDS and (word.isdigit() or len(word) > 2)
    ]


class _Index:
    def __init__(self, chunks: list[tuple[str, str, str]]) -> None:
        self.chunk_ids = [chunk_id for chunk_id, _, _ in chunks]
        self.file_ids = [file_id for _, file_id, _ in chunks]
        self.term_counts = [Counter(tokenize(text)) for _, _, text in chunks]
        self.lengths = [sum(counts.values()) for counts in self.term_counts]
        self.average_length = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        self.document_frequency: Counter[str] = Counter()
        for counts in self.term_counts:
            self.document_frequency.update(counts.keys())

    def idf(self, term: str) -> float:
        # Rare terms (a specific amount, a name) count for much more than common ones.
        n, df = len(self.chunk_ids), self.document_frequency[term]
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, limit: int) -> list[KeywordHit]:
        terms = set(tokenize(query)) & self.document_frequency.keys()
        if not terms:
            return []
        weights = {term: self.idf(term) for term in terms}
        hits = []
        for i, counts in enumerate(self.term_counts):
            score = 0.0
            for term in terms & counts.keys():
                tf = counts[term]
                norm = K1 * (1 - B + B * self.lengths[i] / self.average_length)
                score += weights[term] * tf * (K1 + 1) / (tf + norm)
            if score > 0:
                hits.append(KeywordHit(self.chunk_ids[i], self.file_ids[i], score))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:limit]


_cache: tuple[tuple, _Index] | None = None


def _index() -> _Index:
    global _cache
    # Rebuild only when the stored chunks changed (or the data folder did, in tests).
    key = (str(settings.chroma_dir), vector_service.collection_name(), vector_service.generation())
    if _cache is None or _cache[0] != key:
        _cache = (key, _Index(vector_service.all_chunk_texts()))
    return _cache[1]


def search(query: str, limit: int = 200) -> list[KeywordHit]:
    """Chunks ranked by BM25 score, best first. Only chunks sharing a term are returned."""
    return _index().search(query, limit)
