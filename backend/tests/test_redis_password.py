"""Redis password at start-up: the app refuses to start when Redis and REDIS_URL disagree on the password.

The Redis replies are simulated (the same errors redis-py raises against Redis 7, checked by hand against
real containers). No network.
Usage: cd backend && python -m pytest tests/test_redis_password.py
"""
import os

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import pytest
import redis as redis_lib

from app.core import redis_check


class FakeClient:
    def __init__(self, error):
        self.error = error

    def ping(self):
        if self.error:
            raise self.error
        return True

    def close(self):
        pass


@pytest.fixture()
def reply(monkeypatch):
    def set_reply(error):
        monkeypatch.setattr(redis_check.redis_lib, "from_url", lambda url, **kw: FakeClient(error))
    return set_reply


def test_password_required_but_missing(reply):
    reply(redis_lib.AuthenticationError("Authentication required."))
    problem = redis_check.redis_password_problem("redis://redis:6379/0")
    assert "requires a password" in problem and "REDIS_PASSWORD" in problem


def test_noauth_as_response_error(reply):
    reply(redis_lib.ResponseError("NOAUTH Authentication required."))
    assert "requires a password" in redis_check.redis_password_problem("redis://redis:6379/0")


def test_wrong_password(reply):
    reply(redis_lib.AuthenticationError("invalid username-password pair or user is disabled."))
    assert "rejected the password" in redis_check.redis_password_problem("redis://:nope@redis:6379/0")


def test_password_sent_to_a_redis_without_one(reply):
    reply(redis_lib.AuthenticationError("AUTH <password> called without any password configured for the "
                                        "default user. Are you sure your configuration is correct?"))
    assert "Redis has none" in redis_check.redis_password_problem("redis://:pw@redis:6379/0")


@pytest.mark.parametrize("error", [None, redis_lib.ConnectionError("refused"), redis_lib.TimeoutError("slow")])
def test_no_problem_when_it_answers_or_is_down(reply, error):
    assert redis_check.redis_password_problem("redis://:pw@redis:6379/0") is None


def test_create_app_refuses_to_start(tmp_path, reply):
    from app import create_app
    from app.config import Config

    class ProdLikeConfig(Config):
        TESTING = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {}
        REDIS_URL = "redis://redis:6379/0"

    reply(redis_lib.AuthenticationError("Authentication required."))
    with pytest.raises(RuntimeError, match="SwarMind cannot start: Redis requires a password"):
        create_app(ProdLikeConfig)
