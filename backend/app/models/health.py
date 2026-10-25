from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    # Reports only whether keys are present, never their values.
    openai_configured: bool
    anthropic_configured: bool
