"""flask create-superadmin (app/cli_admin.py) on SQLite.

Usage: cd backend && python -m pytest tests/test_cli_admin.py
"""
import os

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import pytest

from app import create_app
from app.config import Config
from app.models import AuditLog, User
from app.models.plan import PlanTier
from app.models.user import Role


@pytest.fixture()
def app(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {}
        SECRET_KEY = "test-secret"

    return create_app(TestConfig)


def run(app, *args, env=None, input=None):
    return app.test_cli_runner().invoke(args=["create-superadmin", *args], env=env, input=input)


def test_creates_superadmin_with_prompted_password(app):
    result = run(app, "--email", "Owner@Example.com", "--name", "Owner", input="long-enough-pw\nlong-enough-pw\n")
    assert result.exit_code == 0, result.output
    with app.app_context():
        user = User.query.filter_by(email="owner@example.com").one()
        assert user.role == Role.SUPERADMIN and user.is_active and user.full_name == "Owner"
        assert user.check_password("long-enough-pw")
        assert user.subscription.plan.tier == PlanTier.ENTERPRISE
        assert AuditLog.query.filter_by(action="superadmin_created_cli", user_id=user.id).count() == 1


def test_password_from_environment_and_reset(app):
    env = {"ADMIN_PW": "first-password"}
    assert run(app, "--email", "a@example.com", "--password-env", "ADMIN_PW", env=env).exit_code == 0

    again = run(app, "--email", "a@example.com", "--password-env", "ADMIN_PW", env=env)
    assert again.exit_code != 0 and "already exists" in again.output

    reset = run(app, "--email", "a@example.com", "--password-env", "ADMIN_PW", "--reset-password",
                env={"ADMIN_PW": "second-password"})
    assert reset.exit_code == 0, reset.output
    with app.app_context():
        assert User.query.filter_by(email="a@example.com").one().check_password("second-password")


@pytest.mark.parametrize("args, env, message", [
    (["--email", "b@example.com", "--password-env", "ADMIN_PW"], {"ADMIN_PW": "short"}, "at least 8"),
    (["--email", "b@example.com", "--password-env", "MISSING_PW"], {}, "empty or not set"),
    (["--email", "nobody@example.com", "--password-env", "ADMIN_PW", "--reset-password"],
     {"ADMIN_PW": "long-enough-pw"}, "does not exist"),
    (["--email", "not-an-email", "--password-env", "ADMIN_PW"], {"ADMIN_PW": "long-enough-pw"}, "Invalid email"),
])
def test_rejects_bad_input(app, args, env, message):
    result = run(app, *args, env=env)
    assert result.exit_code != 0 and message in result.output
    with app.app_context():
        assert User.query.count() == 0


def test_secret_key_is_derived_when_unset():
    from app.config import _derived_secret_key
    key = _derived_secret_key("Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")
    assert len(key) == 64 and key == _derived_secret_key("Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")
    assert key != _derived_secret_key("another-key")
