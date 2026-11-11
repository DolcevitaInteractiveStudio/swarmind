"""Plans page: public plans endpoint only with BILLING_ENABLED, ranked plans and the contact for a change.

The page called /api/admin/plans (admins only) and filtered on a field the plans did not have: it was empty
for every user. SQLite, dummy users, no network.
Usage: cd backend && python -m pytest tests/test_plans_page.py
"""
import os

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import pytest

from app import create_app
from app.config import Config
from app.core.i18n import t
from app.models import Plan, db


def _app(tmp_path, billing: bool, contact: str = ""):
    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {}
        UPLOADS_DIR = str(tmp_path / "uploads")
        SIMULATIONS_DIR = str(tmp_path / "sims")
        SECRET_KEY = "test-secret"
        BILLING_ENABLED = billing
        CONTACT_EMAIL = contact

    return create_app(TestConfig)


def test_plans_are_not_served_without_billing(tmp_path):
    res = _app(tmp_path, billing=False).test_client().get("/api/site/plans")
    assert res.status_code == 404


def test_plans_are_public_ranked_and_carry_the_contact(tmp_path):
    app = _app(tmp_path, billing=True, contact="plans@example.com")
    with app.app_context():
        tiers = sorted(p.tier.value for p in Plan.query.all())
    res = app.test_client().get("/api/site/plans")          # no token: the page is public
    assert res.status_code == 200
    data = res.get_json()
    assert data["contact_email"] == "plans@example.com"
    assert [p["rank"] for p in data["plans"]] == list(range(len(tiers)))
    order = {"free": 0, "pro": 1, "enterprise": 2}
    assert [order[p["tier"]] for p in data["plans"]] == sorted(order[x] for x in tiers)
    assert all(p["is_active"] for p in data["plans"])


def test_inactive_plans_are_left_out(tmp_path):
    app = _app(tmp_path, billing=True)
    with app.app_context():
        plan = Plan.query.filter_by(tier=Plan.query.first().tier).first()
        plan.is_active = False
        db.session.commit()
        hidden = plan.id
    data = app.test_client().get("/api/site/plans").get_json()
    assert hidden not in {p["id"] for p in data["plans"]}
    assert data["contact_email"] == ""


@pytest.mark.parametrize("lang", ["en", "it"])
def test_project_limit_message_does_not_offer_an_upgrade(lang):
    text = t(lang, "errors.project_limit", max=3).lower()
    assert "upgrade" not in text and "aggiorna" not in text
