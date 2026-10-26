from pydantic import BaseModel, Field


class KeyStatusOut(BaseModel):
    configured: bool
    # Masked, e.g. "sk-…a1B2". The full key is never returned.
    hint: str | None


class KeysOut(BaseModel):
    openai: KeyStatusOut
    anthropic: KeyStatusOut


class KeyIn(BaseModel):
    key: str = Field(min_length=1, max_length=400)
