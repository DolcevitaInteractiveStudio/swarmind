# Security policy

## Reporting a vulnerability

Please report security problems **privately**, never in a public issue or pull request:

- use GitHub's private vulnerability reporting: the **Security** tab of this repository →
  **Report a vulnerability**.

Include the affected version or commit, the steps to reproduce, and the impact you expect.
We aim to acknowledge reports within 5 working days and to agree on a disclosure date with you.
Please give us a reasonable time to release a fix before any public disclosure.

## Supported versions

Security fixes are made on the latest release on the `main` branch.

## Scope and hardening notes for operators

SwarMind is designed to run behind a reverse proxy with TLS, on a server you control:

- All container ports are bound to `127.0.0.1`. Only the reverse proxy should be reachable from
  the network.
- Keep `.env` private (`chmod 600 .env`) and backed up. `ENCRYPTION_KEY` protects the stored LLM
  provider keys; `SECRET_KEY` (or, when empty, a key derived from `ENCRYPTION_KEY`) signs login
  tokens.
- Replace every `change-me` value of `.env.example`.
- Flower (Celery monitoring) is off by default; if you enable it, set a strong `FLOWER_PASSWORD`
  and keep it on `127.0.0.1`.
- Briefs and simulations are sent to the LLM provider each user configures. Do not upload material
  you are not allowed to share with that provider.

Out of scope: findings that need a compromised server or `.env`, denial of service through
expensive LLM calls by an authenticated user within their plan, and reports from automated scanners
without a demonstrated impact.
