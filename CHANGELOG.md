# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security

- Sign-in throttling: failed password checks (sign-in and password change) are limited per account
  and per client IP, with a 429 answer and Retry-After, in English and Italian. New settings
  `LOGIN_MAX_FAILURES_PER_ACCOUNT`, `LOGIN_MAX_FAILURES_PER_IP`, `LOGIN_THROTTLE_WINDOW_SECONDS` and
  `TRUSTED_PROXY_COUNT` (client IP from `X-Forwarded-For`).
- A password change or reset signs out the user's other sessions (`token_version`, migration
  `f1b7d3c9a2e5`). Tokens issued before the upgrade stay valid until the next password change.
- Redis requires a password (`REDIS_PASSWORD`); the app refuses to start, with the reason, when Redis
  and `REDIS_URL` disagree.
- flask-cors 6.0.5 (CVE-2024-6221, CVE-2024-6844, CVE-2024-6866, CVE-2024-6839).

### Changed

- Graph builds use the user's own provider key whenever there is one; on the system key they are
  limited per user and month by `GRAPH_SYSTEM_KEY_MONTHLY_LIMIT` (default 20; migration `a8e2c4f6b0d3`).
- The unused `stripe` package is removed (rebuild the images).
- Continuous integration: backend tests with PostgreSQL, template validation, frontend checks and a
  gitleaks secret scan on every pull request and push to `main`.

### Upgrade notes (from 1.0.0)

1. Add `REDIS_PASSWORD` to `.env` (letters and digits only; `./start.sh` adds one).
2. Behind a reverse proxy on the host, set `TRUSTED_PROXY_COUNT=2`.
3. Rebuild the images (`docs/runbooks/rebuild-images.md`) and apply the migrations
   (`flask --app run db upgrade`).
4. Recreate Redis and the services: `docker compose up -d redis backend worker` (and `flower`).

## [1.0.0] — Initial public release

First release of SwarMind as open source, under the GNU AGPL v3.0.

### Included

- Brief upload (PDF, Word, text, Markdown, JSON, CSV), knowledge graph and per-project knowledge base.
- Population of stakeholder personas generated from the brief, with critical voices from the
  templates (at most 15% of the agents).
- Multi-round simulation with a ranked feed, agent memories and stance tracking.
- Report with consensus and confidence computed by code, debate metrics (polarisation delta,
  echo-chamber index, information diversity), scenarios without probabilities, PDF export and
  agent chat.
- Five simulation templates (brand rebranding, product launch, B2B SaaS pricing, crisis
  communication, feature validation), in English with an Italian overlay.
- English and Italian interface, agents and reports.
- Multi-provider LLM support (OpenRouter, Groq, OpenAI, Anthropic) with encrypted per-user keys.
- Admin area: users, plans and quotas, simulations, audit log, site & branding, optional landing page.
- Self-hosting: Docker Compose with Compose-managed volumes, `.env.example` covering every setting,
  `flask create-superadmin`, optional Flower profile, manual in English and Italian.
