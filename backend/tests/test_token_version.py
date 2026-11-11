"""token_version: a password change or reset revokes the login tokens issued before it.

SQLite for the API and the CLI; the migration on PostgreSQL only with SWARMIND_TEST_PG_URL (empty database):
  SWARMIND_TEST_PG_URL=postgresql://user:pw@localhost:5432/swarmind_test python -m pytest tests/test_token_version.py
"""
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import jwt
import pytest
from sqlalchemy import text

from app import create_app
from app.config import Config
from app.core import login_throttle
from app.models import Plan, Subscription, User, db
from app.models.plan import PlanTier
from app.models.user import Role

PG_URL = os.environ.get("SWARMIND_TEST_PG_URL")


class NoRedis:
    """Throttle store that never blocks: these tests are about tokens."""
    def get(self, key): return None
    def ttl(self, key): return -2
    def delete(self, *keys): return 0
    def pipeline(self, transaction=True): return self
    def incr(self, key): return 1
    def expire(self, *a, **k): return True
    def execute(self): return []


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(login_throttle, "_client", lambda: NoRedis())

    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {}
        UPLOADS_DIR = str(tmp_path / "uploads")
        SIMULATIONS_DIR = str(tmp_path / "sims")
        SECRET_KEY = "test-secret"

    application = create_app(TestConfig)
    with application.app_context():
        user = User(email="dana@example.com", role=Role.USER, is_active=True)
        user.set_password("first-password")
        db.session.add(user)
        db.session.add(Subscription(user=user, plan=Plan.query.filter_by(tier=PlanTier.FREE).one()))
        db.session.commit()
    return application


def _login(client, password="first-password"):
    res = client.post("/api/auth/login", json={"email": "dana@example.com", "password": password})
    assert res.status_code == 200, res.get_json()
    return res.get_json()["token"]


def _me(client, token):
    return client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})


def test_password_change_revokes_older_tokens(app):
    client = app.test_client()
    other_session, this_session = _login(client), _login(client)
    res = client.put("/api/auth/me", json={"current_password": "first-password", "new_password": "second-password"},
                     headers={"Authorization": f"Bearer {this_session}"})
    assert res.status_code == 200
    new_token = res.get_json()["token"]
    for old in (other_session, this_session):
        revoked = _me(client, old)
        assert revoked.status_code == 401 and "password changed" in revoked.get_json()["error"]
    assert _me(client, new_token).status_code == 200
    assert _me(client, _login(client, "second-password")).status_code == 200


def test_profile_update_without_password_keeps_the_token(app):
    client = app.test_client()
    token = _login(client)
    res = client.put("/api/auth/me", json={"full_name": "Dana Rossi"}, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200 and "token" not in res.get_json()
    assert _me(client, token).status_code == 200


def test_cli_reset_revokes_tokens(app):
    client = app.test_client()
    with app.app_context():
        user = User.query.filter_by(email="dana@example.com").one()
        user.role = Role.SUPERADMIN
        db.session.commit()
    token = _login(client)
    result = app.test_cli_runner().invoke(args=["create-superadmin", "--email", "dana@example.com",
                                                "--password-env", "NEW_PW", "--reset-password"],
                                          env={"NEW_PW": "reset-password-1"})
    assert result.exit_code == 0, result.output
    assert _me(client, token).status_code == 401


def test_token_without_version_is_version_zero(app):
    """Tokens issued before token_version existed have no "tv": valid until the first password change."""
    with app.app_context():
        user = User.query.filter_by(email="dana@example.com").one()
        user.token_version = 0
        db.session.commit()
        now = datetime.now(timezone.utc)
        legacy = jwt.encode({"sub": user.id, "iat": now, "exp": now + timedelta(hours=1)},
                            app.config["SECRET_KEY"], algorithm="HS256")
    client = app.test_client()
    assert _me(client, legacy).status_code == 200
    with app.app_context():
        User.query.filter_by(email="dana@example.com").one().set_password("changed-password")
        db.session.commit()
    assert _me(client, legacy).status_code == 401


# ── Migration on PostgreSQL ──────────────────────────────────────────────────

@pytest.mark.skipif(not PG_URL, reason="SWARMIND_TEST_PG_URL not set")
def test_migration_on_a_populated_database():
    from flask_migrate import downgrade, stamp, upgrade
    from app import MIGRATIONS_DIR

    class PgConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = PG_URL

    application = create_app(PgConfig)
    directory = str(MIGRATIONS_DIR)
    try:
        with application.app_context():
            # Production before this deploy: users without the column, with rows in it
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE users DROP COLUMN token_version"))
                conn.execute(text("INSERT INTO users (id, email, password_hash, full_name, role, is_active, "
                                  "is_verified) VALUES ('u-1', 'old@example.com', 'x', 'Old', 'USER', true, false)"))
            stamp(directory=directory, revision="b5d2f8e41c73")
            upgrade(directory=directory, revision="f1b7d3c9a2e5")
            with db.engine.connect() as conn:
                column = conn.execute(text(
                    "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_name = 'users' AND column_name = 'token_version'")).one()
                assert column[0] == "integer" and column[1] == "NO" and column[2] == "0"
                assert conn.execute(text("SELECT token_version FROM users WHERE id = 'u-1'")).scalar() == 0
            downgrade(directory=directory, revision="b5d2f8e41c73")
            with db.engine.connect() as conn:
                assert conn.execute(text("SELECT count(*) FROM information_schema.columns WHERE "
                                         "table_name = 'users' AND column_name = 'token_version'")).scalar() == 0
                assert conn.execute(text("SELECT email FROM users WHERE id = 'u-1'")).scalar() == "old@example.com"
            upgrade(directory=directory)
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()
            with db.engine.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
