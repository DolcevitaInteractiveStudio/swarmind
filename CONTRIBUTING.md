# Contributing to SwarMind

Thank you for helping. Bug reports, documentation fixes and focused pull requests are all welcome.

## Before you start

- For anything larger than a small fix, open an issue first and describe the problem and the
  change you have in mind. SwarMind's positioning is deliberate (a stress test for messages, not a
  market forecast): features that present simulated numbers as predictions will not be merged.
- Security problems: do **not** open a public issue, see [SECURITY.md](SECURITY.md).
- By contributing you agree that your contribution is licensed under the
  [AGPL-3.0](LICENSE), the license of the project.

## Development setup

```bash
cp .env.example .env          # set ENCRYPTION_KEY, see the README
docker compose up -d --build
docker compose exec backend flask --app run create-superadmin --email dev@example.com
```

`./backend` is bind-mounted into the backend and worker containers: after a Python change run
`docker compose restart backend worker`. For the frontend, either rebuild the `frontend` image or run
the Vite dev server (`cd frontend && npm install && npm run dev`) with a proxy to the backend.

## Tests and checks

GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the checks below on every
pull request and every push to `main`, the migration tests on PostgreSQL included, plus a gitleaks
secret scan ([`.gitleaks.toml`](.gitleaks.toml)). Run them locally before pushing.

Backend (inside the backend image, or a virtualenv with `requirements.txt -c constraints.txt`):

```bash
docker compose exec backend sh -c "pip install pytest pillow && python -m pytest tests"
docker compose exec backend python -m app.templates.validate   # after editing a template
```

The PostgreSQL migration tests run only when `SWARMIND_TEST_PG_URL` points to an empty database.

Frontend:

```bash
cd frontend
npm install
npm run check:i18n      # every key exists in en and it, no unused keys
npm run build
npm run check:bundle    # no runtime message compiler in the bundle
npm run check:contrast  # theme colours meet WCAG AA
```

## Guidelines

- **Languages**: the UI, the agents and the report are bilingual (en, it). New UI strings go in
  both `frontend/src/i18n/en.json` and `it.json`; new backend strings in
  `backend/app/locales/en.yml` and `it.yml`. Prompts are written in English and end with the
  language directive.
- **Templates** (`backend/app/templates/simulations/`): the English file holds the structure and
  numbers, `locales/it/` only the translatable fields. Keep them generic: no real brands, clients
  or people. Run the validator after every change.
- **Database**: schema changes need an Alembic migration in `backend/migrations/versions/`.
  Generate it outside the containers so the file is not owned by root.
- **Numbers in the report** (consensus, confidence, metrics) are computed by code. Do not ask the
  model to produce figures that look like measurements.
- **Test data** must be fictional: invented companies and people, no real brands or clients.
- Keep pull requests focused, describe how you tested them, and update the manual
  (`docs/manual/en` and `docs/manual/it`) when behaviour changes.
