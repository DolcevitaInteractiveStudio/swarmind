"""Simulation language and locale catalog: English by default, Italian as an option.

Prompts are written once, in English, and end with language_directive(lang): the model writes
its human-readable output in the simulation language. Text shown to the reader verbatim
(report headings, appendix, canonical sentences, labels, fallbacks, API errors) comes from
locales/<lang>.yml through t(), never from a translated copy of a prompt.
"""
from __future__ import annotations

import copy
import functools
import pathlib

import structlog
import yaml

log = structlog.get_logger()

SUPPORTED_LANGUAGES = ("en", "it")
DEFAULT_LANGUAGE = "en"
LANGUAGE_NAMES = {"en": "English", "it": "Italian"}
LOCALES_DIR = pathlib.Path(__file__).resolve().parent.parent / "locales"


def normalize_language(value) -> str | None:
    """"it", "IT", "it-IT" -> "it". None for a missing or unsupported value."""
    if not isinstance(value, str):
        return None
    primary = value.strip().lower().replace("_", "-").split("-", 1)[0]
    return primary if primary in SUPPORTED_LANGUAGES else None


@functools.lru_cache(maxsize=None)
def configured_default_language(value) -> str:
    """SIMULATION_DEFAULT_LANGUAGE as a supported language. Unset or empty: "en". Invalid: "en" and a
    warning, once per process for each value."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return DEFAULT_LANGUAGE
    lang = normalize_language(value)
    if lang is None:
        log.warning("simulation_default_language_invalid", value=str(value)[:40],
                    allowed=list(SUPPORTED_LANGUAGES), fallback=DEFAULT_LANGUAGE)
        return DEFAULT_LANGUAGE
    return lang


def _lang(lang) -> str:
    return normalize_language(lang) or DEFAULT_LANGUAGE


# -- Prompts -------------------------------------------------------------------

def language_directive(lang) -> str:
    """The last line of every prompt: the output language. JSON keys and enum values never change."""
    return (f"Write all human-readable values in {LANGUAGE_NAMES[_lang(lang)]}. "
            "JSON keys and enum values stay in English.")


def with_directive(text: str, lang) -> str:
    """text followed by the language directive, as the last thing the model reads."""
    return f"{text.rstrip()}\n\n{language_directive(lang)}"


# -- Catalog -------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def catalog(lang: str) -> dict:
    """locales/<lang>.yml, read once per process."""
    with open(LOCALES_DIR / f"{lang}.yml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _lookup(lang: str, key: str):
    node = catalog(lang)
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(key)
        node = node[part]
    return node


def t_value(lang, key: str):
    """Raw catalog value (string, list or dict), a copy. Missing in lang: the English value."""
    lang = _lang(lang)
    try:
        return copy.deepcopy(_lookup(lang, key))
    except KeyError:
        if lang == DEFAULT_LANGUAGE:
            raise
        log.warning("i18n_key_missing", lang=lang, key=key)
        return copy.deepcopy(_lookup(DEFAULT_LANGUAGE, key))


def t(lang, key: str, **params) -> str:
    """Catalog string for lang, formatted with params. A missing key falls back to English;
    missing in English too, the key itself (logged): the reader never gets an exception."""
    try:
        value = t_value(lang, key)
    except KeyError:
        log.error("i18n_key_missing", lang=_lang(lang), key=key)
        return key
    text = str(value)
    return text.format(**params) if params else text


# -- Coded messages --------------------------------------------------------------

def render_coded(lang, detail: dict, namespace: str) -> str:
    """Text of a message stored as a code: {"key": k, "params": {...}} -> <namespace>.<k> formatted.

    A param that is itself a {"key": ...} dict is rendered first (a failure reason inside a phase
    message); {"text": s} is text that has no code (an exception message) and is used as is.
    Raises KeyError/ValueError/TypeError when the detail does not match the catalog.
    """
    if "text" in detail:
        return str(detail["text"])
    key = detail["key"]
    if not isinstance(key, str) or not key:
        raise KeyError(key)
    params = {
        name: render_coded(lang, value, namespace) if isinstance(value, dict) else value
        for name, value in (detail.get("params") or {}).items()
    }
    template = t_value(lang, f"{namespace}.{key}")
    if not isinstance(template, str):
        raise KeyError(key)
    return template.format(**params)


def coded_message(lang, detail, fallback, namespace: str = "lifecycle", max_chars: int | None = None):
    """A stored coded message in lang. fallback (the stored text) for rows written before codes
    existed, or whose code the catalog no longer has: old rows stay readable."""
    if not isinstance(detail, dict) or not detail:
        return fallback
    try:
        text = render_coded(lang, detail, namespace)
    except (KeyError, IndexError, ValueError, TypeError, AttributeError) as e:
        log.warning("coded_message_unrenderable", namespace=namespace, error=str(e)[:200])
        return fallback
    return text[:max_chars] if max_chars else text


# -- API -----------------------------------------------------------------------

def accept_language(header: str | None) -> str:
    """Best supported language in an Accept-Language header ("it-IT,it;q=0.9,en;q=0.8"). Default: en."""
    best, best_q = None, -1.0
    for i, part in enumerate((header or "").split(",")):
        tag, _, params = part.strip().partition(";")
        lang = normalize_language(tag)
        if not lang:
            continue
        q = 1.0
        for param in params.split(";"):
            name, _, value = param.strip().partition("=")
            if name.strip() == "q":
                try:
                    q = float(value)
                except ValueError:
                    q = 0.0
        # Same q: the first one listed wins
        if q > best_q and q > 0:
            best, best_q = lang, q
    return best or DEFAULT_LANGUAGE


def request_language() -> str:
    """Language of the current HTTP request (Accept-Language); en outside a request."""
    try:
        from flask import has_request_context, request
        if has_request_context():
            return accept_language(request.headers.get("Accept-Language"))
    except ImportError:
        pass
    return DEFAULT_LANGUAGE


def api_error(key: str, **params) -> str:
    """API error message (errors.<key>) in the language of the request."""
    return t(request_language(), f"errors.{key}", **params)
