"""API keys entered in the app: status, a free validity check, and saving to backend/.env.

A key only ever travels browser -> local backend -> its own provider. The
frontend never gets it back: status responses carry a masked hint at most.
"""

import os
import re
from dataclasses import dataclass
from typing import Literal

import anthropic
import openai

from app.core.config import settings
from app.core.errors import ApiError
from app.services import agent_service, embedding_service

Provider = Literal["openai", "anthropic"]

_CHECK_TIMEOUT_SECONDS = 10
# Keys are plain tokens; anything else (spaces, quotes, newlines) would also corrupt .env.
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{20,300}$")


@dataclass(frozen=True)
class _Spec:
    label: str
    env_var: str
    setting: str
    prefix: str


SPECS: dict[str, _Spec] = {
    "openai": _Spec("OpenAI", "OPENAI_API_KEY", "openai_api_key", "sk-"),
    "anthropic": _Spec("Anthropic", "ANTHROPIC_API_KEY", "anthropic_api_key", "sk-ant-"),
}


@dataclass
class KeyStatus:
    configured: bool
    hint: str | None


def mask(key: str) -> str | None:
    return f"{key[:3]}…{key[-4:]}" if key else None


def status() -> dict[str, KeyStatus]:
    result = {}
    for provider, spec in SPECS.items():
        key = getattr(settings, spec.setting)
        result[provider] = KeyStatus(configured=bool(key), hint=mask(key))
    return result


def check_format(provider: str, key: str) -> str:
    spec = SPECS[provider]
    key = key.strip()
    looks_right = bool(_KEY_PATTERN.match(key)) and key.startswith(spec.prefix)
    # Both providers use "sk-"; an Anthropic key pasted into the OpenAI box is a common slip.
    if provider == "openai" and key.startswith("sk-ant-"):
        looks_right = False
    if not looks_right:
        raise ApiError(
            422,
            "invalid_key_format",
            f"That doesn't look like an {spec.label} API key. It should start with '{spec.prefix}'.",
        )
    return key


def verify_with_provider(provider: str, key: str) -> None:
    """Ask the provider to list its models with this key: free, no tokens used."""
    label = SPECS[provider].label
    try:
        if provider == "openai":
            client = openai.OpenAI(api_key=key, timeout=_CHECK_TIMEOUT_SECONDS, max_retries=0)
            client.models.list()
        else:
            client = anthropic.Anthropic(api_key=key, timeout=_CHECK_TIMEOUT_SECONDS, max_retries=0)
            client.models.list(limit=1)
    except (openai.AuthenticationError, anthropic.AuthenticationError):
        raise ApiError(
            400,
            "key_rejected",
            f"{label} rejected this key. Check that it was copied completely and is still active.",
        )
    except (openai.PermissionDeniedError, anthropic.PermissionDeniedError):
        raise ApiError(400, "key_rejected", f"{label} recognised this key but denied access to it.")
    except (openai.APIConnectionError, anthropic.APIConnectionError):
        raise ApiError(
            502,
            "provider_unreachable",
            f"Could not reach {label} to check the key. Check your internet connection.",
        )
    except (openai.APIError, anthropic.APIError):
        raise ApiError(502, "provider_error", f"{label} could not check the key right now. Try again.")


def save(provider: str, key: str) -> KeyStatus:
    spec = SPECS[provider]
    key = check_format(provider, key)
    verify_with_provider(provider, key)
    _write_env(spec.env_var, key)
    # Use it straight away, without a restart.
    os.environ[spec.env_var] = key
    setattr(settings, spec.setting, key)
    _reset_clients()
    return KeyStatus(configured=True, hint=mask(key))


def _reset_clients() -> None:
    """The SDK clients are cached with the old key; the next call builds new ones."""
    embedding_service._client.cache_clear()
    agent_service._client.cache_clear()


def _write_env(name: str, value: str) -> None:
    """Set NAME=value in .env, keeping every other line. A new .env starts from .env.example."""
    path = settings.env_file
    example = path.with_name(".env.example")
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    elif example.exists():
        lines = example.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    assignment = re.compile(rf"^\s*{re.escape(name)}\s*=")
    out: list[str] = []
    written = False
    for line in lines:
        if assignment.match(line):
            if not written:
                out.append(f"{name}={value}")
                written = True
            continue  # drop duplicate assignments
        out.append(line)
    if not written:
        out.append(f"{name}={value}")

    # Write a sibling file and swap it in, so a crash never leaves a half-written .env.
    temp = path.with_name(path.name + ".tmp")
    temp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(temp, path)
