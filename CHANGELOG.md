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

### Fixed

- Italian text owned by the code uses real accents (no "e'", "piu'"); a test guards the catalogues,
  the Italian template text and the frontend strings.
- Report quotes never end mid-word: post excerpts are cut at the end of a sentence or of a word, and
  a quote cut mid-word is shortened to its last complete sentence or removed.
- No internal names in the report: excluded critical-voice archetypes, template ids, configuration
  keys and sampling methods. The appendix states the same facts in plain language and explains the
  two different caps (share of critical agents vs share of critical posts).
- Top influencers are natural agents only; the critical voices' post counts are listed apart.
- An agent never publishes the same post twice: one retry asking for something new, then the post
  is skipped (`repetition_retries` / `repetition_skipped` in the run counters).
- Report writing rules: complete sentences, agent lists as "name (role)".
- Wrong consensus thresholds next to a level, list counts after a removed item, "enthusiastic
  adoption" with few enthusiastic agents, the recommendations limitation in reports without
  recommendations.
- The feed tab shows the real number of posts (it stopped at 500) and the newest posts first.
- The plans page lists the plans (it was empty for every user); with no payment flow, a change of
  plan goes through the contact address, and a user on the highest plan is told so.

### Upgrade notes (from 1.0.0)

1. Add `REDIS_PASSWORD` to `.env` (letters and digits only; `./start.sh` adds one).
2. Check `TRUSTED_PROXY_COUNT`: `1` (default) when the host proxy sends `/api/` and `/socket.io/`
   straight to the backend, `2` when requests also pass through the frontend container's nginx.
   Never higher than the real number of proxies (clients could spoof their IP).
3. Rebuild the images (`docs/runbooks/rebuild-images.md`).
4. Recreate Redis first: `docker compose up -d --no-deps redis`. The app refuses to start while Redis
   and `REDIS_URL` disagree, and that includes the migration command.
5. Apply the migrations (`docker compose run --rm backend flask --app run db upgrade`), then
   `docker compose up -d`.

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
