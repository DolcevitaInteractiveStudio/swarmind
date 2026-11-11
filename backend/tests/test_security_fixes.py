"""Regression tests for the fixes of the 2026-11 security audit.

PDF export markup escaping, bounded document parsing, admin/superadmin target guard, JWT claims,
login input validation. SQLite, dummy users, no network.
Usage: cd backend && python -m pytest tests/test_security_fixes.py
"""
import io
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import jwt
import pytest

from app import create_app
from app.config import Config
from app.models import Plan, Project, Simulation, Subscription, User, db
from app.models.plan import PlanTier
from app.models.user import Role
from app.utils import document_parser as dp
from app.utils.state_store import StateStore


@pytest.fixture()
def app(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {}
        UPLOADS_DIR = str(tmp_path / "uploads")
        SIMULATIONS_DIR = str(tmp_path / "sims")
        SECRET_KEY = "test-secret"

    app = create_app(TestConfig)
    with app.app_context():
        for email, role, tier in (("super@example.com", Role.SUPERADMIN, PlanTier.ENTERPRISE),
                                  ("admin@example.com", Role.ADMIN, PlanTier.ENTERPRISE),
                                  ("user@example.com", Role.USER, PlanTier.PRO)):
            u = User(email=email, role=role, is_active=True)
            u.set_password("pw-123456")
            db.session.add(u)
            db.session.add(Subscription(user=u, plan=Plan.query.filter_by(tier=tier).one()))
        db.session.commit()
    return app


def token(app, email, **claims):
    from app.api.auth import _make_token
    with app.app_context():
        uid = User.query.filter_by(email=email).one().id
        if not claims:
            return _make_token(uid)
        return jwt.encode({"sub": uid, **claims}, app.config["SECRET_KEY"], algorithm="HS256")


def hdr(t):
    return {"Authorization": f"Bearer {t}"}


# ── PDF export ───────────────────────────────────────────────────────────────

def test_pdf_text_escapes_markup_and_keeps_bold():
    from app.api.report import _pdf_text
    out = _pdf_text('Topic <img src="http://127.0.0.1:9/x.png"/> & **bold**')
    assert "<img" not in out and "&lt;img" in out and "&amp;" in out
    assert out.endswith("<b>bold</b>")


def test_pdf_export_does_not_load_resources_named_by_the_report(app, tmp_path):
    secret_png = tmp_path / "local.png"
    from PIL import Image
    Image.new("RGB", (4, 4), "red").save(secret_png)
    with app.app_context():
        user = User.query.filter_by(email="user@example.com").one()
        db.session.add(Project(id="p-pdf", user_id=user.id, name="P", source_filename="b.txt",
                               source_file_path="/nonexistent", graph_built=True))
        db.session.add(Simulation(id="s-pdf", project_id="p-pdf", user_id=user.id,
                                  topic="t", prediction_requirement="q"))
        db.session.commit()
        StateStore(app.config["SIMULATIONS_DIR"]).save_report("s-pdf", {"report_markdown": (
            f"# Report\n\n- Topic analysed: <img src=\"{secret_png}\" width=\"4\" height=\"4\"/>\n"
            "| a | b |\n|---|---|\n| <img src=\"http://127.0.0.1:9/x.png\"/> | 2 |\n")})
    res = app.test_client().get("/api/report/s-pdf/export/pdf", headers=hdr(token(app, "user@example.com")))
    assert res.status_code == 200 and res.mimetype == "application/pdf"
    assert b"/Subtype /Image" not in res.data


# ── Document parsing bounds ──────────────────────────────────────────────────

def test_json_brief_is_not_re_indented(tmp_path):
    payload = "[" * 300 + ",".join(["0"] * 2000) + "]" * 300
    f = tmp_path / "brief.json"
    f.write_text(payload, encoding="utf-8")
    assert dp.parse_document(str(f)) == payload


def test_docx_with_large_uncompressed_content_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "MAX_DOCX_UNCOMPRESSED_BYTES", 100_000)
    body = "".join("<w:p><w:r><w:t>%s</w:t></w:r></w:p>" % ("A" * 1000) for _ in range(200))
    f = tmp_path / "brief.docx"
    with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
    with pytest.raises(dp.DocumentTooLarge):
        dp.parse_document(str(f))


def test_extracted_text_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "MAX_EXTRACTED_CHARS", 1000)
    f = tmp_path / "brief.txt"
    f.write_text("x" * 1001, encoding="utf-8")
    with pytest.raises(dp.DocumentTooLarge):
        dp.parse_document(str(f))


# ── Admin guard, JWT claims, login validation ────────────────────────────────

def test_admin_cannot_modify_a_superadmin(app):
    with app.app_context():
        sa = User.query.filter_by(email="super@example.com").one()
        free = Plan.query.filter_by(tier=PlanTier.FREE).one()
        sa_id, free_id = sa.id, free.id
    c = app.test_client()
    res = c.put(f"/api/admin/users/{sa_id}", json={"plan_id": free_id, "full_name": "x"},
                headers=hdr(token(app, "admin@example.com")))
    assert res.status_code == 403
    with app.app_context():
        assert User.query.get(sa_id).subscription.plan.tier == PlanTier.ENTERPRISE
    ok = c.put(f"/api/admin/users/{sa_id}", json={"full_name": "Owner"}, headers=hdr(token(app, "super@example.com")))
    assert ok.status_code == 200


def test_tokens_without_exp_are_rejected(app):
    now = datetime.now(timezone.utc)
    c = app.test_client()
    assert c.get("/api/auth/me", headers=hdr(token(app, "user@example.com", iat=now))).status_code == 401
    good = token(app, "user@example.com", iat=now, exp=now + timedelta(hours=1))
    assert c.get("/api/auth/me", headers=hdr(good)).status_code == 200


@pytest.mark.parametrize("body", [{"email": ["a"], "password": "x"}, {"email": "user@example.com", "password": 123}, {}])
def test_login_rejects_malformed_input(app, body):
    assert app.test_client().post("/api/auth/login", data=json.dumps(body),
                                  content_type="application/json").status_code == 400
