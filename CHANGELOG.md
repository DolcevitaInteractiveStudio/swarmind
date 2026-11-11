# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

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
