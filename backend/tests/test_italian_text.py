"""Italian text owned by the code uses real accents, never an apostrophe in place of an accent.

Covers the backend catalogue (app/locales/it.yml), the Italian text of the simulation templates
(app/templates/simulations/locales/it/*.yml), the frontend catalogue (frontend/src/i18n/it.json, when the
frontend is checked out next to the backend) and the Italian phrases kept in Python modules.
Usage: cd backend && python -m pytest tests/test_italian_text.py
"""
import json
import os
import re
from pathlib import Path

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import pytest
import yaml

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND_IT = BACKEND.parent / "frontend" / "src" / "i18n" / "it.json"

# A vowel followed by an apostrophe at the end of a word: "e'", "piu'", "C'e'", "varieta'".
# An elision is followed by a letter ("dell'agente", "un'alternativa") and does not match.
APOSTROPHE_ACCENT = re.compile(r"[aeiouAEIOU]'(?!\w)")
# Words that are only correct with the accent (written without accent and without apostrophe)
UNACCENTED_WORDS = re.compile(
    r"\b(?:sara|piu|perche|gia|puo|cosi|citta|qualita|attivita|poiche|anziche|affinche|cioe)\b", re.I)
# Text between single quotes used as quotation marks ('adozione'): the closing quote is not an accent.
# The opening quote follows a space, punctuation or the start, never a letter (C'e' is not a quotation)
QUOTED = re.compile(r"(?<![\w'])'[^'\n]*'(?!\w)")
# Legitimate apostrophes at the end of a word
ALLOWED = ("po'",)            # un po'
# Proper names spelled like an unaccented word (capitalised exactly like this)
PROPER_NAMES = {"Sara"}


def accent_problems(text: str) -> list[str]:
    """The fragments of text that use an apostrophe for an accent or miss an accent."""
    checked = QUOTED.sub(" ", text)
    for allowed in ALLOWED:
        checked = re.sub(rf"(?<!\w){re.escape(allowed)}", " ", checked)
    problems = [m.group(0) for m in UNACCENTED_WORDS.finditer(checked) if m.group(0) not in PROPER_NAMES]
    for m in APOSTROPHE_ACCENT.finditer(checked):
        start = m.start()
        while start > 0 and (checked[start - 1].isalpha() or checked[start - 1] == "'"):
            start -= 1
        problems.append(checked[start:m.end()])
    return problems


def _strings(value, path=""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _strings(item, f"{path}[{i}]")


def italian_strings():
    sources = [BACKEND / "app" / "locales" / "it.yml",
               *sorted((BACKEND / "app" / "templates" / "simulations" / "locales" / "it").glob("*.yml"))]
    for source in sources:
        for path, text in _strings(yaml.safe_load(source.read_text(encoding="utf-8"))):
            yield f"{source.name}:{path}", text
    if FRONTEND_IT.exists():
        for path, text in _strings(json.loads(FRONTEND_IT.read_text(encoding="utf-8"))):
            yield f"it.json:{path}", text
    from app.population.persona_generator import _TEMPLATE_PHRASES
    yield "persona_generator._TEMPLATE_PHRASES[it]", _TEMPLATE_PHRASES["it"]


@pytest.mark.parametrize("text, expected", [
    ("C'e' ascolto tra le fazioni.", ["C'e'"]),
    ("mantiene una varieta' costante", ["varieta'"]),
    ("senza appiattirsi ne' espandersi", ["ne'"]),
    ("Quale sara la reazione del mercato?", ["sara"]),
    ("Non e' stato possibile", ["e'"]),
    ("Piu clienti, perche il prezzo e gia noto", ["Piu", "perche", "gia"]),
])
def test_checker_flags_missing_accents(text, expected):
    assert accent_problems(text) == expected


@pytest.mark.parametrize("text", [
    "C'è ascolto, più varietà, né l'uno né l'altro: è già così.",
    "dell'agente, un'alternativa, l'intensità",
    "aspetta un po' di tempo",
    "'adozione' significa accettazione",
    "tu{'@'}esempio.com",
    "Sara e Chiara",             # proper name, not the verb
])
def test_checker_accepts_correct_text(text):
    assert accent_problems(text) == []


def test_italian_strings_found():
    sources = {name.split(":")[0] for name, _ in italian_strings()}
    assert "it.yml" in sources
    assert {"product_launch.yml", "brand_rebranding.yml", "crisis_comms.yml"} <= sources


def test_italian_code_owned_text_has_real_accents():
    problems = [f"{where}: {found} in {text[:80]!r}"
                for where, text in italian_strings() if (found := accent_problems(text))]
    assert not problems, "Italian text with apostrophe-accents or missing accents:\n" + "\n".join(problems)
