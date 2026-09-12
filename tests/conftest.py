"""Test fixtures.

DATABASE_URL is set before main is imported: database.py builds the engine at
import time, so pointing it at an in-memory database afterwards would be too
late and the suite would write to the developer's real urls.db.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ENVIRONMENT"] = "development"
os.environ["BACKEND_URL"] = "http://testserver"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from database import engine  # noqa: E402
from models import Base  # noqa: E402


@pytest.fixture
def client():
    """A client backed by an empty database, rebuilt for every test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(main.app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def shorten(client):
    """Create a short link and return the parsed response body."""
    def _shorten(url="https://example.com/some/long/path", custom=None):
        payload = {"original_url": url}
        if custom is not None:
            payload["custom"] = custom
        return client.post("/api/shorten", json=payload)
    return _shorten
