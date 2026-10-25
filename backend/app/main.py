"""FastAPI entry point.

Run from the backend folder:
    python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import debug, documents, health
from app.core.config import settings
from app.core.database import init_db
from app.core.errors import register_error_handlers
from app.services import metadata_service

logger = logging.getLogger("filemind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once at startup: create data folders and the SQLite schema.
    settings.ensure_data_dirs()
    init_db()
    # Indexed documents persist in ChromaDB and are not reprocessed. Anything
    # caught mid-indexing by a shutdown is flagged so it can be reindexed.
    interrupted = metadata_service.mark_unfinished_as_failed()
    if interrupted:
        logger.warning("Marked %d interrupted document(s) as failed", interrupted)
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(debug.router)
