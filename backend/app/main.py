"""FastAPI entry point.

Run from the backend folder:
    python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once at startup: make sure data/uploads and data/chroma exist.
    settings.ensure_data_dirs()
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

app.include_router(health.router)
