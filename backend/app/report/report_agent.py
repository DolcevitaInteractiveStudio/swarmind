"""
SwarMind Report Agent

Uses a ReACT loop (Reason → Act → Observe) to:
  1. Query the simulation data with specialized tools
  2. Interview individual agents for qualitative insight
  3. Identify dominant narratives, consensus, and outliers
  4. Synthesize a structured prediction report

Tools available to the ReportAgent:
  - query_feed(filter)       → search simulation posts
  - interview_agent(id)      → get an agent's current view
  - get_opinion_distribution → histogram of opinions
  - get_top_influencers      → most-cited agents
  - get_emerging_topics      → topic clusters from posts
  - compute_consensus        → measure of agreement
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from ..core.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, normalize_language, t, t_value, with_directive
from ..core.llm import get_llm
from ..population.integration import render_subject_card
from ..simulation.engine import SimulationState
from ..utils.excerpt import trim_excerpt
from . import postprocess
from .sections import ALWAYS_SECTIONS, SECTION_DESCRIPTIONS, section_title
from .metrics import compute_all_debate_metrics
from .stance_metrics import compute_stance_metrics

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# SYSTEM PROMPT — anti-hallucination, data-anchored
# ---------------------------------------------------------------------------

# Titoli del report prima di "Narrative Stress-Test Report" / "Report di stress-test"
LEGACY_REPORT_TITLES = ("Prediction Report", "Report di Previsione")

REPORT_SYSTEM = """You are SwarMind's Report Agent — an analytical AI that synthesizes
multi-agent simulation data into structured prediction reports.

═══════════════════════════════════════════════
ABSOLUTE RULES — NEVER VIOLATE THESE
═══════════════════════════════════════════════
1. NEVER invent numbers, percentages, or statistics.
   Every number in your report MUST come from a tool OBSERVATION you received.
2. NEVER describe agent behaviour, opinions, or statements you did not observe
   via query_feed, interview_agent, or get_opinion_distribution.
3. If a tool returns no data, say "insufficient data" — do NOT fill the gap with guesses.
4. Every quantitative claim must be traceable: if you cannot point to the
   OBSERVATION that produced it, do not include it.
5. NO NUMERIC PROBABILITIES. Never give a scenario a probability, a percentage or a percentage
   range (no "65-75%", no "probability: 20%"): on a small simulation of LLM agents they are false
   precision. Rank scenarios only with a qualitative likelihood ({L_MOST} / {L_PLAUSIBLE} /
   {L_LESS}) and tie each one to the evidence (stance distribution, stance consensus and shift, quoted posts).

ANALYTICAL BIAS RULES — APPLY TO EVERY REPORT
═══════════════════════════════════════════════
6. SILENCE IS NOT A GAP. If a topic is not mentioned in the feed, do NOT interpret
   this as a weakness or missed opportunity. Absence of verbalization ≠ absence of value.
   Only flag a gap if agents explicitly express an unmet expectation.

7. NEGATIVE BENEFITS ARE REAL VALUE. Problems avoided, friction removed, and effort
   saved are systematically under-verbalized but highly valued by users. If agents praise
   convenience or ease, interpret this as strong positive signal — not generic enthusiasm.

8. DISTINGUISH PRE-PURCHASE ENTHUSIASM FROM POST-PURCHASE SATISFACTION.
   Simulation agents express pre-purchase opinions. Do NOT extrapolate these as
   predictions of post-purchase satisfaction or retention. State this limitation explicitly.

9. WEIGHT ANALYST NARRATIVES APPROPRIATELY. Discussions about margins, production
   costs, and competitive strategy come from analyst/journalist agents. These do NOT
   represent mainstream user sentiment. Clearly label the source type when citing these
   narratives and do not treat them as general market signals.

10. DO NOT INVENT RISKS FROM SILENCE. Only report risks that are explicitly evidenced
    by agent statements. If no agent mentions a risk (e.g. fitness use case, audio quality),
    do not introduce it as a finding. Stick strictly to what the data shows.

11. RECOMMENDATIONS MUST RESPECT PRODUCT MATURITY. Infer the product's maturity stage
    from the topic and prediction_requirement (concept / pre-launch / beta / live).
    Do NOT recommend actions that presuppose resources not yet available at that stage:
    no "publish case studies" for concept products, no "leverage existing testimonials"
    for pre-launch, etc. Recommendations must be actionable given the resources actually
    available at the stage described. When in doubt, prefer recommendations that do not
    assume unstated resources.

12. CONVICTION IS NOT APPROVAL. opinion_strength (and the conviction buckets of
    get_opinion_distribution: {BUCKETS}) measures how firmly an agent holds its position, NOT
    whether it approves: a critic with opinion_strength 0.9 sits in "{BUCKET_VERY_HIGH}". Never
    describe the buckets or a high mean opinion_strength as positive, favourable, approval or support
    (no "100% positive distribution"). An agent with high opinion_strength and a skeptical
    emotional_state is a "convinced critic": describe this pattern when it emerges.
    STANCE is measured separately: the "stance" block of compute_consensus gives each agent's position
    on the change being tested (support / neutral / oppose), natural agents and critical voices apart,
    with the stance consensus and the shift between first and last measurement. emotional_state is a
    tone label (enthusiastic, skeptical, ...), not a measure of approval: report its counts as tone only.

13. POPULATION TRANSPARENCY. The user prompt includes a POPULATION COMPOSITION
    block produced by the Demographer (persona-pipeline). When this block contains
    real data (not the "not available" placeholder), you MUST include in the
    {H_APPENDIX} a section titled "{H_POPULATION}" that:
    - quotes the domain_summary verbatim or close-paraphrases it
    - lists the segments with their labels, percentages, and counts
    - quotes or close-paraphrases the rationale, attributing it to the Demographer
    This is mandatory: the consultant reading the report needs to inspect and
    contest the population composition, not just the simulation outcome. If the
    block is the placeholder, omit the section entirely (do NOT fabricate data)
    and add a brief note in the {H_APPENDIX} that the composition was not recorded.

13. ENTROPY INTERPRETATION. Whenever you cite opinion_entropy, you MUST add its inline
    interpretation. The reading of this run is opinion_entropy_label of compute_consensus (the same
    reading is in the CONFIDENCE LEVEL block and in the metrics table): use it as is, everywhere, and
    never derive another one. For reference, the thresholds it comes from:
{ENTROPY_THRESHOLDS}
    Never write a bare number like "{L_ENTROPY}: 0.502" without its interpretation.
    Example: "{L_ENTROPY} 0.502 ({E_MID}) indicates that...".
    opinion_entropy is ONE value, the last round's, as returned by compute_consensus and in the
    CONFIDENCE LEVEL block: never compute or cite another one.
    opinion_entropy is the CONVICTION ENTROPY: how the agents' conviction is spread over the conviction
    buckets. It says nothing about positions, stance or agreement: never write a sentence that draws
    positions from it (no "the entropy shows consolidated positions").

14. SEGMENT SHARES ARE NOT MARKET WEIGHTS. The segment percentages in POPULATION COMPOSITION
    are the mix the Demographer chose for the simulated population, and the number of agents is a
    setting of the run. Never use them as market shares or as weights in {H_SCENARIOS} or
    {H_PREDICTION}: no "27% of the simulated population", no "2 of 17 agents (11.8%)" there.
    Describe the agents qualitatively (a few, a minority, most); the figures stay in the metrics
    table and in the {H_APPENDIX}.

15. ADVERSARIAL AGENTS ARE GIVEN. The ADVERSARIAL AGENTS block of the user prompt lists, from
    the run data, the agents with is_adversarial=true. Never write that there are no
    adversarial agents when it lists some, and never call a listed agent a natural agent.

16. READER LABELS, NOT FIELD NAMES. The observations use technical field names (mean_opinion_strength,
    opinion_strength, opinion_entropy, consensus_level, emotional_state, posts_made, is_adversarial, ...)
    and English enum values (high, skeptical, curious, ...). In the report write only the reader labels
    of the REPORT VOCABULARY below and the *_label fields of the observations, never the field names or
    the English enum values. Raw field names may appear only in the {H_APPENDIX}.

17. CONSENSUS MEANS STANCE AGREEMENT, NOTHING ELSE. Write "consensus" only for the stance consensus
    (consensus_level of compute_consensus: the share of the natural agents holding the majority stance,
    with the reading rules given there). The variance of conviction gives conviction_uniformity: how
    similar the agents' conviction is, NOT consensus (a convinced supporter and a convinced critic have
    the same conviction). Never write consensus next to a conviction value, the variance or the entropy.
    If compute_consensus.stance.measured is false, write that the stance was not measured and do not
    write about consensus at all.
    The consensus levels and their thresholds (the only ones: never state other thresholds, and never
    describe the threshold of one level as another level's):
{CONSENSUS_THRESHOLDS}

18. AGENT CLAIMS ARE NOT EVIDENCE. Agents cite figures, percentages, dates, past cases and company
    events from their own simulated experience ("a competitor's 2012 pivot collapsed within 18 months",
    "60% of the budget goes to digital"): these are the agent's claims, not facts. In {H_SCENARIOS} and
    {H_PREDICTION} evidence is only what the simulation measured (stance, conviction, debate metrics,
    the agents' stated opinions) and what the SUBJECT CARD and the prediction requirement state. If you
    mention an agent's figure, date or named event there, attribute it ("according to <agent>") and do
    not use it as evidence. Never introduce such facts yourself.

19. CONVICTION METRICS ARE NOT POSITIONS. The conviction polarization of the debate table and the
    conviction entropy are computed on conviction (opinion_strength). Whether positions moved is said
    only by the stance shift: never write that positions did not move, or that the convinced stayed
    convinced, from them. If the stance shift is moderate or large, positions did move.

20. STANCE SHARES BELONG TO THEIR GROUP. A stance percentage of compute_consensus.stance is a share of
    the natural agents (or of the critical voices): write it with "of the natural agents" and never
    attach it to a segment or a target ("primary target (wellness consumers, 33% support)" is wrong).
    Stance per segment exists only in compute_consensus.stance.by_segment: cite those figures, and only
    for the segment they belong to. Percentages exist only for segments with at least 3 agents; smaller
    segments have counts only ("1 of 1 oppose"): cite them as counts and never generalise from them.
    Write "majority" only for a share above 50%: the most common stance at 50% or less is a plurality.

21. GROUNDED ANALYSIS, NO OUTSIDE FACTS. In every section, the template sections included, reason only
    from the posts, the observations and the brief. Write what follows from them as a hypothesis
    ("if ..., it is plausible that ..."), never as a forecast or an established fact. Do not write numbers,
    dates or durations (days, hours, how long a reaction lasts) that are not in the observations or the brief.
    Name a company, brand, product, slogan, campaign or past event only if it appears in the brief or in a
    post; otherwise describe it generically ("a competitor on the same emotional ground"). Never attribute
    to an agent something it did not write.

22. ROLES. When you name an agent together with a role, use that agent's own role (get_top_influencers,
    interview_agent): never another agent's role.

23. NO INTERNAL NAMES. Write only about the agents that took part in this run. Never mention a critical
    voice or an archetype that is not in the ADVERSARIAL AGENTS block, and never write that a voice, a role
    or an archetype "was not present", "was missing" or "did not take part". Never write template ids,
    configuration keys (names with underscores), sampling methods or how the system chose the agents: the
    system states those facts itself in the {H_APPENDIX}.

24. COMPLETE SENTENCES. Every sentence and every bullet is a grammatically complete sentence with a main
    clause. A conditional always has its consequence: never "If the price drops below the competitors'." alone,
    write "If the price drops below the competitors', it is plausible that the objection weakens.". Never end a
    bullet on a subordinate clause, a colon or a dangling "and"/"or"; never leave a sentence half-written.

25. LISTS OF AGENTS. Name each agent with the name first, then the role in brackets: "Giulia Ferri (freelance
    designer)". Join the items correctly for the language: "A (role), B (role) and C (role)", with commas
    between the items and the conjunction only before the last one; never a role without its agent, never
    two roles in a row, never an agent name repeated in the same list.

REPORT VOCABULARY (field or value → label to write)
{VOCABULARY}

{EXTRA_INSTRUCTIONS}

═══════════════════════════════════════════════
MANDATORY TOOL SEQUENCE (follow this order)
═══════════════════════════════════════════════
You MUST call ALL of the following tools before writing the report:
  Step 1: {"tool": "compute_consensus"}
  Step 2: {"tool": "get_opinion_distribution"}
  Step 3: {"tool": "get_top_influencers", "n": 5}
  Step 4: {"tool": "get_emerging_topics", "n": 8}
  Step 5: {"tool": "query_feed", "filter": "<most relevant keyword from topics>"}
  Step 6: {"tool": "interview_agent", "agent_id": "<id of top influencer>"}
  Step 7: {"tool": "DONE"}

Only call DONE after completing all 6 steps above.

═══════════════════════════════════════════════
ReACT FORMAT — FOLLOW EXACTLY
═══════════════════════════════════════════════
For each step use EXACTLY this format (no markdown, no bold, no ##):
THOUGHT: <one sentence: what you need and why>
ACTION: {"tool": "tool_name", "param": "value"}
OBSERVATION: <filled in by system>

CRITICAL FORMAT RULES:
- Write THOUGHT: and ACTION: as plain text — never use ## or ** around them
- The ACTION line must contain ONLY the JSON object, nothing else
- Do not write any text between ACTION: and the JSON

═══════════════════════════════════════════════
REPORT FORMAT (after DONE)
═══════════════════════════════════════════════
Write the report in Markdown using ONLY this structure, with the headings exactly as written below.

# {REPORT_TITLE}: {topic}

## {H_EXEC}
2-3 sentences. State the dominant trend and the confidence level given in the CONFIDENCE LEVEL
block of the user prompt, unchanged.

## {H_METRICS}
The system inserts the metrics table here (rounds, agents, total posts, stance distribution of natural
agents and critical voices, stance consensus, stance shift, conviction uniformity, mean conviction,
conviction variance, conviction entropy of the last round): do NOT write a table. You may add one sentence
that reads the table, with its labels.

## {H_LANDSCAPE}
Describe the STANCE distribution (support / neutral / oppose; natural agents and critical voices
separately) from compute_consensus, then how CONVICTION is distributed (the conviction buckets of
get_opinion_distribution, exact percentages): conviction, never approval (rule 12). Report
emotional_state counts only as tone.
Name the top 3 influencers with their actual post counts from get_top_influencers.top_influencers (natural
agents only). Never rank or call a critical voice an influencer: its post count is set by the system and goes
in {H_PERSPECTIVES}.

## {H_NARRATIVES}
List the top topics from get_emerging_topics with their actual counts. A topic can be a phrase of
2-3 words (e.g. "brand architecture"): quote it whole, never split it into single words.
Quote 1-2 actual post excerpts from query_feed to illustrate.

## {H_PERSPECTIVES}
Summarise the interviewed agent's actual stated opinion and emotional state.
Do not paraphrase beyond what the OBSERVATION returned.

Distinguish explicitly between natural agents (from KB entities) and
adversarial agents (marked is_adversarial=True). If adversarial agents are
present, treat them as stress-test signals: ALWAYS report the objections they
raised and the vulnerability each one exposes, labelled as coming from
deliberately injected critics. Their post volume is set by the system (the
share is in the {H_APPENDIX}), so do NOT use it to say how widespread
a criticism is. List each critical voice with its post count from
get_top_influencers.critical_voices (name, then role in brackets), saying that
the system sets how often these voices post. Weigh an objection by how specific it is and by whether natural
agents raise it too, and state which of the two applies.

MANDATORY DISCLOSURE ON ADVERSARIAL AGENTS: If any adversarial agents were
included in the simulation, add a brief note (1-2 sentences) explaining that
these agents were deliberately spawned to stress-test the prevailing positions and do
NOT represent a naturally occurring market distribution. This note exists
for reader transparency and must be written in plain language accessible
to non-technical readers.

{DYNAMIC_SECTIONS}

## {H_SCENARIOS}
Based on the stance distribution, the stance consensus and the stance shift from compute_consensus,
define 2-3 scenarios.
Give each scenario ONE qualitative likelihood label, "{L_MOST}", "{L_PLAUSIBLE}" or
"{L_LESS}" (at most one "{L_MOST}"), followed by the evidence that supports it.
NEVER write a probability, a percentage or a percentage range for a scenario.
If the confidence level is "{CONF_LOW}" and the stance consensus is not "{CONS_HIGH}", or the stance was not
measured, no scenario is "{L_MOST}": label them "{L_PLAUSIBLE}" or "{L_LESS}" and close the section saying
that the evidence does not separate them.

## {H_PREDICTION}
State the most likely outcome. Justify with specific metrics from your observations.
Do NOT introduce any fact not grounded in an OBSERVATION.

## {H_CONFIDENCE}
The confidence level is computed by the system (CONFIDENCE LEVEL block) from sample size
(agents, rounds, posts) and the stability of the stance (consensus and shift; conviction variance and
entropy only for simulations without the stance measure). Report it unchanged and explain which data
supports or limits it. You may explain the level but never raise or lower it.

## {H_APPENDIX}
Do NOT write the adversarial post share (how many or what percentage of the posts came from adversarial
agents) anywhere in the report: the system adds the exact figure to this appendix from the run counters.
Add this final section VERBATIM (adapt only the bracketed values from OBSERVATIONS and simulation context):

{APPENDIX}"""

# ---------------------------------------------------------------------------
def top3_share(state) -> dict | None:
    """Quota dei post pubblicati scritta dai 3 agenti NATURALI con piu' post, e a parte i post delle voci critiche:
    quante volte intervengono lo decide il sistema, quindi non sono influencer.
    {"share", "top_posts", "total_posts", "critical_posts", "critical_share", "rest_share"}."""
    total = run_post_totals(state)["posts"]
    natural = sorted((int(_agent_field(a, "posts_made", 0) or 0) for a in state.agents if not _is_adversarial(a)),
                     reverse=True)
    top = sum(natural[:3])
    if not total or not top or top > total:
        return None
    critical = min(total - top, sum(int(_agent_field(a, "posts_made", 0) or 0)
                                    for a in state.agents if _is_adversarial(a)))
    return {"share": top / total, "top_posts": top, "total_posts": total, "critical_posts": critical,
            "critical_share": critical / total, "rest_share": (total - top - critical) / total}


def run_post_totals(state) -> dict:
    """Totali dell'intera simulazione, dai contatori del run (simulation_response_stats).

    Il feed salvato tiene solo gli ultimi post (200) e serve per le citazioni. Le simulazioni salvate
    prima dei contatori non li hanno: per quelle si usa il feed, come prima.
    """
    stats = getattr(state, "response_stats", None) or {}
    saved = len(state.social_feed)
    if any(stats.values()):
        posts = int(stats.get("posted", 0))
        return {"posts": posts, "interactions": posts + int(stats.get("engagement", 0)),
                "saved_posts": saved, "source": "run_counters"}
    return {"posts": saved, "interactions": saved, "saved_posts": saved, "source": "saved_feed"}


def final_opinion_entropy(state) -> float | None:
    """opinion_entropy dell'ultimo round: l'unico valore del report (compute_consensus, confidenza, testo)."""
    if not state.rounds:
        return None
    r = state.rounds[-1]
    return round(r.get("entropy", 0.5) if isinstance(r, dict) else r.opinion_entropy, 3)


# Qualifiers dropped to find the state ("cautiously skeptical", "molto preoccupato")
_EMOTION_QUALIFIERS = {"very", "slightly", "somewhat", "quite", "rather", "a", "bit", "little", "more", "less",
                       "molto", "poco", "un", "po'", "po", "leggermente", "abbastanza", "piuttosto", "più", "meno"}


def _emotion_reverse() -> dict[str, str]:
    """Reader label (any language of the catalog) -> enum value: "curioso" -> "curious"."""
    reverse: dict[str, str] = {}
    for code in SUPPORTED_LANGUAGES:
        for key, label in t_value(code, "report.emotional_states").items():
            reverse.setdefault(label.lower(), key)
    return reverse


def emotion_key(state) -> str:
    """The enum value of an emotional state written in any form: case, separators, Italian labels and their
    gender/number ("Curiosa" -> curious), adverbs and qualifiers ("cautiously skeptical" -> skeptical).
    Unknown: the value lowercased with "_" separators. Counting uses it, so one state is counted once."""
    text = re.sub(r"[\s_\-]+", " ", str(state or "").strip().lower()).strip(" .,;:!")
    if not text:
        return ""
    known = t_value(DEFAULT_LANGUAGE, "report.emotional_states")
    reverse = _emotion_reverse()

    def lookup(words: str) -> str | None:
        key = words.replace(" ", "_")
        if key in known:
            return key
        if words in reverse:
            return reverse[words]
        if " " not in words and len(words) > 3 and words[-1] in "aie":
            for variant in (words[:-1] + "o", words[:-1] + "e"):
                if variant in reverse:
                    return reverse[variant]
        return None

    found = lookup(text)
    if found is None:
        core = [w for w in text.split() if w not in _EMOTION_QUALIFIERS and not w.endswith(("ly", "mente"))]
        if core and len(core) < len(text.split()):
            found = lookup(" ".join(core))
    return found or text.replace(" ", "_")


def emotion_label(lang: str, state) -> str:
    """Reader label of an emotional state (English enum value in the data). Unknown: the value, readable."""
    key = emotion_key(state)
    if not key:
        return ""
    return t_value(lang, "report.emotional_states").get(key, key.replace("_", " "))


def report_vocabulary(lang: str) -> str:
    """The REPORT VOCABULARY block of the system prompt: field names and enum values -> reader labels."""
    labels = t_value(lang, "report.labels")
    fields = [("mean_opinion_strength", labels["mean_conviction"]), ("opinion_strength", labels["conviction"]),
              ("variance", labels["variance"]), ("opinion_entropy", labels["opinion_entropy"]),
              ("conviction_uniformity", labels["conviction_uniformity"]),
              ("consensus_level (stance only)", labels["consensus_level"]), ("stance", labels["stance"]),
              ("emotional_state", labels["emotional_state"]),
              ("posts_made / posts", labels["posts"]), ("total_posts", labels["total_posts"]),
              ("rounds", labels["rounds"]), ("agents", labels["agents"])]
    levels = t_value(lang, "report.consensus_levels")
    uniformity = t_value(lang, "report.conviction_uniformity_levels")
    stances = t_value(lang, "report.stance_values")
    buckets = t_value(lang, "report.conviction_buckets")
    states = t_value(lang, "report.emotional_states")
    lines = ["- fields: " + "; ".join(f"{k} → {v}" for k, v in fields),
             "- stance values: " + "; ".join(f"{k} → {v}" for k, v in stances.items()),
             "- stance consensus levels: " + "; ".join(f"{k} → {v}" for k, v in levels.items()),
             "- conviction uniformity levels: " + "; ".join(f"{k} → {v}" for k, v in uniformity.items()),
             "- conviction buckets (already labels): " + ", ".join(buckets.values()),
             "- emotional states: " + "; ".join(f"{k} → {v}" for k, v in states.items())]
    return "\n".join(lines)


def _is_adversarial(agent) -> bool:
    return bool(agent.get("is_adversarial", False) if isinstance(agent, dict) else getattr(agent, "is_adversarial", False))


def _agent_field(agent, key: str, default=None):
    if isinstance(agent, dict):
        if key in ("name", "role"):
            return agent.get(key) or agent.get("persona", {}).get(key, default)
        return agent.get(key, default)
    if key in ("name", "role"):
        return getattr(agent.persona, key, default)
    return getattr(agent, key, default)


# USER PROMPT — passes concrete seed data to anchor the model from turn 1
# ---------------------------------------------------------------------------

REPORT_USER_TEMPLATE = """
════════════════════════════════════════
SIMULATION CONTEXT
════════════════════════════════════════
Simulation ID : {simulation_id}
Topic         : {topic}
Rounds        : {rounds}
Agents        : {num_agents}
Total posts   : {total_posts}
Saved posts   : {saved_posts} (the most recent of the run: use them only for quotes and examples, never as totals)

Prediction requirement: {prediction_requirement}

════════════════════════════════════════
SEED DATA (verified — use as ground truth)
════════════════════════════════════════
Sample posts (first 5):
{sample_posts}

Agent IDs available for interview:
{agent_ids}

════════════════════════════════════════
ADVERSARIAL AGENTS (from the run data: is_adversarial=true)
════════════════════════════════════════
{adversarial_block}

════════════════════════════════════════
DEBATE DYNAMICS METRICS (pre-computed, deterministic)
════════════════════════════════════════
{debate_metrics_block}

════════════════════════════════════════
CONFIDENCE LEVEL (pre-computed, deterministic: use it as is, never override it)
════════════════════════════════════════
{confidence_block}

════════════════════════════════════════
POPULATION COMPOSITION (from Demographer, persona-pipeline)
════════════════════════════════════════
{population_block}

════════════════════════════════════════
INSTRUCTIONS
════════════════════════════════════════
Follow the MANDATORY TOOL SEQUENCE in the system prompt.
Do NOT skip any tool step.
Do NOT write the final report until you have called DONE.
Begin now with Step 1.
"""


@dataclass
class ReportResult:
    simulation_id: str
    topic: str
    prediction_requirement: str
    report_markdown: str
    tool_calls_made: int
    key_findings: list[str]
    confidence_score: float
    scenario_probabilities: dict[str, float]
    confidence_label: str = ""
    confidence_basis: dict = field(default_factory=dict)


class ReportAgent:
    """ReACT-pattern agent that produces prediction reports."""

    # Minimum tool calls before we accept a report as valid
    MIN_TOOL_CALLS = 4
    # Avversari in testa alla lista degli intervistabili, senza riempirla: a 100 agenti sarebbero tutti voci critiche
    MAX_ADVERSARIAL_INTERVIEWABLE = 4

    def __init__(
        self,
        max_tool_calls: int = 12,
        max_reflection_rounds: int = 3,
        temperature: float = 0.2,   # lowered from 0.4 → reduces creative hallucination
        llm=None,
    ):
        self._llm_instance = llm
        self._llm_factory = get_llm
        self.max_tool_calls = max_tool_calls
        self.max_reflection_rounds = max_reflection_rounds
        self.temperature = temperature

    @classmethod
    def _ensure_share_disclosure(cls, report: str, disclosure: str) -> str:
        """La frase sulla quota e' del codice: le varianti del modello si tolgono, resta solo quella esatta."""
        if not report:
            return report
        report, outcome = postprocess.ensure_share_sentence(report, disclosure)
        log.info("report_share_sentence", removed_model_variants=outcome["removed"], placed=outcome["placed"])
        return report

    @staticmethod
    def _archetypes_limitation(template_id: str | None, population_spec: dict | None,
                               lang: str = DEFAULT_LANGUAGE) -> str:
        """Riga dei limiti noti: da dove vengono gli agenti, con o senza template."""
        population = t(lang, "report.archetypes.population_demographer" if population_spec
                       else "report.archetypes.population_kb")
        key = "with_template" if template_id else "without_template"
        return t(lang, f"report.archetypes.{key}", population=population)

    @staticmethod
    def _appendix(lang: str, template_id: str | None, archetypes_limitation: str, top3: dict | None = None,
                  parameters: str | None = None) -> str:
        """L'appendice metodologica che il modello copia: testo del catalogo con i valori del run (la quota dei
        top 3 la calcola il sistema: prima il catalogo aveva un esempio, 37.5%, che il modello svuotava)."""
        if top3:
            top3_sentence = t(lang, "report.top3.share_with_critical" if top3.get("critical_posts")
                              else "report.top3.share",
                              top_pct=postprocess.fmt_pct(top3["share"], 1, lang),
                              rest_pct=postprocess.fmt_pct(top3.get("rest_share", 1 - top3["share"]), 1, lang),
                              critical_pct=postprocess.fmt_pct(top3.get("critical_share", 0), 1, lang),
                              critical_posts=top3.get("critical_posts", 0),
                              top_posts=top3["top_posts"], total_posts=top3["total_posts"])
        else:
            top3_sentence = t(lang, "report.top3.unknown")
        template_label = template_id or t(lang, "report.template_none")
        parameters = parameters or postprocess.appendix_parameters({"template": template_label}, lang)
        return t(lang, "report.appendix",
                 template_label=template_label,
                 confidence_rule=postprocess.confidence_rule_text(lang),
                 archetypes_limitation=archetypes_limitation, top3_sentence=top3_sentence, parameters=parameters)

    @staticmethod
    def _report_title(lang: str) -> str:
        return t(lang, "report.headings.title")

    @classmethod
    def _system_prompt(cls, lang: str, *, topic: str, template_id: str | None, archetypes_limitation: str,
                       dynamic_sections: str, extra_instructions: str, top3: dict | None = None,
                       parameters: str | None = None) -> str:
        """REPORT_SYSTEM in English with the reader-facing words (headings, labels) of the catalog,
        ending with the language directive."""
        h = t_value(lang, "report.headings")
        buckets = t_value(lang, "report.conviction_buckets")
        values = {
            "{REPORT_TITLE}": h["title"], "{H_EXEC}": h["executive_summary"],
            "{H_METRICS}": h["simulation_metrics"], "{H_LANDSCAPE}": h["opinion_landscape"],
            "{H_NARRATIVES}": h["emerging_narratives"], "{H_PERSPECTIVES}": h["agent_perspectives"],
            "{H_SCENARIOS}": h["scenario_analysis"], "{H_PREDICTION}": h["prediction"],
            "{H_CONFIDENCE}": h["confidence_assessment"], "{H_APPENDIX}": h["appendix"],
            "{H_POPULATION}": h["population_composition"],
            "{L_MOST}": t(lang, "report.likelihood.most"), "{L_PLAUSIBLE}": t(lang, "report.likelihood.plausible"),
            "{L_LESS}": t(lang, "report.likelihood.less"),
            "{E_LOW}": t(lang, "report.entropy.low"), "{E_LOW_M}": t(lang, "report.entropy.low_meaning"),
            "{E_MID}": t(lang, "report.entropy.mid"), "{E_MID_M}": t(lang, "report.entropy.mid_meaning"),
            "{E_HIGH}": t(lang, "report.entropy.high"), "{E_HIGH_M}": t(lang, "report.entropy.high_meaning"),
            "{BUCKETS}": ", ".join(buckets[k] for k in ("very_low", "low", "medium", "high", "very_high")),
            "{BUCKET_VERY_HIGH}": buckets["very_high"],
            "{CONF_LOW}": t(lang, "confidence.levels.bassa").lower(),
            "{CONS_HIGH}": t(lang, "report.consensus_levels.high"),
            "{L_ENTROPY}": t(lang, "report.labels.opinion_entropy"),
            "{ENTROPY_THRESHOLDS}": postprocess.entropy_threshold_lines(lang),
            "{CONSENSUS_THRESHOLDS}": postprocess.consensus_threshold_lines(lang),
            "{VOCABULARY}": report_vocabulary(lang),
        }
        prompt = REPORT_SYSTEM
        for key, value in values.items():
            prompt = prompt.replace(key, value)
        # Run data last: a brace in the topic or in the template text is never read as a placeholder
        prompt = (prompt
                  .replace("{APPENDIX}", cls._appendix(lang, template_id, archetypes_limitation, top3, parameters))
                  .replace("{topic}", topic)
                  .replace("{DYNAMIC_SECTIONS}", dynamic_sections)
                  .replace("{EXTRA_INSTRUCTIONS}", extra_instructions))
        return with_directive(prompt, lang)

    @staticmethod
    def _has_report_heading(text: str) -> bool:
        """Il modello ha gia' scritto il report: titolo in una qualsiasi lingua del catalogo, o uno dei titoli
        di prima del cambio di nome."""
        titles = [t(code, "report.headings.title") for code in SUPPORTED_LANGUAGES] + list(LEGACY_REPORT_TITLES)
        return any(f"# {title}" in text for title in titles)

    @staticmethod
    def _format_adversarial_block(adv_agents: list, stats: dict | None) -> str:
        """Gli agenti con is_adversarial=true del run, per nome, con i loro post."""
        if not adv_agents:
            return "No agent with is_adversarial=true in this simulation: all agents are natural."
        lines = [f"{len(adv_agents)} adversarial agents (is_adversarial=true): critical voices added by the system "
                 "to stress-test the prevailing positions, NOT natural agents."]
        for a in adv_agents:
            lines.append(f"- {_agent_field(a, 'name', '?')} (agent_id {_agent_field(a, 'agent_id', '?')}, "
                         f"role: {_agent_field(a, 'role', '')}): {_agent_field(a, 'posts_made', 0)} posts")
        if stats and stats.get("posts"):
            lines.append(f"Adversarial posts in the whole simulation: {stats.get('adversarial_posts', 0)} "
                         f"of {stats['posts']}.")
        lines.append("Never write that there are no adversarial agents and never call these agents natural.")
        return "\n".join(lines)

    @staticmethod
    def _format_population_block(spec: dict | None, adversarial_names: list[str] | None = None,
                                 lang: str = DEFAULT_LANGUAGE) -> str:
        """Formatta PopulationSpec come blocco testuale per il prompt user."""
        if not spec:
            return (
                "(Population spec not available for this simulation. "
                "The simulation was probably generated before the persona-pipeline refactor. "
                "Do not describe the population composition in the methodological appendix.)"
            )
        try:
            domain_summary = spec.get("domain_summary", "")
            rationale = spec.get("rationale", "")
            # Senza il campo subject la scheda ripeterebbe il domain summary qui sotto
            subject_block = (
                "Subject card (the report is about this subject, not about homonyms):\n"
                + render_subject_card(spec, lang) + "\n\n"
                if spec.get("subject") else ""
            )
            segments = spec.get("segments", [])
            seg_lines = []
            for s in segments:
                seg_lines.append(
                    "  - " + str(s.get("label", s.get("segment_id", "?"))) + ": "
                    + str(s.get("count", 0)) + " agents ("
                    + str(s.get("percentage", 0)) + "%) - "
                    + str(s.get("role_description", ""))[:120]
                )
            voices = ""
            if adversarial_names:
                voices = ("\n\nSimulated critical voices (adversarial agents, is_adversarial=true; they are not "
                          "segments of the natural population):\n"
                          + "\n".join("  - " + n for n in adversarial_names))
            return (
                subject_block
                + "Domain summary:\n  " + domain_summary + "\n\n"
                "Segments (" + str(len(segments)) + "):\n"
                + "\n".join(seg_lines)
                + "\n  The segment percentages are the mix the Demographer chose for the simulated "
                "population: they are not market shares and must not be used as weights in the "
                "scenarios or in the prediction."
                + voices
                + "\n\nRationale (Demographer):\n  " + rationale
            )
        except Exception as e:
            return "(Error formatting population_spec: " + str(e) + ")"

    async def generate(
        self,
        state: SimulationState,
        prediction_requirement: str,
        population_spec: dict | None = None,
        adversarial_post_stats: dict | None = None,
        language: str = DEFAULT_LANGUAGE,
        brief_text: str | None = None,
    ) -> ReportResult:
        """Run the full ReACT loop and return a prediction report in the simulation language.

        brief_text: the project brief, to tell the agents' claims from the facts of the brief in the
        scenarios and the prediction (postprocess.mark_unverified_claims). Without it that check is skipped.
        """

        language = normalize_language(language) or DEFAULT_LANGUAGE
        log.info("report_language", simulation_id=state.simulation_id, language=language)
        tool_executor = SimulationToolExecutor(state, language, population_spec=population_spec)
        totals = run_post_totals(state)
        log.info("report_post_totals", simulation_id=state.simulation_id, **totals)
        stance = tool_executor.stance_metrics()
        log.info("report_stance", simulation_id=state.simulation_id, measured=stance["measured"],
                 consensus=postprocess.stance_consensus_level(stance),
                 agreement=(stance.get("agreement") or {}).get("share"),
                 shift=(stance.get("shift") or {}).get("share"))
        confidence = self._assess_confidence(state, tool_executor, totals, language)
        log.info("report_confidence", simulation_id=state.simulation_id,
                 **{k: v for k, v in confidence.items() if k != "basis"})

        # Build seed data for the user prompt
        adversarial_ids = {a.get("agent_id") if isinstance(a, dict) else a.agent_id
                           for a in state.agents if _is_adversarial(a)}
        sample_posts = self._format_sample_posts(state.social_feed, n=5, adversarial_ids=adversarial_ids)

        # Patch 2: calcolo delle debate dynamics metrics (deterministiche, no LLM)
        # Le metriche sono accessibili al ReportAgent via il prompt user.
        try:
            round_metrics_dicts = [
                {"polarization": r.polarization_score if hasattr(r, "polarization_score") else r.get("polarization", 0.0)}
                for r in state.rounds
            ]
            debate_metrics = compute_all_debate_metrics(round_metrics_dicts, state.social_feed, language)
            log.info(
                "debate_metrics_computed",
                polarization_delta=debate_metrics["polarization_delta"].get("delta"),
                echo_chamber=debate_metrics["echo_chamber_index"].get("score"),
                diversity_interp=debate_metrics["information_diversity"].get("interpretation"),
            )
            debate_metrics_block = self._format_debate_metrics(debate_metrics)
        except Exception as metrics_err:
            log.warning("debate_metrics_failed", error=str(metrics_err))
            debate_metrics = {}
            debate_metrics_block = "(metrics not available for this simulation)"

        # Critical voices left out by the cap on agents (spawn): stated by the code in the appendix, in plain
        # language. The model is not told about them: it wrote that the excluded voices "were not present"
        trunc, agent_cap = self._critical_voices_meta(state.simulation_id)
        if trunc:
            log.info("adversarial_truncation_in_report", simulation_id=state.simulation_id,
                     original=trunc.get("original_count"), kept=trunc.get("kept_count"))

        # Prima alcuni adversari, poi i naturali, fino a max 12
        def _is_adv(a):
            return getattr(a, "is_adversarial", False) if hasattr(a, "is_adversarial") else bool(a.get("is_adversarial", False))
        def _aid(a):
            return a.agent_id if hasattr(a, "agent_id") else a.get("agent_id", "")
        adv_agents = [a for a in state.agents if _is_adv(a)]
        nat_agents = [a for a in state.agents if not _is_adv(a)]
        cut = self.MAX_ADVERSARIAL_INTERVIEWABLE
        selected = adv_agents[:cut] + nat_agents + adv_agents[cut:]
        agent_ids = [_aid(a) for a in selected[:12] if _aid(a)]
        log.info("report_agents_selected",
                 total=len(state.agents),
                 adversarial_first=len(adv_agents),
                 selected=len(agent_ids))
        adversarial_names = [str(_agent_field(a, "name", "") or "") for a in adv_agents]
        adversarial_block = self._format_adversarial_block(adv_agents, adversarial_post_stats)
        adversarial_count = len(adv_agents) or int((adversarial_post_stats or {}).get("adversarial_agents") or 0)

        # Carica template della simulazione (se presente) per sezioni dinamiche + istruzioni extra
        dynamic_sections_md, extra_instructions, template_id = self._load_template_metadata(
            state.simulation_id, language)
        template_info = self._template_info(template_id, language)
        # Archetypes of the template that are not in the run (left out by the cap on agents): the instructions
        # never name them, and the report never mentions them
        run_names = {str(_agent_field(a, "name", "") or "").strip().lower() for a in adv_agents}
        absent_names = [n for n in template_info["persona_names"] if n.strip().lower() not in run_names]
        absent_names += [n for n in (trunc or {}).get("excluded") or [] if n and n.strip().lower() not in run_names]
        extra_instructions = postprocess.drop_names(extra_instructions, absent_names)
        if agent_cap is None:
            agent_cap = template_info["agent_cap"]
        internal_terms = [*postprocess.INTERNAL_KEYS, *template_info["all_ids"], *absent_names]
        share_disclosure = postprocess.critical_voices_disclosure(
            adversarial_post_stats, language, agent_cap=agent_cap if adversarial_count else None, truncation=trunc)
        # Parametri dell'appendice dai dati salvati della simulazione: righe del codice, mai scritte dal modello
        appendix_parameters = postprocess.appendix_parameters({
            "template": template_info["name"] or t(language, "report.template_none"), "agents": len(state.agents),
            "rounds": state.current_round, "topic": state.topic, "question": prediction_requirement,
        }, language)
        archetypes_limitation = self._archetypes_limitation(template_id, population_spec, language)
        system_prompt = self._system_prompt(
            language, topic=state.topic, template_id=template_id, archetypes_limitation=archetypes_limitation,
            dynamic_sections=dynamic_sections_md, extra_instructions=extra_instructions,
            top3=top3_share(state), parameters=appendix_parameters,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": with_directive(REPORT_USER_TEMPLATE.format(
                    simulation_id=state.simulation_id,
                    topic=state.topic,
                    rounds=state.current_round,
                    num_agents=len(state.agents),
                    total_posts=totals["posts"],
                    saved_posts=totals["saved_posts"],
                    prediction_requirement=prediction_requirement,
                    sample_posts=sample_posts,
                    agent_ids=json.dumps(agent_ids),
                    adversarial_block=adversarial_block,
                    debate_metrics_block=debate_metrics_block,
                    confidence_block=postprocess.confidence_prompt_block(confidence),
                    population_block=self._format_population_block(population_spec, adversarial_names, language),
                ), language),
            },
        ]

        tool_calls_made = 0
        final_report = ""
        last_response = ""

        for iteration in range(self.max_tool_calls + self.max_reflection_rounds):
            response = await (self._llm_instance or self._llm_factory()).complete(
                messages,
                tier="heavy",
                temperature=self.temperature,
                max_tokens=2048,
                stop=["OBSERVATION:"],
            )
            # Difesa in profondita': se il modello ha emesso OBSERVATION comunque,
            # tagliamo tutto da li' in poi cosi' il parser lavora su ACTION pulita.
            if "OBSERVATION:" in response:
                response = response.split("OBSERVATION:")[0].rstrip()
            last_response = response
            messages.append({"role": "assistant", "content": response})

            # ── Check for DONE ──────────────────────────────────────────────
            if '{"tool": "DONE"}' in response:
                # Has the model gathered enough data?
                if tool_calls_made < self.MIN_TOOL_CALLS:
                    # Force it to keep going
                    messages.append({
                        "role": "user",
                        "content": with_directive(
                            f"You called DONE too early. You have only used {tool_calls_made} tools. "
                            f"You must complete ALL steps in the MANDATORY TOOL SEQUENCE before calling DONE. "
                            f"Continue from where you left off.", language
                        ),
                    })
                    continue

                # Extract or request the report
                if not self._has_report_heading(response):
                    messages.append({
                        "role": "user",
                        "content": with_directive(
                            "Now write the complete prediction report in Markdown following the REPORT FORMAT "
                            "in the system prompt. Use ONLY data from your OBSERVATIONS above — "
                            "do not introduce any number or fact not present in an OBSERVATION. "
                            f"Start directly with '# {self._report_title(language)}:'.", language
                        ),
                    })
                    final_response = await (self._llm_instance or self._llm_factory()).complete(
                        messages,
                        tier="heavy",
                        temperature=self.temperature,
                        max_tokens=16000,
                    )
                    final_report = self._extract_report(final_response)
                else:
                    final_report = self._extract_report(response)
                break

            # ── Hard cap on tool calls ──────────────────────────────────────
            if tool_calls_made >= self.max_tool_calls:
                messages.append({
                    "role": "user",
                    "content": with_directive(
                        "You have reached the maximum number of tool calls. "
                        "Write the final prediction report now using ONLY data from your OBSERVATIONS. "
                        f"Start directly with '# {self._report_title(language)}:'.", language
                    ),
                })
                final_response = await (self._llm_instance or self._llm_factory()).complete(
                    messages,
                    tier="heavy",
                    temperature=self.temperature,
                    max_tokens=16000,
                )
                final_report = self._extract_report(final_response)
                break

            # ── Execute tool call ───────────────────────────────────────────
            tool_call = self._extract_tool_call(response)
            if tool_call:
                observation = tool_executor.execute(tool_call)
                messages.append({
                    "role": "user",
                    "content": with_directive(
                        f"OBSERVATION: {json.dumps(observation, ensure_ascii=False)}", language),
                })
                tool_calls_made += 1
            else:
                # No tool call and no DONE → model may be writing report directly
                if "# " in response and tool_calls_made >= self.MIN_TOOL_CALLS:
                    final_report = self._extract_report(response)
                    break
                else:
                    # Nudge it back on track
                    messages.append({
                        "role": "user",
                        "content": with_directive(
                            "Continue the ReACT loop. Call the next tool in the MANDATORY TOOL SEQUENCE. "
                            "Use the format: THOUGHT: ... ACTION: {\"tool\": \"...\"}", language
                        ),
                    })

        if not final_report:
            final_report = self._extract_report(last_response)
        consensus = tool_executor._compute_consensus() or {}
        metrics_table = postprocess.simulation_metrics_table({
            "rounds": state.current_round, "agents": len(state.agents), "posts": totals["posts"],
            "stance": stance,
            "conviction_uniformity": consensus.get("conviction_uniformity"),
            "mean_opinion_strength": consensus.get("mean_opinion_strength"),
            "variance": consensus.get("variance"), "entropy": consensus.get("opinion_entropy"),
        }, language)
        final_report = self._finalize_report(
            final_report,
            share_disclosure=share_disclosure,
            metrics_table=metrics_table,
            debate_block=(debate_block := postprocess.debate_metrics_block(debate_metrics, language)),
            template_id=template_id,
            archetypes_limitation=archetypes_limitation,
            confidence=confidence,
            adversarial_count=adversarial_count,
            adversarial_names=adversarial_names,
            natural_names=[str(_agent_field(a, "name", "") or "") for a in nat_agents],
            agent_roles={str(_agent_field(a, "name", "") or ""): str(_agent_field(a, "role", "") or "")
                         for a in state.agents},
            appendix_parameters=appendix_parameters,
            internal_terms=internal_terms,
            lang=language,
            stance=stance,
            population={"agents": len(state.agents), "natural": len(nat_agents),
                        "segments": (population_spec or {}).get("segments") or [],
                        "simulation_id": state.simulation_id},
            claims={
                "brief": brief_text or "",
                # Facts and figures that are not agents' claims: run data and the subject of the simulation
                "allowed_texts": [state.topic or "", prediction_requirement or "",
                                  json.dumps(population_spec, ensure_ascii=False) if population_spec else "",
                                  metrics_table, debate_block, share_disclosure, confidence.get("basis", "")],
                "agent_texts": self._agent_texts(state),
                # Every number the system computed and gave the report: never an agent's claim
                "computed": tool_executor.computed_numbers(),
                # Words of the personas' roles are never third-party names
                "agent_roles": [str(_agent_field(a, "role", "") or "") for a in state.agents],
                "simulation_id": state.simulation_id,
            },
        )

        # Post-process
        key_findings = self._extract_findings(final_report)
        scenarios = self._extract_scenarios(final_report)

        log.info(
            "report_generated",
            sim_id=state.simulation_id,
            tool_calls=tool_calls_made,
            report_len=len(final_report),
        )

        return ReportResult(
            simulation_id=state.simulation_id,
            topic=state.topic,
            prediction_requirement=prediction_requirement,
            report_markdown=final_report,
            tool_calls_made=tool_calls_made,
            key_findings=key_findings,
            confidence_score=confidence["score"],
            scenario_probabilities=scenarios,
            confidence_label=confidence["label"],
            confidence_basis=confidence,
        )

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _assess_confidence(state: SimulationState, tool_executor: "SimulationToolExecutor", totals: dict,
                           lang: str = DEFAULT_LANGUAGE) -> dict:
        """Livello di confidenza deterministico: campione (agenti, round, post) e stabilita'."""
        consensus = tool_executor._compute_consensus() or {}
        # Gli stessi valori che il modello riceve da compute_consensus
        return postprocess.assess_confidence(
            agents=len(state.agents), rounds=state.current_round, posts=totals["posts"],
            variance=consensus.get("variance"), entropy=consensus.get("opinion_entropy"), lang=lang,
            stance=tool_executor.stance_metrics(),
        )

    @classmethod
    def _finalize_report(cls, report: str, *, share_disclosure: str, debate_block: str,
                         template_id: str | None, archetypes_limitation: str,
                         confidence: dict | None = None, adversarial_count: int = 0,
                         adversarial_names: list[str] | None = None,
                         lang: str = DEFAULT_LANGUAGE, metrics_table: str | None = None,
                         natural_names: list[str] | None = None, stance: dict | None = None,
                         agent_roles: dict[str, str] | None = None, appendix_parameters: str | None = None,
                         claims: dict | None = None, population: dict | None = None,
                         internal_terms: list[str] | None = None) -> str:
        """Le parti del report che appartengono al codice, applicate dopo la risposta del modello.

        Ordine (ogni passo lavora sul testo lasciato dai precedenti; nessuno deve creare input che un passo
        successivo legga male):
          1. blocchi del codice: tabella delle metriche, sezione del dibattito;
          2. probabilita' degli scenari tolte (una percentuale di probabilita' non e' un dato);
          3. confidenza ed entropia: livello, valore e lettura calcolati (le frasi sulle soglie restano);
          4. nomi dei campi -> parole del lettore (i controlli seguenti leggono le parole del lettore);
          5. frasi del modello sbagliate per significato: agenti adversarial, convinzione letta come
             approvazione, "consenso" solo per la posizione, soglie di consenso sbagliate, posizioni ricavate
             dalla convinzione;
          6. quote di posizione attaccate a un segmento (prima delle quote di popolazione: una quota di
             posizione non deve essere letta come quota di composizione);
          7. quote di composizione della popolazione e conteggi usati come peso (scenari, previsione);
          8. citazioni tagliate a meta' parola (accorciate all'ultima frase completa o tolte); affermazioni
             degli agenti (scenari, previsione): solo i numeri che non sono nel brief ne' calcolati dal
             sistema, dopo che i passi 6-7 hanno finito di cambiare le cifre;
          9. etichette a meta' frase, riga delle raccomandazioni, riga degli archetipi, nomi interni (chiavi di
            configurazione, id dei template, archetipi esclusi), paragrafo delle voci critiche;
         10. controllo finale dei frammenti (repair_text) sul testo completo.
        Dopo ogni passo che toglie frasi (5-10), repair_orphan_references ripara o toglie la frase seguente
        se comincia rimandando alla frase tolta ("Questa dispersione, ..."): report_text_repaired.
        """
        if not report:
            return report

        def orphans(before: str, after: str) -> str:
            after, repaired = postprocess.repair_orphan_references(before, after, lang)
            for found in repaired:
                log.warning("report_text_repaired", **found)
            return after

        # 1
        if metrics_table:
            report, table_info = postprocess.ensure_metrics_table(report, metrics_table, lang)
            log.info("report_metrics_table", **table_info)
        report, debate = postprocess.ensure_debate_section(report, debate_block, lang)
        report, params = postprocess.ensure_appendix_parameters(report, appendix_parameters, lang)
        if params:
            log.info("report_appendix_parameters", action=params)
        log.info("report_debate_section", **debate)
        # 2
        report, stripped = postprocess.strip_scenario_probabilities(report)
        if stripped:
            log.warning("report_probability_stripped", values=stripped)
        # 3
        if confidence:
            conf_stats: dict = {}
            report, overridden = postprocess.enforce_confidence(report, confidence, lang, stats=conf_stats)
            if overridden:
                log.warning("report_confidence_overridden", model_levels=overridden, level=confidence["label"])
            if conf_stats.get("line_copies_removed"):
                log.warning("report_confidence_line_deduplicated", copies=conf_stats["line_copies_removed"])
        report, likelihood = postprocess.enforce_scenario_likelihood(report, confidence, stance, lang)
        if likelihood["relabelled"] or likelihood["note_added"]:
            log.warning("report_scenario_likelihood_relabelled", **likelihood)
            report, fixed = postprocess.fix_entropy_values(report, confidence.get("entropy"))
            if fixed:
                log.warning("report_entropy_fixed", values=fixed, entropy=confidence.get("entropy"))
            report, readings = postprocess.fix_entropy_readings(report, confidence.get("entropy"), lang)
            if readings:
                log.warning("report_entropy_reading_fixed", readings=readings, entropy=confidence.get("entropy"))
        # 4
        report, localized = postprocess.localize_field_names(report, lang)
        if localized:
            log.info("report_field_names_localized", replacements=localized)
        # 5
        before = report
        report, adv_fix = postprocess.fix_adversarial_claims(
            report, adversarial_count, adversarial_names or [], lang, natural_names or [])
        report = orphans(before, report)
        if adv_fix["removed"] or adv_fix["relabelled"]:
            log.warning("report_adversarial_claim_fixed", adversarial_agents=adversarial_count, **adv_fix)
        report, roles = postprocess.fix_agent_roles(report, agent_roles, lang)
        for found in roles:
            log.warning("report_role_fixed", **found)
        report, majority = postprocess.fix_false_majority(report, lang)
        for found in majority:
            log.warning("report_majority_wording_fixed", **found)
        before = report
        report, misread = postprocess.strip_conviction_as_approval(report)
        if misread:
            log.warning("report_strength_reading_fixed", sentences=misread)
        report = orphans(before, report)
        before = report
        report, wording = postprocess.fix_consensus_wording(report, stance, lang)
        if any(wording.values()):
            log.warning("report_consensus_wording_fixed", stance_measured=postprocess.stance_measured(stance),
                        **wording)
        report = orphans(before, report)
        before = report
        report, thresholds = postprocess.fix_consensus_thresholds(report, lang)
        for found in thresholds:
            log.warning("report_consensus_threshold_removed", **found)
        report = orphans(before, report)
        before = report
        report, claims_on_positions = postprocess.fix_position_claims(report, stance, lang)
        for found in claims_on_positions:
            log.warning("report_position_claim_removed", **found)
        report = orphans(before, report)
        # 6
        before = report
        report, segment_shares = postprocess.fix_segment_stance_shares(
            report, stance, (population or {}).get("segments"), lang)
        for found in segment_shares:
            log.warning("report_segment_stance_removed", **found)
        report = orphans(before, report)
        # 7
        if population is not None:
            before = report
            report, shares = postprocess.remove_population_shares(
                report, total_agents=population.get("agents") or 0, natural_agents=population.get("natural") or 0,
                segments=population.get("segments"), lang=lang, stance=stance)
            for share in shares:
                log.warning("report_population_share_removed", simulation_id=population.get("simulation_id"), **share)
            report = orphans(before, report)
        # 8
        before = report
        report, cut_quotes = postprocess.fix_cut_quotes(report, (claims or {}).get("agent_texts"))
        for found in cut_quotes:
            log.warning("report_cut_quote_fixed", **found)
        report = orphans(before, report)
        if claims is not None:
            before = report
            report = cls._mark_claims(report, claims, lang)
            report = orphans(before, report)
        # 9
        report, recased = postprocess.fix_label_case(report, lang)
        if recased:
            log.info("report_label_case_fixed", labels=recased)
        before = report
        report, dropped = postprocess.drop_recommendations_limit(report)
        if dropped:
            log.info("report_recommendations_limit_dropped", lines=dropped)
        report = orphans(before, report)
        if not template_id:
            # La riga degli archetipi del template, in qualsiasi lingua del catalogo
            fixed = 0
            for code in SUPPORTED_LANGUAGES:
                report, n = postprocess.replace_lines_containing(
                    report, t(code, "report.archetypes.template_needle"), archetypes_limitation)
                fixed += n
            if fixed:
                log.info("report_template_limitation_fixed", lines=fixed)
        if internal_terms:
            before = report
            report, internal = postprocess.strip_internal_names(report, internal_terms)
            for found in internal:
                log.warning("report_internal_name_removed", **found)
            report = orphans(before, report)
        report = cls._ensure_share_disclosure(report, share_disclosure)
        # 10
        before = report
        report, repaired = postprocess.repair_text(report, lang)
        for found in repaired:
            log.warning("report_text_repaired", **found)
        report = orphans(before, report)
        # Nessuna sezione comincia con "La sua opinione" / "Her opinion" o un rimando senza antecedente
        report, dangling = postprocess.fix_dangling_section_starts(report, lang)
        for found in dangling:
            log.warning("report_text_repaired", **found)
        return report

    @staticmethod
    def _mark_claims(report: str, claims: dict, lang: str) -> str:
        """Agents' claims in the scenarios and the prediction: attributed, never evidence."""
        if not (claims.get("brief") or "").strip():
            log.warning("report_claims_check_skipped", simulation_id=claims.get("simulation_id"), reason="no_brief")
            return report
        report, found = postprocess.mark_unverified_claims(
            report, brief=claims["brief"], allowed_texts=claims.get("allowed_texts") or [],
            agent_texts=claims.get("agent_texts") or {}, lang=lang, computed=claims.get("computed"),
            agent_roles=claims.get("agent_roles"))
        for claim in found:
            log.warning("report_unverified_claim", simulation_id=claims.get("simulation_id"), **claim)
        return report

    @staticmethod
    def _agent_texts(state) -> list[tuple[str, str]]:
        """(agent name, text) for what each agent wrote or was given, where its claims come from: the posts in
        feed order, then current opinion and persona. System posts (breaking news) keep their author name."""
        names = {_agent_field(a, "agent_id"): _agent_field(a, "name", "") for a in state.agents}
        texts = []
        for post in state.social_feed:
            name = post.get("author_name") or names.get(post.get("author_id")) or post.get("agent_name") or ""
            texts.append((str(name), str(post.get("content") or "")))
        for a in state.agents:
            name = str(_agent_field(a, "name", "") or "")
            beliefs = [str(b) for b in (_agent_field(a, "core_beliefs", []) or []) if isinstance(b, str)]
            texts.append((name, " ".join([str(_agent_field(a, "current_opinion", "") or ""),
                                          str(_agent_field(a, "background", "") or ""), *beliefs])))
        return [(name, text) for name, text in texts if name and text.strip()]

    @staticmethod
    def _sections_markdown(section_names: list[str], template_id: str | None = None,
                           lang: str = DEFAULT_LANGUAGE) -> str:
        """Sezioni del template piu' quelle sempre presenti (ALWAYS_SECTIONS), senza doppioni."""
        names = list(dict.fromkeys([*section_names, *ALWAYS_SECTIONS]))
        md_parts = []
        for sec_name in names:
            sec_def = SECTION_DESCRIPTIONS.get(sec_name)
            if not sec_def:
                log.warning("unknown_section_in_template",
                            template_id=template_id, section=sec_name)
                continue
            md_parts.append(f"## {section_title(sec_name, lang)}\n{sec_def['prompt']}")
        return "\n\n".join(md_parts)

    @staticmethod
    def _critical_voices_meta(simulation_id: str) -> tuple[dict | None, float | None]:
        """(truncation of the critical voices at spawn, cap on the share of critical AGENTS) from the saved meta."""
        try:
            from app.config import Config
            from app.utils.state_store import StateStore
            meta = StateStore(Config.SIMULATIONS_DIR).load_meta(simulation_id) or {}
        except Exception as meta_err:
            log.debug("adversarial_truncation_load_failed", error=str(meta_err))
            return None, None
        cap = meta.get("adversarial_agent_share_cap")
        try:
            cap = float(cap) if cap is not None else None
        except (TypeError, ValueError):
            cap = None
        return meta.get("adversarial_truncation") or None, cap

    @staticmethod
    def _template_info(template_id: str | None, lang: str) -> dict:
        """The template as the reader knows it: its name, its critical-voice archetypes and its cap on the share of
        critical agents; plus every template id, an internal name the report never shows."""
        info = {"name": None, "persona_names": [], "agent_cap": None, "all_ids": []}
        try:
            from app.templates import get_registry
            registry = get_registry()
            info["all_ids"] = [tpl["id"] for tpl in registry.list_all(lang)]
            tpl = registry.get(template_id, lang) if template_id else None
        except Exception as tpl_err:
            log.warning("report_template_info_failed", template_id=template_id, error=str(tpl_err))
            return info
        if tpl:
            info["name"] = str(tpl.get("name") or "").strip() or None
            info["persona_names"] = [str(p.get("name")) for p in tpl.get("adversarial_personas") or [] if p.get("name")]
            try:
                info["agent_cap"] = float(tpl.get("max_adversarial_share", 0.15))
            except (TypeError, ValueError):
                info["agent_cap"] = 0.15
        return info

    def _load_template_metadata(self, simulation_id: str,
                                lang: str = DEFAULT_LANGUAGE) -> tuple[str, str, str | None]:
        """
        Legge template_id della simulazione dal DB, carica il template dal
        registry, ritorna (dynamic_sections_markdown, extra_instructions, template_id).
        Senza template restano le sezioni di ALWAYS_SECTIONS, extra vuoto e template_id None.
        """
        sections: list[str] = []
        extra = ""
        template_id = None
        try:
            import os as _os
            import psycopg2 as _psycopg2
            from app.templates import get_registry as _get_tpl_registry

            db_url = _os.environ.get("DATABASE_URL", "")
            row = None
            if db_url and simulation_id:
                conn = _psycopg2.connect(db_url)
                cur = conn.cursor()
                cur.execute("SELECT template_id FROM simulations WHERE id=%s", (simulation_id,))
                row = cur.fetchone()
                cur.close(); conn.close()
            if row and row[0]:
                # Sezioni ed extra_instructions nella lingua del report (quella della simulazione)
                tpl = _get_tpl_registry().get(row[0], lang)
                if not tpl:
                    log.warning("report_template_not_found", template_id=row[0])
                else:
                    template_id = row[0]
                    rf = tpl.get("report_focus", {})
                    sections = list(rf.get("mandatory_sections") or [])
                    extra = (rf.get("extra_instructions") or "").strip()
        except Exception as e:
            log.warning("report_template_load_error", error=str(e))

        dynamic_md = self._sections_markdown(sections, template_id, lang)
        log.info("report_template_loaded",
                 template_id=template_id,
                 sections=dynamic_md.count("## "),
                 has_extra_instructions=bool(extra))
        return dynamic_md, extra, template_id

    @staticmethod
    def _format_debate_metrics(metrics: dict) -> str:
        """Formatta le debate dynamics metrics come blocco leggibile dal ReportAgent."""
        if not metrics:
            return "(no data)"
        parts = []
        pd = metrics.get("polarization_delta", {})
        if pd.get("interpretation") != "insufficient_data":
            parts.append(
                f"- POLARIZATION_DELTA: initial={pd.get('initial_polarization')}, "
                f"final={pd.get('final_polarization')}, delta={pd.get('delta')} "
                f"[{pd.get('interpretation')}]\n  {pd.get('description','')}"
            )
        ec = metrics.get("echo_chamber_index", {})
        if ec.get("score") is not None:
            parts.append(
                f"- ECHO_CHAMBER_INDEX: score={ec.get('score')} (method={ec.get('method')}) "
                f"[{ec.get('interpretation')}]\n  {ec.get('description','')}"
            )
        inf = metrics.get("information_diversity", {})
        if inf.get("interpretation") != "insufficient_data":
            parts.append(
                f"- INFORMATION_DIVERSITY: first_half_avg={inf.get('first_half_keywords_avg')}, "
                f"second_half_avg={inf.get('second_half_keywords_avg')}, delta_pct={inf.get('delta_pct')}% "
                f"[{inf.get('interpretation')}]\n  {inf.get('description','')}"
            )
        return "\n".join(parts) if parts else "(insufficient data)"

    @staticmethod
    def _format_sample_posts(feed: list, n: int = 5, adversarial_ids: set | None = None) -> str:
        """Return the first n posts as a readable block for grounding."""
        if not feed:
            return "(no posts available)"
        lines = []
        for i, post in enumerate(feed[:n], 1):
            agent = post.get("author_name") or post.get("agent_name") or post.get("author_id") or post.get("agent_id", "?")
            if adversarial_ids and post.get("author_id") in adversarial_ids:
                agent += ", critical voice is_adversarial=true"
            # Cut at the end of a sentence or of a word, never mid-word: the report quotes these lines
            content = trim_excerpt(post.get("content") or "", 200)
            lines.append(f"{i}. [{agent}]: {content}")
        return "\n".join(lines)

    @staticmethod
    def _extract_tool_call(text: str) -> dict | None:
        """Parse ACTION in tutte le varianti: ACTION:, **ACTION:**, ## ACTION, ## ACTION:"""
        # Cerca qualsiasi variante di ACTION seguita da JSON
        match = re.search(
            r"(?:#{1,3}\s*)?\*{0,2}ACTION\*{0,2}:?\s*(\{.*?\})",
            text, re.DOTALL | re.IGNORECASE
        )
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        # Fallback: cerca JSON con "tool" direttamente
        match = re.search(r'(\{"tool"\s*:.*?\})', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _extract_report(text: str) -> str:
        """Extract markdown report from final response, removing ReACT artifacts."""
        import re as _re
        REACT_WORDS = {"THOUGHT", "ACTION", "OBSERVATION", "DONE"}

        # Rimuovi righe ReACT in tutte le varianti:
        # THOUGHT, **THOUGHT**, THOUGHT:, **ACTION:** {"tool":...}, # ACTION, ecc.
        lines = text.split("\n")
        cleaned_lines = []
        skip_next_json = False
        for line in lines:
            stripped = line.strip()
            # Rimuovi asterischi markdown e # per il check
            bare = stripped.lstrip("#").lstrip("*").rstrip("*").strip()
            # Controlla se la riga inizia con una parola ReACT
            is_react = any(bare.upper().startswith(w) for w in REACT_WORDS)
            # Controlla se è una riga JSON solitaria (tool call)
            is_json = stripped.startswith("{") and "tool" in stripped
            if is_react:
                skip_next_json = True
                continue
            if is_json and skip_next_json:
                skip_next_json = False
                continue
            skip_next_json = False
            cleaned_lines.append(line)

        cleaned = "\n".join(cleaned_lines).strip()
        # Rimuovi righe vuote multiple
        cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned).strip()

        # Cerca il primo heading non-ReACT
        for i, line in enumerate(cleaned_lines):
            if line.startswith("#"):
                bare = line.lstrip("#").strip()
                if not any(bare.upper().startswith(w) for w in REACT_WORDS):
                    result = "\n".join(cleaned_lines[i:]).strip()
                    return _re.sub(r"\n{3,}", "\n\n", result)

        return cleaned if cleaned else text.strip()

    @staticmethod
    def _extract_findings(report: str) -> list[str]:
        """Extract bullet points as key findings."""
        bullets = re.findall(r"[-*]\s+(.+)", report)
        return bullets[:10]

    @staticmethod
    def _extract_scenarios(report: str) -> dict[str, float]:
        """Gli scenari hanno solo una plausibilita' qualitativa: nessuna probabilita' numerica da estrarre.

        Il campo resta nel report salvato (vuoto) per compatibilita' con chi lo legge.
        """
        return {}


class SimulationToolExecutor:
    """Executes tool calls for the ReportAgent."""

    def __init__(self, state: SimulationState, lang: str = DEFAULT_LANGUAGE, population_spec: dict | None = None):
        self._state = state
        self._lang = normalize_language(lang) or DEFAULT_LANGUAGE
        self._stance: dict | None = None
        self._segments = (population_spec or {}).get("segments") or []

    def stance_metrics(self) -> dict:
        """Distribuzione, consenso e spostamento della posizione (report/stance_metrics), calcolati una volta."""
        if self._stance is None:
            self._stance = compute_stance_metrics(self._state.agents, self._segments)
        return self._stance

    def computed_numbers(self) -> set[float]:
        """Every number the system computed and gave the report: compute_consensus (stance distribution,
        per-segment stance, conviction, entropy, totals), conviction buckets, emotional-state counts and their
        shares, influencers' counts, topic counts, post and agent counts, the readings' thresholds. Shares of
        the same group are also summed in pairs ("contrari o neutrali", "alta o molto alta").
        The report's claims check never treats them as claims."""
        values: set[float] = set()
        top3 = top3_share(self._state)
        if top3:
            values.update({round(top3["share"] * 100, 1), round((1 - top3["share"]) * 100, 1),
                           round(top3["critical_share"] * 100, 1), round(top3["rest_share"] * 100, 1),
                           float(top3["top_posts"]), float(top3["total_posts"]), float(top3["critical_posts"])})

        def add(v):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                values.add(round(float(v), 3))

        def pairs(nums):
            nums = [float(n) for n in nums if isinstance(n, (int, float)) and not isinstance(n, bool)]
            for i, a in enumerate(nums):
                for b in nums[i + 1:]:
                    values.add(round(a + b, 3))

        def walk(node):
            if isinstance(node, dict):
                if isinstance(node.get("shares_pct"), dict):
                    pairs(node["shares_pct"].values())
                buckets = node.get("conviction_buckets")
                if isinstance(buckets, dict):
                    pairs(b.get("pct", 0) for b in buckets.values() if isinstance(b, dict))
                for v in node.values():
                    walk(v)
            elif isinstance(node, (list, tuple)):
                for v in node:
                    walk(v)
            else:
                add(node)

        total = len(self._state.agents) or 1
        distribution = self._get_opinion_distribution()
        walk([self._compute_consensus(), distribution, self._get_top_influencers(total),
              self._get_emerging_topics(20), run_post_totals(self._state)])
        for count in (distribution.get("emotional_state_counts") or {}).values():
            add(round(count / total * 100, 1))
        stance = self.stance_metrics()
        if stance.get("measured"):
            for group in ("natural", "adversarial"):
                for dist in (stance[group]["final"], stance[group]["initial"]):
                    for v in dist["shares"].values():
                        add(round(v * 100, 1))
        # Thresholds the report may quote (confidence sample sizes, stance readings)
        for table in (postprocess.SMALL_SAMPLE, postprocess.MEDIUM_SAMPLE):
            for v in table.values():
                add(v)
        for v in (postprocess.STANCE_CONSENSUS_HIGH_FROM, postprocess.STANCE_CONSENSUS_MEDIUM_FROM,
                  postprocess.STANCE_SHIFT_MODERATE_FROM, postprocess.STANCE_SHIFT_LARGE_FROM):
            add(v * 100)
        add(postprocess.STANCE_SHIFT_MIN_REMEASURED)
        add(postprocess.SEGMENT_STANCE_MIN_AGENTS)
        add(len(self._state.agents))
        add(self._state.current_round)
        return values

    def _stance_of(self, agent) -> dict:
        stance = _agent_field(agent, "stance")
        if stance not in t_value(self._lang, "report.stance_values"):
            return {"stance": None, "stance_label": t(self._lang, "report.stance.not_measured")}
        return {"stance": stance, "stance_label": t(self._lang, f"report.stance_values.{stance}")}

    def execute(self, tool_call: dict) -> Any:
        tool = tool_call.get("tool", "")
        try:
            if tool == "query_feed":
                return self._query_feed(tool_call.get("filter", ""))
            elif tool == "interview_agent":
                return self._interview_agent(tool_call.get("agent_id", ""))
            elif tool == "get_opinion_distribution":
                return self._get_opinion_distribution()
            elif tool == "get_top_influencers":
                return self._get_top_influencers(int(tool_call.get("n", 5)))
            elif tool == "get_emerging_topics":
                return self._get_emerging_topics(int(tool_call.get("n", 5)))
            elif tool == "compute_consensus":
                return self._compute_consensus()
            else:
                return {"error": f"Unknown tool: {tool}"}
        except Exception as e:
            return {"error": str(e)}

    def _query_feed(self, filter_term: str) -> dict:
        matching = [
            p for p in self._state.social_feed
            if filter_term.lower() in p.get("content", "").lower()
        ]
        totals = run_post_totals(self._state)
        adversarial_ids = {_agent_field(a, "agent_id") for a in self._state.agents if _is_adversarial(a)}
        return {
            "count": len(matching),
            # Il conteggio e' sui soli post salvati, non su tutta la simulazione
            "searched_posts": totals["saved_posts"],
            "total_posts_in_simulation": totals["posts"],
            "sample": [{**p, "author_is_adversarial": p.get("author_id") in adversarial_ids} for p in matching[:10]],
        }

    def _interview_agent(self, agent_id: str) -> dict:
        def _get(a, *keys):
            if hasattr(a, keys[0]):
                obj = a
                for k in keys:
                    obj = getattr(obj, k)
                return obj
            d = a
            for k in keys:
                if isinstance(d, dict):
                    d = d.get(k, "")
                else:
                    d = getattr(d, k, "")
            return d

        agent = next(
            (a for a in self._state.agents
             if (a.agent_id if hasattr(a, "agent_id") else a.get("agent_id")) == agent_id),
            None
        )
        if not agent:
            return {"error": "Agent not found"}
        return {
            "name": agent.get("name") or agent.get("persona", {}).get("name", "") if isinstance(agent, dict) else agent.persona.name,
            "role": agent.get("role") or agent.get("persona", {}).get("role", "") if isinstance(agent, dict) else agent.persona.role,
            "current_opinion": agent.get("current_opinion", "") if isinstance(agent, dict) else agent.current_opinion,
            "opinion_strength": agent.get("opinion_strength", 0.5) if isinstance(agent, dict) else agent.opinion_strength,
            "emotional_state": agent.get("emotional_state", "") if isinstance(agent, dict) else agent.emotional_state,
            "emotional_state_label": emotion_label(self._lang, _agent_field(agent, "emotional_state", "")),
            "posts_made": agent.get("posts_made", 0) if isinstance(agent, dict) else agent.posts_made,
            "is_adversarial": agent.get("is_adversarial", False) if isinstance(agent, dict) else getattr(agent, "is_adversarial", False),
            **self._stance_of(agent),
        }

    def _get_opinion_distribution(self) -> dict:
        """Distribuzione della CONVINZIONE (opinion_strength), non dell'approvazione.

        La simulazione non ha una misura di approvazione o sentiment: l'unico segnale separato e'
        emotional_state, un'etichetta di tono della persona, riportata a parte come tale.
        """
        if not self._state.agents:
            return {}
        # Nomi delle fasce dal catalogo: il report li cita, nella lingua della simulazione
        bucket_names = t_value(self._lang, "report.conviction_buckets")
        names = tuple(bucket_names[k] for k in ("very_low", "low", "medium", "high", "very_high"))
        buckets = dict.fromkeys(names, 0)
        tones: dict[str, int] = {}
        for agent in self._state.agents:
            s = agent.get("opinion_strength", 0.5) if isinstance(agent, dict) else agent.opinion_strength
            buckets[names[min(4, max(0, int(float(s) * 5)))]] += 1
            raw_tone = _agent_field(agent, "emotional_state", "")
            tone = emotion_label(self._lang, raw_tone) if raw_tone else t(self._lang, "report.tone_not_stated")
            tones[tone] = tones.get(tone, 0) + 1
        total = len(self._state.agents)
        return {
            "measure": ("opinion_strength = conviction (0-1): how firmly the agent holds its position, "
                        f"NOT approval. A very convinced critic sits in {names[-1]}."),
            "conviction_buckets": {k: {"count": v, "pct": round(v / total * 100, 1)} for k, v in buckets.items()},
            # Keys are the reader labels of the emotional states (REPORT VOCABULARY)
            "emotional_state_counts": dict(sorted(tones.items(), key=lambda kv: -kv[1])),
            "emotional_state_note": "emotional tone labels of the personas: they are not a measure of approval",
            "stance": "the agents' position on the change (support / neutral / oppose) is in the stance block of "
                      "compute_consensus: conviction buckets and tones are not stance",
        }

    def _get_top_influencers(self, n: int) -> dict:
        """The natural agents with the most posts. Critical voices are never ranked: the system sets how often
        they post. Their post counts come apart, in critical_voices."""
        def _posts(a):
            return a.get("posts_made", 0) if isinstance(a, dict) else a.posts_made

        def _get_name(a):
            if isinstance(a, dict):
                # Prova prima name diretto, poi persona.name
                return a.get("name") or a.get("persona", {}).get("name", "") or ""
            return a.persona.name if hasattr(a, "persona") else ""

        def _get_role(a):
            if isinstance(a, dict):
                return a.get("role") or a.get("persona", {}).get("role", "") or ""
            return a.persona.role if hasattr(a, "persona") else ""

        natural = sorted((a for a in self._state.agents if not _is_adversarial(a)), key=_posts, reverse=True)
        critical = sorted((a for a in self._state.agents if _is_adversarial(a)), key=_posts, reverse=True)
        return {
            "top_influencers": [
                {
                    "agent_id": _agent_field(a, "agent_id", ""),
                    "name": _get_name(a),
                    "role": _get_role(a),
                    "posts": _posts(a),
                    "opinion_strength": a.get("opinion_strength", 0.5) if isinstance(a, dict) else a.opinion_strength,
                    "emotional_state": a.get("emotional_state", "") if isinstance(a, dict) else a.emotional_state,
                    "emotional_state_label": emotion_label(self._lang, _agent_field(a, "emotional_state", "")),
                    **self._stance_of(a),
                }
                for a in natural[:n]
            ],
            "critical_voices": [
                {"agent_id": _agent_field(a, "agent_id", ""), "name": _get_name(a), "role": _get_role(a),
                 "posts": _posts(a)}
                for a in critical
            ],
            "note": ("top_influencers ranks natural agents only. The system sets how often critical voices post: "
                     "give their post counts apart, where the report discusses the critical voices, and never "
                     "call a critical voice an influencer."),
        }

    # Stopword set (italiane + inglesi) usate per topic extraction
    REPORT_STOPWORDS = {
        # Italiano - articoli, preposizioni, preposizioni articolate, congiunzioni, pronomi
        "della", "dello", "delle", "degli", "dalla", "dallo", "dalle", "dagli",
        "nella", "nello", "nelle", "negli", "sulla", "sullo", "sulle", "sugli",
        "alla", "allo", "alle", "agli", "dalla", "dalle", "dagli", "coi", "cogli",
        "che", "chi", "cui", "con", "come", "anche", "ancora", "altro", "altra",
        "altre", "altri", "quando", "quanto", "quali", "quale", "questo", "questa",
        "questi", "queste", "quello", "quella", "quelli", "quelle", "tutto", "tutti",
        "tutte", "tutta", "sono", "essere", "stato", "stata", "stati", "state",
        "avere", "hanno", "abbiamo", "avete", "avevo", "aveva", "avere",
        "molto", "molti", "molte", "molta", "poco", "pochi", "poca", "poche",
        "solo", "sola", "soli", "sole", "stesso", "stessa", "stessi", "stesse",
        "senza", "sotto", "sopra", "dopo", "prima", "mentre", "perche", "perché",
        "mai", "sempre", "forse", "pero", "però", "quindi", "cosi", "così",
        "ogni", "alcuni", "alcune", "alcuna", "alcuno",
        "del", "dal", "nel", "sul", "col", "all", "dell", "nell", "sull",
        "verso", "dentro", "fuori", "contro", "presso", "circa", "oltre", "durante", "attraverso", "intorno",
        "invece", "ormai", "proprio", "appunto", "infatti", "inoltre", "comunque", "davvero", "almeno",
        "soltanto", "spesso", "adesso", "allora", "perciò", "percio", "dunque", "neanche", "nemmeno", "magari",
        "dove", "cosa", "cose", "qualcosa", "qualche", "niente", "nulla", "nessuno", "nessuna", "ciascuno",
        "ognuno", "tanto", "tanta", "tanti", "tante", "troppo", "troppa", "troppi", "troppe", "quel", "quei",
        "nostro", "nostra", "nostri", "nostre", "vostro", "vostra", "loro", "suoi", "sue", "suo", "sua",
        "fare", "fatto", "fatta", "fanno", "sarà", "sara", "saranno", "sarebbe", "sarebbero", "siamo", "siete",
        "potrebbe", "potrebbero", "dovrebbe", "dovrebbero", "possono", "devono", "deve", "può", "puo",
        "vuole", "vogliono", "bisogna", "serve", "servono", "essere", "avere", "secondo", "mentre",
        "altrimenti", "tuttavia", "pertanto", "intanto", "anzi", "praticamente", "semplicemente",
        "probabilmente", "veramente", "effettivamente", "ovviamente",
        # Inglese
        "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
        "her", "was", "one", "our", "out", "day", "get", "has", "him", "his",
        "how", "man", "new", "now", "old", "see", "two", "way", "who", "boy",
        "did", "its", "let", "put", "say", "she", "too", "use", "with", "this",
        "that", "from", "they", "know", "want", "been", "good", "much", "some",
        "time", "very", "when", "come", "here", "just", "like", "long", "make",
        "many", "over", "such", "take", "than", "them", "well", "were", "what",
        "have", "also", "into", "your", "will", "about", "which", "their", "there",
        "would", "could", "should", "these", "those", "being", "through", "toward", "towards", "while", "where",
        "every", "other", "others", "after", "before", "again", "because", "between", "without", "within",
        "under", "still", "even", "though", "although", "only", "more", "most", "less", "does", "doing", "done",
        "might", "must", "shall", "upon", "across", "against", "around", "onto", "whose", "whom",
        "anyone", "someone", "something", "nothing", "everything", "really", "quite", "rather", "maybe",
        "perhaps", "already", "always", "never", "ever", "same", "each", "both", "either", "neither", "then",
        "until", "unless", "whether", "since", "instead", "almost", "enough", "else", "here's", "there's",
        "otherwise", "however", "therefore", "thus", "hence", "meanwhile", "besides", "indeed", "actually",
        "simply", "probably", "anyway",
        # Aggettivi generici: non sono temi ("clear", "messaggio chiaro")
        "clear", "unclear", "clearly", "real", "really", "important", "different", "possible", "specific",
        "general", "strong", "simple", "great", "better", "worse", "little", "large", "major", "whole", "certain",
        "likely", "unlikely", "right", "wrong", "true", "obvious", "interesting", "nice", "huge", "small", "high",
        "chiaro", "chiara", "chiari", "chiare", "chiaramente", "vero", "vera", "veri", "vere", "importante",
        "importanti", "grande", "grandi", "piccolo", "piccola", "piccoli", "piccole", "diverso", "diversa", "diversi",
        "diverse", "possibile", "possibili", "specifico", "specifica", "generale", "generali", "forte", "forti",
        "semplice", "semplici", "giusto", "giusta", "migliore", "migliori", "peggiore", "nuovo", "nuova", "nuovi",
        "nuove", "reale", "reali", "certo", "certa", "interessante", "evidente", "ovvio", "ovvia",
    }

    # Parole funzione corte: non sono mai un termine da sole e spezzano le frasi multi-parola,
    # salvo le preposizioni di PHRASE_JOINERS dentro un trigramma ("punto di vendita").
    PHRASE_FUNCTION_WORDS = {
        "il", "lo", "la", "le", "gli", "un", "uno", "una", "di", "da", "in", "su", "per", "tra", "fra",
        "con", "del", "dei", "al", "ai", "nel", "nei", "sul", "sui", "dal", "dai", "ma", "se", "non",
        "si", "ci", "vi", "ne", "mi", "ti", "chi", "che", "cui", "più", "piu", "poi", "già", "gia",
        "sì", "qui", "là", "lì", "ed", "od", "è", "e", "o", "a", "i",
        "of", "to", "in", "on", "at", "by", "as", "is", "it", "be", "or", "an", "a", "if", "so", "do",
        "no", "we", "my", "me", "us", "up",
    }
    PHRASE_JOINERS = {"di", "del", "della", "dello", "dei", "degli", "delle", "d", "dell", "of"}
    # Articoli e preposizioni elisi ("dell'azienda" -> "azienda"); "life's" resta intero
    ELISION_PREFIXES = {"l", "un", "dell", "nell", "all", "dall", "sull", "coll", "d", "c", "s", "m", "t",
                        "v", "n", "quest", "quell", "nessun", "po", "tutt", "anch", "dov", "com"}
    PHRASE_MIN_COUNT = 2  # una frase vista una volta sola non e' un tema
    # Un trigramma prende il posto dei suoi bigrammi solo se ne copre almeno questa quota delle
    # occorrenze: "posizionamento active well-being" (2) non spezza "active well-being" (5)
    PHRASE_EXTENSION_SHARE = 0.5

    def _get_emerging_topics(self, n: int) -> list[dict]:
        """Termini piu' frequenti: parole singole e frasi di 2-3 parole, con il filtro stopword IT/EN
        e il filtro sui nomi del topic.

        Le parole con il trattino restano intere ("well-being"). Le frasi ("active well-being",
        "punto vendita", "brand architecture") contano se compaiono almeno PHRASE_MIN_COUNT volte e
        prevalgono sulle parti: le occorrenze della frase non contano piu' per le sue parole.
        Esclude dinamicamente le parole presenti nel topic della simulazione
        per evitare rumore (es. "lens: 101" in una sim su un prodotto "SmartLens").
        """
        from collections import Counter
        import re
        # Estrai parole dal topic della simulazione (nomi del prodotto/argomento).
        # Prima splitta su camelCase/PascalCase (es. "SmartLens" -> "Smart Lens"),
        # poi tokenizza e applica lowercase.
        topic_raw = self._state.topic or ""
        # Inserisce spazio tra lower-Upper (es. "smartLens" -> "smart Lens")
        topic_split = re.sub(r"([a-zàèéìòùÀÈÉÌÒÙ])([A-Z])", r"\1 \2", topic_raw)
        # Inserisce spazio tra UpperUpper-Lower (es. "SMARTLens" -> "SMART Lens")
        topic_split = re.sub(r"([A-Z]+)([A-Z][a-zàèéìòùÀÈÉÌÒÙ])", r"\1 \2", topic_split)
        topic_text = topic_split.lower()
        topic_words = set(re.findall(r"[a-zàèéìòùÀÈÉÌÒÙ]+", topic_text))
        topic_words = {w for w in topic_words if len(w) > 3}
        topic_raw_lower = topic_raw.lower().replace("\u2019", "'")

        letters = "a-zA-ZàèéìòùÀÈÉÌÒÙ"
        token_re = re.compile(rf"[{letters}]+(?:[-'][{letters}]+)*")
        # Le frasi non attraversano punteggiatura, numeri o simboli
        clause_split = re.compile(r"[.,;:!?()\[\]{}\"«»“”…/|*#+=<>\d]+|\s[-–—]+\s|\s[-–—]+|[-–—]+\s")

        def tokens(clause: str) -> list[str]:
            out = []
            for tok in token_re.findall(clause):
                head, apos, rest = tok.partition("'")
                if apos and head in self.ELISION_PREFIXES:
                    out += [head, rest]
                elif apos and rest == "s" and (head in topic_words or tok not in brand_possessives):
                    # Possessivo: "acme's" -> "acme", "the brand's" -> "brand". Resta intero un nome con la
                    # maiuscola nei post che non e' il soggetto ("Life's", il marchio)
                    out.append(head)
                else:
                    out.append(tok)
            return out

        def is_content(tok: str) -> bool:
            head = tok.split("'")[0]  # "that's" vale come "that"
            return (len(tok) > 2 and tok not in self.ELISION_PREFIXES
                    and head not in self.PHRASE_FUNCTION_WORDS and head not in self.REPORT_STOPWORDS)

        word_counts: Counter = Counter()
        phrase_counts: Counter = Counter()
        brand_possessives = {
            m.lower() for post in self._state.social_feed[-100:]
            for m in re.findall(r"(?<![\w'])[A-ZÀ-Ý][\w-]*'s\b",
                                (post.get("content", "") or "").replace("’", "'").replace("`", "'"))
        }
        for post in self._state.social_feed[-100:]:
            text = post.get("content", "").lower().replace("\u2019", "'").replace("`", "'")
            for clause in clause_split.split(text):
                toks = tokens(clause)
                word_counts.update(
                    w for w in toks
                    if len(w) > 4
                    and w not in self.REPORT_STOPWORDS
                    and w not in topic_words
                    and is_content(w)
                )
                for i in range(len(toks) - 1):
                    a, b = toks[i], toks[i + 1]
                    if is_content(a) and is_content(b):
                        phrase_counts[(a, b)] += 1
                    if i + 2 < len(toks):
                        c = toks[i + 2]
                        if is_content(a) and is_content(c) and (is_content(b) or b in self.PHRASE_JOINERS):
                            phrase_counts[(a, b, c)] += 1

        def contains(longer: tuple, shorter: tuple) -> bool:
            k = len(shorter)
            return any(longer[i:i + k] == shorter for i in range(len(longer) - k + 1))

        # Prima i trigrammi: un bigramma conta solo per le occorrenze fuori dai trigrammi scelti
        selected: dict[tuple, int] = {}
        for phrase, count in sorted(phrase_counts.items(), key=lambda kv: (-len(kv[0]), -kv[1], kv[0])):
            words = [w for w in phrase if is_content(w)]
            if all(w in topic_words for w in words):
                continue
            parts = [phrase_counts.get(phrase[i:i + 2], 0) for i in range(len(phrase) - 1)] if len(phrase) > 2 else []
            if any(count < self.PHRASE_EXTENSION_SHARE * p for p in parts):
                continue
            count -= sum(c for longer, c in selected.items() if len(longer) > len(phrase) and contains(longer, phrase))
            if len(phrase) == 2:
                # Occorrenze che si sovrappongono a un bigramma gia' scelto (piu' frequente):
                # "posizionamento active" dentro "posizionamento active well-being"
                a, b = phrase
                count -= sum(phrase_counts.get((a, b, s[1]), 0) for s in selected if len(s) == 2 and s[0] == b)
                count -= sum(phrase_counts.get((s[0], a, b), 0) for s in selected if len(s) == 2 and s[1] == a)
            if count >= self.PHRASE_MIN_COUNT:
                selected[phrase] = count

        # La frase prevale sulle sue parti: le sue occorrenze non contano piu' per le parole singole
        for phrase, count in selected.items():
            for w in set(phrase):
                if w in word_counts:
                    word_counts[w] -= count
        terms = Counter({w: c for w, c in word_counts.items() if c > 0})
        def display(phrase: tuple) -> str:
            out = ""
            for w in phrase:
                out += w + ("'" if w in self.ELISION_PREFIXES else " ")
            return out.strip()

        terms.update({display(p): c for p, c in selected.items()})
        ranked = sorted(terms.items(), key=lambda kv: (-kv[1], -kv[0].count(" "), kv[0]))
        return [{"topic": w, "count": c} for w, c in ranked[:n]]

    def _compute_consensus(self) -> dict:
        if not self._state.agents:
            return {}
        strengths = [
            a.get("opinion_strength", 0.5) if isinstance(a, dict) else a.opinion_strength
            for a in self._state.agents
        ]
        mean = sum(strengths) / len(strengths)
        variance = sum((x - mean) ** 2 for x in strengths) / len(strengths)
        stance = self.stance_metrics()
        consensus = postprocess.stance_consensus_level(stance)
        return {
            "mean_opinion_strength": round(mean, 3),
            "opinion_strength_meaning": "conviction (how firmly the agent holds its position), not approval",
            "variance": round(variance, 3),
            "conviction_uniformity": (level := postprocess.conviction_uniformity_reading(variance)),
            "conviction_uniformity_label": t(self._lang, f"report.conviction_uniformity_levels.{level}"),
            "conviction_uniformity_meaning": ("how similar the agents' conviction is (from the variance). It is NOT "
                                              "consensus: a convinced supporter and a convinced critic have the same "
                                              "conviction"),
            # Consensus = agreement on the stance, and nothing else (rule 17)
            "consensus_level": consensus,
            "consensus_level_label": (t(self._lang, f"report.consensus_levels.{consensus}") if consensus
                                      else t(self._lang, "report.stance.not_measured")),
            "stance": postprocess.stance_observation(stance, self._lang),
            # Ultimo round: lo stesso valore del livello di confidenza (final_opinion_entropy)
            "opinion_entropy": (entropy := final_opinion_entropy(self._state)),
            # The one reading of this value: the metrics table and the post-check use the same table
            "opinion_entropy_label": postprocess.entropy_label(entropy, self._lang) or None,
            "opinion_entropy_definition": "opinion_entropy of the last round",
            "total_rounds": self._state.current_round,
            "total_posts": run_post_totals(self._state)["posts"],
            "total_interactions": run_post_totals(self._state)["interactions"],
            # Labels to write in the report instead of the field names
            "labels": {
                "mean_opinion_strength": t(self._lang, "report.labels.mean_conviction"),
                "variance": t(self._lang, "report.labels.variance"),
                "conviction_uniformity": t(self._lang, "report.labels.conviction_uniformity"),
                "consensus_level": t(self._lang, "report.labels.consensus_level"),
                "stance": t(self._lang, "report.labels.stance"),
                "opinion_entropy": t(self._lang, "report.labels.opinion_entropy"),
                "total_rounds": t(self._lang, "report.labels.rounds"),
                "total_posts": t(self._lang, "report.labels.total_posts"),
            },
        }
