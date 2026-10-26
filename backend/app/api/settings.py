from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.errors import ApiError
from app.models.settings import KeyIn, KeysOut, KeyStatusOut
from app.services import keys_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _status() -> KeysOut:
    return KeysOut(**{p: KeyStatusOut(**asdict(s)) for p, s in keys_service.status().items()})


@router.get("/keys", response_model=KeysOut)
def get_keys() -> KeysOut:
    return _status()


@router.put("/keys/{provider}", response_model=KeysOut)
async def put_key(provider: Literal["openai", "anthropic"], body: KeyIn, request: Request) -> KeysOut:
    # Writing secrets to disk: only the FileMind frontend may ask, not some other open website.
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        raise ApiError(403, "forbidden_origin", "Keys can only be changed from the FileMind app.")
    await run_in_threadpool(keys_service.save, provider, body.key)
    return _status()
