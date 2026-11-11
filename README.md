# SwarMind

**Stress-test a message before you launch it.** SwarMind simulates how a population of AI agents,
built from your brief, reacts to a rebrand, a new price, a product launch or a crisis statement.
You read the debate, see which objections come up and how they spread, and walk into the client
meeting prepared for them.

[Italiano](README.it.md) · [Manual](docs/manual/en/README.md) · [License](LICENSE)

## What it is, and what it is not

SwarMind **is** a rehearsal tool for consultants, brand strategists and agencies:

- it surfaces the objections a narrative will meet, in the words people would use;
- it shows which groups push back, which arguments hold, how positions move over several rounds;
- it produces a structured report you can trace back, post by post, to the simulated debate.

SwarMind **is not** a forecast. It does not predict sales, adoption or market share, and its
numbers are not survey results. Agents are language-model personas: they reflect your brief and
the model's knowledge, with the biases of both. Treat the output as a structured brainstorm of
reactions, never as evidence about the real market.

## Features

- **Brief to population**: upload a brief (PDF, Word, text, Markdown, JSON or CSV); SwarMind builds a knowledge
  graph and a population of stakeholder personas from it.
- **Multi-round debate**: agents post, reply and change their minds; a ranked feed decides what
  gains traction. Templates add **critical voices** (at most 15% of the agents) so objections are
  not left to chance.
- **Five templates**: brand rebranding, product launch, B2B SaaS pricing, crisis communication,
  feature validation. English base with an Italian overlay.
- **Report**: main objections, supporting arguments, exposed groups, scenarios and recommendations,
  grounded in the brief and the agents' posts; consensus and confidence computed by code, not by
  the model; debate metrics (polarisation, echo chamber, information diversity).
- **Agent chat and PDF export**, per plan.
- **English and Italian** for the interface, the agents and the report.
- **Bring your own model**: OpenRouter, Groq, OpenAI or Anthropic keys, stored encrypted; models
  chosen per project and per simulation.
- **Admin area**: users, plans and quotas, simulations, audit log, site & branding, an optional
  public landing page.

## Screenshots

<!-- Screenshots: add images under docs/images/ and reference them here. -->
_Dashboard · Simulation feed · Report · Knowledge graph · Admin_ (coming soon)

## Quick start (Docker)

Requirements: Docker Engine 24+ with Compose v2, 4 CPU cores and 8 GB RAM recommended, and an API key
for at least one LLM provider.

```bash
git clone https://github.com/DolcevitaInteractiveStudio/swarmind.git swarmind
cd swarmind
./start.sh
```

`start.sh` creates `.env` from `.env.example` with random secrets, builds the images and starts the
services. The manual way:

```bash
cp .env.example .env
# ENCRYPTION_KEY is required; generate one and paste it into .env:
python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
# also replace POSTGRES_PASSWORD, CHROMA_TOKEN and REDIS_PASSWORD with random values
docker compose up -d --build
```

Then create the first administrator (the password is asked twice):

```bash
docker compose exec backend flask --app run create-superadmin --email you@example.com
```

Open <http://localhost:3000>, sign in, add a provider key in **AI connections**, create a project
from a brief and run a simulation. The [manual](docs/manual/en/README.md) walks through each step.

All ports are bound to `127.0.0.1`. To serve SwarMind on a domain, put a reverse proxy with TLS in
front of port 3000 and set `FRONTEND_URL`: see
[Installation and reverse proxy](docs/manual/en/01-installation.md).

## Configuration

Everything is in `.env`; [`.env.example`](.env.example) documents every setting. The main ones:

| Setting | Purpose |
|---|---|
| `ENCRYPTION_KEY` | Required. Encrypts the stored provider keys. Back it up; never change it casually |
| `SECRET_KEY` | Signs login tokens. Empty: derived from `ENCRYPTION_KEY` |
| `POSTGRES_PASSWORD`, `CHROMA_TOKEN`, `REDIS_PASSWORD` | Internal service credentials |
| `TRUSTED_PROXY_COUNT` | Proxies in front of the backend: `1` with Compose alone, `2` behind a host reverse proxy |
| `LOGIN_MAX_FAILURES_PER_ACCOUNT`, `LOGIN_MAX_FAILURES_PER_IP` | Failed sign-ins allowed per account and per IP in 15 minutes |
| `FRONTEND_URL` | Public URL of the app (CORS and WebSocket origin) |
| `SIMULATION_DEFAULT_LANGUAGE` | `en` or `it` |
| `KB_EMBEDDING` | Empty for multilingual-e5-small, `default` for Chroma's built-in model |
| `CONTACT_EMAIL`, `BILLING_ENABLED` | Landing page contact; plan and billing pages |
| `GROQ_API_KEY` | Optional system key for users without keys of their own |
| `GRAPH_SYSTEM_KEY_MONTHLY_LIMIT` | Graph builds per user and month on the system key (default 20) |

## LLM providers

Each user connects their own accounts in **AI connections**: OpenRouter, Groq, OpenAI or
Anthropic. Keys are encrypted with `ENCRYPTION_KEY` (Fernet) before they are stored. Models are
picked per project (the *heavy* model: knowledge graph, population, report) and per simulation
(the *agent* model for personas, the *fast* model for the debate rounds). A good starting point:
a strong model such as `anthropic/claude-sonnet-4.5` as heavy and `google/gemini-2.5-flash` as fast,
both through OpenRouter. Costs and data handling are those of the provider you choose: the brief and
the debate are sent to it.

## Upgrade

```bash
git pull
docker compose build
docker compose run --rm backend flask --app run db upgrade
docker compose up -d
```

Read [CHANGELOG.md](CHANGELOG.md) first, and back up before upgrading:
[Operations](docs/manual/en/08-operations.md).
Upgrading from 1.0.0: add `REDIS_PASSWORD` to `.env` and run `docker compose up -d --no-deps redis` before the
migrations
([Operations](docs/manual/en/08-operations.md#upgrading-from-100-redis-password)).

## Documentation

- [Manual (English)](docs/manual/en/README.md) · [Manuale (italiano)](docs/manual/it/README.md)
- [Runbooks](docs/runbooks/) for maintenance tasks
- [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md) · [Changelog](CHANGELOG.md)

## License

Copyright (C) 2026 DolceVita Interactive Studio.

SwarMind is free software: you can redistribute it and/or modify it under the terms of the
[GNU Affero General Public License v3.0](LICENSE). If you run a modified version as a network
service, you must offer its source code to its users (AGPL-3.0, section 13). Third-party components
and their licenses are listed in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
