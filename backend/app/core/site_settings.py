"""Site settings: landing switch, branding and landing content (models/site.py).

One document, three parts:
  landing_enabled  bool
  branding         product name, logo per theme, favicon, primary/accent colour per theme
  content          per locale (en, it): hero, ordered sections, footer, SEO

default_document() is the fallback when nothing is saved: default copy comes from the locale
catalog (locales/<lang>.yml, key landing). validate_document() is the only way in: it keeps known
keys only, enforces types, lengths, URL schemes and colour format, and returns coded errors
({"path", "code", "params"}) that the admin UI translates. public_view() is what anonymous
visitors get: no ids, no users, no revision, disabled sections left out, assets as URLs.

Images (process_image) are re-encoded from pixels: no metadata survives, SVG is never accepted.
"""
from __future__ import annotations

import copy
import hashlib
import io
import os
import re
import time
from urllib.parse import urlsplit

from flask import current_app, has_app_context

from app.core.i18n import SUPPORTED_LANGUAGES, t_value

# -- Schema --------------------------------------------------------------------

THEMES = ("dark", "light")
SECTION_TYPES = ("value", "how", "use_cases", "deliverables", "open_source", "contact")
# Sections made of a list of {title, text}, with the maximum number of items
ITEM_SECTIONS = {"value": 6, "how": 6, "use_cases": 8, "deliverables": 8}

LIMITS = {
    "product_name": 40,
    "hero_title": 140,
    "hero_subtitle": 500,
    "cta_label": 40,
    "section_title": 100,
    "section_intro": 600,
    "item_title": 80,
    "item_text": 400,
    "license_name": 60,
    "install_snippet": 1000,
    "install_snippet_lines": 15,
    "company_name": 120,
    "email": 254,
    "url": 500,
    "seo_title": 90,
    "seo_description": 300,
}

HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
EMAIL = re.compile(r"^[^@\s<>\"'()\[\]\\,;:]+@[^@\s<>\"'()\[\]\\,;:]+\.[^@\s<>\"'()\[\]\\,;:]+$")
FRAGMENT = re.compile(r"^#[A-Za-z][A-Za-z0-9_-]{0,63}$")
LOCAL_PATH = re.compile(r"^/(?![/\\])[A-Za-z0-9._~!$&'()*+,;=:@%/?#-]*$")
URL_SCHEMES = ("http", "https", "mailto")
# Control characters, except tab and newline (kept in multi-line fields only)
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏ -‮⁦-⁩]")

# -- Assets ----------------------------------------------------------------------

ASSET_KINDS = ("logo", "favicon", "og", "image")
ASSET_NAME = re.compile(r"^(logo|favicon|og|image)-[0-9a-f]{32}\.(png|jpg|webp)$")
ASSET_MIME = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
ASSET_URL_PREFIX = "/api/site/assets/"
ASSETS_SUBDIR = "site"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
# A file saved but not used by the settings is removed by a later save once older than this:
# an upload in progress in another tab is not lost
ORPHAN_GRACE_SECONDS = 24 * 3600

# Per kind: largest file, smallest and largest accepted size, size it is scaled down to fit in
IMAGE_RULES = {
    "logo":    {"max_bytes": 2 * 1024 * 1024, "min": (16, 16),   "max": (4096, 4096), "fit": (1024, 1024)},
    "favicon": {"max_bytes": 1 * 1024 * 1024, "min": (16, 16),   "max": (2048, 2048), "fit": (128, 128)},
    "og":      {"max_bytes": MAX_UPLOAD_BYTES, "min": (200, 200), "max": (6000, 6000), "fit": (1200, 1200)},
    "image":   {"max_bytes": MAX_UPLOAD_BYTES, "min": (64, 64),   "max": (6000, 6000), "fit": (1600, 1600)},
}
ALLOWED_FORMATS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}


class ImageRejected(ValueError):
    """An upload that is not accepted. code: errors.site_upload_<code> in the locale catalog."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = params


# -- Defaults --------------------------------------------------------------------

# The locale catalogs carry this placeholder for the public repository URL. scripts/export_public.py
# replaces it with the real URL in the published snapshot; split here so the export leaves this
# constant alone. Still present (a checkout of the private repository): no link, neutral snippet.
REPO_URL_PLACEHOLDER = "__SWARMIND_" + "PUBLIC_REPO_URL__"


def _configured_contact_email() -> str:
    """CONTACT_EMAIL from the app config (.env), or the environment outside an app context."""
    if has_app_context():
        return (current_app.config.get("CONTACT_EMAIL") or "").strip()
    return os.environ.get("CONTACT_EMAIL", "").strip()


def _repo_url(value: str) -> str:
    return "" if REPO_URL_PLACEHOLDER in value else value


def _install_snippet(value: str) -> str:
    return value.replace(REPO_URL_PLACEHOLDER, "<repository-url>")


def default_content(lang: str) -> dict:
    """Default landing content for lang, from the locale catalog (landing.default).

    The contact address comes from CONTACT_EMAIL: without it the contact section starts disabled
    (an enabled one needs an address) and the footer shows none.
    """
    d = t_value(lang, "landing.default")
    contact_email = _configured_contact_email()
    sections = []
    for kind in SECTION_TYPES:
        src = d["sections"][kind]
        section = {"type": kind, "enabled": True, "title": src["title"], "intro": src.get("intro", "")}
        if kind in ITEM_SECTIONS:
            section["items"] = [{"title": i["title"], "text": i.get("text", "")} for i in src["items"]]
        elif kind == "open_source":
            section.update(github_url=_repo_url(src.get("github_url", "")), docs_url=src.get("docs_url", ""),
                           license_name=src.get("license_name", ""),
                           install_snippet=_install_snippet(src.get("install_snippet", "")))
        elif kind == "contact":
            section.update(cta_label=src["cta_label"], email=contact_email, url=src.get("url", ""))
            section["enabled"] = bool(contact_email or section["url"])
        sections.append(section)
    hero = d["hero"]
    return {
        "hero": {
            "title": hero["title"],
            "subtitle": hero["subtitle"],
            "image": None,
            "primary_cta": {"label": hero["primary_cta"]["label"], "target": hero["primary_cta"]["target"]},
            "secondary_cta": {"label": hero["secondary_cta"]["label"], "target": hero["secondary_cta"]["target"]},
        },
        "sections": sections,
        "footer": {
            "company_name": d["footer"]["company_name"],
            "contact_email": contact_email,
            "privacy_url": d["footer"].get("privacy_url", ""),
            "terms_url": d["footer"].get("terms_url", ""),
        },
        "seo": {"title": d["seo"]["title"], "description": d["seo"]["description"], "og_image": None},
    }


def default_branding() -> dict:
    return {
        "product_name": "SwarMind",
        "logo": {"dark": None, "light": None},
        "favicon": None,
        # None: the theme's own token (frontend src/styles/tokens.css)
        "colors": {theme: {"primary": None, "accent": None} for theme in THEMES},
    }


def default_document() -> dict:
    # Off until an admin turns it on: the default copy links a repository and a contact address
    # that the owner should review before the page is public
    return {
        "landing_enabled": False,
        "branding": default_branding(),
        "content": {lang: default_content(lang) for lang in SUPPORTED_LANGUAGES},
    }


def merge_stored(landing_enabled, branding, content) -> dict:
    """The stored row as a full document: a missing part (NULL column, a locale added later) is
    the default. Stored parts were validated when saved."""
    doc = default_document()
    if landing_enabled is not None:
        doc["landing_enabled"] = bool(landing_enabled)
    if isinstance(branding, dict):
        doc["branding"] = copy.deepcopy(branding)
    if isinstance(content, dict):
        for lang in SUPPORTED_LANGUAGES:
            if isinstance(content.get(lang), dict):
                doc["content"][lang] = copy.deepcopy(content[lang])
    return doc


# -- Validation ------------------------------------------------------------------

class _Validator:
    def __init__(self, asset_exists):
        self.errors: list[dict] = []
        self.asset_exists = asset_exists

    def error(self, path: str, code: str, **params):
        self.errors.append({"path": path, "code": code, "params": params})

    def obj(self, value, path) -> dict:
        if value is None:
            return {}
        if not isinstance(value, dict):
            self.error(path, "invalid_type")
            return {}
        return value

    def text(self, value, path, limit, required=False, multiline=False) -> str:
        if value is None:
            value = ""
        if not isinstance(value, str):
            self.error(path, "invalid_type")
            return ""
        value = value.replace("\r\n", "\n").replace("\r", "\n")
        if not multiline:
            value = value.replace("\n", " ").replace("\t", " ")
        value = CONTROL.sub("", value).strip()
        if multiline:
            value = "\n".join(line.rstrip() for line in value.split("\n"))
            value = re.sub(r"\n{3,}", "\n\n", value)
        if required and not value:
            self.error(path, "required")
        elif len(value) > limit:
            self.error(path, "too_long", max=limit)
        return value

    def boolean(self, value, path, default) -> bool:
        if value is None:
            return default
        if not isinstance(value, bool):
            self.error(path, "invalid_type")
            return default
        return value

    def url(self, value, path, required=False, local=False) -> str:
        """http(s) or mailto URL. local=True also allows a page path (/login) or a fragment (#contact)."""
        value = self.text(value, path, LIMITS["url"], required=required)
        if not value or len(value) > LIMITS["url"]:
            return value
        if any(c.isspace() for c in value):
            self.error(path, "invalid_url")
            return value
        if local and value.startswith("#"):
            if not FRAGMENT.match(value):
                self.error(path, "invalid_url")
            return value
        if local and value.startswith("/"):
            if not LOCAL_PATH.match(value):
                self.error(path, "invalid_url")
            return value
        try:
            parts = urlsplit(value)
        except ValueError:
            self.error(path, "invalid_url")
            return value
        scheme = parts.scheme.lower()
        if scheme not in URL_SCHEMES:
            self.error(path, "url_scheme", allowed="http, https, mailto")
            return value
        if scheme == "mailto":
            if not EMAIL.match(parts.path or ""):
                self.error(path, "invalid_url")
        elif not parts.hostname or "\\" in value or parts.username or parts.password:
            # No host, or credentials in the URL (https://user@host is a phishing pattern)
            self.error(path, "invalid_url")
        return value

    def email(self, value, path, required=False) -> str:
        value = self.text(value, path, LIMITS["email"], required=required)
        if value and len(value) <= LIMITS["email"] and not EMAIL.match(value):
            self.error(path, "invalid_email")
        return value

    def color(self, value, path):
        if value in (None, ""):
            return None
        if not isinstance(value, str) or not HEX_COLOR.match(value.strip()):
            self.error(path, "invalid_color")
            return None
        h = value.strip().lower()[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return f"#{h}"

    def asset(self, value, path, kinds):
        """Name of an uploaded asset of one of kinds, or None. Accepts the public URL too."""
        if value in (None, ""):
            return None
        if not isinstance(value, str):
            self.error(path, "invalid_type")
            return None
        name = value[len(ASSET_URL_PREFIX):] if value.startswith(ASSET_URL_PREFIX) else value
        m = ASSET_NAME.match(name)
        if not m or m.group(1) not in kinds:
            self.error(path, "invalid_asset")
            return None
        if not self.asset_exists(name):
            self.error(path, "asset_missing")
            return None
        return name


def _validate_branding(v: _Validator, raw) -> dict:
    raw = v.obj(raw, "branding")
    logo = v.obj(raw.get("logo"), "branding.logo")
    colors = v.obj(raw.get("colors"), "branding.colors")
    out_colors = {}
    for theme in THEMES:
        c = v.obj(colors.get(theme), f"branding.colors.{theme}")
        out_colors[theme] = {k: v.color(c.get(k), f"branding.colors.{theme}.{k}") for k in ("primary", "accent")}
    return {
        "product_name": v.text(raw.get("product_name"), "branding.product_name", LIMITS["product_name"], required=True),
        "logo": {theme: v.asset(logo.get(theme), f"branding.logo.{theme}", ("logo",)) for theme in THEMES},
        "favicon": v.asset(raw.get("favicon"), "branding.favicon", ("favicon",)),
        "colors": out_colors,
    }


def _validate_cta(v: _Validator, raw, path, required) -> dict:
    raw = v.obj(raw, path)
    label = v.text(raw.get("label"), f"{path}.label", LIMITS["cta_label"], required=required)
    # A button with a label needs somewhere to go; an empty label hides the button
    target = v.url(raw.get("target"), f"{path}.target", required=bool(label), local=True)
    return {"label": label, "target": target}


def _validate_section(v: _Validator, raw, path) -> dict | None:
    raw = v.obj(raw, path)
    kind = raw.get("type")
    if kind not in SECTION_TYPES:
        v.error(f"{path}.type", "invalid_section")
        return None
    enabled = v.boolean(raw.get("enabled"), f"{path}.enabled", True)
    out = {
        "type": kind,
        "enabled": enabled,
        "title": v.text(raw.get("title"), f"{path}.title", LIMITS["section_title"], required=enabled),
        "intro": v.text(raw.get("intro"), f"{path}.intro", LIMITS["section_intro"], multiline=True),
    }
    if kind in ITEM_SECTIONS:
        items = raw.get("items")
        if items is None:
            items = []
        if not isinstance(items, list):
            v.error(f"{path}.items", "invalid_type")
            items = []
        if len(items) > ITEM_SECTIONS[kind]:
            v.error(f"{path}.items", "too_many", max=ITEM_SECTIONS[kind])
            items = items[:ITEM_SECTIONS[kind]]
        if enabled and not items:
            v.error(f"{path}.items", "required")
        out["items"] = []
        for i, item in enumerate(items):
            item = v.obj(item, f"{path}.items.{i}")
            out["items"].append({
                "title": v.text(item.get("title"), f"{path}.items.{i}.title", LIMITS["item_title"], required=True),
                "text": v.text(item.get("text"), f"{path}.items.{i}.text", LIMITS["item_text"], multiline=True),
            })
    elif kind == "open_source":
        snippet = v.text(raw.get("install_snippet"), f"{path}.install_snippet", LIMITS["install_snippet"], multiline=True)
        if snippet.count("\n") >= LIMITS["install_snippet_lines"]:
            v.error(f"{path}.install_snippet", "too_many_lines", max=LIMITS["install_snippet_lines"])
        out.update(
            github_url=v.url(raw.get("github_url"), f"{path}.github_url"),
            docs_url=v.url(raw.get("docs_url"), f"{path}.docs_url"),
            license_name=v.text(raw.get("license_name"), f"{path}.license_name", LIMITS["license_name"]),
            install_snippet=snippet,
        )
    elif kind == "contact":
        out.update(
            cta_label=v.text(raw.get("cta_label"), f"{path}.cta_label", LIMITS["cta_label"], required=enabled),
            email=v.email(raw.get("email"), f"{path}.email"),
            url=v.url(raw.get("url"), f"{path}.url"),
        )
        if enabled and not out["email"] and not out["url"]:
            v.error(f"{path}.email", "contact_missing")
    return out


def _validate_locale(v: _Validator, raw, lang) -> dict:
    base = f"content.{lang}"
    raw = v.obj(raw, base)
    hero = v.obj(raw.get("hero"), f"{base}.hero")
    footer = v.obj(raw.get("footer"), f"{base}.footer")
    seo = v.obj(raw.get("seo"), f"{base}.seo")

    sections_raw = raw.get("sections")
    sections = []
    if not isinstance(sections_raw, list):
        v.error(f"{base}.sections", "invalid_sections")
    else:
        for i, s in enumerate(sections_raw):
            section = _validate_section(v, s, f"{base}.sections.{i}")
            if section:
                sections.append(section)
        # Every section exactly once: the order is all an admin changes
        if sorted(s["type"] for s in sections) != sorted(SECTION_TYPES):
            v.error(f"{base}.sections", "invalid_sections")

    return {
        "hero": {
            "title": v.text(hero.get("title"), f"{base}.hero.title", LIMITS["hero_title"], required=True),
            "subtitle": v.text(hero.get("subtitle"), f"{base}.hero.subtitle", LIMITS["hero_subtitle"], multiline=True),
            "image": v.asset(hero.get("image"), f"{base}.hero.image", ("image",)),
            "primary_cta": _validate_cta(v, hero.get("primary_cta"), f"{base}.hero.primary_cta", required=True),
            "secondary_cta": _validate_cta(v, hero.get("secondary_cta"), f"{base}.hero.secondary_cta", required=False),
        },
        "sections": sections,
        "footer": {
            "company_name": v.text(footer.get("company_name"), f"{base}.footer.company_name", LIMITS["company_name"]),
            "contact_email": v.email(footer.get("contact_email"), f"{base}.footer.contact_email"),
            "privacy_url": v.url(footer.get("privacy_url"), f"{base}.footer.privacy_url"),
            "terms_url": v.url(footer.get("terms_url"), f"{base}.footer.terms_url"),
        },
        "seo": {
            "title": v.text(seo.get("title"), f"{base}.seo.title", LIMITS["seo_title"], required=True),
            "description": v.text(seo.get("description"), f"{base}.seo.description", LIMITS["seo_description"]),
            "og_image": v.asset(seo.get("og_image"), f"{base}.seo.og_image", ("og", "image")),
        },
    }


def validate_document(raw, asset_exists) -> tuple[dict, list[dict]]:
    """(clean document, errors). Unknown keys are dropped. asset_exists(name) -> bool."""
    v = _Validator(asset_exists)
    raw = v.obj(raw, "")
    content = v.obj(raw.get("content"), "content")
    doc = {
        "landing_enabled": v.boolean(raw.get("landing_enabled"), "landing_enabled", False),
        "branding": _validate_branding(v, raw.get("branding")),
        "content": {lang: _validate_locale(v, content.get(lang), lang) for lang in SUPPORTED_LANGUAGES},
    }
    return doc, v.errors


# -- Views -----------------------------------------------------------------------

def asset_url(name):
    return f"{ASSET_URL_PREFIX}{name}" if name else None


def _with_urls(content: dict) -> dict:
    content = copy.deepcopy(content)
    content["hero"]["image"] = asset_url(content["hero"].get("image"))
    content["seo"]["og_image"] = asset_url(content["seo"].get("og_image"))
    return content


def branding_view(branding: dict) -> dict:
    return {
        "product_name": branding["product_name"],
        "logo": {theme: asset_url(branding["logo"].get(theme)) for theme in THEMES},
        "favicon": asset_url(branding.get("favicon")),
        "colors": copy.deepcopy(branding["colors"]),
    }


def public_view(doc: dict, lang: str) -> dict:
    """What GET /api/site returns: branding always, landing content only when the landing is on."""
    content = None
    if doc["landing_enabled"]:
        content = _with_urls(doc["content"][lang])
        content["sections"] = [s for s in content["sections"] if s.get("enabled")]
    return {
        "lang": lang,
        "landing_enabled": doc["landing_enabled"],
        "branding": branding_view(doc["branding"]),
        "content": content,
    }


def admin_view(doc: dict) -> dict:
    """The full document for the editor, assets as URLs (the editor sends either form back)."""
    return {
        "landing_enabled": doc["landing_enabled"],
        "branding": branding_view(doc["branding"]),
        "content": {lang: _with_urls(doc["content"][lang]) for lang in SUPPORTED_LANGUAGES},
    }


def changed_paths(old, new, prefix="", limit=60) -> list[str]:
    """Leaf paths that differ between two documents, for the audit log (values are not logged)."""
    out: list[str] = []

    def walk(a, b, path):
        if len(out) >= limit:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                walk(a.get(key), b.get(key), f"{path}.{key}" if path else str(key))
        elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, f"{path}.{i}")
        elif a != b:
            out.append(path)

    walk(old, new, prefix)
    return out


def referenced_assets(doc: dict) -> set[str]:
    names = {doc["branding"].get("favicon"), *doc["branding"]["logo"].values()}
    for content in doc["content"].values():
        names.add(content["hero"].get("image"))
        names.add(content["seo"].get("og_image"))
    return {n for n in names if n}


# -- Asset files -----------------------------------------------------------------

def assets_dir(uploads_dir: str) -> str:
    return os.path.join(uploads_dir, ASSETS_SUBDIR)


def asset_path(uploads_dir: str, name: str) -> str | None:
    """Path of an asset file, None for a name that is not an asset name (no traversal possible)."""
    if not isinstance(name, str) or not ASSET_NAME.match(name):
        return None
    return os.path.join(assets_dir(uploads_dir), name)


def prune_orphans(uploads_dir: str, keep: set[str], now: float | None = None) -> int:
    """Delete asset files not in keep and older than the grace period. Returns how many."""
    folder = assets_dir(uploads_dir)
    if not os.path.isdir(folder):
        return 0
    now = now or time.time()
    removed = 0
    for name in os.listdir(folder):
        if not ASSET_NAME.match(name) or name in keep:
            continue
        path = os.path.join(folder, name)
        try:
            if now - os.path.getmtime(path) > ORPHAN_GRACE_SECONDS:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    return removed


def _looks_like_svg(data: bytes) -> bool:
    head = data[:1024].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith(b"<") or b"<svg" in head


def process_image(data: bytes, kind: str, filename: str = "") -> tuple[bytes, str, int, int]:
    """Validate and re-encode an uploaded image. Returns (bytes, ext, width, height).

    PNG, JPEG and WebP only, detected from the content (never from the name or the declared type).
    The output is rebuilt from the pixels: EXIF, XMP, ICC profiles, text chunks and extra frames
    are gone. Raises ImageRejected.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    rules = IMAGE_RULES.get(kind)
    if rules is None:
        raise ImageRejected("invalid_kind")
    if not data:
        raise ImageRejected("empty")
    if len(data) > rules["max_bytes"]:
        raise ImageRejected("too_large", max_mb=rules["max_bytes"] // (1024 * 1024))
    if filename.lower().endswith((".svg", ".svgz")) or _looks_like_svg(data):
        raise ImageRejected("svg_not_allowed")

    try:
        im = Image.open(io.BytesIO(data))
        fmt = im.format
    except Image.DecompressionBombError:
        raise ImageRejected("dimensions_too_large", max_w=rules["max"][0], max_h=rules["max"][1])
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImageRejected("unsupported_type")
    if fmt not in ALLOWED_FORMATS:
        raise ImageRejected("unsupported_type")

    # Size from the header, before decoding: a huge canvas is refused without allocating it
    w, h = im.size
    max_w, max_h = rules["max"]
    min_w, min_h = rules["min"]
    if w > max_w or h > max_h:
        raise ImageRejected("dimensions_too_large", max_w=max_w, max_h=max_h)
    if w < min_w or h < min_h:
        raise ImageRejected("dimensions_too_small", min_w=min_w, min_h=min_h)

    try:
        im.seek(0)                      # animated PNG / WebP: first frame only
        im.load()
        im = ImageOps.exif_transpose(im)  # a photo shows the way it was taken
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise ImageRejected("unsupported_type")

    has_alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
    out_ext = "png" if kind == "favicon" else ALLOWED_FORMATS[fmt]
    keep_alpha = has_alpha and out_ext != "jpg"
    im = im.convert("RGBA" if keep_alpha else "RGB")
    im.thumbnail(rules["fit"], Image.LANCZOS)

    if kind == "favicon":
        side = max(im.size)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(im.convert("RGBA"), ((side - im.width) // 2, (side - im.height) // 2))
        im = square

    # A new image from raw pixels: nothing from the source's info dict can reach the encoder
    clean = Image.frombytes(im.mode, im.size, im.tobytes())
    out = io.BytesIO()
    if out_ext == "png":
        clean.save(out, "PNG", optimize=True)
    elif out_ext == "jpg":
        clean.save(out, "JPEG", quality=88, optimize=True, progressive=True)
    else:
        clean.save(out, "WEBP", quality=88, method=4)
    return out.getvalue(), out_ext, clean.width, clean.height


def asset_name(kind: str, data: bytes, ext: str) -> str:
    """Content-addressed name: the same image uploaded twice is one file, and its URL never
    changes meaning, so it can be cached forever."""
    return f"{kind}-{hashlib.sha256(data).hexdigest()[:32]}.{ext}"


def store_asset(uploads_dir: str, name: str, data: bytes) -> str:
    folder = assets_dir(uploads_dir)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    if os.path.exists(path):
        os.utime(path)  # re-uploaded: counts as new for the orphan grace period
        return path
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return path
