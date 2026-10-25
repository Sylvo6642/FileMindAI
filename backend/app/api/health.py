from fastapi import APIRouter

from app.core.config import settings
from app.models.health import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.version,
        openai_configured=bool(settings.openai_api_key),
        anthropic_configured=bool(settings.anthropic_api_key),
    )
