# 1. Installazione e reverse proxy

[Indice del manuale](README.md) · Successivo: [Primo amministratore e provider](02-first-admin-and-providers.md)

## Requisiti

- Server Linux (o una workstation per i test) con Docker Engine 24+ e il plugin Compose v2.
- 4 core CPU e 8 GB di RAM consigliati; circa 10 GB di disco per immagini, modelli e dati.
- Accesso HTTPS in uscita verso il tuo provider LLM e, al primo utilizzo, verso Hugging Face (modello di embedding) e
  verso il download del modello di Chroma (embedding delle memorie degli agenti).
- Un nome di dominio e un reverse proxy con TLS se gli utenti si collegano dalla rete.

## Servizi

`docker-compose.yml` avvia:

| Servizio | Ruolo | Porta (host) |
|---|---|---|
| `frontend` | SPA Vue servita da nginx; inoltra `/api` e `/socket.io` al backend | `127.0.0.1:3000` |
| `backend` | API Flask (gunicorn + gevent) | `127.0.0.1:5001` |
| `worker` | Worker Celery: costruzione del grafo, simulazioni, report | — |
| `postgres` | PostgreSQL 16: utenti, progetti, simulazioni, impostazioni | `127.0.0.1:5432` |
| `redis` | Broker Celery e coda di messaggi di Socket.IO | `127.0.0.1:6379` |
| `chroma` | ChromaDB 1.0.21: knowledge base dei progetti e memorie degli agenti | `127.0.0.1:8001` |
| `flower` | Monitoraggio di Celery, facoltativo (profilo `monitoring`) | `127.0.0.1:5555` |

I dati risiedono in volumi con nome creati da Compose: `postgres_data`, `redis_data`, `chroma_data_v1`,
`simulation_data`, `uploads`, `hf_cache`, `chroma_onnx_cache` (con il prefisso del nome del progetto, che
è il nome della cartella a meno che tu non imposti `COMPOSE_PROJECT_NAME`).

## Installazione

```bash
git clone https://github.com/DolcevitaInteractiveStudio/swarmind.git swarmind
cd swarmind
./start.sh
```

`start.sh` crea `.env` a partire da `.env.example` con valori casuali per `ENCRYPTION_KEY`, `POSTGRES_PASSWORD`,
`CHROMA_TOKEN` e `REDIS_PASSWORD`, esegue `docker compose up -d --build` e attende il backend.

Per farlo a mano:

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

Al primo avvio il backend crea lo schema del database e i piani predefiniti (Free, Pro,
Enterprise). La prima simulazione scarica i modelli di embedding (circa 135 MB e 90 MB) nei volumi
`hf_cache` e `chroma_onnx_cache`.

**Fai subito un backup di `.env`.** Senza la stessa `ENCRYPTION_KEY`, le chiavi dei provider salvate nel database
non possono essere decifrate.

Passo successivo: crea il primo amministratore, vedi il [capitolo 2](02-first-admin-and-providers.md).

## Dietro un reverse proxy

Esponi solo il frontend (`127.0.0.1:3000`). Il suo nginx inoltra già `/api/` e `/socket.io/` al
backend, quindi al proxy basta un solo upstream. Il proxy deve:

- terminare il TLS;
- lasciar passare gli upgrade WebSocket su `/socket.io/` (avanzamento in tempo reale delle simulazioni);
- accettare upload grandi quanto consentono i tuoi piani (fino a 500 MB);
- consentire richieste lunghe (la generazione del report e la chat con gli agenti possono richiedere alcuni minuti).

Poi imposta l'indirizzo pubblico in `.env` e ricrea il backend:

```bash
FRONTEND_URL=https://swarmind.example.com
docker compose up -d backend
```

`FRONTEND_URL` è l'unica origine accettata da CORS e dal WebSocket. Una discrepanza si manifesta come
chiamate API non riuscite o come una barra di avanzamento che non si muove mai.

Dietro un reverse proxy che invia `X-Forwarded-For` (lo fa Caddy, e anche l'esempio nginx qui sotto),
imposta anche `TRUSTED_PROXY_COUNT=2`: così il backend vede il vero IP del client, su cui si contano i
limiti di accesso per IP. Con il valore predefinito `1` tutti gli utenti condividerebbero l'IP del proxy
e il suo limite.

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

Caddy ottiene il certificato e gestisce gli upgrade WebSocket in autonomia.

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

Il backend invia da sé HSTS, CSP e gli altri header di sicurezza; servi SwarMind solo tramite HTTPS.

### Firewall

Devono essere aperte solo le porte 80 e 443 (e SSH). Docker pubblica le porte dei servizi solo su `127.0.0.1`,
quindi PostgreSQL, Redis, Chroma e Flower non sono raggiungibili dall'esterno.

## Aggiornamento

```bash
cd swarmind
git pull
docker compose build
docker compose run --rm backend flask --app run db upgrade   # database migrations
docker compose up -d
```

Leggi `CHANGELOG.md` prima di aggiornare e fai un backup ([capitolo 8](08-operations.md)).
Le nuove versioni possono aggiungere impostazioni a `.env.example`: confrontalo con il tuo `.env`.
Aggiornamento dalla 1.0.0: imposta `REDIS_PASSWORD` e ricrea Redis prima delle migrazioni
([capitolo 8](08-operations.md#aggiornamento-dalla-100-password-di-redis)).

## Disinstallazione

`docker compose down` ferma tutto e conserva i dati. `docker compose down -v` elimina anche
i volumi, cioè tutti gli utenti, i progetti, le simulazioni e i report: non si può tornare indietro.
