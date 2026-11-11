"""
SwarMind Simulation Engine

Core loop:
  For each round:
    1. Sample a subset of agents to act (prevents O(n²) calls)
    2. Build each agent's context (feed + environment)
    3. Run all agent decisions in parallel (Groq batch)
    4. Process actions → update social feed, opinions, relationships
    5. Compute round metrics (entropy, polarization, consensus)
    6. Emit real-time updates via Redis pub/sub → WebSocket
    7. Check stopping conditions (convergence, max rounds)

Key improvements over MiroFish:
  - Opinion entropy monitoring (stops if collapsed or too polarized)
  - Active diversity injection (re-seeds stubborn convergence)
  - Redis-backed event stream for real-time UI
  - Platform-agnostic (not just Twitter/Reddit)
  - Configurable action set per platform type
"""
from __future__ import annotations
import os
import os

import asyncio
import json
import math
import random
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import redis as sync_redis
import structlog

from ..agents.agent import Agent
from ..agents.stance import STANCE_DEFINITION, STANCE_ENUM, record_stance
from ..agents.response_parser import (
    FAILED_OUTCOMES,
    OUTCOME_EMPTY,
    OUTCOME_PARSE_FAILED,
    OUTCOME_TRUNCATED,
    parse_json_object,
    reply_failure,
)
from ..core.i18n import DEFAULT_LANGUAGE, t, with_directive
from ..core.llm import get_llm
from ..core.llm_response import llm_log_fields
from ..config import Config
from ..memory.chroma_client import ChromaSkipped, chroma_settings, error_text, is_outage, run_chroma
from ..memory.knowledge_base import KB_PROMPT_EXCERPTS, format_kb_excerpts
from ..utils.excerpt import trim_excerpt

log = structlog.get_logger()

# Tetto alla quota di post adversarial sul totale della simulazione. I template possono cambiarlo.
DEFAULT_ADVERSARIAL_POST_SHARE_CAP = 0.25


class SimStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


PLATFORM_ACTIONS = {
    "social_media": [
        "CREATE_POST", "COMMENT", "LIKE", "DISLIKE", "REPOST",
        "FOLLOW", "UNFOLLOW", "QUOTE", "REACT_ANGRY", "DO_NOTHING",
    ],
    "forum": [
        "CREATE_POST", "CREATE_COMMENT", "UPVOTE", "DOWNVOTE",
        "AWARD", "REPORT", "FOLLOW", "DO_NOTHING",
    ],
    "financial": [
        "BUY", "SELL", "HOLD", "ANNOUNCE", "RUMOR",
        "ANALYZE", "RECOMMEND", "DO_NOTHING",
    ],
    "political": [
        "SPEAK", "VOTE", "PROPOSE", "OPPOSE", "ALLY_WITH",
        "LOBBY", "LEAK", "DO_NOTHING",
    ],
}


# Esito di ogni risposta di agente: la somma dei contatori e' il totale delle risposte
RESPONSE_STAT_KEYS = (
    "posted",
    "engagement",  # LIKE/DISLIKE/REPOST applicati a un post esistente, senza nuovo post
    "do_nothing",  # nessun effetto: DO_NOTHING, azione senza testo, target inesistente
    "repetition_skipped",  # ripeteva un post dello stesso agente anche dopo il nuovo tentativo: non pubblicato
    *FAILED_OUTCOMES,
    "errors",      # eccezione durante la chiamata LLM
)
# Non e' un esito (fuori dalla somma): nuovi tentativi chiesti perche' la risposta ripeteva un post dello
# stesso agente (agents/repetition.py). La risposta del nuovo tentativo ha poi il suo esito
REPETITION_RETRIES = "repetition_retries"

# One English prompt; the language of the news item comes from the directive at the end
_DIVERSITY_EVENT_PROMPT = """SUBJECT CARD
{subject_card}

Write ONE single news item, plausible and specific, that directly concerns the subject of the card and reopens the debate on the operation.
- One sentence, at most 240 characters.
- Only the text of the news item: no titles, markdown, lists or comments.
- Do not change subject or sector. Do not mention simulations, rounds or debates.
Reply ONLY with JSON: {{"event": "..."}}"""

DIVERSITY_EVENT_MIN_CHARS = 40
DIVERSITY_EVENT_MAX_CHARS = 280
_SIMULATION_TERMS = (
    re.compile(r"\bsimul\w*", re.IGNORECASE),
    re.compile(r"\bround\b", re.IGNORECASE),
)
_WORD = re.compile(r"\w+")


def diversity_event_rejection(event: Any, subject_card: str = "", homonyms: Any = ()) -> str | None:
    """Ritorna il motivo per cui l'evento va scartato, o None se si puo' pubblicare."""
    if not isinstance(event, str) or not event.strip():
        return "missing_event"
    text = event.strip()
    if "\n" in text or "\r" in text:
        return "multiline"
    if len(text) < DIVERSITY_EVENT_MIN_CHARS:
        return "too_short"
    if len(text) > DIVERSITY_EVENT_MAX_CHARS:
        return "too_long"
    if text[0] in "#*-{":
        return "markup"
    # Il soggetto puo' essere esso stesso un simulatore: il termine conta solo se non e' nella scheda
    if any(term.search(text) and not term.search(subject_card) for term in _SIMULATION_TERMS):
        return "mentions_simulation"
    words = set(_WORD.findall(text.lower()))
    for homonym in homonyms:
        # Almeno due parole: un omonimo di una sola parola scarterebbe anche le notizie sul soggetto vero
        significant = {w for w in _WORD.findall(homonym.lower()) if len(w) >= 4}
        if len(significant) >= 2 and significant <= words:
            return "homonym"
    return None


@dataclass
class SimulationRound:
    round_num: int
    actions: list[dict] = field(default_factory=list)
    opinion_entropy: float = 0.0
    polarization_score: float = 0.0
    dominant_narrative: str = ""
    emerging_topics: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class SimulationState:
    simulation_id: str
    project_id: str
    topic: str
    status: SimStatus = SimStatus.PENDING
    current_round: int = 0
    total_rounds: int = 50
    agents: list[Agent] = field(default_factory=list)
    rounds: list[SimulationRound] = field(default_factory=list)
    social_feed: list[dict] = field(default_factory=list)  # global post feed
    _last_feed_map: dict = field(default_factory=dict)  # short_id -> post_id per Patch D
    post_engagement: dict = field(default_factory=dict)  # Patch H: aggregato engagement per TUTTI i post, sopravvive al trim del feed
    response_stats: dict = field(default_factory=lambda: dict.fromkeys((*RESPONSE_STAT_KEYS, REPETITION_RETRIES), 0))
    adversarial_post_share_cap: float = DEFAULT_ADVERSARIAL_POST_SHARE_CAP
    adversarial_posts: int = 0  # sul totale response_stats["posted"]: il feed viene tagliato
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    error: str | None = None
    subject_card: str = ""  # cosa viene simulato: il topic e' solo il nome del progetto
    language: str = DEFAULT_LANGUAGE  # simulation language (simulations.language), not the brief's
    subject_homonyms: list[str] = field(default_factory=list)
    change_tested: str = ""  # what the agents take a stance on (population.integration.change_tested)

    @property
    def total_posts(self) -> int:
        """Post dell'intera simulazione, dal contatore del run: il feed in memoria tiene solo gli ultimi FEED_MAX_SIZE."""
        return int(self.response_stats.get("posted", 0))

    @property
    def subject_block(self) -> str:
        return f"SUBJECT CARD:\n{self.subject_card}\n\n" if self.subject_card else ""

    def adversarial_post_stats(self) -> dict:
        posts = self.response_stats["posted"]
        return {
            "share": round(self.adversarial_posts / posts, 4) if posts else 0.0,
            "adversarial_posts": self.adversarial_posts,
            "posts": posts,
            "cap": self.adversarial_post_share_cap,
            "adversarial_agents": sum(getattr(a, "is_adversarial", False) for a in self.agents),
            "total_agents": len(self.agents),
        }

    def summary(self) -> dict:
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "topic": self.topic,
            "status": self.status.value,
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "num_agents": len(self.agents),
            "num_posts": self.total_posts,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


class SimulationEngine:
    """
    Orchestrates the multi-agent simulation loop.
    """

    FEED_MAX_SIZE = 500         # keep last N posts in active feed
    AGENTS_PER_ROUND_RATIO = 0.3  # fraction of agents active each round
    # Seed della memoria in parallelo. Prima partivano tutti insieme (20+ scritture concorrenti su
    # Chroma, che su un nodo scrive su SQLite un writer alla volta): con 4 il seed resta di pochi
    # secondi (una scrittura per agente, ~100-300 ms con l'embedding) e Chroma non riceve raffiche
    MEMORY_SEED_CONCURRENCY = 4
    DIVERSITY_INJECT_INTERVAL = 10  # re-inject diversity every N rounds
    OPINION_UPDATE_INTERVAL = 3     # refresh current_opinion / opinion_strength every N rounds

    def __init__(self, redis_url: str = "redis://localhost:6379/0", llm=None):
        self._redis = sync_redis.from_url(redis_url, decode_responses=True)
        self._llm = llm or get_llm()
        self._kb = None  # Inizializzata lazy al primo round (serve project_id)

    async def run(
        self,
        state: SimulationState,
        platform_type: str = "social_media",
        agents_per_round: int | None = None,
        entropy_threshold: float = 0.3,
        on_round_complete: Any = None,
    ) -> SimulationState:
        """Main simulation loop."""

        state.status = SimStatus.RUNNING
        available_actions = PLATFORM_ACTIONS.get(
            platform_type, PLATFORM_ACTIONS["social_media"]
        )

        # Seed agent memories with persona knowledge
        await self._seed_memories(state.agents)

        active_count = agents_per_round or max(
            5, int(len(state.agents) * self.AGENTS_PER_ROUND_RATIO)
        )

        log.info(
            "simulation_start",
            sim_id=state.simulation_id,
            agents=len(state.agents),
            rounds=state.total_rounds,
            active_per_round=active_count,
        )

        for round_num in range(1, state.total_rounds + 1):
            if state.status == SimStatus.STOPPED:
                break

            state.current_round = round_num
            round_result = await self._run_round(
                state,
                round_num,
                active_count,
                available_actions,
            )
            state.rounds.append(round_result)

            # Emit real-time update
            self._emit_round_event(state, round_result)

            # Opinion refresh (summary per agenti che hanno postato)
            if round_num % self.OPINION_UPDATE_INTERVAL == 0:
                await self._update_agent_opinions(state, round_num)

            # Diversity injection
            if round_num % self.DIVERSITY_INJECT_INTERVAL == 0:
                await self._inject_diversity_events(state)

            # Stopping condition: opinion entropy collapsed
            if round_result.opinion_entropy < entropy_threshold and round_num > 10:
                log.info(
                    "simulation_converged",
                    sim_id=state.simulation_id,
                    round=round_num,
                    entropy=round_result.opinion_entropy,
                )
                break

            if on_round_complete:
                await on_round_complete(state, round_result)

            # Brief pause to avoid Groq rate limits
            await asyncio.sleep(0.5)

        state.status = SimStatus.COMPLETED
        state.completed_at = time.time()
        log.info("simulation_response_stats", sim_id=state.simulation_id, **state.response_stats)
        log.info("adversarial_post_share", sim_id=state.simulation_id, **state.adversarial_post_stats())
        self._emit_event(state.simulation_id, "simulation_complete", state.summary())
        log.info(
            "simulation_complete",
            sim_id=state.simulation_id,
            rounds=state.current_round,
            posts=state.total_posts,
            feed_posts=len(state.social_feed),
        )
        return state

    async def _run_round(
        self,
        state: SimulationState,
        round_num: int,
        active_count: int,
        available_actions: list[str],
    ) -> SimulationRound:
        """Execute one simulation round."""

        # Sample active agents (biased toward high-influence agents)
        active_agents = self._sample_agents(
            state.agents, active_count, self._adversarial_slots(state, active_count)
        )

        # Build environment context (shared across all agents this round)
        env_context = self._build_env_context(state, round_num)

        # Recent feed (last 20 posts)
        # Patch D: feed ordinato per hot_score invece che cronologico
        recent_feed = self._rank_feed_by_hot_score(state.social_feed, top_n=20)
        # Costruisce short_id map (P1, P2, ...) per permettere all'agente di
        # riferirsi ai post nelle azioni LIKE/DISLIKE/REPOST.
        feed_map = {}
        for idx, post in enumerate(recent_feed, start=1):
            short_id = f"P{idx}"
            post["_short_id"] = short_id
            feed_map[short_id] = post["post_id"]
        state._last_feed_map = feed_map

        # Lazy init della KB del progetto
        if self._kb is None:
            self._kb = await self._open_kb(state)

        # Retrieval KB multi-query per ogni agente attivo.
        # Ogni agente riceve i chunk migliori di 3 query diverse (role, beliefs, fears)
        # con scoring reciprocal-rank. Questo massimizza la diversita' informativa
        # e rompe la convergenza sui frame dominanti del grafo.
        # Un agente alla volta come prima, ma in un thread e con un tetto di tempo: se Chroma non
        # risponde il prompt resta senza blocco KB e il round prosegue.
        kb_contexts: dict[str, str] = {}
        if self._kb:
            for agent in active_agents:
                started = time.monotonic()
                try:
                    chunks = await run_chroma(
                        "kb_retrieve",
                        self._kb.retrieve_for_agent,
                        agent,
                        topic=state.topic,
                        n_per_query=3,
                        final_n=KB_PROMPT_EXCERPTS,
                        timeout=Config.CHROMA_KB_OP_TIMEOUT,
                    )
                    kb_contexts[agent.agent_id] = format_kb_excerpts(chunks)
                except Exception as kb_err:
                    emit = log.debug if isinstance(kb_err, ChromaSkipped) else log.warning
                    emit("kb_retrieve_failed", agent=agent.agent_id, sim_id=state.simulation_id,
                         op="retrieve_for_agent", error=error_text(kb_err),
                         ms=round((time.monotonic() - started) * 1000))
                    kb_contexts[agent.agent_id] = ""

        # Run all agent decisions in parallel
        tasks = [
            agent.decide_action(
                environment_context=env_context,
                available_actions=available_actions,
                recent_feed=recent_feed,
                round_num=round_num,
                kb_context=kb_contexts.get(agent.agent_id, ""),
            )
            for agent in active_agents
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        # Patch C: gestione azioni multiple (LIKE/DISLIKE/REPOST/DO_NOTHING)
        round_actions = []
        # Mappa post_id -> post dict per lookup rapido durante like/dislike
        post_by_id = {p["post_id"]: p for p in state.social_feed}
        # Mappa short_id (es. "P3") -> post_id reale, costruita in _build_env_context
        # L'agente vede "P3" nel context e risponde con target_post_id="P3".
        # Recuperiamo la mappa dal result (passata via agent).
        for agent, result in zip(active_agents, results):
            if isinstance(result, Exception):
                log.warning("agent_action_error", agent=agent.agent_id, error=str(result))
                state.response_stats["errors"] += 1
                continue
            outcome = result.get("response_outcome")
            if result.get("repetition"):
                state.response_stats[REPETITION_RETRIES] = state.response_stats.get(REPETITION_RETRIES, 0) + 1
            if outcome in FAILED_OUTCOMES:
                state.response_stats[outcome] += 1
                continue
            if result.get("repetition") == "skipped":
                state.response_stats["repetition_skipped"] = state.response_stats.get("repetition_skipped", 0) + 1
                continue
            action = (result.get("action") or "CREATE_POST").upper()

            # --- Azioni di engagement su post esistenti -------------------
            if action in ("LIKE", "DISLIKE", "REPOST"):
                target_short = result.get("target_post_id") or ""
                # Risolve short_id ("P3") -> post_id reale usando la mappa
                # salvata nello state durante _build_env_context
                short_map = getattr(state, "_last_feed_map", {}) or {}
                real_post_id = short_map.get(target_short, target_short)
                target_post = post_by_id.get(real_post_id)
                if not target_post:
                    # Target non trovato: skip silenzioso
                    state.response_stats["do_nothing"] += 1
                    continue
                if action == "LIKE":
                    target_post["likes"] = target_post.get("likes", 0) + 1
                    # Patch H: aggiorna anche l'aggregato
                    agg = state.post_engagement.get(real_post_id)
                    if agg:
                        agg["likes"] = agg.get("likes", 0) + 1
                elif action == "DISLIKE":
                    target_post["dislikes"] = target_post.get("dislikes", 0) + 1
                    agg = state.post_engagement.get(real_post_id)
                    if agg:
                        agg["dislikes"] = agg.get("dislikes", 0) + 1
                elif action == "REPOST":
                    target_post["reposts"] = target_post.get("reposts", 0) + 1
                    agg = state.post_engagement.get(real_post_id)
                    if agg:
                        agg["reposts"] = agg.get("reposts", 0) + 1
                    # Il repost crea anche un post amplificato nel feed
                    if result.get("content"):
                        repost = {
                            "post_id": f"r{round_num}_{agent.agent_id}_rp",
                            "round": round_num,
                            "author_id": agent.agent_id,
                            "author_name": agent.persona.name,
                            "author_role": agent.persona.role,
                            "action": "REPOST",
                            "content": result.get("content", ""),
                            "target_agent": target_post.get("author_id"),
                            "target_post_id": real_post_id,
                            "timestamp": time.time(),
                            "likes": 0,
                            "dislikes": 0,
                            "reposts": 0,
                        }
                        state.social_feed.append(repost)
                        post_by_id[repost["post_id"]] = repost
                        # Patch H: registra anche il repost amplificato nell'aggregato
                        state.post_engagement[repost["post_id"]] = {
                            "post_id": repost["post_id"],
                            "round": repost["round"],
                            "author_id": repost["author_id"],
                            "author_name": repost["author_name"],
                            "content_preview": trim_excerpt(repost.get("content") or "", 200),
                            "action": "REPOST",
                            "target_post_id": real_post_id,
                            "likes": 0,
                            "dislikes": 0,
                            "reposts": 0,
                        }
                        round_actions.append(repost)
                        state.response_stats["posted"] += 1
                        continue
                state.response_stats["engagement"] += 1
                continue

            # --- DO_NOTHING, FOLLOW, UNFOLLOW: skip silenzioso ------------
            if action in ("DO_NOTHING", "FOLLOW", "UNFOLLOW"):
                state.response_stats["do_nothing"] += 1
                continue

            # --- Azioni che creano un nuovo post --------------------------
            # CREATE_POST, COMMENT, QUOTE, REACT_ANGRY
            if result.get("content"):
                post = {
                    "post_id": f"r{round_num}_{agent.agent_id}",
                    "round": round_num,
                    "author_id": agent.agent_id,
                    "author_name": agent.persona.name,
                    "author_role": agent.persona.role,
                    "action": action,
                    "content": result.get("content", ""),
                    "target_agent": result.get("target_agent"),
                    "timestamp": time.time(),
                    "likes": 0,
                    "dislikes": 0,
                    "reposts": 0,
                }
                state.social_feed.append(post)
                post_by_id[post["post_id"]] = post
                # Patch H: registra il post nell'aggregato engagement (sopravvive al trim)
                state.post_engagement[post["post_id"]] = {
                    "post_id": post["post_id"],
                    "round": post["round"],
                    "author_id": post["author_id"],
                    "author_name": post["author_name"],
                    "content_preview": trim_excerpt(post.get("content") or "", 200),
                    "action": post["action"],
                    "likes": 0,
                    "dislikes": 0,
                    "reposts": 0,
                }
                round_actions.append(post)
                state.response_stats["posted"] += 1
            else:
                state.response_stats["do_nothing"] += 1

        adversarial_ids = {a.agent_id for a in active_agents if getattr(a, "is_adversarial", False)}
        state.adversarial_posts += sum(p["author_id"] in adversarial_ids for p in round_actions)

        # Trim feed
        if len(state.social_feed) > self.FEED_MAX_SIZE:
            state.social_feed = state.social_feed[-self.FEED_MAX_SIZE :]

        # Compute metrics
        entropy = self._compute_opinion_entropy(state.agents)
        polarization = self._compute_polarization(state.agents)

        sim_round = SimulationRound(
            round_num=round_num,
            actions=round_actions,
            opinion_entropy=entropy,
            polarization_score=polarization,
        )

        log.debug(
            "round_done",
            round=round_num,
            actions=len(round_actions),
            entropy=round(entropy, 3),
        )
        return sim_round

    @staticmethod
    def _adversarial_slots(state: SimulationState, n: int) -> int:
        """
        Posti per gli avversari in un round di n agenti: tengono la quota di post sul tetto.

        Il conto usa i post realmente pubblicati piu' quelli possibili in questo round, quindi
        si corregge da solo quando gli agenti non postano (DO_NOTHING, risposte scartate).
        Il limite per round evita che i posti accumulati finiscano tutti nello stesso round.
        """
        n = min(n, len(state.agents))
        cap = state.adversarial_post_share_cap
        quota = cap * (state.response_stats["posted"] + n) - state.adversarial_posts
        return max(0, min(math.floor(quota), math.ceil(cap * n)))

    @staticmethod
    def _sample_agents(agents: list[Agent], n: int, adversarial_slots: int) -> list[Agent]:
        """
        Sample agents per il round:
          1. Gli agenti avversari (is_adversarial=True) occupano al massimo adversarial_slots
             posti, a turno: prima chi ha postato meno, cosi' ogni voce critica viene sentita.
          2. Gli altri slot vengono riempiti campionando casualmente tra i naturali
             con bias verso chi posta di piu' (influence).
        """
        adversarial = [a for a in agents if getattr(a, "is_adversarial", False)]
        natural = [a for a in agents if not getattr(a, "is_adversarial", False)]

        # Senza naturali non c'e' una quota da difendere
        if not natural:
            return adversarial[:n]

        speaking = sorted(adversarial, key=lambda a: (a.posts_made, random.random()))[:adversarial_slots]
        remaining_slots = n - len(speaking)
        if len(natural) <= remaining_slots:
            return speaking + natural

        # Fill con sampling pesato sui naturali
        weights = [1 + a.posts_made for a in natural]
        total = sum(weights)
        probs = [w / total for w in weights]
        indices = random.choices(range(len(natural)), weights=probs, k=remaining_slots)
        sampled_natural = [natural[i] for i in set(indices)]

        return speaking + sampled_natural

    @staticmethod
    def _build_env_context(state: SimulationState, round_num: int) -> str:
        """Generate a brief narrative context for the current round."""
        return (
            f"{state.subject_block}"
            f"Simulation topic: {state.topic}\n"
            f"Current round: {round_num} of {state.total_rounds}\n"
            f"Total posts so far: {len(state.social_feed)}\n"
            f"Time pressure: {'high' if round_num > state.total_rounds * 0.7 else 'normal'}"
        )

    @staticmethod
    def _compute_hot_score(post: dict) -> float:
        """
        Reddit-style hot score per ranking dei post nel feed.
        Formula: log10(max(|likes - dislikes|, 1)) + sign(likes - dislikes) * (t - t0) / 45000
        Incorporata anche componente reposts come moltiplicatore di engagement.
        """
        likes = post.get("likes", 0)
        dislikes = post.get("dislikes", 0)
        reposts = post.get("reposts", 0)
        # Reposts contribuiscono come likes (amplificano la narrativa)
        effective_score = (likes + reposts * 2) - dislikes
        magnitude = max(abs(effective_score), 1)
        sign = 1 if effective_score > 0 else (-1 if effective_score < 0 else 0)
        t = post.get("timestamp", time.time())
        t0 = 1700000000  # epoch di riferimento ~ nov 2023
        return math.log10(magnitude) + sign * (t - t0) / 45000

    @staticmethod
    def _rank_feed_by_hot_score(feed: list[dict], top_n: int = 20) -> list[dict]:
        """Ordina il feed per hot_score decrescente e restituisce i top_n post."""
        if not feed:
            return []
        scored = [(SimulationEngine._compute_hot_score(p), p) for p in feed]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:top_n]]

    @staticmethod
    def _compute_opinion_entropy(agents: list[Agent]) -> float:
        """
        Measure diversity of opinions using Shannon entropy.
        Low entropy = convergence (everyone thinks the same).
        High entropy = chaotic (no consensus forming).
        """
        if not agents:
            return 1.0
        # Bucket opinion strengths into 5 bins
        buckets = [0] * 5
        for agent in agents:
            idx = min(4, int(agent.opinion_strength * 5))
            buckets[idx] += 1
        total = len(agents)
        entropy = 0.0
        for count in buckets:
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p)
        # Normalize to [0, 1]
        return entropy / math.log2(5) if entropy > 0 else 0.0

    @staticmethod
    def _compute_polarization(agents: list[Agent]) -> float:
        """
        Polarization: bimodal distribution of opinion strengths.
        Returns 0 (uniform) to 1 (two opposing camps).
        """
        if len(agents) < 2:
            return 0.0
        strengths = [a.opinion_strength for a in agents]
        mean = sum(strengths) / len(strengths)
        # Bimodality coefficient approximation
        variance = sum((x - mean) ** 2 for x in strengths) / len(strengths)
        return min(1.0, variance * 4)

    async def _open_kb(self, state: SimulationState):
        """La KB del progetto; False se vuota o inutilizzabile (niente KB per la simulazione),
        None se Chroma non risponde (si riprova al round dopo)."""
        from ..memory.knowledge_base import ProjectKnowledgeBase

        # Host e porta qui, nel thread del loop: nel thread di Chroma non c'e' l'app context Flask
        host, port, token = chroma_settings()

        def _open():
            kb = ProjectKnowledgeBase(state.project_id, host=host, port=port, token=token)
            return kb, kb.count()

        started = time.monotonic()
        try:
            kb, count = await run_chroma("kb_open", _open, timeout=Config.CHROMA_KB_OP_TIMEOUT)
        except Exception as e:
            if is_outage(e):
                emit = log.debug if isinstance(e, ChromaSkipped) else log.warning
                emit("kb_retrieve_failed", sim_id=state.simulation_id, project_id=state.project_id,
                     op="open", error=error_text(e), ms=round((time.monotonic() - started) * 1000))
                return None
            log.warning("kb_init_failed", error=str(e))
            return False
        # KB vuota: una sola warning per simulazione e nessun retrieval per-agente
        if count == 0:
            log.warning("kb_empty", project_id=state.project_id, sim_id=state.simulation_id)
            return False
        return kb

    async def _seed_memories(self, agents: list[Agent]):
        """Pre-populate each agent's memory with their persona knowledge.

        Al massimo MEMORY_SEED_CONCURRENCY agenti alla volta. Un seed fallito lascia l'agente senza
        memoria iniziale (memory_store_failed con l'errore): la simulazione prosegue.
        """
        sem = asyncio.Semaphore(self.MEMORY_SEED_CONCURRENCY)

        async def _seed(agent: Agent) -> bool:
            async with sem:
                return await agent.memory.seed_from_persona(
                    persona_summary=f"{agent.persona.background} Communication style: {agent.persona.communication_style}",
                    beliefs=agent.persona.core_beliefs,
                )

        started = time.monotonic()
        results = await asyncio.gather(*(_seed(agent) for agent in agents), return_exceptions=True)
        # seed_from_persona ritorna False se Chroma non ha salvato; un errore arriva come eccezione
        failures = [r for r in results if r is False or isinstance(r, BaseException)]
        elapsed_ms = round((time.monotonic() - started) * 1000)
        if failures:
            log.warning("memories_seed_failed", failed=len(failures), agents=len(agents), ms=elapsed_ms)
        if len(failures) < len(agents):
            log.info("memories_seeded", agents=len(agents) - len(failures), ms=elapsed_ms)

    async def _update_agent_opinions(self, state: SimulationState, round_num: int):
        """
        Chiede a ciascun agente attivo di sintetizzare la propria opinione corrente
        sulla base dei post che ha scritto. Aggiorna current_opinion (testo) e
        opinion_strength (0-1) dell'agente.
        """
        import asyncio as _asyncio

        # Filtra agenti che hanno postato almeno un contenuto
        agents_to_update = [a for a in state.agents if getattr(a, "posts_made", 0) > 0]
        if not agents_to_update:
            return
        # The change is usually already in the subject card: repeated only when it is not there
        change = state.change_tested or state.topic
        in_card = bool(state.change_tested) and state.change_tested in state.subject_card
        change_line = "" if in_card else f"Change being tested: {change}\n"
        stance_seen = {"support": 0, "neutral": 0, "oppose": 0, "unparsed": 0}

        async def _one(agent):
            # Recupera gli ultimi 3 post di questo agente dal feed globale
            own_posts = [
                p.get("content", "") for p in state.social_feed[-200:]
                if p.get("author_id") == agent.agent_id
            ][-3:]
            if not own_posts:
                return "no_recent_posts"
            posts_block = "\n".join(f"- {trim_excerpt(p, 200)}" for p in own_posts)

            # Prompt differenziato per adversari: rinforza il ruolo critico invece di rivalutare neutralmente
            if getattr(agent, "is_adversarial", False):
                fears_txt = ", ".join(getattr(agent.persona, "fears", []) or []) or "none specified"
                system = (
                    f"You are {agent.persona.name}, {agent.persona.role}. "
                    f"You are a DELIBERATE CRITICAL VOICE in the simulation. "
                    f"Your specific fears: {fears_txt}. "
                    f"Your task is NOT to re-evaluate your position neutrally — "
                    f"your task is to keep or strengthen your critical angle "
                    f"on the topic, anchored to your fears and your core_beliefs, "
                    f"NOT to the consensus of the feed."
                )
            else:
                system = (
                    f"You are {agent.persona.name}, {agent.persona.role}. "
                    f"You are summarising your current opinion on the topic of the simulation."
                )
            user = with_directive(
                f"{state.subject_block}"
                f"Topic: {state.topic}\n"
                f"{change_line}\n"
                f"Your latest posts:\n{posts_block}\n\n"
                f"Reply ONLY with valid JSON (no markdown, no extra text):\n"
                f"{{\n"
                f'  "opinion": "your current opinion in 1 sentence, max 150 characters",\n'
                f'  "strength": 0.0,\n'
                f'  "stance": "{STANCE_ENUM}"\n'
                f"}}\n"
                f"strength is a number from 0.0 (very unsure) to 1.0 (strongly convinced). {STANCE_DEFINITION}",
                state.language,
            )

            try:
                resp = await self._llm.complete(
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    tier="fast",
                    temperature=0.4,
                    max_tokens=150,
                )
                failure = reply_failure(resp)
                data = None if failure else parse_json_object(resp, repair_fields=("opinion",))
                if data is None:
                    outcome = failure or OUTCOME_PARSE_FAILED
                    log.debug(
                        "opinion_reply_skipped",
                        agent=agent.agent_id,
                        outcome=outcome,
                        **llm_log_fields(resp),
                    )
                    return outcome
                new_opinion = str(data.get("opinion", "")).strip()[:280]
                new_strength = float(data.get("strength", agent.opinion_strength))
                new_strength = max(0.0, min(1.0, new_strength))
                # ADVERSARIAL_STRENGTH_FLOOR: impedisce l'ammorbidimento per osmosi nel feed
                if getattr(agent, "is_adversarial", False):
                    new_strength = max(new_strength, 0.65)
                if new_opinion:
                    agent.current_opinion = new_opinion
                agent.opinion_strength = new_strength
                # Missing or unknown stance: neutral, counted as unparsed
                if not record_stance(agent, data.get("stance"), round_num):
                    stance_seen["unparsed"] += 1
                stance_seen[agent.stance] += 1
                return "updated"
            except Exception as e:
                log.debug("opinion_update_skip", agent=agent.agent_id, error=str(e)[:80])
                return "errors"

        # Esegui in parallelo con concorrenza limitata per non saturare il provider
        sem = _asyncio.Semaphore(8)

        async def _bounded(a):
            async with sem:
                return await _one(a)

        outcomes = await _asyncio.gather(*[_bounded(a) for a in agents_to_update], return_exceptions=True)
        log.info(
            "opinions_refresh",
            round=round_num,
            agents=len(agents_to_update),
            updated=outcomes.count("updated"),
            empty=outcomes.count(OUTCOME_EMPTY),
            truncated=outcomes.count(OUTCOME_TRUNCATED),
            parse_failed=outcomes.count(OUTCOME_PARSE_FAILED),
            errors=sum(o == "errors" or isinstance(o, Exception) for o in outcomes),
            no_recent_posts=outcomes.count("no_recent_posts"),
            stance_support=stance_seen["support"],
            stance_neutral=stance_seen["neutral"],
            stance_oppose=stance_seen["oppose"],
            stance_unparsed=stance_seen["unparsed"],
        )

    def _llm_identity(self, tier: str) -> tuple[str, str]:
        """Ritorna (provider, model) del client della simulazione, per i log."""
        config = getattr(self._llm, "config", None)
        if config is not None:  # MultiProviderLLM
            return config.provider, self._llm._model_for_tier(tier)
        return "groq", getattr(self._llm, "_models", {}).get(tier, "unknown")  # LLMClient

    async def _inject_diversity_events(self, state: SimulationState):
        """
        Inject a disruptive external event to prevent convergence.
        This is the 'God's-eye' injection that MiroFish allows manually —
        here it happens automatically when diversity collapses.
        """
        # Senza scheda (simulazioni senza population_spec) resta solo il topic
        subject_card = state.subject_card or state.topic
        prompt = with_directive(_DIVERSITY_EVENT_PROMPT.format(subject_card=subject_card), state.language)
        provider, model = self._llm_identity("fast")
        # L'evento e' accessorio: un errore LLM qui non deve interrompere la simulazione
        try:
            event = await self._llm.complete(
                [{"role": "user", "content": prompt}],
                tier="fast",
                temperature=0.9,
                max_tokens=160,
            )
        except Exception as e:
            # tenacity avvolge l'errore reale in RetryError
            last_attempt = getattr(e, "last_attempt", None)
            cause = last_attempt.exception() if last_attempt else e
            log.warning(
                "diversity_event_failed",
                round=state.current_round,
                model=model,
                provider=provider,
                error=str(cause)[:300],
            )
            return
        failure = reply_failure(event)
        if failure:
            log.warning(
                "diversity_event_empty" if failure == OUTCOME_EMPTY else "diversity_event_truncated",
                round=state.current_round,
                model=model,
                provider=provider,
                **llm_log_fields(event),
            )
            return
        data = parse_json_object(event, repair_fields=("event",))
        news = data.get("event") if data else None
        rejection = (
            OUTCOME_PARSE_FAILED if data is None
            else diversity_event_rejection(news, subject_card, state.subject_homonyms)
        )
        if rejection:
            log.warning(
                "diversity_event_rejected",
                round=state.current_round,
                model=model,
                provider=provider,
                reason=rejection,
                preview=str(news or event)[:120],
                **llm_log_fields(event),
            )
            return
        news = news.strip()
        disruption = {
            "post_id": f"SYSTEM_{state.current_round}",
            "round": state.current_round,
            "author_id": "SYSTEM",
            "author_name": t(state.language, "feed.breaking_author"),
            "author_role": "system",
            "action": "ANNOUNCE",
            "content": f"{t(state.language, 'feed.breaking_prefix')} {news}",
            "timestamp": time.time(),
            # Patch I: coerenza con engagement infrastructure (Patch A/H)
            "likes": 0,
            "dislikes": 0,
            "reposts": 0,
        }
        state.social_feed.append(disruption)
        # Patch I: registra anche il disruption nell'aggregato engagement
        state.post_engagement[disruption["post_id"]] = {
            "post_id": disruption["post_id"],
            "round": disruption["round"],
            "author_id": disruption["author_id"],
            "author_name": disruption["author_name"],
            "content_preview": trim_excerpt(disruption.get("content") or "", 200),
            "action": "ANNOUNCE",
            "likes": 0,
            "dislikes": 0,
            "reposts": 0,
        }
        log.info("diversity_injected", round=state.current_round, disruption_event=news[:80])

    def _emit_round_event(self, state: SimulationState, round_result: SimulationRound):
        data = {
            "round": round_result.round_num,
            "total_rounds": state.total_rounds,
            "actions": round_result.actions[:10],  # send sample
            "entropy": round_result.opinion_entropy,
            "polarization": round_result.polarization_score,
            "total_posts": state.total_posts,
        }
        # Pub/sub per WebSocket
        self._emit_event(state.simulation_id, "round_complete", data)
        # SET per polling HTTP — sovrascrive sempre l'ultimo round
        try:
            self._redis.setex(
                f"sim:{state.simulation_id}:latest_round",
                300,  # TTL 5 minuti
                __import__("json").dumps(data),
            )
        except Exception as e:
            log.warning("redis_set_error", error=str(e))

    def _emit_event(self, simulation_id: str, event_type: str, data: dict):
        """Publish event to Redis channel for WebSocket relay."""
        try:
            channel = f"sim:{simulation_id}:events"
            payload = json.dumps({"type": event_type, "data": data})
            self._redis.publish(channel, payload)
        except Exception as e:
            log.warning("redis_emit_error", error=str(e))
