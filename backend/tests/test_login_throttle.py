"""Login throttling: per-account and per-IP limits on failed password checks, 429 with Retry-After, en/it.

In-memory stand-in for Redis, SQLite, dummy users. No network.
Usage: cd backend && python -m pytest tests/test_login_throttle.py
"""
import os
import time

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import pytest
import redis as redis_lib

from app import create_app
from app.config import Config
from app.core import login_throttle
from app.models import Plan, Subscription, User, db
from app.models.plan import PlanTier
from app.models.user import Role


class FakeRedis:
    """The few Redis commands the throttle uses, with expiry."""

    def __init__(self):
        self.values, self.expiry = {}, {}

    def _alive(self, key):
        if key in self.expiry and self.expiry[key] <= time.time():
            self.values.pop(key, None)
            self.expiry.pop(key, None)
        return key in self.values

    def get(self, key):
        return str(self.values[key]).encode() if self._alive(key) else None

    def ttl(self, key):
        if not self._alive(key):
            return -2
        return int(self.expiry[key] - time.time()) if key in self.expiry else -1

    def incr(self, key):
        self.values[key] = (self.values[key] if self._alive(key) else 0) + 1
        return self.values[key]

    def expire(self, key, seconds, nx=False):
        if nx and key in self.expiry:
            return False
        self.expiry[key] = time.time() + seconds
        return True

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
            self.expiry.pop(key, None)

    def pipeline(self, transaction=True):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis):
        self.redis, self.calls = redis, []

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append((name, a, k))

    def execute(self):
        return [getattr(self.redis, name)(*a, **k) for name, a, k in self.calls]


class DownRedis:
    def __getattr__(self, name):
        def fail(*a, **k):
            raise redis_lib.ConnectionError("redis is down")
        return fail


@pytest.fixture()
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(login_throttle, "_client", lambda: fake)
    return fake


@pytest.fixture()
def app(tmp_path, fake_redis):
    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {}
        UPLOADS_DIR = str(tmp_path / "uploads")
        SIMULATIONS_DIR = str(tmp_path / "sims")
        SECRET_KEY = "test-secret"
        LOGIN_MAX_FAILURES_PER_ACCOUNT = 3
        LOGIN_MAX_FAILURES_PER_IP = 5
        LOGIN_THROTTLE_WINDOW_SECONDS = 600
        TRUSTED_PROXY_COUNT = 1

    application = create_app(TestConfig)
    with application.app_context():
        for email in ("ada@example.com", "bea@example.com", "cleo@example.com"):
            user = User(email=email, role=Role.USER, is_active=True)
            user.set_password("right-password")
            db.session.add(user)
            db.session.add(Subscription(user=user, plan=Plan.query.filter_by(tier=PlanTier.FREE).one()))
        db.session.commit()
    return application


def login(client, email, password, ip="198.51.100.7", lang="en"):
    return client.post("/api/auth/login", json={"email": email, "password": password},
                       headers={"X-Forwarded-For": ip, "Accept-Language": lang})


def test_account_is_throttled_after_the_failures_limit(app):
    client = app.test_client()
    for _ in range(3):
        assert login(client, "ada@example.com", "wrong").status_code == 401
    res = login(client, "ada@example.com", "right-password")            # even the right password waits
    assert res.status_code == 429
    assert 0 < int(res.headers["Retry-After"]) <= 600
    assert res.get_json()["code"] == "too_many_attempts"
    assert res.get_json()["error"] == "Too many failed attempts. Try again in 10 min."
    it = login(client, "ada@example.com", "right-password", lang="it")
    assert it.get_json()["error"] == "Troppi tentativi falliti. Riprova tra 10 min."
    # another account from another IP is not affected
    assert login(client, "bea@example.com", "right-password", ip="198.51.100.8").status_code == 200


def test_ip_is_throttled_across_accounts(app):
    client = app.test_client()
    for i in range(5):
        login(client, f"nobody{i}@example.com", "wrong", ip="203.0.113.9")
    assert login(client, "cleo@example.com", "right-password", ip="203.0.113.9").status_code == 429
    # the client IP comes from X-Forwarded-For (trusted proxy): another client is fine
    assert login(client, "cleo@example.com", "right-password", ip="203.0.113.10").status_code == 200


def test_success_clears_the_account_counter(app):
    client = app.test_client()
    for _ in range(2):
        login(client, "ada@example.com", "wrong")
    assert login(client, "ada@example.com", "right-password").status_code == 200
    for _ in range(2):
        assert login(client, "ada@example.com", "wrong").status_code == 401
    assert login(client, "ada@example.com", "right-password").status_code == 200


def test_no_email_stored_in_redis(app, fake_redis):
    login(app.test_client(), "ada@example.com", "wrong")
    assert not any("ada" in key for key in fake_redis.values)


def test_login_works_when_redis_is_down(app, monkeypatch):
    monkeypatch.setattr(login_throttle, "_client", lambda: DownRedis())
    client = app.test_client()
    for _ in range(5):
        assert login(client, "ada@example.com", "wrong").status_code == 401
    assert login(client, "ada@example.com", "right-password").status_code == 200


def test_password_change_is_throttled(app):
    client = app.test_client()
    token = login(client, "bea@example.com", "right-password").get_json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-Forwarded-For": "198.51.100.20"}
    for _ in range(3):
        res = client.put("/api/auth/me", json={"current_password": "wrong", "new_password": "another-password"},
                         headers=headers)
        assert res.status_code == 400
    res = client.put("/api/auth/me", json={"current_password": "right-password", "new_password": "another-password"},
                     headers=headers)
    assert res.status_code == 429


def test_client_written_forwarded_for_is_ignored_with_one_proxy(app):
    """TRUSTED_PROXY_COUNT=1: only the entry added by the proxy counts. A client that prepends a fake IP to
    X-Forwarded-For stays on its real IP's counter and cannot bypass the per-IP limit."""
    client = app.test_client()
    for i in range(5):
        login(client, f"nobody{i}@example.com", "wrong", ip=f"10.9.9.{i}, 203.0.113.50")
    res = login(client, "cleo@example.com", "right-password", ip="10.9.9.99, 203.0.113.50")
    assert res.status_code == 429
