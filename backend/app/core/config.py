"""Application settings loaded from backend/.env.

All paths are resolved relative to the backend folder with pathlib, so the
project works no matter which drive or user directory it lives in.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# backend/app/core/config.py -> parents[2] is backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]

load_dotenv(BACKEND_DIR / ".env")


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Settings:
    app_name: str = "FileMind AI"
    version: str = "0.1.0"

    # Secrets: only ever read on the backend, never sent to the frontend.
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", ""))

    # Only the local Angular dev server may call the API from a browser.
    cors_origins: list[str] = field(
        default_factory=lambda: _split_csv(
            os.getenv("CORS_ORIGINS", "http://localhost:4200,http://127.0.0.1:4200")
        )
    )

    data_dir: Path = BACKEND_DIR / "data"

    max_upload_bytes: int = 20 * 1024 * 1024
    chunk_size_tokens: int = 600
    chunk_overlap_tokens: int = 100

    # Documents and queries must always be embedded with the same model.
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    )
    embedding_dimensions: int = field(
        default_factory=lambda: int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
    )
    embedding_batch_size: int = 100

    # Measured on the sample set: relevant top hits scored 0.38-0.59 distance,
    # weaker candidates up to ~0.76, nonsense queries 0.89+. Re-checked in
    # Stage 8 on 16 documents: no-match queries still scored 0.63+ distance, so
    # the cutoff only removes nonsense; deciding "no match" is Claude's job.
    search_max_distance: float = 0.85
    # "hybrid" = vector + keyword (BM25) merged with Reciprocal Rank Fusion;
    # "vector" = embeddings only. See eval/README.md for the measurements.
    search_mode: str = field(default_factory=lambda: os.getenv("SEARCH_MODE", "hybrid"))
    search_rrf_k: int = 60
    search_excerpts_per_file: int = 3
    search_excerpt_chars: int = 400

    # Claude agent. Haiku 5.5 thinks adaptively; effort controls how much.
    agent_effort: str = field(default_factory=lambda: os.getenv("AGENT_EFFORT", "medium"))
    agent_max_tool_rounds: int = 5
    agent_max_tokens: int = 16000
    anthropic_timeout_seconds: float = 60.0
    anthropic_max_retries: int = 2

    # inspect_file returns a bounded view, never the whole document.
    inspect_preview_chars: int = 1500
    inspect_passages: int = 3
    inspect_passage_chars: int = 800
    openai_timeout_seconds: float = 30.0
    openai_max_retries: int = 3

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "filemind.db"

    def ensure_data_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
