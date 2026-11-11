"""Checks the simulation templates and their language overlays.

    python -m app.templates.validate [templates_dir]

Base files (English): required fields, a unique key per persona, every translatable field present and
not empty, {persona:<key>} references that exist. Overlays (locales/<lang>/<id>.yml, one per template and
supported language): only translatable fields, every key present in the base, the same persona keys as
the base, every translatable field of the base present (same type, not empty), valid persona references.
Exit code 1 and one line per problem when something is wrong.
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.core.i18n import SUPPORTED_LANGUAGES
from app.templates.loader import (
    BASE_LANGUAGE, LOCALES_SUBDIR, PERSONA_KEY_RE, PERSONA_REF_RE, REQUIRED_FIELDS, REQUIRED_PERSONA_FIELDS,
    TEMPLATES_DIR, TRANSLATABLE_PATHS, TRANSLATABLE_PERSONA_FIELDS, get_path, overlay_items, read_file,
)

_EXTS = (".yml", ".yaml", ".json")


def _empty(value) -> bool:
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value or any(not str(v).strip() for v in value)
    return value is None


def _translatable_fields(base: dict) -> list[tuple[str, ...]]:
    """The translatable paths the base has: top-level paths, then ("adversarial_personas", key, field)."""
    paths = [p for p in TRANSLATABLE_PATHS if get_path(base, p) is not None]
    for persona in base.get("adversarial_personas") or []:
        if isinstance(persona, dict) and persona.get("key"):
            paths += [("adversarial_personas", persona["key"], f) for f in TRANSLATABLE_PERSONA_FIELDS if f in persona]
    return paths


def _value(data: dict, path: tuple[str, ...], overlay: bool):
    if path[0] != "adversarial_personas":
        return get_path(data, path)
    if overlay:
        return get_path(data, path)
    persona = next((p for p in data.get("adversarial_personas") or [] if isinstance(p, dict) and p.get("key") == path[1]), None)
    return None if persona is None else persona.get(path[2])


def _check_refs(where: str, text, keys: set[str]) -> list[str]:
    if not isinstance(text, str):
        return []
    return [f"{where}: report_focus.extra_instructions refers to unknown persona '{k}'"
            for k in PERSONA_REF_RE.findall(text) if k not in keys]


def validate_base(name: str, base) -> tuple[list[str], set[str]]:
    errors = []
    if not isinstance(base, dict):
        return [f"{name}: the root is not a mapping"], set()
    missing = REQUIRED_FIELDS - set(base)
    if missing:
        errors.append(f"{name}: missing fields {sorted(missing)}")
    keys: set[str] = set()
    personas = base.get("adversarial_personas")
    if not isinstance(personas, list) or not personas:
        errors.append(f"{name}: adversarial_personas must be a non-empty list")
        personas = []
    for i, p in enumerate(personas):
        if not isinstance(p, dict):
            errors.append(f"{name}: persona #{i} is not a mapping")
            continue
        pmissing = REQUIRED_PERSONA_FIELDS - set(p)
        if pmissing:
            errors.append(f"{name}: persona #{i} misses {sorted(pmissing)}")
        key = p.get("key")
        if key is not None and not PERSONA_KEY_RE.match(str(key)):
            errors.append(f"{name}: persona #{i} key '{key}' must be lowercase letters, digits and _")
        elif key in keys:
            errors.append(f"{name}: persona key '{key}' is used twice")
        elif key:
            keys.add(key)
    for path in _translatable_fields(base):
        if _empty(_value(base, path, overlay=False)):
            errors.append(f"{name}: {'.'.join(path)} is empty in {BASE_LANGUAGE}")
    for path in TRANSLATABLE_PATHS:
        if get_path(base, path) is None:
            errors.append(f"{name}: {'.'.join(path)} is missing in {BASE_LANGUAGE}")
    errors += _check_refs(name, get_path(base, ("report_focus", "extra_instructions")), keys)
    return errors, keys


def validate_overlay(name: str, base: dict, keys: set[str], overlay) -> list[str]:
    errors = []
    if not isinstance(overlay, dict):
        return [f"{name}: the root is not a mapping"]
    allowed = set(_translatable_fields(base))
    for path, _ in overlay_items(overlay):
        if path in allowed:
            continue
        if path[0] == "adversarial_personas" and len(path) >= 2 and path[1] not in keys:
            errors.append(f"{name}: persona key '{path[1]}' does not exist in the base")
        elif path[0] == "adversarial_personas" or path in TRANSLATABLE_PATHS:
            errors.append(f"{name}: {'.'.join(path)} does not exist in the base")
        else:
            errors.append(f"{name}: {'.'.join(path)} is not a translatable field (numbers and structure stay "
                          f"in the base) or does not exist in the base")
    overlay_keys = set((overlay.get("adversarial_personas") or {}).keys()) \
        if isinstance(overlay.get("adversarial_personas"), dict) else set()
    if overlay.get("adversarial_personas") is not None and not isinstance(overlay.get("adversarial_personas"), dict):
        errors.append(f"{name}: adversarial_personas must be a mapping persona key -> fields")
    for key in sorted(keys - overlay_keys):
        errors.append(f"{name}: persona '{key}' is missing")
    for path in sorted(allowed):
        if path[0] == "adversarial_personas" and path[1] not in overlay_keys:
            continue  # already reported once per persona
        value = _value(overlay, path, overlay=True)
        if value is None:
            errors.append(f"{name}: {'.'.join(path)} is missing")
        elif type(value) is not type(_value(base, path, overlay=False)):
            errors.append(f"{name}: {'.'.join(path)} must be a {type(_value(base, path, overlay=False)).__name__}")
        elif _empty(value):
            errors.append(f"{name}: {'.'.join(path)} is empty")
    errors += _check_refs(name, get_path(overlay, ("report_focus", "extra_instructions")), keys)
    return errors


def validate(directory: Path = TEMPLATES_DIR) -> tuple[list[str], int]:
    """(problems, templates checked)."""
    errors: list[str] = []
    bases: dict[str, tuple[dict, set[str]]] = {}
    for path in sorted(p for p in directory.iterdir() if p.is_file() and p.suffix in _EXTS):
        try:
            base = read_file(path)
        except Exception as e:
            errors.append(f"{path.name}: unreadable ({e})")
            continue
        base_errors, keys = validate_base(path.name, base)
        errors += base_errors
        if isinstance(base, dict) and base.get("id"):
            if path.stem != base["id"]:
                errors.append(f"{path.name}: id '{base['id']}' differs from the file name")
            bases[str(base["id"])] = (base, keys)
    for lang in SUPPORTED_LANGUAGES:
        if lang == BASE_LANGUAGE:
            continue
        folder = directory / LOCALES_SUBDIR / lang
        found = {p.stem: p for p in folder.iterdir() if p.is_file() and p.suffix in _EXTS} if folder.exists() else {}
        for stem in sorted(set(found) - set(bases)):
            errors.append(f"{LOCALES_SUBDIR}/{lang}/{found[stem].name}: no base template with id '{stem}'")
        for tid, (base, keys) in bases.items():
            name = f"{LOCALES_SUBDIR}/{lang}/{tid}.yml"
            if tid not in found:
                errors.append(f"{name}: missing")
                continue
            try:
                overlay = read_file(found[tid])
            except Exception as e:
                errors.append(f"{name}: unreadable ({e})")
                continue
            errors += validate_overlay(name, base, keys, overlay)
    return errors, len(bases)


def main(argv: list[str]) -> int:
    directory = Path(argv[0]) if argv else TEMPLATES_DIR
    errors, count = validate(directory)
    for e in errors:
        print(f"ERROR {e}")
    languages = ", ".join(SUPPORTED_LANGUAGES)
    if errors:
        print(f"{len(errors)} problem(s) in {count} template(s) [{languages}]")
        return 1
    print(f"OK: {count} template(s) valid in {languages}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
