"""Graph builds on the shared system key are counted per user and per month (GRAPH_SYSTEM_KEY_MONTHLY_LIMIT).

A user with a provider key of their own builds with it, never on the system key. SQLite, fake Celery task,
fictional brief. The migration on PostgreSQL only with SWARMIND_TEST_PG_URL (empty database).
Usage: cd backend && python -m pytest tests/test_graph_system_key.py
"""
import io
import os
from datetime import datetime

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app import create_app
from app.config import Config
from app.models import LLMCredential, Plan, Project, Subscription, User, db
from app.models.plan import PlanTier
from app.models.user import Role

PG_URL = os.environ.get("SWARMIND_TEST_PG_URL")


def make_app(tmp_path, monkeypatch, limit=2, groq_key="gsk-system-test"):
    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {}
        UPLOADS_DIR = str(tmp_path / "uploads")
        SIMULATIONS_DIR = str(tmp_path / "sims")
        SECRET_KEY = "test-secret"
        GROQ_API_KEY = groq_key
        GRAPH_SYSTEM_KEY_MONTHLY_LIMIT = limit

    from app.simulation import tasks
    queued = []
    fake = SimpleNamespace(delay=lambda *a, **k: queued.append(a) or SimpleNamespace(id=f"task-{len(queued)}"),
                           apply_async=lambda *a, **k: queued.append(a) or SimpleNamespace(id=f"task-{len(queued)}"))
    monkeypatch.setattr(tasks, "build_graph_task", fake)
    app = create_app(TestConfig)
    app.queued = queued
    with app.app_context():
        plan = Plan.query.filter_by(tier=PlanTier.PRO).one()
        plan.max_projects = -1
        user = User(email="user@example.com", role=Role.USER, is_active=True)
        user.set_password("pw-123456")
        db.session.add(user)
        db.session.add(Subscription(user=user, plan=plan))
        db.session.commit()
    return app


def headers(app):
    from app.api.auth import _make_token
    with app.app_context():
        return {"Authorization": f"Bearer {_make_token(User.query.one().id)}"}


def upload(app, **form):
    data = {"file": (io.BytesIO(b"A fictional brief about a bakery app."), "brief.txt"), "name": "Test", **form}
    return app.test_client().post("/api/graph/upload", data=data, headers=headers(app),
                                  content_type="multipart/form-data")


def used(app):
    with app.app_context():
        return User.query.one().subscription.graph_system_builds_used


def add_credential(app, provider="openrouter"):
    with app.app_context():
        cred = LLMCredential(user_id=User.query.one().id, provider=provider, label="mine", is_active=True)
        cred.set_api_key("sk-fictional-0000")
        db.session.add(cred)
        db.session.commit()
        return cred.id


def test_system_key_builds_stop_at_the_monthly_limit(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, limit=2)
    assert upload(app).status_code == 202 and upload(app).status_code == 202
    assert used(app) == 2
    res = upload(app)
    assert res.status_code == 403 and res.get_json()["code"] == "graph_system_key_limit"
    assert "2" in res.get_json()["error"]
    with app.app_context():
        assert Project.query.count() == 2
    assert len(os.listdir(app.config["UPLOADS_DIR"])) == 2        # the refused upload left no files
    assert len(app.queued) == 2


def test_own_key_is_used_and_not_counted(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, limit=0)
    cred_id = add_credential(app)
    res = upload(app, llm_provider="groq", model_heavy="llama-3.3-70b-versatile")
    assert res.status_code == 202
    assert used(app) == 0
    with app.app_context():
        project = db.session.get(Project, res.get_json()["project_id"])
        assert project.llm_credential_id == cred_id and project.llm_provider == "openrouter"
        assert project.model_heavy is None                 # chosen for another provider


def test_limit_zero_refuses_the_system_key(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, limit=0)
    assert upload(app).status_code == 403


def test_unlimited_still_counts(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, limit=-1)
    for _ in range(3):
        assert upload(app).status_code == 202
    assert used(app) == 3


def test_new_period_starts_again(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, limit=2)
    with app.app_context():
        sub = User.query.one().subscription
        sub.graph_system_builds_used = 2
        sub.graph_system_builds_period = datetime(2020, 1, 1)
        db.session.commit()
    assert upload(app).status_code == 202
    assert used(app) == 1


def test_rebuild_is_counted_and_refused_at_the_limit(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, limit=1)
    brief = tmp_path / "brief.txt"
    brief.write_text("A fictional brief.", encoding="utf-8")
    with app.app_context():
        db.session.add(Project(id="p-1", user_id=User.query.one().id, name="P", source_filename="brief.txt",
                               source_file_path=str(brief), graph_built=True))
        db.session.commit()
    client = app.test_client()
    assert client.post("/api/graph/p-1/rebuild", headers=headers(app)).status_code == 202
    assert used(app) == 1
    with app.app_context():
        db.session.get(Project, "p-1").graph_task_id = None
        db.session.get(Project, "p-1").graph_built = True
        db.session.commit()
    res = client.post("/api/graph/p-1/rebuild", headers=headers(app))
    assert res.status_code == 403 and res.get_json()["code"] == "graph_system_key_limit"


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
            plan_id = Plan.query.filter_by(tier=PlanTier.FREE).one().id
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE subscriptions DROP COLUMN graph_system_builds_used"))
                conn.execute(text("ALTER TABLE subscriptions DROP COLUMN graph_system_builds_period"))
                conn.execute(text("INSERT INTO users (id, email, password_hash, full_name, role, is_active, "
                                  "is_verified, token_version) VALUES ('u-1', 'old@example.com', 'x', 'Old', 'USER', "
                                  "true, false, 0)"))
                conn.execute(text("INSERT INTO subscriptions (id, user_id, plan_id, status, simulations_used_this_month)"
                                  " VALUES ('s-1', 'u-1', :plan, 'ACTIVE', 0)"), {"plan": plan_id})
            stamp(directory=directory, revision="f1b7d3c9a2e5")
            upgrade(directory=directory, revision="a8e2c4f6b0d3")
            with db.engine.connect() as conn:
                row = conn.execute(text("SELECT graph_system_builds_used, graph_system_builds_period "
                                        "FROM subscriptions WHERE id = 's-1'")).one()
                assert row == (0, None)
            downgrade(directory=directory, revision="f1b7d3c9a2e5")
            upgrade(directory=directory)
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()
            with db.engine.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.mark.skipif(not PG_URL, reason="SWARMIND_TEST_PG_URL not set")
def test_reservation_sql_on_postgres():
    """The conditional UPDATE (limit, period rollover) on PostgreSQL."""
    from app.api.graph import _release_system_graph_build, _reserve_system_graph_build

    class PgConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = PG_URL
        GRAPH_SYSTEM_KEY_MONTHLY_LIMIT = 2

    application = create_app(PgConfig)
    try:
        with application.app_context():
            user = User(email="pg@example.com", role=Role.USER, is_active=True)
            user.set_password("pw-123456")
            db.session.add(user)
            db.session.add(Subscription(user=user, plan=Plan.query.filter_by(tier=PlanTier.FREE).one()))
            db.session.commit()
            sub = user.subscription
            assert [_reserve_system_graph_build(sub) for _ in range(3)] == [True, True, False]
            db.session.commit()
            _release_system_graph_build(sub)
            db.session.commit()
            assert sub.graph_system_builds_used == 1
            sub.graph_system_builds_used, sub.graph_system_builds_period = 2, datetime(2020, 1, 1)
            db.session.commit()
            assert _reserve_system_graph_build(sub) is True
            db.session.commit()
            assert sub.graph_system_builds_used == 1
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()
            with db.engine.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
