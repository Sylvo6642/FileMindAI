import os

import httpx
import openai

import pytest

from app.core.config import settings
from app.core.errors import ApiError
from app.services import keys_service

OPENAI_KEY = "sk-proj-" + "a" * 40 + "WXYZ"
ANTHROPIC_KEY = "sk-ant-api03-" + "b" * 40 + "QRST"
APP_ORIGIN = {"Origin": "http://localhost:4200"}


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    """Start every test with no keys, and restore the real ones afterwards."""
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")


@pytest.fixture
def verified(monkeypatch):
    """Pretend the provider accepted the key: tests never contact OpenAI or Anthropic."""
    checked = []
    monkeypatch.setattr(keys_service, "verify_with_provider", lambda p, k: checked.append((p, k)))
    monkeypatch.setattr(keys_service, "_reset_clients", lambda: None)
    return checked


def _put(client, provider: str, key: str, headers=APP_ORIGIN):
    return client.put(f"/api/settings/keys/{provider}", json={"key": key}, headers=headers)


def test_reports_missing_keys(client):
    body = client.get("/api/settings/keys").json()

    assert body == {
        "openai": {"configured": False, "hint": None},
        "anthropic": {"configured": False, "hint": None},
    }


def test_saves_a_verified_key_to_env_and_uses_it_immediately(client, verified, isolated_env_file):
    isolated_env_file.write_text("# my settings\nSEARCH_MODE=vector\nOPENAI_API_KEY=\n", encoding="utf-8")

    response = _put(client, "openai", f"  {OPENAI_KEY}\n")

    assert response.status_code == 200, response.text
    assert response.json()["openai"] == {"configured": True, "hint": "sk-…WXYZ"}
    assert OPENAI_KEY not in response.text  # never echoed back
    assert verified == [("openai", OPENAI_KEY)]
    assert isolated_env_file.read_text(encoding="utf-8") == (
        f"# my settings\nSEARCH_MODE=vector\nOPENAI_API_KEY={OPENAI_KEY}\n"
    )
    assert settings.openai_api_key == OPENAI_KEY
    assert os.environ["OPENAI_API_KEY"] == OPENAI_KEY
    assert client.get("/api/health").json()["openai_configured"] is True


def test_new_env_file_starts_from_the_example(client, verified, isolated_env_file):
    isolated_env_file.with_name(".env.example").write_text(
        "OPENAI_API_KEY=\nANTHROPIC_API_KEY=\nAGENT_EFFORT=medium\n", encoding="utf-8"
    )

    assert _put(client, "anthropic", ANTHROPIC_KEY).status_code == 200

    assert isolated_env_file.read_text(encoding="utf-8") == (
        f"OPENAI_API_KEY=\nANTHROPIC_API_KEY={ANTHROPIC_KEY}\nAGENT_EFFORT=medium\n"
    )


@pytest.mark.parametrize(
    "provider, key",
    [
        ("openai", "not-a-key"),
        ("openai", ANTHROPIC_KEY),  # Anthropic key in the OpenAI box
        ("anthropic", OPENAI_KEY),
        ("openai", OPENAI_KEY + "\nCORS_ORIGINS=http://evil.example"),  # .env injection
        ("openai", "sk-" + "x" * 10),
    ],
)
def test_rejects_malformed_keys_without_contacting_the_provider(client, verified, isolated_env_file, provider, key):
    response = _put(client, provider, key)

    assert response.status_code == 422
    assert verified == []
    assert not isolated_env_file.exists()


def test_a_key_the_provider_rejects_is_not_saved(client, monkeypatch, isolated_env_file):
    def reject(provider, key):
        raise ApiError(400, "key_rejected", "OpenAI rejected this key.")

    monkeypatch.setattr(keys_service, "verify_with_provider", reject)

    response = _put(client, "openai", OPENAI_KEY)

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "OpenAI rejected this key."
    assert not isolated_env_file.exists()
    assert settings.openai_api_key == ""


def test_other_websites_cannot_set_keys(client, verified, isolated_env_file):
    response = _put(client, "openai", OPENAI_KEY, headers={"Origin": "http://evil.example"})

    assert response.status_code == 403
    assert verified == []
    assert not isolated_env_file.exists()


def test_unknown_provider_is_rejected(client, verified):
    assert _put(client, "gemini", OPENAI_KEY).status_code == 422


def test_provider_errors_become_clear_messages(monkeypatch):
    request = httpx.Request("GET", "https://api.openai.com/v1/models")

    class FakeModels:
        def __init__(self, error):
            self.error = error

        def list(self, **_):
            raise self.error

    def client_raising(error):
        return lambda **_: type("FakeClient", (), {"models": FakeModels(error)})()

    rejected = openai.AuthenticationError("bad key", response=httpx.Response(401, request=request), body=None)
    monkeypatch.setattr(keys_service.openai, "OpenAI", client_raising(rejected))
    with pytest.raises(ApiError) as caught:
        keys_service.verify_with_provider("openai", OPENAI_KEY)
    assert (caught.value.status_code, caught.value.code) == (400, "key_rejected")

    offline = openai.APIConnectionError(request=request)
    monkeypatch.setattr(keys_service.openai, "OpenAI", client_raising(offline))
    with pytest.raises(ApiError) as caught:
        keys_service.verify_with_provider("openai", OPENAI_KEY)
    assert (caught.value.status_code, caught.value.code) == (502, "provider_unreachable")
