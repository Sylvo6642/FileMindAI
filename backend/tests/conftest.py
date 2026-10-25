import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point every test at a throwaway data folder instead of backend/data."""
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.ensure_data_dirs()
    yield settings.data_dir


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
