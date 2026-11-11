"""PersonaGenerator: consuma una PopulationSpec e produce Agent istanziati.

Differenza chiave dal vecchio agent.py:spawn_agents:
  - VECCHIO: prompt riceve "Entity: <scheda video> (CONCEPT)", il LLM si inventa
    un "pricing strategist" cucendo persona umana su seed non-umano
  - NUOVO: prompt riceve Segment(role_description, key_attitudes,
    typical_motivations, typical_fears, communication_style) come CONSTRAINT
    HARD. Il LLM puo' variare nei dettagli individuali (nome, citta', eta'
    esatta, hobby) ma deve rispettare i tratti strutturali del segmento.

Componente standalone: testabile via CLI con un PopulationSpec JSON gia'
generato dallo Step 1, senza integrazione col resto della pipeline.
"""
from __future__ import annotations

import asyncio
import json
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from ..agents.agent import (
    Agent,
    AgentPersona,
    PERSONALITY_AXES,
)
from ..agents.stance import SPAWN_ROUND, STANCE_ENUM, record_stance
from ..core.i18n import normalize_language, with_directive
from ..core.llm import get_llm, get_llm_for_project
from ..memory.agent_memory import AgentMemory
from .demographer import PopulationSpec, Segment
from .integration import render_subject_card, subject_language
from .name_pool import sample_names

log = structlog.get_logger()


PERSONA_GENERATOR_SYSTEM = """You are generating a realistic individual persona
for a multi-agent simulation. The persona MUST belong to a specific stakeholder
segment defined upstream by a Demographer. Your job is to produce ONE individual
that fits the segment's structural traits, while varying in personal details.

CRITICAL CONSTRAINTS (MUST be respected):
- The persona's NAME is GIVEN to you in the user message - use it EXACTLY as provided
- The persona's INDIVIDUAL_ANGLE is GIVEN - incorporate it as their distinctive trait
- The persona's role MUST match the segment's role_description category
- Their core_beliefs MUST align with the segment's key_attitudes
- Their motivations MUST be drawn from typical_motivations of the segment
- Their fears MUST be drawn from typical_fears of the segment
- Their communication_style MUST follow the segment's communication_style

VARIABLE DETAILS (you decide these freely, varying across personas):
- specific age (within plausible range for the segment)
- specific city/region (consistent with segment geography hints)
- years of experience
- specific personal background details consistent with the GIVEN name and angle
- specific hobbies or side interests
- life events: ONLY the one in the INDIVIDUAL_ANGLE, if it has one. Do not add others the angle does
  not mention (no bonus, windfall, inheritance, pay rise, promotion, new job, move, wedding, birth):
  the other personas of the segment have different angles, and a shared life event makes the
  population look cloned
- the EXACT WORDING of their initial opinion - DO NOT use template phrases
  like {TEMPLATE_PHRASE} if other personas in the segment might use them.
  Vary opening, tone, register, sentence structure. The opinion must reflect
  THIS individual's angle, not the segment's generic stance.

Return ONLY valid JSON with this exact schema:
{
  "name": "full name realistic for the domain",
  "role": "specific role/occupation (must match segment)",
  "background": "2-3 sentences of personal background",
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
  "communication_style": "specific description matching segment style",
  "initial_opinion_on_topic": "their initial stance, written as if THEY said it",
  "opinion_strength": 0.0-1.0,
  "initial_stance": "STANCE_ENUM_PLACEHOLDER",
  "emotional_state": "neutral|anxious|enthusiastic|skeptical|frustrated|curious"
}

initial_stance is the persona's position on the change being tested (the change in SUBJECT, or the domain
without it): support, neutral (undecided or mixed) or oppose. It must match initial_opinion_on_topic.
opinion_strength is how firmly they hold it, not whether they approve.

{LANGUAGE_RULE}

CONSISTENCY: do NOT introduce traits that contradict the segment. If the segment
describes "skeptical accountants who fear hidden costs", do NOT produce an
enthusiastic risk-loving persona just for variety - vary the surface details
(name, age, city) but keep the structural profile faithful.
"""


# Without a simulation language (CLI tools): the language of the segment
_LANGUAGE_RULE_SEGMENT = """LANGUAGE: produce ALL human-readable text in the SAME LANGUAGE as the segment
description. If segment is in Italian, produce Italian. If in English, English."""
_LANGUAGE_RULE_SIMULATION = """LANGUAGE: produce ALL human-readable text in the language given by the final
instruction of the user message, even when the segment description is in another language."""
# Example of a template phrase, in the language the personas write in
_TEMPLATE_PHRASES = {"it": '"secondo me è un errore"', "en": '"in my opinion it is a mistake"'}


def persona_generator_system(language: str | None, phrase_language: str) -> str:
    """System prompt: the language rule follows the simulation language, or the segment without one."""
    rule = _LANGUAGE_RULE_SIMULATION if normalize_language(language) else _LANGUAGE_RULE_SEGMENT
    phrase = _TEMPLATE_PHRASES.get(normalize_language(language) or phrase_language, _TEMPLATE_PHRASES["en"])
    return (PERSONA_GENERATOR_SYSTEM.replace("{LANGUAGE_RULE}", rule).replace("{TEMPLATE_PHRASE}", phrase)
            .replace("STANCE_ENUM_PLACEHOLDER", STANCE_ENUM))


@dataclass
class GenerationResult:
    """Risultato di una chiamata PersonaGenerator.run()."""
    agents: list[Agent] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)  # segment_id, reason

    @property
    def total(self) -> int:
        return len(self.agents)

    @property
    def by_segment(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for a in self.agents:
            sid = a.entity_id  # entity_id encodes segment_id (see below)
            seg = sid.split(":", 1)[1] if ":" in sid else sid
            out[seg] = out.get(seg, 0) + 1
        return out


class PersonaGenerator:
    """Genera Agent istanziati a partire da una PopulationSpec validata."""

    def __init__(
        self,
        llm=None,
        tier: str = "heavy",
        project_id: str | None = None,
        simulation_id: str = "step2-standalone",
        diversity_temperature: float = 1.1,
        language: str | None = None,
    ):
        """Init PersonaGenerator.

        Args:
            llm: client esplicito (per test con mock)
            tier: LLM tier per le chiamate (default 'agent', non 'heavy':
                  generiamo molte personas, una per agente, su tier
                  pi\u00f9 economico va benissimo perche' il ragionamento
                  di dominio l'ha gia' fatto il Demographer a monte)
            project_id: se passato, usa get_llm_for_project per rispettare
                        la configurazione provider/modello del progetto
            simulation_id: identifier per AgentMemory (puo' essere finto in
                           contesti di test standalone)
            diversity_temperature: temperatura LLM per variare i dettagli
                                   individuali tra personas dello stesso
                                   segmento (default 1.1)
            language: lingua della simulazione (en|it) delle personas.
                      None (tool CLI): la lingua del segmento
        """
        if llm is not None:
            self._llm = llm
        elif project_id:
            self._llm = get_llm_for_project(project_id)
        else:
            self._llm = get_llm()
        self._tier = tier
        self._simulation_id = simulation_id
        self._diversity_temperature = diversity_temperature
        self._language = normalize_language(language)

    async def run(
        self,
        spec: PopulationSpec,
        domain_context: str = "",
    ) -> GenerationResult:
        """Genera tutti gli agenti dalla PopulationSpec.

        Args:
            spec: PopulationSpec validata (output del Demographer)
            domain_context: testo opzionale che descrive il contesto di
                            dominio (entita', regolamenti, geografie,
                            competitor noti). Iniettato in ogni prompt
                            persona per dare riferimenti concreti senza
                            che il LLM debba inventarli. Vuoto = nessun
                            contesto (lo Step 2 standalone usa stringa vuota
                            o stub; nello Step 3 sara' estratto dal KG).

        Returns:
            GenerationResult con agenti istanziati + eventuali failure
        """
        log.info(
            "persona_generator_start",
            segments_count=len(spec.segments),
            total_agents=spec.total_agents,
            tier=self._tier,
            has_domain_context=bool(domain_context),
        )

        # Lingua del brief (subject.language del Demographer, altrimenti dedotta dal domain_summary):
        # decide il pool dei nomi, cioe' il mercato. La lingua dei testi e' self._language.
        language = subject_language(spec)
        system_prompt = persona_generator_system(self._language, language)
        subject_card = render_subject_card(spec, self._language)
        rng = random.Random()  # randomness per nomi + angles, no seed esterno

        # Pre-sample dei nomi: garantisce zero collisioni nome+cognome.
        # Il LLM ricevera' "Salvatore Pappalardo" come fatto, non come scelta.
        names = sample_names(
            n=spec.total_agents,
            language=language,
            female_ratio=0.4,
            rng=rng,
        )

        log.info(
            "persona_generator_names_sampled",
            count=len(names),
            language=language,
            unique=len(set(names)),
        )

        # Costruisce le richieste: una per ogni agente da generare
        # (segment ripetuto N volte = N personas dello stesso segmento)
        prompts: list[list[dict]] = []
        prompt_meta: list[Segment] = []
        name_idx = 0
        for seg in spec.segments:
            # Angles diversi dentro il segmento: nessuna coppia di personas con lo stesso evento di vita
            angles = self._angles_for_segment(rng, seg.count)
            for k in range(seg.count):
                assigned_name = names[name_idx]
                individual_angle = angles[k]
                prompts.append(self._build_prompt(
                    seg=seg,
                    domain_summary=spec.domain_summary,
                    domain_context=domain_context,
                    assigned_name=assigned_name,
                    individual_angle=individual_angle,
                    subject_card=subject_card,
                    system_prompt=system_prompt,
                ))
                prompt_meta.append(seg)
                name_idx += 1

        if not prompts:
            log.warning("persona_generator_empty_spec", spec=spec.to_dict())
            return GenerationResult()

        # Bypass batch_complete: serve json_mode=True che batch_complete
        # non supporta. Re-implementa la concorrenza qui con un semaforo,
        # chiamando complete() direttamente per ogni prompt.
        concurrency = 15
        sem = asyncio.Semaphore(concurrency)

        async def _one(msgs: list[dict]) -> str:
            async with sem:
                return await self._llm.complete(
                    messages=msgs,
                    tier=self._tier,
                    temperature=self._diversity_temperature,
                    max_tokens=1536,
                    json_mode=True,
                )

        log.info(
            "persona_generator_batch_dispatch",
            prompts_count=len(prompts),
            concurrency=concurrency,
            tier=self._tier,
            json_mode=True,
        )

        responses = await asyncio.gather(
            *[_one(p) for p in prompts],
            return_exceptions=False,
        )

        result = GenerationResult()
        for seg, raw in zip(prompt_meta, responses):
            try:
                agent = self._build_agent(seg, raw)
                result.agents.append(agent)
            except Exception as e:
                log.warning(
                    "persona_generator_agent_failed",
                    segment_id=seg.segment_id,
                    error=str(e),
                    raw_preview=(raw or "")[:200],
                )
                result.failures.append({
                    "segment_id": seg.segment_id,
                    "reason": str(e),
                })

        log.info(
            "persona_generator_done",
            agents_generated=result.total,
            failures=len(result.failures),
            by_segment=result.by_segment,
        )
        return result

    # ── Internal ──────────────────────────────────────────────────────────

    # Pool di "individual angles" che rompono la simmetria tra personas
    # dello stesso segmento. Pescati a caso, danno al LLM uno spunto di
    # individualizzazione concreto invece di lasciarlo collassare sul modo.
    # Valgono per qualsiasi settore e ruolo: il dominio arriva da segmento e soggetto,
    # un angle su software o sulla gestione di un'azienda sposterebbe la persona fuori dominio.
    # In inglese come il resto del prompt: la persona li scrive nella lingua della simulazione.
    _ANGLES_EN = [
        "has tried an alternative that did not deliver on its promises",
        "is new to this sector",
        "just made a major purchase and is watching their budget",
        "is going through a big change in life or work",
        "recently changed role or job",
        "had a bad experience with a company in this sector",
        "follows new things eagerly in their free time but is cautious when deciding",
        "comes from a different industry, new to this domain",
        "has 30+ years of domain experience",
        "makes decisions without consulting anyone",
        "lives in an area with plenty of alternatives",
        "lives in an isolated area with few alternatives",
        "is very loyal to their habits and choices",
        "has seen a similar change up close",
        "filed a formal complaint in the past",
        "is active in groups or associations tied to the sector",
        "has less money to spend than two years ago",
        "recently got a pay rise",
        "has little trust in what they read online",
        "lived abroad, open mindset",
    ]

    def _make_individual_angle(self, rng: random.Random) -> str:
        return rng.choice(self._ANGLES_EN)

    def _angles_for_segment(self, rng: random.Random, count: int) -> list[str]:
        """count angles all different within the segment (pescati senza reimmissione). Prima pescati con
        reimmissione: in un segmento di 10 personas due avevano spesso lo stesso evento di vita (lo stesso
        "bel bonus" ripetuto). Oltre la dimensione del pool si ricomincia da un nuovo giro mescolato."""
        out: list[str] = []
        while len(out) < count:
            pool = list(self._ANGLES_EN)
            rng.shuffle(pool)
            out.extend(pool)
        return out[:count]

    def _build_prompt(
        self,
        seg: Segment,
        domain_summary: str,
        domain_context: str,
        assigned_name: str,
        individual_angle: str,
        subject_card: str = "",
        system_prompt: str | None = None,
    ) -> list[dict]:
        """Costruisce il prompt per UNA persona del segmento dato.

        assigned_name e individual_angle sono pre-pescati dal caller per
        garantire diversita' deterministica (vedi sample_names + name_pool).
        Il LLM li riceve come dati, non come scelte.
        """
        ctx_block = (
            f"\nDOMAIN CONTEXT (for grounding, do not personify these):\n"
            f"{domain_context}\n"
            if domain_context else ""
        )
        subject_line = f"SUBJECT: {' '.join(subject_card.split())}\n" if subject_card else ""
        user_msg = (
            f"{subject_line}"
            f"DOMAIN: {domain_summary}\n\n"
            f"SEGMENT (constraint - must be respected):\n"
            f"  segment_id: {seg.segment_id}\n"
            f"  label: {seg.label}\n"
            f"  role_description: {seg.role_description}\n"
            f"  key_attitudes: {json.dumps(seg.key_attitudes, ensure_ascii=False)}\n"
            f"  typical_motivations: {json.dumps(seg.typical_motivations, ensure_ascii=False)}\n"
            f"  typical_fears: {json.dumps(seg.typical_fears, ensure_ascii=False)}\n"
            f"  communication_style: {seg.communication_style}\n"
            f"\nGIVEN NAME (use exactly): {assigned_name}\n"
            f"INDIVIDUAL ANGLE (this person's distinctive trait): {individual_angle}\n"
            f"{ctx_block}\n"
            f"Generate this individual persona. The name field MUST be "
            f"'{assigned_name}' verbatim. Build their background and opinion "
            f"around the individual angle, NOT around generic segment cliches."
        )
        if self._language:
            user_msg = with_directive(user_msg, self._language)
        return [
            {"role": "system", "content": system_prompt or persona_generator_system(self._language, "it")},
            {"role": "user", "content": user_msg},
        ]

    def _build_agent(self, seg: Segment, raw: str) -> Agent:
        """Parsa la risposta LLM e costruisce un Agent.

        Solleva eccezione se JSON invalido o campi obbligatori mancanti
        (intercettata dal caller per finire in failures).
        """
        data = json.loads(raw)

        # Sanity check: campi obbligatori
        for field_name in ("name", "role", "personality", "core_beliefs"):
            if field_name not in data:
                raise ValueError(f"missing required field: {field_name}")

        # Riempie eventuali assi personality mancanti con 0.5
        personality = data.get("personality", {})
        for ax in PERSONALITY_AXES:
            if ax not in personality:
                personality[ax] = 0.5

        persona = AgentPersona(
            name=data["name"],
            role=data["role"],
            background=data.get("background", ""),
            personality=personality,
            core_beliefs=data.get("core_beliefs", []),
            motivations=data.get("motivations", []),
            fears=data.get("fears", []),
            communication_style=data.get("communication_style", ""),
            initial_opinion=data.get("initial_opinion_on_topic", ""),
            opinion_strength=float(data.get("opinion_strength", 0.5)),
            emotional_state=data.get("emotional_state", "neutral"),
        )

        agent_id = str(uuid.uuid4())[:8]
        memory = AgentMemory(agent_id=agent_id, simulation_id=self._simulation_id)

        # entity_id codifica segment_id per audit/tracciabilita'
        entity_id = f"segment:{seg.segment_id}"

        agent = Agent(
            agent_id=agent_id,
            entity_id=entity_id,
            entity_type="PERSON",  # forzato: tutto cio' che esce dal PersonaGenerator E' PERSON
            persona=persona,
            memory=memory,
            simulation_id=self._simulation_id,
            current_opinion=persona.initial_opinion,
            opinion_strength=persona.opinion_strength,
            emotional_state=persona.emotional_state,
        )
        if self._language:
            agent.language = self._language
        # Missing or unknown: neutral, marked unparsed (counted in stance_initial at spawn)
        record_stance(agent, data.get("initial_stance"), SPAWN_ROUND)
        return agent
