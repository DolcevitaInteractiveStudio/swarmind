"""
Mapping nomi semantici -> descrizione sezione markdown per il ReportAgent.

I template di simulazione referenziano questi nomi in report_focus.mandatory_sections.
Il ReportAgent costruisce il REPORT_FORMAT dinamicamente usando queste definizioni.

Il titolo di ogni sezione e' nel catalogo (locales, report.sections.<nome>), nella lingua della
simulazione; il prompt e' qui, in inglese (la lingua del report la decide la direttiva finale).

Per aggiungere una nuova sezione semantica:
  1. Aggiungi una chiave a SECTION_DESCRIPTIONS con il prompt
  2. Aggiungi il titolo a report.sections.<nome> in tutti i file di locales
  3. Referenziala nel report_focus.mandatory_sections di un template
"""
from app.core.i18n import DEFAULT_LANGUAGE, t

SECTION_DESCRIPTIONS = {
    # ── Template: b2b_saas_pricing ─────────────────────────────────────────
    "objections_analysis": {
        "prompt": (
            "List the objections raised by the critical (adversarial) agents, "
            "grouped by theme. Quote posts verbatim as evidence. "
            "Distinguish rational objections (cost, ROI, lock-in) from emotional "
            "objections (distrust, fatigue, betrayal)."
        ),
    },
    "buyer_rationalizations": {
        "prompt": (
            "Identify how the favourable agents justify the purchase. "
            "Describe the argument patterns that emerge, quoting posts "
            "verbatim as evidence. Point out whether the agents cite specific "
            "features and verifiable ROI or use generic language with no "
            "concrete referents. Do not rank the agents as 'solid' vs "
            "'fragile': report what they say and leave the interpretation "
            "to the reader."
        ),
    },
    "resistance_by_segment": {
        "prompt": (
            "Map the level of resistance to the price/proposal by customer "
            "segment. Identify which personas resisted the most and why, "
            "and which gave in quickly."
        ),
    },
    "pricing_levers": {
        "prompt": (
            "Based on the objections raised, list the concrete levers a "
            "seller can use to overcome price resistance: volume discounts, "
            "annual billing, trial period, guarantees, bundles, price freeze. "
            "State which lever would work best for each critical segment."
        ),
    },

    # ── Template: product_launch ───────────────────────────────────────────
    "messaging_gaps": {
        "prompt": (
            "Identify the parts of the launch message that the critical agents "
            "found weak, ambiguous or not credible. Point out specific "
            "sentences that could be screenshotted and used against the "
            "product. Suggest rewordings."
        ),
    },
    "positioning_risks": {
        "prompt": (
            "Assess whether the chosen positioning holds up against the "
            "alternatives the agents mention or the brief describes (no "
            "others). Identify the audience segments for "
            "which the positioning is unclear or risks putting them off. "
            "Point out inconsistencies between value proposition and target."
        ),
    },
    "early_adoption_signals": {
        "prompt": (
            "Describe the enthusiasm pattern of the favourable agents. "
            "For each relevant agent, report verbatim what they say and "
            "which use cases they cite (if any). Do not label the enthusiasm "
            "as 'substantial' or 'superficial': report the quotes and point "
            "out whether the agent cites specific features or uses generic "
            "language. Do not estimate retention, conversion or post-purchase "
            "metrics: the simulation measures pre-launch opinions, not real "
            "behaviour."
        ),
    },
    "competitive_response_prediction": {
        "prompt": (
            "From the posts of the competitor voices (adversarial 'indirect "
            "competitor') and of the agents who mention competitors, and from "
            "the competitors named in the brief, set out how competitors could "
            "respond, as hypotheses grounded in those posts ('if ..., it is "
            "plausible that ...'): the narratives they could use, the features "
            "they could stress, the segments they could try to protect. Name a "
            "competitor only if it appears in the brief or in a post; otherwise "
            "describe it ('a competitor focused on performance'). Suggest "
            "defensive counter-narratives."
        ),
    },

    # ── Template: feature_validation ───────────────────────────────────────
    "problem_severity": {
        "prompt": (
            "Assess how strongly the agents feel the problem the feature is "
            "meant to solve. Distinguish between a problem felt daily, an "
            "occasional problem and a theoretical problem. Quote textual "
            "evidence from the posts."
        ),
    },
    "workaround_analysis": {
        "prompt": (
            "Map the workarounds already used by the power-user agents. Assess "
            "how much the proposed feature is a real improvement over the "
            "workarounds, or whether it risks being less powerful/flexible. "
            "Identify the perceived migration cost."
        ),
    },
    "adoption_friction": {
        "prompt": (
            "Estimate how hard it is for each persona to adopt the feature: "
            "learning curve, team re-training, changes to existing workflows. "
            "Identify the persona with the lowest friction (first rollout "
            "target) and the one with the highest friction (possibly to be "
            "excluded)."
        ),
    },
    "opportunity_cost": {
        "prompt": (
            "Based on the voice of the internal Product Manager, compare the "
            "development/maintenance cost of the feature with the expected "
            "impact, as the agents and the brief describe them (no invented "
            "figures). Point out whether alternative features named in the "
            "brief or by the agents have a better impact/effort ratio. State "
            "explicitly if the recommendation is NOT to build it."
        ),
    },

    # ── Template: crisis_comms ─────────────────────────────────────────────
    "narrative_vulnerabilities": {
        "prompt": (
            "Identify the weak points of the proposed communication: "
            "ambiguities, suspicious omissions, contradictions, overly "
            "institutional tones, lack of accountability. Quote specific "
            "sentences that the journalist or the betrayed customer singled "
            "out as problematic."
        ),
    },
    "emotional_resonance": {
        "prompt": (
            "Assess how the message resonates emotionally in the different "
            "audience segments. Distinguish between a rational and an "
            "emotional response. The voice of the betrayed customer must "
            "carry weight: reputational damage emerges there, not in cold data."
        ),
    },
    "amplification_risks": {
        "prompt": (
            "From the posts, identify how the message could be amplified "
            "negatively: the sentences of the message that agents quoted, "
            "mocked or could screenshot, the reactions that could spread "
            "(irony, distrust, shares), the silences agents noticed. Present "
            "each risk as a hypothesis tied to a post ('if ..., it is plausible "
            "that ...'). Do not estimate timings or how long a reaction lasts, "
            "and do not compare with other cases or brands unless the brief or "
            "a post does."
        ),
    },
    "trust_recovery_path": {
        "prompt": (
            "Based on the reactions that emerged, suggest the minimum path of "
            "concrete actions to restore trust with each segment involved "
            "(customers, press, general public), each tied to the reaction it "
            "answers. Distinguish between immediate actions, medium term and "
            "long term, without fixed durations unless the brief gives them."
        ),
    },

    # ── Template: brand_rebranding ─────────────────────────────────────────
    "heritage_coherence": {
        "prompt": (
            "Assess how much the rebranding respects, evolves or betrays the "
            "brand heritage. Identify the elements of the historical "
            "heritage that the loyal-audience agents see as indispensable "
            "and those perceived as dead weight that can be left behind. "
            "Quote posts verbatim as evidence. Distinguish between criticism "
            "based on emotional attachment and criticism based on a strategic "
            "reading of the brand. Do not rank the two categories as "
            "'rational' vs 'irrational': both weigh on the outcome. Cite the "
            "brand's history, slogans or campaigns only as the brief or the "
            "posts give them."
        ),
    },
    "generational_bridge": {
        "prompt": (
            "Analyse the central risk of a rebranding that changes target: "
            "alienating the historical audience while trying to win the new "
            "one, without convincing either. Map three dimensions: (1) how "
            "the loyal historical audience reacts to the operation, (2) how "
            "the intended new target reacts, (3) whether there is common "
            "narrative ground between the two or the choice creates a rift. "
            "If the new-target agents express skepticism or cynicism about "
            "the operation, this is a strong signal: the rebranding is not "
            "only at risk of losing the old audience, it is failing with the "
            "new one too. Quote textual evidence for each dimension."
        ),
    },

    # ── Sezione trasversale (tutti i template): debate_dynamics ────────────
    "debate_dynamics": {
        "prompt": (
            "This section is mandatory in every report. Under the heading the "
            "system inserts a deterministic table with the three DEBATE "
            "DYNAMICS METRICS (polarization_delta, echo_chamber_index, "
            "information_diversity), their values and their interpretation: do "
            "NOT rewrite it, do not repeat the table and do not report values "
            "different from those of the metrics block in the user prompt. "
            "Write only a short reading (4-6 sentences) that connects the three "
            "metrics to the simulation topic and to the voices of the top "
            "influencers you observed. Close with a summary sentence that "
            "combines the three metrics: active polarization + strong echo "
            "chamber + falling diversity = a sign of rigid narrative "
            "consolidation. Stable polarization + parallel silos + high "
            "diversity = the topic did not generate a real debate but "
            "parallel monologues. Use this grid as a guide, not as a rigid "
            "scheme. The polarization is the polarization of CONVICTION "
            "(how strongly the agents hold their view): it says nothing "
            "about whether the agents changed position; for that, use only "
            "the stance shift. If a metric is 'insufficient_data', say so "
            "explicitly and explain what would have been needed to compute it."
        ),
    },
}


# Sezioni presenti in ogni report, con o senza template (in coda a quelle del template)
ALWAYS_SECTIONS = ("debate_dynamics",)


# Sezioni dei template che danno raccomandazioni (leve, riformulazioni, azioni, costruire o no): con una di
# queste, o con un titolo "Raccomandazioni", i limiti del metodo citano le raccomandazioni operative.
RECOMMENDATION_SECTIONS = ("pricing_levers", "messaging_gaps", "trust_recovery_path", "opportunity_cost")


def section_title(name: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """Titolo della sezione nella lingua della simulazione (catalogo)."""
    return t(lang, f"report.sections.{name}")


def get_section(name: str, lang: str = DEFAULT_LANGUAGE) -> dict | None:
    """Ritorna title + prompt per una sezione semantica, o None se sconosciuta."""
    section = SECTION_DESCRIPTIONS.get(name)
    return {"title": section_title(name, lang), **section} if section else None


def known_sections() -> list[str]:
    """Lista dei nomi di sezione supportati (utile per validazione template)."""
    return sorted(SECTION_DESCRIPTIONS.keys())
