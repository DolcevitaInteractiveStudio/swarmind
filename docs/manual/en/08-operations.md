# 8. Operations

[Manual index](README.md) · Previous: [Admin panel](07-admin-site-landing.md) · Next: [Troubleshooting](09-troubleshooting.md)

Run the commands from the folder with `docker-compose.yml`.

## What to back up

| Data | Where | Needed to restore |
|---|---|---|
| `.env` | the checkout | **Yes**: without `ENCRYPTION_KEY` the stored provider keys are lost |
| Database | volume `postgres_data` | **Yes**: users, plans, projects, simulations, reports, settings |
| Uploaded briefs and site images | volume `uploads` | **Yes**: briefs are needed to rebuild knowledge bases |
| Simulation files (feeds, agents, metrics) | volume `simulation_data` | **Yes**: feed, agent chat and report tools read them |
| Chroma | volume `chroma_data_v1` | Recommended: knowledge bases are rebuilt from the briefs, agent memories are deleted when a simulation ends |
| Model caches | volumes `hf_cache`, `chroma_onnx_cache` | No: downloaded again on first use |
| Redis | volume `redis_data` | No: only queues |

### Backup

```bash
STAMP=$(date +%Y%m%d-%H%M)
mkdir -p backups
cp .env "backups/env-$STAMP"
docker compose exec -T postgres pg_dump -U swarmind -Fc swarmind > "backups/db-$STAMP.dump"
P=$(docker compose config --format json | python3 -c "import json,sys; print(json.load(sys.stdin)['name'])")
for v in uploads simulation_data chroma_data_v1; do
  docker run --rm -v "${P}_${v}:/data:ro" -v "$PWD/backups:/backup" alpine \
    tar czf "/backup/${v}-$STAMP.tgz" -C /data .
done
```

For a consistent Chroma copy, stop it first (`docker compose stop chroma`) when no simulation is
running, then start it again. Keep backups off the server and encrypted: they contain the briefs.

### Restore (on an empty install)

```bash
docker compose up -d postgres
docker compose exec -T postgres pg_restore -U swarmind -d swarmind --clean --if-exists < backups/db-STAMP.dump
for v in uploads simulation_data chroma_data_v1; do
  docker run --rm -v "${P}_${v}:/data" -v "$PWD/backups:/backup" alpine \
    sh -c "cd /data && tar xzf /backup/${v}-STAMP.tgz"
done
docker compose up -d
```

Restore `.env` first: it must hold the same `ENCRYPTION_KEY` and `POSTGRES_PASSWORD`.

## Database migrations

A new database gets the full schema on the first start. After an upgrade, apply the migrations:

```bash
docker compose run --rm backend flask --app run db upgrade
docker compose run --rm backend flask --app run db current   # shows the applied revision
```

Never run `flask db migrate` or `flask db revision` inside a container: the new file would be owned
by root in your checkout (see `docs/runbooks/deploy-file-ownership.md`).

## Changing secrets

- `POSTGRES_PASSWORD` is applied only when the database volume is created. To change it:
  `docker compose exec postgres psql -U swarmind -c "ALTER USER swarmind PASSWORD 'new-value'"`,
  update `.env`, then `docker compose up -d`.
- `CHROMA_TOKEN`, `FLOWER_PASSWORD`: update `.env` and `docker compose up -d`.
- `REDIS_PASSWORD`: update `.env`, then `docker compose up -d redis backend worker` (and `flower`).
- `SECRET_KEY`: changing it signs everyone out.
- `ENCRYPTION_KEY`: changing it makes every stored provider key unreadable; users must connect
  their keys again. It also changes the derived `SECRET_KEY` when that is empty.

## Upgrading from 1.0.0: Redis password

Redis now requires a password. On an existing install, before `docker compose up -d`:

1. Add `REDIS_PASSWORD` to `.env`, letters and digits only (it goes inside a URL):
   `echo "REDIS_PASSWORD=$(openssl rand -hex 32)" >> .env`. `./start.sh` adds one if it is missing.
2. Recreate Redis first, when no simulation is running: `docker compose up -d --no-deps redis`.
   Then upgrade as usual: migrations (`docker compose run --rm backend flask --app run db upgrade`)
   and `docker compose up -d`. The order matters: the app, the migration command included, refuses
   to start while Redis still runs without the password.

Without the setting Compose stops with `Set REDIS_PASSWORD in .env`. If Redis and the app disagree
(Redis not recreated, or a different password), the backend and the worker refuse to start and the
log says which side to fix. The Redis volume keeps its data.

## Sign-in protection

- Failed password checks, on sign-in and on a password change, are limited per account
  (`LOGIN_MAX_FAILURES_PER_ACCOUNT`, default 5) and per client IP (`LOGIN_MAX_FAILURES_PER_IP`,
  default 30) in a window of `LOGIN_THROTTLE_WINDOW_SECONDS` (default 900). Past a limit the answer is
  "Too many failed attempts" until the window ends; a successful sign-in clears the account counter.
  `0` turns a limit off. The counters live in Redis; if Redis does not answer, sign-in still works.
- The client IP comes from `X-Forwarded-For`. `TRUSTED_PROXY_COUNT` is the number of proxies that
  append to it: `1` with Compose alone (the frontend's nginx), `2` behind a reverse proxy on the host
  ([chapter 1](01-installation.md#behind-a-reverse-proxy)). Too low, every user shares one IP counter;
  too high, a client can choose its own IP.
- A password change (Profile, or `create-superadmin --reset-password`) signs out every other session
  of that user.

## Chroma

Each project has a knowledge-base collection, versioned and rebuilt automatically when a simulation
starts if the brief or the embedding model changed. Each simulation has one collection of agent
memories (`sim_<id>_memory`), deleted when the simulation completes, fails or is stopped; the worker
retries failed deletions at start-up. To remove collections left by old versions, use
`flask chroma-cleanup` (runbook below).

## Monitoring

- `docker compose ps` and `docker compose logs -f backend worker` (structured `event key=value` logs).
- `GET /api/health` on the backend answers `{"status": "ok"}`.
- Flower, optional: set `COMPOSE_PROFILES=monitoring` and `FLOWER_PASSWORD` in `.env`, run
  `docker compose up -d`, then open `http://127.0.0.1:5555` through an SSH tunnel.

## Runbooks

Step-by-step procedures in [`docs/runbooks/`](../../runbooks/):

- [rebuild-images.md](../../runbooks/rebuild-images.md): rebuild backend, worker and Flower images
  with a rollback tag (after a change to `requirements.txt`, `constraints.txt` or the Dockerfile).
- [chroma-cleanup.md](../../runbooks/chroma-cleanup.md): delete old agent-memory collections.
- [chroma-volume-migration.md](../../runbooks/chroma-volume-migration.md): move Chroma data to the
  `/data` volume used by Chroma 1.x (only for installs that started before that change).
- [deploy-file-ownership.md](../../runbooks/deploy-file-ownership.md): keep the checkout free of
  root-owned files when `./backend` is bind-mounted.
