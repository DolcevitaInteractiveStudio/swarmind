"""Demographer: analizza un brief e propone una distribuzione tipologica
di stakeholder come PopulationSpec.

Brief-driven puro: NON riceve il template YAML scelto dall'utente. La stessa
popolazione viene generata indipendentemente dal tipo di simulazione. Il
template continua a guidare la dinamica del dibattito, non la composizione.

Componente standalone: testabile via CLI senza integrazione col resto della
pipeline.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any

import structlog

from ..core.i18n import normalize_language, with_directive
from ..core.llm import get_llm, get_llm_for_project

log = structlog.get_logger()


DEMOGRAPHER_SYSTEM = """You are a market research expert specialized in
identifying stakeholder populations for product/strategy simulations.

Given a brief describing a product, service, or strategic decision, your
job is to identify WHO should be in the room when this is debated. Not
WHAT (concepts, features, regulations) but WHO (people, roles, segments).

You produce a structured PopulationSpec describing the typological
distribution of stakeholders, with realistic percentages reflecting the
real composition of the relevant market or context.

Return ONLY valid JSON with this exact schema:
{
  "domain_summary": "1-2 sentence summary of what the brief is about",
  "subject": {
    "name": "Exact name of the company, brand or product the brief is about",
    "what_it_is": "What it is, max 12 words, without repeating the name",
    "sector": "Its sector, max 8 words",
    "market": "Geography and type of market, max 8 words",
    "change_tested": "The operation being tested, max 20 words",
    "homonyms_to_avoid": ["unrelated thing with the same or a similar name"],
    "language": "ISO 639-1 code of the brief's language, e.g. it or en"
  },
  "total_agents": <int, the requested agent count>,
  "segments": [
    {
      "segment_id": "snake_case_unique_id",
      "label": "Human-readable segment name",
      "percentage": <int, 0-100>,
      "count": <int, computed as round(total_agents * percentage / 100)>,
      "role_description": "Who they are, age range, key context",
      "key_attitudes": ["attitude 1", "attitude 2", ...],
      "typical_motivations": ["motivation 1", ...],
      "typical_fears": ["fear 1", ...],
      "communication_style": "How they typically express themselves"
    }
  ],
  "rationale": "2-4 sentences explaining WHY this distribution. Anchor it
                to the specific domain and brief content.",
  "critical_voices": [
    {
      "name": "Short descriptive label for this critical voice, not a personal name",
      "role": "Their role in the subject's sector or market",
      "background": "2-3 sentences: who they are and why they doubt the change tested",
      "core_beliefs": ["critical conviction about the change tested, in their own words", ...],
      "fears": ["fear 1", ...],
      "motivations": ["motivation 1", ...]
    }
  ]
}

CRITICAL RULES:
1. Identify 4-8 segments. Fewer = lacks diversity. More = fragmentation.
2. Percentages must sum to 100. Counts must sum to total_agents (rounding
   may produce off-by-one; if so, adjust the largest segment).
3. Segments must be PEOPLE/ROLES, never concepts, products, or places.
4. Be specific to the actual domain in the brief, not generic. A brief
   about Italian motorcycle driving schools should produce
   instructors/owners/students, NOT "generic users" or "stakeholders".
5. Include adversarial-leaning natural segments where realistic (e.g.,
   "skeptical accountant", "competitor partisan"). These are NOT the
   same as system-injected adversarial agents - they are organic critical
   voices that exist in the real market.
6. Write rationale that a domain expert would find defensible. If you
   don't know the market well, say so honestly in the rationale rather
   than inventing confident percentages.
{LANGUAGE_RULE}
8. SUBJECT: state what the brief is actually about, so that a reader who only
   sees the name cannot misread it. Use homonyms_to_avoid when the name is
   also a common word or belongs to something unrelated (e.g. a fashion brand
   that shares its name with a lottery). Use an empty list if there are none:
   do NOT invent homonyms.
9. CRITICAL VOICES: list the 2-3 people most likely to publicly challenge the
   change tested, from THIS subject's own sector and market. Their role, concerns
   and vocabulary must belong to that sector: do NOT carry over software,
   subscription or vendor-procurement framing unless the subject itself sells
   those. Each voice must object to this subject and this change, not express
   generic skepticism. Write their background and core_beliefs in your own words,
   in the language required by rule 7: paraphrase the brief, do not copy its
   sentences, and do not invent specific numbers, dates or company events.
"""


# Rule 7, without a simulation language (CLI tools): the language of the brief
_LANGUAGE_RULE_BRIEF = """7. LANGUAGE: detect the language of the brief and produce ALL human-readable
   text fields in THAT SAME LANGUAGE. This means: domain_summary, the text
   fields of subject, label, role_description, all items in
   key_attitudes/typical_motivations/typical_fears, communication_style,
   rationale and the text fields of critical_voices must match the brief's
   language. Italian brief -> Italian
   output. English brief -> English output. Spanish brief -> Spanish output.
   The ONLY fields that do not follow this rule are segment_id (it is a
   snake_case identifier, not user-facing text) and subject.language (it is
   a code)."""

# Rule 7 of a simulation: the simulation language (final instruction of the user message),
# whatever the language of the brief
_LANGUAGE_RULE_SIMULATION = """7. LANGUAGE: produce ALL human-readable text fields in the language given by
   the final instruction of the user message, whatever the language of the
   brief. This means: domain_summary, the text fields of subject, label,
   role_description, all items in key_attitudes/typical_motivations/typical_fears,
   communication_style, rationale and the text fields of critical_voices.
   The ONLY fields that do not follow this rule are segment_id (it is a
   snake_case identifier, not user-facing text) and subject.language (the
   code of the BRIEF's language, not of your output)."""


def demographer_system(language: str | None) -> str:
    """System prompt: rule 7 follows the simulation language, or the brief without one."""
    rule = _LANGUAGE_RULE_SIMULATION if normalize_language(language) else _LANGUAGE_RULE_BRIEF
    return DEMOGRAPHER_SYSTEM.replace("{LANGUAGE_RULE}", rule)


@dataclass
class Segment:
    """Singolo segmento tipologico nella popolazione."""
    segment_id: str
    label: str
    percentage: int
    count: int
    role_description: str
    key_attitudes: list[str] = field(default_factory=list)
    typical_motivations: list[str] = field(default_factory=list)
    typical_fears: list[str] = field(default_factory=list)
    communication_style: str = ""


@dataclass
class PopulationSpec:
    """Distribuzione tipologica completa proposta dal Demographer."""
    domain_summary: str
    total_agents: int
    segments: list[Segment]
    rationale: str
    # Opzionale, schema in DEMOGRAPHER_SYSTEM. Vuoto nelle spec precedenti al campo:
    # dict e non dataclass perche' una chiave in piu' dell'LLM non deve bloccare lo spawn.
    subject: dict[str, Any] = field(default_factory=dict)
    # Opzionale come subject. Usate solo dalle simulazioni senza template
    # (vedi integration.critical_voices_for_spec): il Demographer non conosce il template.
    critical_voices: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "domain_summary": self.domain_summary,
            "total_agents": self.total_agents,
            "segments": [asdict(s) for s in self.segments],
            "rationale": self.rationale,
        }
        if self.subject:
            data["subject"] = self.subject
        if self.critical_voices:
            data["critical_voices"] = self.critical_voices
        return data

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PopulationSpec:
        subject = d.get("subject")
        critical_voices = d.get("critical_voices")
        return cls(
            domain_summary=d["domain_summary"],
            total_agents=int(d["total_agents"]),
            segments=[Segment(**s) for s in d["segments"]],
            rationale=d["rationale"],
            subject=subject if isinstance(subject, dict) else {},
            critical_voices=critical_voices if isinstance(critical_voices, list) else [],
        )

    def normalize(self) -> dict[str, Any]:
        """Auto-correzione deterministica per garantire coerenza aritmetica.

        I LLM (anche forti) sbagliano spesso le somme di percentuali e count
        quando devono ragionare contemporaneamente su segmentazione qualitativa
        e vincoli numerici. Questa funzione "rimette in ordine":

          1. Riscala le percentuali proporzionalmente per somma=100
          2. Ricalcola i count da round(total_agents * pct / 100)
          3. Aggiusta il segmento piu' grande di +/-1 per far quadrare i count
          4. Ritorna un dict con cosa e' stato cambiato (per logging/audit)

        Idempotente: chiamarla due volte produce lo stesso risultato.
        Non distrugge informazione: le percentuali del LLM sono gia'
        approssimazioni qualitative, normalizzarle conserva le proporzioni
        relative tra segmenti.
        """
        if not self.segments:
            return {"changed": False, "reason": "no segments"}

        original_pcts = [s.percentage for s in self.segments]
        original_counts = [s.count for s in self.segments]
        original_pct_sum = sum(original_pcts)
        original_count_sum = sum(original_counts)

        changes: dict[str, Any] = {
            "changed": False,
            "original_pct_sum": original_pct_sum,
            "original_count_sum": original_count_sum,
            "target_total_agents": self.total_agents,
        }

        # Step 1: riscala le percentuali se non sommano a 100
        if original_pct_sum != 100 and original_pct_sum > 0:
            scale = 100.0 / original_pct_sum
            scaled = [s.percentage * scale for s in self.segments]
            # Round mantenendo somma=100 con largest-remainder method
            floored = [int(x) for x in scaled]
            remainders = [(x - int(x), i) for i, x in enumerate(scaled)]
            deficit = 100 - sum(floored)
            # Distribuisci il deficit ai segmenti con remainder piu' alto
            remainders.sort(key=lambda t: t[0], reverse=True)
            for k in range(abs(deficit)):
                idx = remainders[k % len(remainders)][1]
                floored[idx] += 1 if deficit > 0 else -1
            for i, seg in enumerate(self.segments):
                seg.percentage = max(0, floored[i])
            changes["changed"] = True
            changes["pct_rescaled"] = True

        # Step 2: ricalcola i count da percentuali normalizzate
        new_counts = [
            round(self.total_agents * s.percentage / 100.0)
            for s in self.segments
        ]
        # Step 3: aggiusta per far quadrare la somma a total_agents
        delta = self.total_agents - sum(new_counts)
        if delta != 0:
            # Trova l'indice del segmento piu' grande per assorbire il delta
            largest_idx = max(
                range(len(self.segments)),
                key=lambda i: self.segments[i].percentage,
            )
            new_counts[largest_idx] += delta
        for i, seg in enumerate(self.segments):
            seg.count = max(0, new_counts[i])

        if new_counts != original_counts:
            changes["changed"] = True
            changes["counts_adjusted"] = True

        return changes

    def validate(self) -> list[str]:
        """Validazione interna - ritorna lista di problemi (vuota = ok).

        Eseguita DOPO normalize() in Demographer.run(). Resta come safety net
        per intercettare bug catastrofici (es. normalize buggato), ma in
        pratica dovrebbe sempre passare quando chiamata via run().
        """
        problems = []
        if not self.segments:
            problems.append("no segments defined")
            return problems

        total_pct = sum(s.percentage for s in self.segments)
        if total_pct != 100:
            problems.append(f"percentages sum to {total_pct}, not 100")

        total_count = sum(s.count for s in self.segments)
        if total_count != self.total_agents:
            problems.append(
                f"counts sum to {total_count}, not total_agents={self.total_agents}"
            )

        ids = [s.segment_id for s in self.segments]
        if len(set(ids)) != len(ids):
            problems.append(f"duplicate segment_ids: {ids}")

        if not (4 <= len(self.segments) <= 8):
            problems.append(
                f"segment count {len(self.segments)} outside recommended range 4-8"
            )

        return problems


class Demographer:
    """Genera una PopulationSpec da un brief testuale via LLM."""

    def __init__(
        self,
        llm=None,
        tier: str = "heavy",
        project_id: str | None = None,
    ):
        """Init Demographer.

        LLM resolution order:
          1. explicit `llm` argument (used by tests with mocks)
          2. `project_id` -> get_llm_for_project (uses project's
             configured provider/credentials/models)
          3. fallback to system default get_llm()
        """
        if llm is not None:
            self._llm = llm
        elif project_id:
            self._llm = get_llm_for_project(project_id)
        else:
            self._llm = get_llm()
        self._tier = tier
        self._project_id = project_id

    async def run(
        self,
        brief: str,
        total_agents: int = 30,
        temperature: float = 0.4,
        language: str | None = None,
    ) -> PopulationSpec:
        """Analizza il brief e produce la PopulationSpec.

        Args:
            brief: testo del brief (input cliente)
            total_agents: numero di agenti target per la simulazione
            temperature: bassa di default per favorire output strutturato
                         e ragionamento di dominio coerente
            language: lingua della simulazione (en|it) per i testi della spec.
                      None (tool CLI): la lingua del brief

        Returns:
            PopulationSpec validata (validation problems loggati come warning)
        """
        log.info(
            "demographer_start",
            brief_chars=len(brief),
            total_agents=total_agents,
            tier=self._tier,
            language=language or "brief",
        )

        user_msg = (
            f"Analyze this brief and produce a PopulationSpec for "
            f"{total_agents} agents.\n\n"
            f"=== BRIEF ===\n{brief}\n=== END BRIEF ==="
        )
        if normalize_language(language):
            user_msg = with_directive(user_msg, language)

        raw = await self._llm.complete(
            messages=[
                {"role": "system", "content": demographer_system(language)},
                {"role": "user", "content": user_msg},
            ],
            tier=self._tier,
            temperature=temperature,
            max_tokens=6000,
            json_mode=True,
        )

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            log.error("demographer_json_parse_failed", error=str(e), raw_preview=raw[:500])
            raise ValueError(f"Demographer LLM returned invalid JSON: {e}") from e

        spec = PopulationSpec.from_dict(parsed)
        if not spec.subject:
            log.warning("demographer_subject_missing", note="subject card falls back to domain_summary")

        # Auto-correzione deterministica: i LLM sbagliano spesso le somme
        # di percentuali/count quando ragionano su segmentazione qualitativa.
        # normalize() riscala in modo idempotente per garantire coerenza
        # aritmetica senza distruggere le proporzioni semantiche.
        norm_changes = spec.normalize()
        if norm_changes.get("changed"):
            log.info(
                "demographer_normalized",
                **{k: v for k, v in norm_changes.items() if k != "changed"},
            )

        problems = spec.validate()
        if problems:
            log.warning(
                "demographer_validation_problems_after_normalize",
                problems=problems,
                segments_count=len(spec.segments),
                note="should not happen normally - investigate normalize logic",
            )
        else:
            log.info(
                "demographer_done",
                segments_count=len(spec.segments),
                total_agents=spec.total_agents,
                normalized=norm_changes.get("changed", False),
            )

        return spec
