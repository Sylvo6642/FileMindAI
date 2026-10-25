from fastapi.testclient import TestClient

from app.core.config import BACKEND_DIR, settings
from app.main import app


def test_health_returns_ok():
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "FileMind AI"
    assert isinstance(body["openai_configured"], bool)


def test_health_never_exposes_key_values():
    with TestClient(app) as client:
        text = client.get("/api/health").text

    for key in (settings.openai_api_key, settings.anthropic_api_key):
        if key:
            assert key not in text


def test_cors_allows_angular_origin_only():
    with TestClient(app) as client:
        allowed = client.get("/api/health", headers={"Origin": "http://localhost:4200"})
        blocked = client.get("/api/health", headers={"Origin": "http://evil.example"})

    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:4200"
    assert "access-control-allow-origin" not in blocked.headers


def test_data_paths_live_inside_backend():
    assert settings.data_dir == BACKEND_DIR / "data"
    assert settings.uploads_dir.is_relative_to(BACKEND_DIR)
    assert settings.sqlite_path.name == "filemind.db"
