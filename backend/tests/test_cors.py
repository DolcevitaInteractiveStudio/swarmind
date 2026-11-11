"""CORS: only FRONTEND_URL is an allowed origin, with credentials (flask-cors 6).

SQLite, no network.
Usage: cd backend && python -m pytest tests/test_cors.py
"""
import os

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import pytest

from app import create_app
from app.config import Config


@pytest.fixture()
def client(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {}
        SECRET_KEY = "test-secret"
        FRONTEND_URL = "https://swarmind.example.com"

    return create_app(TestConfig).test_client()


def preflight(client, origin):
    return client.options("/api/auth/login", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type, Authorization"})


def test_frontend_origin_is_allowed_with_credentials(client):
    res = preflight(client, "https://swarmind.example.com")
    assert res.headers.get("Access-Control-Allow-Origin") == "https://swarmind.example.com"
    assert res.headers.get("Access-Control-Allow-Credentials") == "true"
    assert "POST" in res.headers.get("Access-Control-Allow-Methods", "")


@pytest.mark.parametrize("origin", ["https://evil.example.net", "https://swarmind.example.com.evil.net",
                                    "http://swarmind.example.com"])
def test_other_origins_get_no_cors_headers(client, origin):
    res = preflight(client, origin)
    assert "Access-Control-Allow-Origin" not in res.headers
    get = client.get("/api/site", headers={"Origin": origin})
    assert "Access-Control-Allow-Origin" not in get.headers
