"""No system key and no credential: upload and simulation create refuse with no_llm_provider.

Usage: cd backend && python -m pytest tests/test_llm_access.py
"""
import io
import os

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import pytest

from app import create_app
from app.config import Config
from app.models import LLMCredential, Plan, Project, Subscription, User, db
from app.models.plan import PlanTier
from app.models.user import Role


def make_app(tmp_path, groq_key):
    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {}
        UPLOADS_DIR = str(tmp_path / "uploads")
        SECRET_KEY = "test-secret"
        GROQ_API_KEY = groq_key

    app = create_app(TestConfig)
    with app.app_context():
        user = User(email="user@example.com", role=Role.USER, is_active=True)
        user.set_password("pw-123456")
        db.session.add(user)
        db.session.add(Subscription(user=user, plan=Plan.query.filter_by(tier=PlanTier.PRO).one()))
        db.session.commit()
    return app


def headers(app):
    from app.api.auth import _make_token
    with app.app_context():
        return {"Authorization": f"Bearer {_make_token(User.query.one().id)}"}


def upload(client, app):
    data = {"file": (io.BytesIO(b"A fictional brief."), "brief.txt"), "name": "Test"}
    return client.post("/api/graph/upload", data=data, headers=headers(app), content_type="multipart/form-data")


@pytest.fixture()
def no_key_app(tmp_path):
    return make_app(tmp_path, "")


def test_system_models_reports_missing_key(no_key_app):
    body = no_key_app.test_client().get("/api/credentials/system-models", headers=headers(no_key_app)).get_json()
    assert body["available"] is False


def test_upload_refused_without_any_provider(no_key_app):
    res = upload(no_key_app.test_client(), no_key_app)
    assert res.status_code == 400 and res.get_json()["code"] == "no_llm_provider"
    with no_key_app.app_context():
        assert Project.query.count() == 0
    assert not os.listdir(no_key_app.config["UPLOADS_DIR"]) if os.path.isdir(no_key_app.config["UPLOADS_DIR"]) else True


def test_simulation_create_refused_without_any_provider(no_key_app):
    with no_key_app.app_context():
        db.session.add(Project(id="p-fixture", user_id=User.query.one().id, name="Fixture",
                               source_filename="brief.txt", source_file_path="/nonexistent/brief.txt",
                               graph_built=True))
        db.session.commit()
    res = no_key_app.test_client().post("/api/simulation/create", json={"project_id": "p-fixture"},
                                        headers=headers(no_key_app))
    assert res.status_code == 400 and res.get_json()["code"] == "no_llm_provider"
    with no_key_app.app_context():
        assert User.query.one().subscription.simulations_used_this_month == 0


def test_user_credential_is_enough(no_key_app):
    from app.core.llm_router import user_has_llm_access
    with no_key_app.app_context():
        user = User.query.one()
        assert not user_has_llm_access(user.id)
        cred = LLMCredential(user_id=user.id, provider="openrouter", label="k", is_active=True)
        cred.set_api_key("sk-test-not-real")
        db.session.add(cred)
        db.session.commit()
        assert user_has_llm_access(user.id)


def test_system_key_is_enough(tmp_path):
    app = make_app(tmp_path, "gsk-test-not-real")
    body = app.test_client().get("/api/credentials/system-models", headers=headers(app)).get_json()
    assert body["available"] is True
    from app.core.llm_router import user_has_llm_access
    with app.app_context():
        assert user_has_llm_access(User.query.one().id)
