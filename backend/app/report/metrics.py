"""
SwarMind Debate Dynamics Metrics.

Calcola metriche deterministiche (no LLM) per arricchire il report con
insight quantitativi sul dibattito simulato:

  1. polarization_delta
     Quanto le opinioni si sono spostate verso gli estremi tra round 1 e finale.
     Cattura l'effetto "cementazione" delle posizioni nel tempo.

  2. echo_chamber_index
     Similarita' semantica media tra i post di ciascun round.
     Alta similarita' = echo chamber, bassa similarita' = silos paralleli.
     Embedding: all-MiniLM-L6-v2 in ONNX, quello di default di Chroma (niente torch).

  3. information_diversity_trend
     Varieta' semantica dei topic nel tempo. Se cala rapidamente la
     conversazione si appiattisce su poche idee dominanti.

Le metriche sono calcolate UNA VOLTA per simulazione, alla fine,
durante la generazione del report. Zero overhead durante la sim.

Le descrizioni (interpretazioni per il lettore) sono nel catalogo (locales, chiavi metrics.*),
nella lingua della simulazione.
"""
from __future__ import annotations

import math
import re
import time
from collections import Counter
from typing import Any

import structlog

from ..core.i18n import DEFAULT_LANGUAGE, t

log = structlog.get_logger()

# ─── Modello embedding (lazy load) ──────────────────────────────────────────
# all-MiniLM-L6-v2 in ONNX: l'embedding di default di Chroma, lo stesso della memoria degli agenti.
# Da' gli stessi vettori di sentence-transformers con lo stesso modello, senza torch. I file stanno
# in ~/.cache/chroma/onnx_models (nel worker il volume chroma_onnx_cache, gia' popolato dalla
# memoria degli agenti); se mancano Chroma li scarica al primo embedding.
EMBEDDING_MODEL_NAME = "chroma-onnx-all-MiniLM-L6-v2"
# Dopo un fallimento il processo riprova dopo questo intervallo: nel frattempo vale il Jaccard
EMBEDDING_RETRY_SECONDS = 600
_EMBEDDING_MODEL = None
_EMBEDDING_FAILED_AT = 0.0


def _get_embedding_model():
    """Embedding function di Chroma (lista di testi -> lista di vettori), o None se non disponibile."""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL
    if _EMBEDDING_FAILED_AT and time.monotonic() - _EMBEDDING_FAILED_AT < EMBEDDING_RETRY_SECONDS:
        return None
    try:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        _EMBEDDING_MODEL = DefaultEmbeddingFunction()
    except Exception as e:
        _embedding_failed(e)
        return None
    return _EMBEDDING_MODEL


def _embedding_failed(error: Exception) -> None:
    """Scarta il modello: il prossimo tentativo dopo EMBEDDING_RETRY_SECONDS."""
    global _EMBEDDING_MODEL, _EMBEDDING_FAILED_AT
    _EMBEDDING_MODEL = None
    _EMBEDDING_FAILED_AT = time.monotonic()
    log.warning("metric_embedding_failed", model=EMBEDDING_MODEL_NAME, error=str(error)[:300])


# ─── Metrica 1: Polarization Delta ──────────────────────────────────────────
# Soglie di lettura (la formula del delta non cambia). Un delta assoluto piccolo puo' essere un
# cambiamento grande: da 0,038 a 0,158 la polarizzazione quadruplica con delta 0,12. Conta come
# polarizzazione attiva anche un raddoppio, se il delta supera il rumore (0,05) e il valore finale arriva
# almeno a 0,1 (sotto, la convinzione degli agenti e' quasi uniforme comunque).
POLARIZATION_ACTIVE_ABS = 0.15        # delta > 0,15: attiva
POLARIZATION_ACTIVE_RELATIVE = 1.0    # oppure delta >= 0,05 e almeno +100% sul valore iniziale
POLARIZATION_RELATIVE_MIN_DELTA = 0.05
POLARIZATION_RELATIVE_FLOOR = 0.025   # base minima del rapporto: con un iniziale quasi zero non esplode
POLARIZATION_RELATIVE_MIN_FINAL = 0.1
DEPOLARIZATION_ABS = -0.05            # delta < -0,05: depolarizzazione


def compute_polarization_delta(round_metrics: list[dict], lang: str = DEFAULT_LANGUAGE) -> dict:
    """
    Confronta polarization_score tra primo e ultimo round.
    round_metrics e' una lista di dict con chiave 'polarization' (float 0-1).

    Ritorna dict con:
      - delta: differenza numerica (-1 a +1)
      - interpretation: etichetta qualitativa
      - description: testo gia' pronto per il report
    """
    if not round_metrics or len(round_metrics) < 2:
        return {
            "delta": 0.0,
            "interpretation": "insufficient_data",
            "description": t(lang, "metrics.polarization_delta.insufficient_data"),
        }

    initial = round_metrics[0].get("polarization", 0.0)
    final = round_metrics[-1].get("polarization", 0.0)
    delta = round(final - initial, 3)
    relative = round(delta / max(initial, POLARIZATION_RELATIVE_FLOOR), 3)

    if delta > POLARIZATION_ACTIVE_ABS or (
            delta >= POLARIZATION_RELATIVE_MIN_DELTA and relative >= POLARIZATION_ACTIVE_RELATIVE
            and final >= POLARIZATION_RELATIVE_MIN_FINAL):
        interp = "polarization_active"
    elif delta < DEPOLARIZATION_ABS:
        interp = "depolarization"
    else:
        interp = "stable"
    desc = t(lang, f"metrics.polarization_delta.{interp}", delta=delta)

    return {
        "initial_polarization": round(initial, 3),
        "final_polarization": round(final, 3),
        "delta": delta,
        "relative_change": relative,
        "interpretation": interp,
        "description": desc,
    }


# ─── Metrica 2: Echo Chamber Index ──────────────────────────────────────────
def compute_echo_chamber_index(social_feed: list[dict], lang: str = DEFAULT_LANGUAGE) -> dict:
    """
    Misura la similarita' semantica media dei post all'interno di ogni round.
    Usa all-MiniLM-L6-v2 (ONNX di Chroma); solo se l'embedding fallisce
    ripiega sul word-overlap Jaccard e registra metric_embedding_fallback.
    """
    # Raggruppa post per round
    by_round: dict[int, list[str]] = {}
    for post in social_feed:
        r = post.get("round", 0)
        content = (post.get("content") or "").strip()
        if content and len(content) > 20:
            by_round.setdefault(r, []).append(content)

    # Servono almeno 3 round con >=2 post ciascuno per una media sensata
    valid_rounds = {r: posts for r, posts in by_round.items() if len(posts) >= 2}
    if len(valid_rounds) < 3:
        return {
            "score": None,
            "interpretation": "insufficient_data",
            "description": t(lang, "metrics.echo_chamber_index.insufficient_data"),
            "method": "n/a",
        }

    method = "fallback_jaccard"
    model = _get_embedding_model()
    fallback_reason = "model_unavailable" if model is None else None

    if model is not None:
        # Versione embedding (alta qualita'). Un round che fallisce fa ripiegare tutta la
        # metrica sul Jaccard: le soglie dei due metodi non si possono mescolare
        import numpy as np
        round_scores = []
        try:
            for r, posts in sorted(valid_rounds.items()):
                embeddings = np.array(model(posts), dtype=np.float32)
                n = len(embeddings)
                # normalizza per cosine similarity
                norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
                norms[norms == 0] = 1
                normalized = embeddings / norms
                sim_matrix = normalized @ normalized.T
                # media escludendo diagonale
                mask = ~np.eye(n, dtype=bool)
                mean_sim = float(sim_matrix[mask].mean())
                round_scores.append(mean_sim)
            method = "embedding"
            score = round(sum(round_scores) / len(round_scores), 3)
        except Exception as e:
            _embedding_failed(e)
            fallback_reason = "embedding_failed"

    if method == "fallback_jaccard":
        log.warning("metric_embedding_fallback", metric="echo_chamber_index",
                    model=EMBEDDING_MODEL_NAME, reason=fallback_reason, rounds=len(valid_rounds))
        # Fallback: Jaccard su bag-of-words significative
        def tokenize(text: str) -> set[str]:
            words = re.findall(r"[a-zA-ZàèéìòùÀÈÉÌÒÙ]+", text.lower())
            return {w for w in words if len(w) > 4}

        round_scores = []
        for r, posts in sorted(valid_rounds.items()):
            token_sets = [tokenize(p) for p in posts]
            if len(token_sets) < 2:
                continue
            pairs = []
            for i in range(len(token_sets)):
                for j in range(i + 1, len(token_sets)):
                    a, b = token_sets[i], token_sets[j]
                    if not a and not b:
                        continue
                    jaccard = len(a & b) / max(len(a | b), 1)
                    pairs.append(jaccard)
            if pairs:
                round_scores.append(sum(pairs) / len(pairs))
        if not round_scores:
            return {
                "score": None,
                "interpretation": "insufficient_data",
                "description": t(lang, "metrics.echo_chamber_index.failed"),
                "method": "failed",
            }
        score = round(sum(round_scores) / len(round_scores), 3)

    # Soglie leggermente diverse tra embedding e jaccard (jaccard di solito piu' basso)
    if method == "embedding":
        high_th, mid_th = 0.70, 0.50
    else:
        high_th, mid_th = 0.30, 0.15

    if score > high_th:
        interp = "echo_chamber_strong"
    elif score > mid_th:
        interp = "partial_debate"
    else:
        interp = "parallel_silos"
    desc = t(lang, f"metrics.echo_chamber_index.{interp}", score=score)

    return {
        "score": score,
        "interpretation": interp,
        "description": desc,
        "method": method,
    }


# ─── Metrica 3: Information Diversity Trend ─────────────────────────────────
_STOPWORDS_IT_EN_BASE = {
    "sono", "essere", "questo", "questa", "quello", "quella",
    "della", "delle", "degli", "dalla", "dalle", "dagli",
    "nella", "nelle", "negli", "sulla", "sulle", "sugli",
    "molto", "piu", "meno", "anche", "perche", "quando", "dove",
    "come", "cosa", "tutto", "tutti", "tutte", "nulla", "niente",
    "altro", "altra", "altri", "altre", "stesso", "stessa",
    "that", "this", "with", "from", "have", "been", "were",
    "their", "there", "these", "those", "about", "which",
    "should", "would", "could", "really", "something",
}


def compute_information_diversity(social_feed: list[dict], lang: str = DEFAULT_LANGUAGE) -> dict:
    """
    Misura l'evoluzione della diversita' lessicale nei round.
    Se la varieta' cala rapidamente la conversazione si appiattisce.
    """
    by_round: dict[int, list[str]] = {}
    for post in social_feed:
        r = post.get("round", 0)
        content = (post.get("content") or "").strip()
        if content:
            by_round.setdefault(r, []).append(content)

    if len(by_round) < 3:
        return {
            "trend": None,
            "interpretation": "insufficient_data",
            "description": t(lang, "metrics.information_diversity.insufficient_data"),
        }

    def unique_keywords(posts: list[str]) -> set[str]:
        words = []
        for p in posts:
            tokens = re.findall(r"[a-zA-ZàèéìòùÀÈÉÌÒÙ]+", p.lower())
            words.extend(t for t in tokens if len(t) > 5 and t not in _STOPWORDS_IT_EN_BASE)
        return set(words)

    rounds_sorted = sorted(by_round.items())
    keyword_counts = [len(unique_keywords(posts)) for r, posts in rounds_sorted]

    if len(keyword_counts) < 3:
        return {
            "trend": None,
            "interpretation": "insufficient_data",
            "description": t(lang, "metrics.information_diversity.insufficient_trend"),
        }

    # Confronta prima meta' vs seconda meta'
    half = len(keyword_counts) // 2
    first_half_avg = sum(keyword_counts[:half]) / max(half, 1)
    second_half_avg = sum(keyword_counts[half:]) / max(len(keyword_counts) - half, 1)

    if first_half_avg == 0:
        delta_pct = 0.0
    else:
        delta_pct = round((second_half_avg - first_half_avg) / first_half_avg * 100, 1)

    if delta_pct < -30:
        interp = "rapid_collapse"
    elif delta_pct < -10:
        interp = "gradual_convergence"
    elif delta_pct > 20:
        interp = "diversity_growth"
    else:
        interp = "stable_diversity"
    desc = t(lang, f"metrics.information_diversity.{interp}", delta_pct=delta_pct)

    return {
        "first_half_keywords_avg": round(first_half_avg, 1),
        "second_half_keywords_avg": round(second_half_avg, 1),
        "delta_pct": delta_pct,
        "interpretation": interp,
        "description": desc,
    }


# ─── Bundle: tutte le metriche in un colpo ──────────────────────────────────
def compute_all_debate_metrics(
    round_metrics: list[dict],
    social_feed: list[dict],
    lang: str = DEFAULT_LANGUAGE,
) -> dict:
    """Calcola tutte e 3 le metriche e ritorna un dict unificato (descrizioni nella lingua lang)."""
    return {
        "polarization_delta": compute_polarization_delta(round_metrics, lang),
        "echo_chamber_index": compute_echo_chamber_index(social_feed, lang),
        "information_diversity": compute_information_diversity(social_feed, lang),
    }
