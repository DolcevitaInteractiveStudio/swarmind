# 1. Installation and reverse proxy

[Manual index](README.md) · Next: [First admin and providers](02-first-admin-and-providers.md)

## Requirements

- Linux server (or a workstation for testing) with Docker Engine 24+ and the Compose v2 plugin.
- 4 CPU cores and 8 GB of RAM recommended; about 10 GB of disk for images, models and data.
- Outbound HTTPS to your LLM provider and, on first use, to Hugging Face (embedding model) and to
  Chroma's model download (agent-memory embeddings).
- A domain name and a reverse proxy with TLS if users connect over the network.

## Services

`docker-compose.yml` starts:

| Service | Role | Port (host) |
|---|---|---|
| `frontend` | Vue SPA served by nginx; proxies `/api` and `/socket.io` to the backend | `127.0.0.1:3000` |
| `backend` | Flask API (gunicorn + gevent) | `127.0.0.1:5001` |
| `worker` | Celery worker: graph build, simulations, reports | — |
| `postgres` | PostgreSQL 16: users, projects, simulations, settings | `127.0.0.1:5432` |
| `redis` | Celery broker and Socket.IO message queue | `127.0.0.1:6379` |
| `chroma` | ChromaDB 1.0.21: project knowledge bases and agent memories | `127.0.0.1:8001` |
| `flower` | Celery monitoring, optional (profile `monitoring`) | `127.0.0.1:5555` |

Data lives in named volumes created by Compose: `postgres_data`, `redis_data`, `chroma_data_v1`,
`simulation_data`, `uploads`, `hf_cache`, `chroma_onnx_cache` (prefixed with the project name, which
is the folder name unless you set `COMPOSE_PROJECT_NAME`).

## Install

```bash
git clone https://github.com/DolcevitaInteractiveStudio/swarmind.git swarmind
cd swarmind
./start.sh
```

`start.sh` creates `.env` from `.env.example` with a random `ENCRYPTION_KEY`, `POSTGRES_PASSWORD`,
`CHROMA_TOKEN` and `REDIS_PASSWORD`, runs `docker compose up -d --build` and waits for the backend.

To do it by hand:

```bash
cp .env.example .env
chmod 600 .env
# Required: a Fernet key (32 url-safe base64 bytes)
python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
#   or: openssl rand -base64 32 | tr '+/' '-_'
# Paste it as ENCRYPTION_KEY=... and replace POSTGRES_PASSWORD, CHROMA_TOKEN and REDIS_PASSWORD
# with random values (REDIS_PASSWORD: letters and digits only, e.g. openssl rand -hex 32)
docker compose up -d --build
docker compose ps        # every service "healthy" or "running" after a minute or two
```

On the first start the backend creates the database schema and the default plans (Free, Pro,
Enterprise). The first simulation downloads the embedding models (about 135 MB and 90 MB) into the
`hf_cache` and `chroma_onnx_cache` volumes.

**Back up `.env` now.** Without the same `ENCRYPTION_KEY`, the provider keys stored in the database
cannot be decrypted.

Next: create the first administrator, see [chapter 2](02-first-admin-and-providers.md).

## Behind a reverse proxy

Expose only the frontend (`127.0.0.1:3000`). Its nginx already forwards `/api/` and `/socket.io/` to
the backend, so the proxy needs a single upstream. It must:

- terminate TLS;
- pass WebSocket upgrades on `/socket.io/` (live progress of simulations);
- accept uploads as large as your plans allow (up to 500 MB);
- allow long requests (report generation and agent chat can take a few minutes).

Then set the public address in `.env` and recreate the backend:

```bash
FRONTEND_URL=https://swarmind.example.com
docker compose up -d backend
```

`FRONTEND_URL` is the only origin accepted by CORS and by the WebSocket. A mismatch shows up as
failed API calls or a progress bar that never moves.

Behind a reverse proxy that sends `X-Forwarded-For` (Caddy does, and so does the nginx example below),
also set `TRUSTED_PROXY_COUNT=2`: the backend then sees the real client IP, which the sign-in limits
count per IP. With the default `1` every user would share the proxy's IP and its limit.

### Caddy

```caddy
swarmind.example.com {
    request_body {
        max_size 500MB
    }
    reverse_proxy 127.0.0.1:3000 {
        transport http {
            read_timeout 300s
        }
    }
}
```

Caddy obtains the certificate and handles WebSocket upgrades on its own.

### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name swarmind.example.com;
    ssl_certificate     /etc/letsencrypt/live/swarmind.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/swarmind.example.com/privkey.pem;

    client_max_body_size 500m;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }

    location /socket.io/ {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 300s;
    }
}

server {
    listen 80;
    server_name swarmind.example.com;
    return 301 https://$host$request_uri;
}
```

The backend sends HSTS, CSP and the other security headers itself; serve SwarMind only over HTTPS.

### Firewall

Only ports 80 and 443 (and SSH) need to be open. Docker publishes the service ports on `127.0.0.1`
only, so PostgreSQL, Redis, Chroma and Flower are not reachable from outside.

## Upgrade

```bash
cd swarmind
git pull
docker compose build
docker compose run --rm backend flask --app run db upgrade   # database migrations
docker compose up -d
```

Read `CHANGELOG.md` before upgrading and take a backup ([chapter 8](08-operations.md)).
New releases may add settings to `.env.example`: compare it with your `.env`.
Upgrading from 1.0.0: set `REDIS_PASSWORD` first
([chapter 8](08-operations.md#upgrading-from-100-redis-password)).

## Uninstall

`docker compose down` stops everything and keeps the data. `docker compose down -v` also deletes
the volumes, that is every user, project, simulation and report: there is no undo.
