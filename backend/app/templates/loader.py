"""
Registry of the simulation templates.

Base file per template: simulations/<id>.yml (or .json), in English, with every field (text,
structure, numbers). Other languages: simulations/locales/<lang>/<id>.yml with the translatable
fields only (TRANSLATABLE_PATHS, and per persona TRANSLATABLE_PERSONA_FIELDS), personas keyed by their
`key`. get(id, lang) and list_all(lang) return the base deep-merged with the overlay of lang: a field
the overlay lacks stays in English. In extra_instructions a persona is written {persona:<key>} and
becomes the persona's name in the requested language.

Adding a template:
  1. Base file in simulations/ (id, name, description, adversarial_personas with a unique key each,
     report_focus)
  2. One overlay per language in simulations/locales/<lang>/<id>.yml
  3. python -m app.templates.validate   (fails on a missing or broken overlay)
  4. Restart the backend
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Iterator

import structlog
import yaml

from app.core.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, normalize_language

log = structlog.get_logger()

TEMPLATES_DIR = Path(__file__).parent / "simulations"
LOCALES_SUBDIR = "locales"
BASE_LANGUAGE = DEFAULT_LANGUAGE  # the language of the base files

# Minimum fields of a base template
REQUIRED_FIELDS = {"id", "name", "description", "adversarial_personas", "report_focus"}
REQUIRED_PERSONA_FIELDS = {"key", "name", "role", "background", "communication_style"}
REQUIRED_REPORT_FIELDS = {"mandatory_sections"}

# What an overlay may contain. Everything else (shares, sections, communication_style, opinion_strength,
# emotional_state...) belongs to the base only.
TRANSLATABLE_PATHS = (
    ("name",),
    ("description",),
    ("prompt_defaults", "prediction_requirement_placeholder"),
    ("graph_hints", "recommended_entities"),
    ("report_focus", "extra_instructions"),
)
TRANSLATABLE_PERSONA_FIELDS = ("name", "role", "background", "core_beliefs", "fears", "motivations")
PERSONA_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PERSONA_REF_RE = re.compile(r"\{persona:([a-z][a-z0-9_]*)\}")


def read_file(path: Path) -> Any:
    content = path.read_text(encoding="utf-8")
    if path.suffix in (".yml", ".yaml"):
        return yaml.safe_load(content)
    if path.suffix == ".json":
        return json.loads(content)
    return None


def overlay_items(overlay: dict) -> Iterator[tuple[tuple[str, ...], Any]]:
    """(path, value) of every leaf of an overlay. Personas: ("adversarial_personas", key, field)."""
    def walk(node, path):
        if isinstance(node, dict) and path != ("adversarial_personas",):
            for k, v in node.items():
                yield from walk(v, (*path, str(k)))
        elif path == ("adversarial_personas",) and isinstance(node, dict):
            for key, fields in node.items():
                if isinstance(fields, dict):
                    for f, v in fields.items():
                        yield ("adversarial_personas", str(key), str(f)), v
                else:
                    yield ("adversarial_personas", str(key)), fields
        else:
            yield path, node
    yield from walk(overlay, ())


def get_path(data: dict, path: tuple[str, ...]):
    node = data
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def persona_by_key(template: dict, key: str) -> dict | None:
    return next((p for p in template.get("adversarial_personas") or []
                 if isinstance(p, dict) and p.get("key") == key), None)


def merge_overlay(base: dict, overlay: dict) -> tuple[dict, list[str]]:
    """A copy of base with the overlay's translatable fields. Returns (template, overlay paths ignored
    because they are not translatable or do not exist in the base)."""
    merged = copy.deepcopy(base)
    ignored = []
    for path, value in overlay_items(overlay or {}):
        if path[0] == "adversarial_personas":
            persona = persona_by_key(merged, path[1]) if len(path) == 3 else None
            if persona is None or path[2] not in TRANSLATABLE_PERSONA_FIELDS or path[2] not in persona:
                ignored.append(".".join(path))
                continue
            persona[path[2]] = copy.deepcopy(value)
        elif path in TRANSLATABLE_PATHS and get_path(merged, path) is not None:
            get_path(merged, path[:-1])[path[-1]] = copy.deepcopy(value)
        else:
            ignored.append(".".join(path))
    return merged, ignored


def resolve_persona_refs(template: dict) -> list[str]:
    """{persona:<key>} in extra_instructions -> the persona's name. Returns the unknown keys (left as the key)."""
    rf = template.get("report_focus") or {}
    text = rf.get("extra_instructions")
    if not isinstance(text, str):
        return []
    unknown = []

    def name(m):
        persona = persona_by_key(template, m.group(1))
        if persona is None:
            unknown.append(m.group(1))
            return m.group(1)
        return str(persona.get("name") or m.group(1))

    rf["extra_instructions"] = PERSONA_REF_RE.sub(name, text)
    return unknown


class TemplateRegistry:
    """Discovers, validates and serves the templates, in every supported language."""

    def __init__(self, directory: Path = TEMPLATES_DIR):
        self._dir = directory
        self._templates: dict[str, dict] = {}            # base, English
        self._overlays: dict[str, dict[str, dict]] = {}  # lang -> id -> overlay
        self._merged: dict[tuple[str, str], dict] = {}   # (id, lang) -> resolved template
        self._loaded = False

    def _load_file(self, path: Path) -> dict | None:
        """One base file: the dict, or None if invalid."""
        try:
            data = read_file(path)
            if not isinstance(data, dict):
                log.warning("template_invalid_root", file=path.name)
                return None

            missing = REQUIRED_FIELDS - set(data.keys())
            if missing:
                log.warning("template_missing_fields", file=path.name, missing=list(missing))
                return None

            personas = data.get("adversarial_personas", [])
            if not isinstance(personas, list) or not personas:
                log.warning("template_no_personas", file=path.name)
                return None
            keys = set()
            for i, p in enumerate(personas):
                pmissing = REQUIRED_PERSONA_FIELDS - set(p.keys())
                if pmissing:
                    log.warning("template_persona_incomplete", file=path.name, idx=i, missing=list(pmissing))
                    return None
                if not PERSONA_KEY_RE.match(str(p["key"])) or p["key"] in keys:
                    log.warning("template_persona_key_invalid", file=path.name, idx=i, key=str(p["key"])[:40])
                    return None
                keys.add(p["key"])

            rf = data.get("report_focus", {})
            rmissing = REQUIRED_REPORT_FIELDS - set(rf.keys())
            if rmissing:
                log.warning("template_report_focus_incomplete", file=path.name, missing=list(rmissing))
                return None

            return data
        except Exception as e:
            log.warning("template_load_error", file=path.name, error=str(e))
            return None

    def _load_overlays(self):
        for lang in SUPPORTED_LANGUAGES:
            if lang == BASE_LANGUAGE:
                continue
            folder = self._dir / LOCALES_SUBDIR / lang
            self._overlays[lang] = {}
            for tid in self._templates:
                path = next((folder / f"{tid}{ext}" for ext in (".yml", ".yaml", ".json")
                             if (folder / f"{tid}{ext}").exists()), None)
                if path is None:
                    log.warning("template_overlay_missing", id=tid, lang=lang)
                    continue
                try:
                    data = read_file(path)
                except Exception as e:
                    log.warning("template_overlay_load_error", id=tid, lang=lang, error=str(e))
                    continue
                if isinstance(data, dict):
                    self._overlays[lang][tid] = data
                else:
                    log.warning("template_overlay_invalid_root", id=tid, lang=lang)

    def _discover(self):
        """Loads every base file in the directory and its overlays."""
        if not self._dir.exists():
            log.warning("templates_dir_missing", path=str(self._dir))
            self._loaded = True
            return

        for path in sorted(self._dir.iterdir()):
            if not path.is_file() or path.suffix not in (".yml", ".yaml", ".json"):
                continue
            data = self._load_file(path)
            if not data:
                continue
            tid = data["id"]
            if tid in self._templates:
                log.warning("template_duplicate_id", id=tid, file=path.name)
                continue
            self._templates[tid] = data
        self._load_overlays()

        log.info("templates_loaded", count=len(self._templates), ids=list(self._templates.keys()),
                 overlays={lang: sorted(o) for lang, o in self._overlays.items()})
        self._loaded = True

    def _ensure_loaded(self):
        if not self._loaded:
            self._discover()

    def _resolved(self, template_id: str, lang) -> dict | None:
        lang = normalize_language(lang) or DEFAULT_LANGUAGE
        cached = self._merged.get((template_id, lang))
        if cached is not None:
            return cached
        base = self._templates.get(template_id)
        if base is None:
            return None
        overlay = self._overlays.get(lang, {}).get(template_id) if lang != BASE_LANGUAGE else None
        merged, ignored = merge_overlay(base, overlay or {})
        if ignored:
            log.warning("template_overlay_fields_ignored", id=template_id, lang=lang, paths=ignored[:20])
        unknown = resolve_persona_refs(merged)
        if unknown:
            log.warning("template_persona_ref_unknown", id=template_id, lang=lang, keys=unknown)
        self._merged[(template_id, lang)] = merged
        return merged

    def list_all(self, lang=DEFAULT_LANGUAGE) -> list[dict]:
        """The templates with the metadata the UI needs, in lang."""
        self._ensure_loaded()
        out = []
        for tid in self._templates:
            t = self._resolved(tid, lang)
            out.append({
                "id": t["id"],
                "name": t["name"],
                "description": t["description"],
                "version": t.get("version", 1),
                "num_adversarial_personas": len(t.get("adversarial_personas", [])),
                "recommended_entities": t.get("graph_hints", {}).get("recommended_entities", []),
                "prompt_defaults": t.get("prompt_defaults", {}),
            })
        return out

    def get(self, template_id: str, lang=DEFAULT_LANGUAGE) -> dict | None:
        """The full template in lang (a copy), or None if it does not exist."""
        self._ensure_loaded()
        template = self._resolved(template_id, lang)
        return copy.deepcopy(template) if template is not None else None

    def reload(self):
        """Discovers the templates again (dev, or templates added at runtime)."""
        self._templates = {}
        self._overlays = {}
        self._merged = {}
        self._loaded = False
        self._discover()


# Module singleton
_registry: TemplateRegistry | None = None


def get_registry() -> TemplateRegistry:
    global _registry
    if _registry is None:
        _registry = TemplateRegistry()
    return _registry
