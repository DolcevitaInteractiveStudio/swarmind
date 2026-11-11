"""Site settings: public endpoint, admin update and validation, image uploads.

Runs on SQLite (create_all), or on PostgreSQL when SWARMIND_TEST_PG_URL points to an empty
database (tables are dropped after each test). The Alembic migration is in test_site_migration.py.
Usage (dev dependencies: pytest, pillow): cd backend && python -m pytest tests/test_site_settings.py
"""
import copy
import io
import os
import time

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import pytest
from PIL import Image

from app import create_app
from app.config import Config
from app.core import site_settings as ss
from app.core.i18n import t_value
from app.models import AuditLog, User, db
from app.models.user import Role


@pytest.fixture()
def app(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = os.environ.get("SWARMIND_TEST_PG_URL") or f"sqlite:///{tmp_path / 'test.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {}
        UPLOADS_DIR = str(tmp_path / "uploads")
        SECRET_KEY = "test-secret"
        CONTACT_EMAIL = "hello@example.com"

    app = create_app(TestConfig)
    with app.app_context():
        for email, role in (("super@example.com", Role.SUPERADMIN), ("admin@example.com", Role.ADMIN), ("user@example.com", Role.USER)):
            u = User(email=email, role=role, is_active=True)
            u.set_password("pw-123456")
            db.session.add(u)
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()
        if db.engine.dialect.name == "postgresql":
            from sqlalchemy import text
            with db.engine.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture()
def client(app):
    return app.test_client()


def auth(app, email):
    from app.api.auth import _make_token
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        return {"Authorization": f"Bearer {_make_token(user.id)}"}


def admin_doc(client, app):
    r = client.get("/api/admin/site", headers=auth(app, "super@example.com"))
    assert r.status_code == 200
    return r.get_json()


def put(client, app, settings, revision, email="super@example.com"):
    return client.put("/api/admin/site", json={"settings": settings, "revision": revision}, headers=auth(app, email))


def png_bytes(size=(64, 64), mode="RGBA", fmt="PNG", **save):
    buf = io.BytesIO()
    Image.new(mode, size, (20, 120, 140, 255) if mode == "RGBA" else (20, 120, 140)).save(buf, fmt, **save)
    return buf.getvalue()


def upload(client, app, data, kind="logo", filename="logo.png", email="super@example.com"):
    return client.post("/api/admin/site/assets", headers=auth(app, email), content_type="multipart/form-data",
                       data={"kind": kind, "file": (io.BytesIO(data), filename)})


# -- Defaults and public endpoint ----------------------------------------------

def test_defaults_are_valid_in_both_languages():
    clean, errors = ss.validate_document(ss.default_document(), lambda name: False)
    assert errors == []
    assert clean == ss.default_document()


def test_default_copy_has_the_same_structure_in_en_and_it():
    def shape(v):
        if isinstance(v, dict):
            return {k: shape(x) for k, x in v.items()}
        if isinstance(v, list):
            return [shape(x) for x in v]
        return type(v).__name__
    assert shape(t_value("en", "landing.default")) == shape(t_value("it", "landing.default"))


def test_default_copy_states_the_positioning():
    assert "does not predict the market" in ss.default_content("en")["hero"]["subtitle"]
    assert "Non prevede il mercato" in ss.default_content("it")["hero"]["subtitle"]


def test_public_endpoint_defaults(client):
    r = client.get("/api/site?lang=it")
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"lang", "landing_enabled", "billing_enabled", "branding", "content"}
    assert body["lang"] == "it" and body["landing_enabled"] is False and body["content"] is None
    assert body["billing_enabled"] is False
    assert set(body["branding"]) == {"product_name", "logo", "favicon", "colors"}
    assert body["branding"]["product_name"] == "SwarMind"
    assert r.headers["ETag"] and "no-cache" in r.headers["Cache-Control"]
    # Same content, same ETag: 304 without a body
    r2 = client.get("/api/site?lang=it", headers={"If-None-Match": r.headers["ETag"]})
    assert r2.status_code == 304 and r2.data == b""


def test_public_endpoint_language_from_header(client):
    assert client.get("/api/site", headers={"Accept-Language": "it-IT,it;q=0.9"}).get_json()["lang"] == "it"
    assert client.get("/api/site?lang=xx").get_json()["lang"] == "en"


def test_public_endpoint_has_no_private_fields(client, app):
    data = admin_doc(client, app)
    s = data["settings"]
    s["landing_enabled"] = True
    s["content"]["en"]["sections"][2]["enabled"] = False   # use cases off
    assert put(client, app, s, data["revision"]).status_code == 200
    body = client.get("/api/site?lang=en").get_json()
    text = str(body)
    for private in ("super@example.com", "revision", "updated_by", "updated_at", "user_id"):
        assert private not in text
    assert [x["type"] for x in body["content"]["sections"]] == ["value", "how", "deliverables", "open_source", "contact"]


# -- Permissions -----------------------------------------------------------------

@pytest.mark.parametrize("email,status", [(None, 401), ("user@example.com", 403), ("admin@example.com", 403)])
def test_only_superadmin_can_update(client, app, email, status):
    headers = auth(app, email) if email else {}
    doc = ss.admin_view(ss.default_document())
    assert client.put("/api/admin/site", json={"settings": doc, "revision": 0}, headers=headers).status_code == status
    assert client.get("/api/admin/site", headers=headers).status_code == status
    r = client.post("/api/admin/site/assets", headers=headers, content_type="multipart/form-data",
                    data={"kind": "logo", "file": (io.BytesIO(png_bytes()), "a.png")})
    assert r.status_code == status


# -- Update ----------------------------------------------------------------------

def test_update_saves_audits_and_bumps_revision(client, app):
    data = admin_doc(client, app)
    s = data["settings"]
    s["landing_enabled"] = True
    s["branding"]["product_name"] = "Acme Lab"
    s["branding"]["colors"]["light"]["primary"] = "#0A6F7B"
    s["content"]["it"]["hero"]["title"] = "Titolo nuovo"
    r = put(client, app, s, data["revision"])
    assert r.status_code == 200, r.get_json()
    saved = r.get_json()
    assert saved["revision"] == 1
    assert saved["settings"]["branding"]["colors"]["light"]["primary"] == "#0a6f7b"
    assert client.get("/api/site?lang=it").get_json()["content"]["hero"]["title"] == "Titolo nuovo"
    with app.app_context():
        entry = AuditLog.query.filter_by(action="admin_site_updated").one()
        assert entry.details["revision"] == 1
        assert "branding.product_name" in entry.details["changed"]
        assert "content.it.hero.title" in entry.details["changed"]
        assert "Titolo nuovo" not in str(entry.details)    # paths only, no values


def test_stale_revision_is_refused(client, app):
    data = admin_doc(client, app)
    assert put(client, app, data["settings"], 0).status_code == 200
    r = put(client, app, data["settings"], 0)
    assert r.status_code == 409 and r.get_json()["revision"] == 1


def test_unknown_keys_are_dropped(client, app):
    data = admin_doc(client, app)
    s = data["settings"]
    s["evil"] = "x"
    s["content"]["en"]["hero"]["onclick"] = "alert(1)"
    assert put(client, app, s, data["revision"]).status_code == 200
    stored = admin_doc(client, app)["settings"]
    assert "evil" not in stored and "onclick" not in stored["content"]["en"]["hero"]


def errors_for(client, app, mutate):
    data = admin_doc(client, app)
    s = copy.deepcopy(data["settings"])
    mutate(s)
    r = put(client, app, s, data["revision"])
    assert r.status_code == 400, r.get_json()
    return {(e["path"], e["code"]) for e in r.get_json()["fields"]}


def set_path(path, value):
    def mutate(s):
        node = s
        keys = path.split(".")
        for k in keys[:-1]:
            node = node[int(k)] if isinstance(node, list) else node[k]
        last = keys[-1]
        if isinstance(node, list):
            node[int(last)] = value
        else:
            node[last] = value
    return mutate


@pytest.mark.parametrize("path,value,code", [
    ("content.en.hero.primary_cta.target", "javascript:alert(1)", "url_scheme"),
    ("content.en.hero.primary_cta.target", "data:text/html,<script>alert(1)</script>", "url_scheme"),
    ("content.en.hero.primary_cta.target", "//evil.example/x", "invalid_url"),
    ("content.en.hero.primary_cta.target", "#bad fragment", "invalid_url"),
    ("content.en.footer.privacy_url", "ftp://example.com/privacy", "url_scheme"),
    ("content.en.footer.privacy_url", "https://user:pw@example.com", "invalid_url"),
    ("content.en.footer.privacy_url", "https://", "invalid_url"),
    ("content.it.sections.4.github_url", "file:///etc/passwd", "url_scheme"),
    ("content.it.sections.5.url", "vbscript:x", "url_scheme"),
    ("content.en.footer.contact_email", "not-an-email", "invalid_email"),
    ("branding.colors.dark.primary", "red", "invalid_color"),
    ("branding.colors.light.accent", "#12345", "invalid_color"),
    ("branding.colors.light.accent", "#12345g", "invalid_color"),
    ("branding.product_name", "", "required"),
    ("branding.product_name", "x" * 41, "too_long"),
    ("content.en.hero.title", "x" * 141, "too_long"),
    ("content.it.seo.title", "", "required"),
    ("branding.logo.dark", "logo-" + "0" * 32 + ".png", "asset_missing"),
    ("branding.logo.dark", "../../etc/passwd", "invalid_asset"),
    ("branding.favicon", "logo-" + "0" * 32 + ".png", "invalid_asset"),
    ("landing_enabled", "yes", "invalid_type"),
])
def test_validation_rejects(client, app, path, value, code):
    assert (path, code) in errors_for(client, app, set_path(path, value))


def test_validation_accepts_allowed_targets(client, app):
    data = admin_doc(client, app)
    s = data["settings"]
    s["content"]["en"]["hero"]["primary_cta"]["target"] = "mailto:hello@example.com"
    s["content"]["en"]["hero"]["secondary_cta"]["target"] = "/login?next=%2Fdashboard"
    s["content"]["it"]["hero"]["primary_cta"]["target"] = "https://example.com/demo#form"
    assert put(client, app, s, data["revision"]).status_code == 200


def test_validation_of_sections(client, app):
    def duplicate(s):
        s["content"]["en"]["sections"][1] = copy.deepcopy(s["content"]["en"]["sections"][0])
    assert ("content.en.sections", "invalid_sections") in errors_for(client, app, duplicate)

    def contact_without_address(s):
        contact = s["content"]["en"]["sections"][5]
        contact["email"], contact["url"] = "", ""
    assert ("content.en.sections.5.email", "contact_missing") in errors_for(client, app, contact_without_address)

    def too_many_items(s):
        s["content"]["en"]["sections"][0]["items"] = [{"title": "t", "text": ""}] * 7
    assert ("content.en.sections.0.items", "too_many") in errors_for(client, app, too_many_items)


def test_reordering_and_control_characters(client, app):
    data = admin_doc(client, app)
    s = data["settings"]
    s["content"]["en"]["sections"].reverse()
    s["content"]["en"]["hero"]["title"] = "  Line‮one\x00 \n two  "
    assert put(client, app, s, data["revision"]).status_code == 200
    stored = admin_doc(client, app)["settings"]["content"]["en"]
    assert stored["sections"][0]["type"] == "contact"
    assert stored["hero"]["title"] == "Lineone   two"


# -- Uploads ---------------------------------------------------------------------

def test_upload_png_and_serve(client, app):
    r = upload(client, app, png_bytes((300, 120)))
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert ss.ASSET_NAME.match(body["name"]) and body["url"] == f"/api/site/assets/{body['name']}"
    got = client.get(body["url"])
    assert got.status_code == 200
    assert got.headers["Content-Type"] == "image/png"
    assert "immutable" in got.headers["Cache-Control"]
    assert got.headers["X-Content-Type-Options"] == "nosniff"
    with app.app_context():
        assert AuditLog.query.filter_by(action="admin_site_asset_uploaded").count() == 1
    # Usable in the settings, by name or by URL
    data = admin_doc(client, app)
    data["settings"]["branding"]["logo"]["dark"] = body["url"]
    assert put(client, app, data["settings"], data["revision"]).status_code == 200
    assert client.get("/api/site").get_json()["branding"]["logo"]["dark"] == body["url"]


def test_upload_strips_metadata():
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"          # Make
    exif[0x8825] = {1: "N", 2: (45.0, 0.0, 0.0)}  # GPS
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (200, 30, 30)).save(buf, "JPEG", exif=exif, comment=b"secret comment")
    assert b"SecretCamera" in buf.getvalue()
    out, ext, w, h = ss.process_image(buf.getvalue(), "image", "photo.jpg")
    assert ext == "jpg" and (w, h) == (400, 300)
    assert b"SecretCamera" not in out and b"secret comment" not in out
    assert not Image.open(io.BytesIO(out)).getexif()


def test_upload_png_text_chunks_removed():
    from PIL import PngImagePlugin
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "secret-author")
    buf = io.BytesIO()
    Image.new("RGBA", (64, 64), (1, 2, 3, 4)).save(buf, "PNG", pnginfo=info)
    out, ext, _, _ = ss.process_image(buf.getvalue(), "logo", "x.png")
    assert ext == "png" and b"secret-author" not in out


def test_favicon_is_a_square_png():
    out, ext, w, h = ss.process_image(png_bytes((300, 100), mode="RGB", fmt="JPEG"), "favicon", "f.jpg")
    assert ext == "png" and w == h == 128


@pytest.mark.parametrize("data,filename,code,status", [
    (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "logo.svg", "svg_not_allowed", 400),
    (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>', "logo.png", "svg_not_allowed", 400),
    (b"GIF89a" + b"\x00" * 100, "logo.gif", "unsupported_type", 400),
    (b"just some text, not an image", "logo.png", "unsupported_type", 400),
    (b"", "logo.png", "empty", 400),
])
def test_upload_rejects_bad_files(client, app, data, filename, code, status):
    r = upload(client, app, data, filename=filename)
    assert r.status_code == status and r.get_json()["code"] == code


def test_upload_rejects_gif_even_when_valid():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64)).save(buf, "GIF")
    with pytest.raises(ss.ImageRejected) as e:
        ss.process_image(buf.getvalue(), "logo", "a.png")
    assert e.value.code == "unsupported_type"


def test_upload_rejects_oversize_and_dimensions(client, app):
    big = os.urandom(6 * 1024 * 1024)
    r = upload(client, app, big)
    assert r.status_code == 413 and r.get_json()["code"] == "too_large"
    # Logo limit is 2 MB: a 3 MB body is refused for a logo
    r = upload(client, app, b"\x89PNG" + os.urandom(3 * 1024 * 1024))
    assert r.status_code == 413
    r = upload(client, app, png_bytes((5000, 20), mode="RGB"))
    assert r.status_code == 400 and r.get_json()["code"] == "dimensions_too_large"
    r = upload(client, app, png_bytes((8, 8)))
    assert r.status_code == 400 and r.get_json()["code"] == "dimensions_too_small"
    r = upload(client, app, png_bytes(), kind="script")
    assert r.status_code == 400 and r.get_json()["code"] == "invalid_kind"


def test_upload_error_in_request_language(client, app):
    r = client.post("/api/admin/site/assets", headers={**auth(app, "super@example.com"), "Accept-Language": "it"},
                    content_type="multipart/form-data", data={"kind": "logo", "file": (io.BytesIO(b"<svg/>"), "a.svg")})
    assert "SVG" in r.get_json()["error"] and "accettati" in r.get_json()["error"]


@pytest.mark.parametrize("name", ["..%2F..%2Fconfig.py", "logo-123.png", "logo-" + "0" * 32 + ".svg", "x.png"])
def test_asset_route_only_serves_asset_names(client, name):
    assert client.get(f"/api/site/assets/{name}").status_code == 404


def test_orphans_pruned_after_grace_period(client, app):
    used = upload(client, app, png_bytes((40, 40))).get_json()["name"]
    orphan_old = upload(client, app, png_bytes((50, 50))).get_json()["name"]
    orphan_new = upload(client, app, png_bytes((60, 60))).get_json()["name"]
    folder = ss.assets_dir(app.config["UPLOADS_DIR"])
    old = time.time() - ss.ORPHAN_GRACE_SECONDS - 60
    os.utime(os.path.join(folder, orphan_old), (old, old))
    os.utime(os.path.join(folder, used), (old, old))
    data = admin_doc(client, app)
    data["settings"]["branding"]["logo"]["light"] = used
    assert put(client, app, data["settings"], data["revision"]).status_code == 200
    left = set(os.listdir(folder))
    assert used in left and orphan_new in left and orphan_old not in left


# -- Branding outside the SPA --------------------------------------------------

def test_pdf_strings_use_the_product_name(client, app):
    from app.api.site import product_name
    from app.core import i18n
    with app.test_request_context():
        assert product_name() == "SwarMind"
    data = admin_doc(client, app)
    data["settings"]["branding"]["product_name"] = "Acme Lab"
    assert put(client, app, data["settings"], data["revision"]).status_code == 200
    with app.test_request_context():
        name = product_name()
    assert name == "Acme Lab"
    assert i18n.t("it", "pdf.title", name=name).startswith("Acme Lab")
    assert "Acme Lab" in i18n.t("en", "pdf.footer", name=name, sim_id="s-1")
