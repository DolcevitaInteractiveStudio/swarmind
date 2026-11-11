"""
SwarMind Agent

Each agent has:
  - A rich persona (personality traits, beliefs, role, emotional state)
  - A ChromaDB memory collection (episodic + semantic)
  - A Groq-powered decision engine
  - Social graph (who they follow/trust/distrust)
  - Opinion vector (changes over simulation rounds)

Key improvement over MiroFish:
  - Mandatory diversity injection (prevents herd convergence)
  - Opinion entropy tracking
  - Emotional state machine
  - Two-tier memory (short-term context window + long-term ChromaDB)
"""
from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from ..core.i18n import DEFAULT_LANGUAGE, language_directive, t, with_directive
from ..core.llm import get_llm
from ..core.llm_response import llm_log_fields
from ..memory.agent_memory import AgentMemory
from .response_parser import OUTCOME_OK, parse_agent_reply, parse_json_object
from .stance import SPAWN_ROUND, STANCE_ENUM, record_stance

log = structlog.get_logger()

# Personality axes — Big Five + domain-specific
PERSONALITY_AXES = [
    "openness",         # 0=closed, 1=very open to new ideas
    "conscientiousness", # 0=impulsive, 1=very disciplined
    "extraversion",     # 0=introverted, 1=very extroverted
    "agreeableness",    # 0=antagonistic, 1=very cooperative
    "neuroticism",      # 0=stable, 1=very anxious/emotional
    "risk_appetite",    # 0=risk-averse, 1=risk-seeking
    "trust_institutions", # 0=cynical, 1=trusts authorities
    "influence_susceptibility", # 0=stubborn, 1=easily influenced
]

PERSONA_SYSTEM = """You are generating a realistic persona for a multi-agent simulation.
Given an entity from a knowledge graph, create a detailed, UNIQUE character.

Return ONLY valid JSON with this schema:
{
  "name": "full name or label",
  "role": "their primary role/occupation",
  "background": "2-3 sentences of backstory",
  "personality": {
    "openness": 0.0-1.0,
    "conscientiousness": 0.0-1.0,
    "extraversion": 0.0-1.0,
    "agreeableness": 0.0-1.0,
    "neuroticism": 0.0-1.0,
    "risk_appetite": 0.0-1.0,
    "trust_institutions": 0.0-1.0,
    "influence_susceptibility": 0.0-1.0
  },
  "core_beliefs": ["belief 1", "belief 2", "belief 3"],
  "motivations": ["motivation 1", "motivation 2"],
  "fears": ["fear 1", "fear 2"],
  "communication_style": "formal|casual|aggressive|passive|analytical|emotional",
  "initial_opinion_on_topic": "their starting view on the simulation topic (1-2 sentences)",
  "opinion_strength": 0.0-1.0,
  "emotional_state": "neutral|anxious|optimistic|angry|curious|skeptical"
}

Make the personality DIVERSE — do not default to moderate values. Use the full range."""


_ADVERSARIAL_ENRICHMENT_SYSTEM = """You are an expert in stakeholder simulations. You are given the name and role of a critical voice (adversarial persona) and the topic of the simulation.

Your task is to enrich the persona with realistic details, so that it becomes a credible critical voice specific to {CONTEXT}.

Return ONLY valid JSON with this schema (no markdown, no extra text):
{
  "background": "2-3 sentences of backstory specific to the role and to {CONTEXT}",
  "core_beliefs": ["critical belief 1", "critical belief 2", "critical belief 3"],
  "motivations": ["motivation 1", "motivation 2"],
  "fears": ["fear 1", "fear 2"],
  "communication_style": "direct|analytical|emotional|pragmatic|investigative|strategic|technical",
  "initial_opinion_on_topic": "the initial critical opinion on the topic, in 1-2 sentences",
  "opinion_strength": 0.7,
  "initial_stance": "STANCE_ENUM_PLACEHOLDER",
  "emotional_state": "skeptical|betrayed|probing|weary|challenged|critical_neutral"
}

initial_stance is the persona's position on the change being tested (the change in the subject card, or the
topic without a card): support, neutral (undecided or mixed) or oppose.

The persona MUST be critical or skeptical about the topic of the simulation. It must not be neutral or enthusiastic. Use language credible for the stated role. {CONTEXT_RULE}

Write the persona in your own words, in the language required by the final instruction: do not copy sentences of the topic or the subject card. The background and beliefs may describe the persona's experience, but must not contain specific numbers, dates, company events or statistics that are not in the input."""

# Italian-market guidance kept for Italian simulations; English ones use the subject's own market
_ENRICHMENT_CONTEXT = {
    "it": ("the Italian context", "Be specific to the Italian context (do not trivially translate US clichés)."),
    "en": ("the subject's market", "Be specific to the subject's market (do not fall back on generic clichés)."),
}


def adversarial_enrichment_system(language: str) -> str:
    """System prompt of the enrichment call: English, with the market guidance of the language."""
    context, rule = _ENRICHMENT_CONTEXT.get(language, _ENRICHMENT_CONTEXT["en"])
    return (_ADVERSARIAL_ENRICHMENT_SYSTEM.replace("{CONTEXT_RULE}", rule).replace("{CONTEXT}", context)
            .replace("STANCE_ENUM_PLACEHOLDER", STANCE_ENUM))


@dataclass
class AgentPersona:
    name: str
    role: str
    background: str
    personality: dict[str, float]
    core_beliefs: list[str]
    motivations: list[str]
    fears: list[str]
    communication_style: str
    initial_opinion: str
    opinion_strength: float
    emotional_state: str


@dataclass
class Agent:
    agent_id: str
    entity_id: str
    entity_type: str
    persona: AgentPersona
    memory: AgentMemory
    simulation_id: str

    # Dynamic state (changes per round)
    current_opinion: str = ""
    opinion_strength: float = 0.5
    emotional_state: str = "neutral"
    social_connections: list[str] = field(default_factory=list)
    posts_made: int = 0
    influenced_by: list[str] = field(default_factory=list)
    is_adversarial: bool = False
    language: str = DEFAULT_LANGUAGE  # simulation language: posts and opinions are written in it
    # Position on the change being tested (agents/stance.py): None until measured. stance_history has one
    # {"round", "stance"} entry per measurement: round 0 at spawn, then each opinion refresh.
    stance: str | None = None
    stance_history: list[dict] = field(default_factory=list)
    _llm: object = field(default=None, repr=False, compare=False)

    async def decide_action(
        self,
        environment_context: str,
        available_actions: list[str],
        recent_feed: list[dict],
        round_num: int,
        kb_context: str = "",
    ) -> dict:
        """
        Given the current environment, decide what action to take this round.
        Returns: {"action": str, "content": str, "target_agent_id": str|None}
        """
        llm = self._llm or get_llm()

        try:
            recent_memories = await self.memory.get_recent(n=5)
        except Exception:
            recent_memories = []
        memory_context = "\n".join(
            [f"- {m['content']}" for m in recent_memories]
        ) or "No recent memories."

        # Build feed summary (max 5 items to save tokens)
        # Patch E: include short_id (P1, P2...) e contatori engagement per
        # permettere LIKE/DISLIKE/REPOST su post esistenti.
        def _fmt_post(item: dict) -> str:
            sid = item.get("_short_id", "?")
            author = item.get("author_name") or item.get("author", "?")
            content = (item.get("content") or "")[:200]
            likes = item.get("likes", 0)
            dislikes = item.get("dislikes", 0)
            reposts = item.get("reposts", 0)
            return f"  [{sid}] {author} (like:{likes} dislike:{dislikes} repost:{reposts}): {content}"
        feed_summary = "\n".join(
            _fmt_post(item) for item in recent_feed[:5]
        ) or "No recent posts."

        # Rinforzo identity per adversari: evita che si facciano assorbire dal frame dominante
        adversarial_reinforcement = ""
        if getattr(self, "is_adversarial", False):
            fears_txt = ", ".join(getattr(self.persona, "fears", []) or []) or "none specified"
            motivations_txt = ", ".join(getattr(self.persona, "motivations", []) or []) or "bringing critical clarity"
            adversarial_reinforcement = f"""
====================================================================
SPECIAL ROLE - DELIBERATELY CRITICAL VOICE:
You were chosen to bring a CRITICAL and DISTINCT point of view.
You are not here to join the consensus. You are here to bring out what the others
are not seeing.

YOUR SPECIFIC FEARS (use them as a lens when you judge the topic):
{fears_txt}

YOUR MOTIVATIONS (what drives you in the debate):
{motivations_txt}

ADDITIONAL RULES FOR YOUR VOICE:
A. Do NOT align with the dominant frame of the feed. If everyone repeats the same heuristic
   (e.g. "20 euros per tour is sustainable"), question that heuristic itself instead of
   joining the chorus.
B. ALWAYS anchor yourself to YOUR core_beliefs and specific fears, NOT to the themes of the feed.
   The feed is the object of your criticism, not your reference.
C. Speak from YOUR specific role ({self.persona.role}). If your role is about
   finance, talk about finance. If it is about operations, talk about operations.
   Do NOT move onto technical/emotional ground that is not yours.
D. Ask uncomfortable questions, raise objections, ask for evidence. Your tone is
   {self.emotional_state}, not enthusiastic.
E. If the others are building consensus, your task is to break that consensus
   with a substantive objection that comes from YOUR angle.
F. Your objection comes from your own reasoning and experience, in your own words: do not echo
   phrases from the context or the feed, and do not back it with invented figures, dates or
   company events.
====================================================================
"""

        system_prompt = f"""{adversarial_reinforcement}You are {self.persona.name}, {self.persona.role}.

PERSONALITY: {json.dumps(self.persona.personality)}
BACKGROUND: {self.persona.background}
BELIEFS: {", ".join(self.persona.core_beliefs)}
COMMUNICATION STYLE: {self.persona.communication_style}
EMOTIONAL STATE: {self.emotional_state}
YOUR OPINION: {self.current_opinion}
OPINION STRENGTH: {self.opinion_strength:.2f} (0=unsure, 1=convinced)
RECENT MEMORY:
{memory_context}

RULES:
1. ALWAYS answer in the first person as {self.persona.name}.
2. Your opinion MUST reflect your background — do NOT copy the others.
3. If others have already said the same thing, CHALLENGE them or add a DIFFERENT point.
4. If opinion_strength > 0.7 you are decided and do not let yourself be influenced.
5. If opinion_strength < 0.3 you are doubtful, you ask questions.
6. ALWAYS bring a perspective tied to your role: {self.persona.role}.
7. If there are FACTS FROM THE DOMAIN, ANCHOR your post to them - do not improvise.
8. If the context contains a SUBJECT CARD, that is the subject: do not reinterpret it and do not confuse it with homonyms.
9. Speak in your own words, in the language required by the final instruction. Paraphrase what you read in
   the context (facts from the domain, subject card, feed): never copy its sentences or expressions, with or
   without quotation marks. The only thing you may quote as written is a product or brand name.
10. Know only what someone in your role could plausibly know: no internal documents, studies or figures
   that a person in your position would not have seen.
11. Opinions and personal experience are welcome, but do not state specific numbers, dates, events of
   companies or statistics that are not in the context, and never present an invented fact as true."""

        kb_block = f"""RELEVANT FACTS FROM THE DOMAIN (ground your post in them, in your own words):
{kb_context}

""" if kb_context else ""

        user_prompt = f"""{kb_block}SIMULATION CONTEXT (Round {round_num}):
{environment_context}

RECENT SOCIAL FEED (sorted by engagement):
{feed_summary}

AVAILABLE ACTIONS: {", ".join(available_actions)}

Act as {self.persona.name} ({self.persona.role}).

CHOOSE THE MOST APPROPRIATE ACTION — you do not always have to write a post:
- CREATE_POST: when you have something NEW and distinctive to add to the debate.
- LIKE: if an existing post (e.g. P1, P2) already expresses your thinking well; amplify it instead of repeating it. Give target_post_id.
- DISLIKE: if you substantially disagree with an existing post. Give target_post_id.
- REPOST: if a post deserves to be relaunched with a comment of yours. Give target_post_id AND content.
- DO_NOTHING: if you have nothing useful to add this round. Better silent than repetitive.

When you write a post (CREATE_POST or REPOST):
- Ground your post in the facts from the domain above, in your own words: you may name concrete
  products and brands and use the figures given there, but do not copy its sentences.
- Do NOT repeat what others have said.
- Bring YOUR UNIQUE point of view based on your role.
- Minimum 25 characters, maximum 280.

Reply ONLY with valid JSON (no markdown):
{{
  "action": "one of the available actions (CREATE_POST, LIKE, DISLIKE, REPOST, DO_NOTHING, etc.)",
  "content": "text of the post for CREATE_POST or REPOST, otherwise an empty string",
  "target_post_id": "P1/P2/... for LIKE/DISLIKE/REPOST, otherwise null",
  "reasoning": "short internal reasoning",
  "opinion_shift": 0.0,
  "emotional_shift": null,
  "target_agent": null
}}"""
        user_prompt = with_directive(user_prompt, self.language)

        response = await llm.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tier="fast",
            temperature=0.8 + (self.persona.personality.get("neuroticism", 0.5) * 0.3),
            max_tokens=512,
            json_mode=False,
        )

        log.debug(
            "agent_response_raw",
            agent=self.agent_id,
            resp=repr(response[:100]) if response else "EMPTY",
            **llm_log_fields(response),
        )
        # Una risposta inutilizzabile diventa DO_NOTHING: mai testo di ripiego nel feed
        action_data = parse_agent_reply(response, available_actions)
        if action_data["response_outcome"] != OUTCOME_OK:
            log.warning(
                "agent_response_dropped",
                agent=self.agent_id,
                round=round_num,
                outcome=action_data["response_outcome"],
                preview=(response or "")[:100],
                **llm_log_fields(response),
            )

        # Update agent state
        shift = float(action_data.get("opinion_shift", 0.0))
        susceptibility = self.persona.personality.get("influence_susceptibility", 0.5)
        self.opinion_strength = max(
            0.0, min(1.0, self.opinion_strength + shift * susceptibility)
        )

        if action_data.get("emotional_shift"):
            self.emotional_state = action_data["emotional_shift"]

        # Store action in memory
        if action_data.get("content"):
            try:
                await self.memory.store(
                    content=f"[Round {round_num}] I {action_data['action']}: {action_data['content'][:200]}",
                    metadata={"round": round_num, "action": action_data["action"]},
                )
            except Exception:
                pass
            self.posts_made += 1

        return action_data

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "name": self.persona.name,
            "role": self.persona.role,
            "personality": self.persona.personality,
            "communication_style": self.persona.communication_style,
            "background": self.persona.background,
            "core_beliefs": self.persona.core_beliefs,
            "motivations": self.persona.motivations,
            "fears": self.persona.fears,
            "current_opinion": self.current_opinion,
            "opinion_strength": self.opinion_strength,
            "emotional_state": self.emotional_state,
            "posts_made": self.posts_made,
            "is_adversarial": self.is_adversarial,
            "stance": self.stance,
            "stance_history": list(self.stance_history),
        }


class AgentFactory:
    """Spawns agents from knowledge graph entity seeds."""

    def __init__(self, llm=None):
        self._llm = llm or get_llm()

    async def spawn_agents(
        self,
        seeds: list[dict],
        simulation_id: str,
        sim_topic: str,
        diversity_temperature: float = 1.3,
        language: str = DEFAULT_LANGUAGE,
    ) -> list[Agent]:
        """Generate personas for all seeds in parallel, then instantiate agents."""

        # Generate personas in batch
        prompts = [
            [
                {"role": "system", "content": PERSONA_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Entity: {seed['label']} ({seed['type']})\n"
                        f"Description: {seed['description']}\n"
                        f"Connections: {', '.join(seed.get('connections', [])[:5])}\n"
                        f"Simulation topic: {sim_topic}\n\n"
                        f"Generate a unique, diverse persona. "
                        f"Diversity seed: {random.random():.4f}\n\n"
                        + language_directive(language)
                    ),
                },
            ]
            for seed in seeds
        ]

        log.info("spawning_agents", count=len(seeds), simulation_id=simulation_id)

        responses = await self._llm.batch_complete(
            prompts,
            tier="agent",
            temperature=diversity_temperature,
            max_tokens=1024,
            concurrency=15,
        )

        agents = []
        for seed, raw_persona in zip(seeds, responses):
            try:
                persona_data = json.loads(raw_persona)
            except json.JSONDecodeError:
                # Fallback minimal persona
                persona_data = {
                    "name": seed["label"],
                    "role": seed["type"].lower(),
                    "background": seed.get("description", t(language, "agent.unknown_background")),
                    "personality": {ax: random.random() for ax in PERSONALITY_AXES},
                    "core_beliefs": [t(language, "agent.fallback_belief_pragmatism"),
                                     t(language, "agent.fallback_belief_self_interest")],
                    "motivations": [t(language, "agent.fallback_motivation")],
                    "fears": [t(language, "agent.fallback_fear")],
                    "communication_style": "casual",
                    "initial_opinion_on_topic": t(language, "agent.no_opinion_yet"),
                    "opinion_strength": 0.5,
                    "emotional_state": "neutral",
                }

            persona = AgentPersona(
                name=persona_data.get("name", seed["label"]),
                role=persona_data.get("role", "citizen"),
                background=persona_data.get("background", ""),
                personality=persona_data.get(
                    "personality", {ax: 0.5 for ax in PERSONALITY_AXES}
                ),
                core_beliefs=persona_data.get("core_beliefs", []),
                motivations=persona_data.get("motivations", []),
                fears=persona_data.get("fears", []),
                communication_style=persona_data.get("communication_style", "casual"),
                initial_opinion=persona_data.get("initial_opinion_on_topic", ""),
                opinion_strength=float(persona_data.get("opinion_strength", 0.5)),
                emotional_state=persona_data.get("emotional_state", "neutral"),
            )

            agent_id = str(uuid.uuid4())[:8]
            memory = AgentMemory(
                agent_id=agent_id,
                simulation_id=simulation_id,
            )

            agent = Agent(
                agent_id=agent_id,
                entity_id=seed.get("entity_id") or seed.get("id", "unknown"),
                entity_type=seed.get("type", "PERSON"),
                persona=persona,
                memory=memory,
                simulation_id=simulation_id,
                current_opinion=persona.initial_opinion,
                opinion_strength=persona.opinion_strength,
                emotional_state=persona.emotional_state,
                language=language,
            )
            agents.append(agent)

        log.info("agents_spawned", count=len(agents), simulation_id=simulation_id)
        return agents

    async def spawn_adversarial_agents(
        self,
        adversarial_specs: list[dict],
        simulation_id: str,
        sim_topic: str,
        subject_card: str = "",
        language: str = DEFAULT_LANGUAGE,
    ) -> list[Agent]:
        """
        Crea agenti avversari da specifiche strutturate.

        Ogni spec puo' essere:
          - Completa: ha name, role, background, core_beliefs, fears,
            communication_style, opinion_strength, emotional_state
            -> costruisce l'Agent senza chiamate LLM
          - Minimale: ha solo name e role (es. custom_adversaries dall'utente)
            -> fa 1 chiamata LLM per arricchire la persona
        """
        if not adversarial_specs:
            return []

        # Separa specs complete da quelle minimali
        complete_specs = []
        minimal_specs = []
        for spec in adversarial_specs:
            has_full = all(k in spec for k in ("background", "core_beliefs", "communication_style"))
            if has_full:
                complete_specs.append(spec)
            else:
                minimal_specs.append(spec)

        # Arricchisci le minimali con 1 chiamata LLM ciascuna (batch)
        enriched_from_minimal = []
        if minimal_specs:
            subject_block = f"SUBJECT CARD (do not reinterpret it):\n{subject_card}\n" if subject_card else ""
            system = adversarial_enrichment_system(language)
            prompts = [
                [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": with_directive(
                            f"Critical voice: {spec.get('name', t(language, 'agent.fallback_critic_name'))}\n"
                            f"Role: {spec.get('role', t(language, 'agent.fallback_critic_role'))}\n"
                            f"Simulation topic: {sim_topic}\n"
                            f"{subject_block}\n"
                            f"Generate a complete persona following the JSON schema in the system prompt.",
                            language,
                        ),
                    },
                ]
                for spec in minimal_specs
            ]
            responses = await self._llm.batch_complete(
                prompts,
                tier="agent",
                temperature=0.8,
                max_tokens=1024,
                concurrency=5,
            )
            for spec, raw in zip(minimal_specs, responses):
                data = parse_json_object(raw, repair_fields=("background", "initial_opinion_on_topic"))
                if data is None:
                    # Niente persona inventata: la voce viene saltata e resta traccia nei log
                    log.warning(
                        "adversarial_enrichment_failed",
                        simulation_id=simulation_id,
                        name=spec.get("name"),
                        preview=(raw or "")[:100],
                        **llm_log_fields(raw),
                    )
                    continue
                merged = {**spec, **data, "name": spec.get("name"), "role": spec.get("role"),
                          "initial_stance": data.get("initial_stance")}
                enriched_from_minimal.append(merged)

        all_specs = complete_specs + enriched_from_minimal
        agents = []
        for spec in all_specs:
            persona = AgentPersona(
                name=spec.get("name", t(language, "agent.fallback_critic_name")),
                role=spec.get("role", t(language, "agent.fallback_critic_role")),
                background=spec.get("background", ""),
                personality=spec.get("personality", {ax: 0.5 for ax in PERSONALITY_AXES}),
                core_beliefs=spec.get("core_beliefs", []),
                motivations=spec.get("motivations", []),
                fears=spec.get("fears", []),
                communication_style=spec.get("communication_style", "direct"),
                initial_opinion=spec.get("initial_opinion_on_topic",
                                         t(language, "agent.fallback_initial_opinion", topic=sim_topic)),
                opinion_strength=float(spec.get("opinion_strength", 0.75)),
                emotional_state=spec.get("emotional_state", "skeptical"),
            )
            agent_id = str(uuid.uuid4())[:8]
            memory = AgentMemory(agent_id=agent_id, simulation_id=simulation_id)
            # Template personas: the stable key (same in every language); custom voices: the name
            safe_name = (spec.get("key") or spec.get("name", "adv") or "adv").lower().replace(" ", "_")[:40]
            agent = Agent(
                agent_id=agent_id,
                entity_id=f"adversarial:{safe_name}",
                entity_type="ADVERSARIAL",
                persona=persona,
                memory=memory,
                simulation_id=simulation_id,
                current_opinion=persona.initial_opinion,
                opinion_strength=persona.opinion_strength,
                emotional_state=persona.emotional_state,
                is_adversarial=True,
                language=language,
            )
            # Template personas written in the YAML have no stance: measured at the first refresh
            if "initial_stance" in spec:
                record_stance(agent, spec.get("initial_stance"), SPAWN_ROUND)
            agents.append(agent)

        log.info("adversarial_agents_spawned", count=len(agents), simulation_id=simulation_id,
                 from_complete=len(complete_specs), from_minimal=len(enriched_from_minimal))
        return agents
