# 3. Projects and briefs

[Manual index](README.md) · Previous: [First admin and providers](02-first-admin-and-providers.md) · Next: [Running a simulation](04-running-a-simulation.md)

A **project** is one brief: the document that describes what you want to test. Every simulation
of the project starts from the same brief and the same knowledge graph.

## Create a project

**Projects → New project**:

1. **Name** and **topic** (what the simulation is about).
2. **Source document**: PDF, DOCX, TXT, MD, JSON or CSV, up to the file size of your plan.
3. **LLM**: one of your AI connections, and the *heavy* model for the project (graph, population,
   report). "System default (Groq)" appears only when the server has a system key.

If no provider is available (no system key and no connection of yours), the page asks you to
connect one in **AI connections** first; nothing is uploaded until you do.

After the upload SwarMind:

- extracts the text (PDF: the text layer only, scanned pages are not read; DOCX: paragraphs);
- builds a **knowledge graph** of entities and relations with the heavy model, in chunks of about
  3,000 words;
- stores the text in a **knowledge base** (Chroma), split into chunks of 120 words, that agents and
  the report query during the simulation.

The project page shows the progress. If the build fails, the error says why (invalid key, credit
exhausted, model not found, rate limit, provider error). Fix the cause and use **Rebuild**; while
rebuilding, the previous graph is kept.

## Write a complete brief

The report **only cites facts that are in the brief or in what the agents wrote**. Numbers, names,
dates and amounts that appear nowhere are removed from the analysis, or attributed to the agent who
said them. A thin brief gives a thin, generic report; a complete brief gives agents real material to
argue about and the report real facts to cite.

A good brief contains:

- **The subject**: company, product or service, and what exactly changes (new name, new price,
  launch, statement). State the change being tested in one sentence.
- **Facts**: prices, dates, features, what stays the same, what customers get. Agents can only react
  to what they know.
- **The market**: who the customers are, segments, competitors and their prices, the context
  (regulation, recent news).
- **The message**: the actual copy, claims or statement you want to test, word for word.
- **Known risks and open questions**: what worries you; the report will look for them.
- **What you want to learn**: the decision the simulation should inform.

Write in plain prose; headings and lists help. Several short documents can be merged into one file.
Remove what you are not allowed to send to your LLM provider: the whole brief is sent to it.

## Projects and plans

The number of projects and the maximum file size depend on the plan (Free: 3 projects, 5 MB; Pro:
20, 50 MB; Enterprise: unlimited, 500 MB). Deleting a project deletes its simulations.
