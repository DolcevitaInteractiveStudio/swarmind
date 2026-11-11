"""Regenerate site-fixture.json (GET /api/site and GET /api/admin/site for mock.mjs) from the
backend's own defaults and views, so the screenshots show what the API really returns.

Run after changing the default landing copy (backend/app/locales/*.yml, key landing) or the
site settings schema, with the backend's Python environment:
    python frontend/scripts/ui-check/site_fixture.py
"""
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[2] / "backend"
sys.path.insert(0, str(BACKEND))
# config.py requires a key at import; the fixture never encrypts anything
os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

from app.core import site_settings as ss  # noqa: E402

doc = ss.default_document()
doc["landing_enabled"] = True   # the screenshots show the landing; "off" is a mock variant
fixture = {
    "public": {lang: ss.public_view(doc, lang) for lang in ("en", "it")},
    "admin": {
        "settings": ss.admin_view(doc),
        "revision": 4,
        "updated_at": "2026-11-10T09:30:00+00:00",
        "defaults": ss.admin_view(ss.default_document()),
        "limits": ss.LIMITS,
        "item_limits": ss.ITEM_SECTIONS,
        "upload": {kind: {"max_bytes": r["max_bytes"], "min": r["min"], "max": r["max"]}
                   for kind, r in ss.IMAGE_RULES.items()},
    },
}
out = HERE / "site-fixture.json"
with open(out, "w", encoding="utf-8", newline="\n") as f:
    json.dump(fixture, f, ensure_ascii=False, indent=1)
    f.write("\n")
print(f"wrote {out}")
