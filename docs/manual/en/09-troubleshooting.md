# 9. Troubleshooting

[Manual index](README.md) · Previous: [Operations](08-operations.md)

Start with `docker compose ps` and `docker compose logs --tail 200 backend worker`.

## Start-up

| Symptom | Cause and fix |
|---|---|
| `required variable POSTGRES_PASSWORD is missing a value` (or `CHROMA_TOKEN`) | `.env` is missing or incomplete. `cp .env.example .env` and fill it in |
| Backend exits with `ENCRYPTION_KEY environment variable is required` | Set `ENCRYPTION_KEY` in `.env` (generation command in `.env.example`), then `docker compose up -d` |
| `env file .env not found` | Run Compose from the checkout folder, after creating `.env` |
| Chroma stays `unhealthy` | Look at `docker compose logs chroma`. Too few open files: the Compose file sets `ulimits.nofile` to 65536, check that your Docker daemon allows it |
| Postgres: `password authentication failed` after changing `POSTGRES_PASSWORD` | The password is set only when the volume is created; change it in the database too ([Operations](08-operations.md#changing-secrets)) |
| Flower restarts with `Set FLOWER_PASSWORD in .env` | Set `FLOWER_PASSWORD`, or remove `monitoring` from `COMPOSE_PROFILES` |

## Signing in and the browser

| Symptom | Cause and fix |
|---|---|
| No account exists yet | Create the superadmin: `docker compose exec backend flask --app run create-superadmin --email …` |
| Forgotten superadmin password | Same command with `--reset-password` |
| Everyone signed out after an update | `SECRET_KEY` (or `ENCRYPTION_KEY`, when `SECRET_KEY` is empty) changed: sign in again |
| API calls fail with CORS errors, or progress never updates | `FRONTEND_URL` does not match the address in the browser (scheme, host and port). Fix it and `docker compose up -d backend` |
| Live progress missing behind a proxy | The proxy does not pass WebSocket upgrades on `/socket.io/` ([reverse proxy](01-installation.md#behind-a-reverse-proxy)) |
| Upload fails with 413 | The reverse proxy limits the request size: raise `client_max_body_size` (nginx) or `request_body max_size` (Caddy) |

## Providers and simulations

| Symptom | Cause and fix |
|---|---|
| "Your own API keys are available from the Pro plan" | The user is on the Free plan: assign Pro or Enterprise, or edit the Free plan (Admin panel → Plans) |
| Provider key stops working after a restore | `.env` was restored with a different `ENCRYPTION_KEY`: restore the original or have users connect their keys again |
| Graph build fails: the document has no readable text | Scanned PDF without a text layer: run OCR first or upload the text |
| Simulation fails with a provider error (credit, rate limit, model not found) | The message in the simulation names the provider's answer. Check credit and model name, then run again; a failed simulation gives its quota back |
| Simulation shown as running forever after a crash | At start-up the worker closes simulations with no live task older than `STALE_SIMULATION_MINUTES`: `docker compose restart worker` |
| Log line `kb_embedding_fallback` | The e5 model could not be downloaded (no access to Hugging Face). Allow outbound HTTPS, or set `KB_EMBEDDING=default` |
| Echo-chamber metric reports `fallback_jaccard` | Chroma's ONNX model did not load (download blocked); the metric falls back to word overlap |

## Getting help

Search the issues of the repository, then open one with the SwarMind version or commit, the steps,
and the relevant log lines (remove keys, emails and brief content). Security problems: see
[SECURITY.md](../../../SECURITY.md).
