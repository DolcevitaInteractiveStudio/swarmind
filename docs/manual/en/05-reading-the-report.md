# 5. Reading the report

[Manual index](README.md) · Previous: [Running a simulation](04-running-a-simulation.md) · Next: [Templates](06-templates.md)

The report is written by a language model and then **checked and completed by code**: every number
that measures the simulation (consensus, confidence, debate metrics, segment counts) is computed
deterministically, not written by the model. This chapter explains how to read those numbers and
what they cannot tell you.

## What the report is

A structured reading of a simulated debate, built from your brief. It tells you which objections
came up, which arguments held, which groups pushed back and how positions moved. It is **not a
forecast**: agents are language-model personas, the sample is small, and percentages describe the
simulated population, never the real market.

## Grounding: where the facts come from

The report reasons only from the brief, the agents' posts and the data the system computed:

- a number, date, amount or company name that appears in neither the brief nor the posts is removed
  from the analysis sections;
- a claim an agent made is kept but attributed ("according to <agent>"): an agent's opinion is not
  evidence;
- segment shares of the population are never presented as market weights.

If the report feels generic, the brief is usually too thin ([chapter 3](03-projects-and-briefs.md#write-a-complete-brief)).

## Stance and conviction: two different things

- **Stance** is the agent's *position* on the change being tested: **support**, **neutral** or
  **oppose**. It is measured when the agent is created and every 3 rounds. An unclear answer counts
  as neutral and is flagged.
- **Conviction** (`opinion_strength`, 0 to 1) is *how strongly* the agent holds its opinion, whatever
  that opinion is.

An agent can be strongly convinced and neutral, or weakly convinced and opposed. The report never
calls uniform conviction "consensus": it calls it **conviction uniformity** (high when the variance
is below 0.05, medium below 0.15, low otherwise).

## Consensus

Consensus is agreement on **stance** among the **natural agents** (critical voices are excluded,
unless no natural agent was measured):

| Consensus | Share of agents on the most common final stance |
|---|---|
| High | 75% or more |
| Medium | 50% to under 75% |
| Low | under 50%, **or any tie** between two stances |

"Majority" is used only above 50%; at 50% or less the report says "plurality".

**Shift** is the share of agents measured at least twice whose stance changed: stable under 15%,
moderate from 15%, large from 35%, but "large" requires at least 10 re-measured agents (with fewer,
one agent decides the reading and it is capped at moderate).

**Per segment**, percentages are shown only for segments with at least 3 agents; smaller segments
show counts ("1 of 1 oppose").

## Confidence and its sample caps

The confidence line at the top of the *Confidence assessment* section is written by the code; the
model is not allowed to change it. It combines two things.

1. **Stability of the result**, from the stance:
   - **Low**: consensus is low, or the shift is large;
   - **High**: consensus is high, the shift is stable, and at least 10 agents were re-measured;
   - **Medium**: everything else.
2. **A cap from the sample size**, because a small simulation cannot support a strong claim:

   | Sample | Maximum confidence |
   |---|---|
   | fewer than 20 agents, **or** fewer than 5 rounds, **or** fewer than 50 posts | Low (shown as "indicative") |
   | fewer than 50 agents, **or** fewer than 10 rounds, **or** fewer than 200 posts | Medium |
   | larger | no cap |

The final level is the lower of the two. The line states the sample and the reason for any cap.
Confidence is not calibrated against real outcomes: it says how stable the result is *inside the
simulation*, not how likely it is to happen.

## Critical voices and the adversarial share

Templates (and you) add critical voices, personas built to raise objections. They are capped at 15%
of the agents and at 25% of the posts, are listed separately in the report, and do not count in the
consensus. If some had to be dropped to respect the cap, the appendix says so.

Read their objections as a checklist of attacks your message must survive, not as a measure of how
common those attacks are.

## Debate dynamics

The *Debate dynamics* section starts with a table computed by the system (no model involved),
followed by a short reading.

| Metric | What it measures | Reading |
|---|---|---|
| **Polarisation delta** | Change in polarisation of **conviction** (not of stance) from the first to the last round; polarisation per round = min(1, 4 × variance of conviction) | above +0.15 (or a large relative rise): active polarisation; below −0.05: depolarisation; otherwise stable. ±0.05 is noise |
| **Echo-chamber index** | Average similarity of the posts within each round (sentence embeddings) | above 0.70: echo chamber; above 0.50: partial debate; otherwise parallel silos. If the embedding model is unavailable, a word-overlap fallback is used with thresholds 0.30 / 0.15, and the report says so |
| **Information diversity** | Change in the number of distinct keywords per round, second half vs first half | below −30%: rapid collapse; below −10%: gradual convergence; above +20%: growing diversity; otherwise stable |

These metrics need at least 2 or 3 rounds. They describe the simulated conversation; they do not
transfer to real social networks.

## Why scenarios have no percentages

The report ranks scenarios only as **most plausible**, **plausible** or **less plausible**, with at
most one "most plausible". Probabilities are removed by the code even if the model writes them:
on a few hundred posts written by language models, a figure like "62%" is false precision.

When confidence is Low and consensus is not high (or stance was not measured), no scenario can be
called "most plausible", and the report adds a note.

Percentages that describe data ("40% of the agents oppose") stay: they count the simulation, they
do not predict.

## Run-to-run variability

Two simulations of the same brief will not give identical reports. Agents are sampled at random in
each round and personas are written with a high temperature, on purpose, to keep the population
diverse. With small samples one agent moves the distribution by several points: with fewer than 20
agents, a single agent is more than 5 points.

In practice:

- trust the **objections and arguments that come back** across runs more than any single number;
- before a client meeting, run the same configuration two or three times and compare the stance
  distribution and the main objections;
- change one thing at a time (template, models, brief) when you compare runs.

## Report structure

Typical sections: summary, main objections, supporting arguments, exposed segments, the
template's mandatory sections, debate dynamics, scenarios, recommendations, confidence assessment and
an appendix with the parameters of the run (agents, rounds, models, template, critical voices,
truncations). Export to Markdown or PDF with the buttons above the report (Pro and Enterprise).
