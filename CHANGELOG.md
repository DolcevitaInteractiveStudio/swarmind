# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
