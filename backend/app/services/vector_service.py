"""ChromaDB: persistent storage and nearest-neighbour search for chunk vectors.

We always pass our own OpenAI embeddings. The collection is created with
embedding_function=None, so Chroma refuses any text that arrives without one
and its built-in default model is never used.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings
from app.services.chunking_service import Chunk, make_chunk_id


@dataclass
class ChunkHit:
    chunk_id: str
    file_id: str
    filename: str
    chunk_index: int
    text: str
    # Cosine distance: 0 = same direction (very similar), 1 = unrelated.
    distance: float
    metadata: dict[str, Any]


@lru_cache(maxsize=4)
def _client(path: str) -> ClientAPI:
    return chromadb.PersistentClient(
        path=path, settings=ChromaSettings(anonymized_telemetry=False)
    )


def collection_name() -> str:
    # Model and size in the name: vectors from different models never mix.
    return f"chunks__{settings.embedding_model}__{settings.embedding_dimensions}"


def _collection() -> Collection:
    return _client(str(settings.chroma_dir)).get_or_create_collection(
        collection_name(),
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )


def _chunk_metadata(file_id: str, filename: str, file_type: str, chunk: Chunk) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "file_id": file_id,
        "filename": filename,
        "file_type": file_type,
        "chunk_index": chunk.chunk_index,
        "token_count": chunk.token_count,
    }
    references = {
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "paragraph_start": chunk.paragraph_start,
        "paragraph_end": chunk.paragraph_end,
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
        "section": chunk.section,
    }
    metadata.update({key: value for key, value in references.items() if value is not None})
    return metadata


def upsert_chunks(
    file_id: str,
    filename: str,
    file_type: str,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("Each chunk needs exactly one embedding.")
    collection = _collection()
    batch = _client(str(settings.chroma_dir)).get_max_batch_size()
    for start in range(0, len(chunks), batch):
        part = chunks[start : start + batch]
        # Upsert + stable IDs: indexing the same file twice overwrites, never duplicates.
        collection.upsert(
            ids=[make_chunk_id(file_id, c.chunk_index) for c in part],
            embeddings=embeddings[start : start + batch],
            documents=[c.text for c in part],
            metadatas=[_chunk_metadata(file_id, filename, file_type, c) for c in part],
        )


def delete_file_vectors(file_id: str) -> None:
    _collection().delete(where={"file_id": file_id})


def count_file_vectors(file_id: str) -> int:
    return len(_collection().get(where={"file_id": file_id}, include=[])["ids"])


def count_all_vectors() -> int:
    return _collection().count()


def get_file_chunks(file_id: str) -> list[tuple[int, str, dict[str, Any]]]:
    """All stored chunks of one file as (chunk_index, text, metadata), in order."""
    result = _collection().get(where={"file_id": file_id}, include=["documents", "metadatas"])
    chunks = [
        (int(metadata["chunk_index"]), text or "", dict(metadata))
        for text, metadata in zip(result["documents"], result["metadatas"])
    ]
    return sorted(chunks, key=lambda chunk: chunk[0])


def query_chunks(
    embedding: list[float], n_results: int, file_id: str | None = None
) -> list[ChunkHit]:
    """Return the n chunks closest to the query vector, optionally within one file."""
    collection = _collection()
    total = count_file_vectors(file_id) if file_id else collection.count()
    if total == 0:
        return []
    result = collection.query(
        query_embeddings=[embedding],
        n_results=min(n_results, total),
        where={"file_id": file_id} if file_id else None,
        include=["documents", "metadatas", "distances"],
    )
    hits = []
    for chunk_id, text, metadata, distance in zip(
        result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        hits.append(
            ChunkHit(
                chunk_id=chunk_id,
                file_id=str(metadata["file_id"]),
                filename=str(metadata["filename"]),
                chunk_index=int(metadata["chunk_index"]),
                text=text or "",
                distance=float(distance),
                metadata=dict(metadata),
            )
        )
    return hits
