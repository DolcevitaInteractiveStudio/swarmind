# 4. Running a simulation

[Manual index](README.md) · Previous: [Projects and briefs](03-projects-and-briefs.md) · Next: [Reading the report](05-reading-the-report.md)

Open a project whose graph is built and choose **New simulation**.

## Settings

| Setting | What it does |
|---|---|
| **Name** and **Question to test** | What the report must answer, for example "Will long-time subscribers accept the new price?" |
| **Template** | Optional. Adds critical voices, mandatory report sections and instructions for a type of test ([chapter 6](06-templates.md)) |
| **Agents** | Size of the population (default 100, capped by your plan) |
| **Rounds** | Length of the debate (default 30, capped by your plan) |
| **Language** | English or Italian: language of the agents' posts and of the report. Defaults to the interface language |
| **Models** | *Agent* model (writes the personas) and *fast* model (every post). The heavy model comes from the project |
| **Platform** | Tone of the simulated venue: social media, forum, financial or political |
| **Critical voices** | Optional, your own: one per line as `Name - Role`, for example `Procurement lead - Cuts every SaaS budget` |

Creating a simulation uses one simulation of your monthly quota. If it fails while spawning agents
or during the rounds (not because of a stop or a failed report), the quota is given back.

## What happens

1. **Population.** From the brief, a demographer step proposes stakeholder segments (4 to 8) with
   their share of the population; one persona is written per agent, inside its segment's traits.
   These segment shares are a design choice for the simulation, **not market weights**.
2. **Critical voices.** The template's adversarial personas and yours join the population, up to
   **15% of the agents** (`max_adversarial_share`). If there are more, a reproducible random
   selection is kept and the report says so in the appendix. Without a template, the brief can
   propose up to 3 critical voices to fill the free places. Critical voices are labelled as such
   and are **excluded from the consensus**.
3. **Rounds.** Each round a sample of agents reads a feed ranked by a hot score (recent and
   engaging posts first), with their own memories and the relevant parts of the brief, and decides
   what to do: write a post, comment, vote or share, depending on the platform. Critical voices may write at most 25% of the posts, so they
   cannot drown the debate. Every 3 rounds agents refresh their opinion and their **stance** on the
   change being tested (support, neutral, oppose) is measured again.
4. **Report.** A report agent queries the feed, interviews agents and writes the report; the code
   then computes the numbers and checks the text ([chapter 5](05-reading-the-report.md)).

Progress is live on the simulation page (rounds, posts, polarisation and entropy per round). You can
**stop** a simulation; a stopped simulation has no report.

## Choosing agents and rounds

- The report's confidence is capped by the sample: with fewer than 20 agents, 5 rounds or 50 posts
  it is at most **Low**; with fewer than 50 agents, 10 rounds or 200 posts at most **Medium**.
- For a first look at a brief, 30 to 50 agents and 10 rounds are enough to see the main objections.
- For a report you will show to a client, use at least 50 agents and 10 rounds, and run the
  simulation more than once (see [run-to-run variability](05-reading-the-report.md#run-to-run-variability)).
- Cost and time grow with agents × rounds: every active agent makes one call to the fast model per
  round.

## After the simulation

- **Feed**: every post and reply, by round and by agent.
- **Agents**: personas, segment, stance history.
- **Graph**: the knowledge graph of the brief.
- **Report**: see [chapter 5](05-reading-the-report.md). Export to Markdown or PDF (Pro and
  Enterprise).
- **Chat**: ask an agent why it changed its mind, or ask the report agent a question (Pro and
  Enterprise). Answers come from the persona and the report, in the simulation language.

When a simulation ends (completed, failed or stopped) its agent memories are deleted from Chroma;
posts, agents and the report stay.
