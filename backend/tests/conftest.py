import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import agent_service, embedding_service
from tests.fake_anthropic import FakeAnthropic
from tests.fake_openai import FakeOpenAI


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point every test at a throwaway data folder instead of backend/data."""
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.ensure_data_dirs()
    yield settings.data_dir


@pytest.fixture(autouse=True)
def fake_openai(monkeypatch) -> FakeOpenAI:
    """Tests never call the real OpenAI API."""
    fake = FakeOpenAI()
    monkeypatch.setattr(embedding_service, "_client", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def fake_claude(monkeypatch) -> FakeAnthropic:
    """Tests never call the real Anthropic API; each test scripts Claude's replies."""
    fake = FakeAnthropic()
    monkeypatch.setattr(agent_service, "_client", lambda: fake)
    return fake


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def upload(client):
    """Upload a text document and return its JSON record."""

    def _upload(filename: str, content: str) -> dict:
        response = client.post(
            "/api/documents/upload", files={"file": (filename, content.encode(), "text/plain")}
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _upload
