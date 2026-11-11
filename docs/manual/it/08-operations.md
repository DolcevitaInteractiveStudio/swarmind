# 8. Operazioni

[Indice del manuale](README.md) · Precedente: [Admin panel](07-admin-site-landing.md) · Successivo: [Risoluzione dei problemi](09-troubleshooting.md)

Esegui i comandi dalla cartella che contiene `docker-compose.yml`.

## Che cosa includere nel backup

| Dati | Dove | Necessario per il ripristino |
|---|---|---|
| `.env` | il checkout | **Sì**: senza `ENCRYPTION_KEY` le chiavi dei provider salvate sono perse |
| Database | volume `postgres_data` | **Sì**: utenti, piani, progetti, simulazioni, report, impostazioni |
| Brief caricati e immagini del sito | volume `uploads` | **Sì**: i brief servono per ricostruire le knowledge base |
| File delle simulazioni (feed, agenti, metriche) | volume `simulation_data` | **Sì**: il feed, la chat con gli agenti e gli strumenti del report li leggono |
| Chroma | volume `chroma_data_v1` | Consigliato: le knowledge base vengono ricostruite dai brief, le memorie degli agenti vengono eliminate quando una simulazione termina |
| Cache dei modelli | volumi `hf_cache`, `chroma_onnx_cache` | No: vengono riscaricate al primo utilizzo |
| Redis | volume `redis_data` | No: solo code |

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

Per una copia coerente di Chroma, fermalo prima (`docker compose stop chroma`) quando non ci sono simulazioni
in esecuzione, poi riavvialo. Conserva i backup fuori dal server e cifrati: contengono i brief.

### Ripristino (su un'installazione vuota)

```bash
docker compose up -d postgres
docker compose exec -T postgres pg_restore -U swarmind -d swarmind --clean --if-exists < backups/db-STAMP.dump
for v in uploads simulation_data chroma_data_v1; do
  docker run --rm -v "${P}_${v}:/data" -v "$PWD/backups:/backup" alpine \
    sh -c "cd /data && tar xzf /backup/${v}-STAMP.tgz"
done
docker compose up -d
```

Ripristina prima `.env`: deve contenere la stessa `ENCRYPTION_KEY` e la stessa `POSTGRES_PASSWORD`.

## Migrazioni del database

Un database nuovo riceve lo schema completo al primo avvio. Dopo un aggiornamento, applica le migrazioni:

```bash
docker compose run --rm backend flask --app run db upgrade
docker compose run --rm backend flask --app run db current   # shows the applied revision
```

Non eseguire mai `flask db migrate` o `flask db revision` dentro un container: il nuovo file apparterrebbe
a root nel tuo checkout (vedi `docs/runbooks/deploy-file-ownership.md`).

## Cambiare i segreti

- `POSTGRES_PASSWORD` viene applicata solo quando viene creato il volume del database. Per cambiarla:
  `docker compose exec postgres psql -U swarmind -c "ALTER USER swarmind PASSWORD 'new-value'"`,
  aggiorna `.env`, poi `docker compose up -d`.
- `CHROMA_TOKEN`, `FLOWER_PASSWORD`: aggiorna `.env` ed esegui `docker compose up -d`.
- `REDIS_PASSWORD`: aggiorna `.env`, poi `docker compose up -d redis backend worker` (e `flower`).
- `SECRET_KEY`: cambiarla disconnette tutti gli utenti.
- `ENCRYPTION_KEY`: cambiarla rende illeggibili tutte le chiavi dei provider salvate; gli utenti devono ricollegare
  le proprie chiavi. Cambia anche la `SECRET_KEY` derivata, quando questa è vuota.

## Aggiornamento dalla 1.0.0: password di Redis

Ora Redis richiede una password. In un'installazione esistente, prima di `docker compose up -d`:

1. Aggiungi `REDIS_PASSWORD` a `.env`, solo lettere e cifre (finisce dentro un URL):
   `echo "REDIS_PASSWORD=$(openssl rand -hex 32)" >> .env`. `./start.sh` ne aggiunge una se manca.
2. Ricrea Redis e i servizi che lo usano, quando non ci sono simulazioni in corso:
   `docker compose up -d redis backend worker` (e `flower` se lo usi).

Senza l'impostazione Compose si ferma con `Set REDIS_PASSWORD in .env`. Se Redis e l'app non sono
d'accordo (Redis non ricreato, o una password diversa), backend e worker si rifiutano di partire e il
log dice quale lato correggere. Il volume di Redis conserva i suoi dati.

## Protezione degli accessi

- I controlli di password falliti, all'accesso e al cambio password, sono limitati per account
  (`LOGIN_MAX_FAILURES_PER_ACCOUNT`, default 5) e per IP del client (`LOGIN_MAX_FAILURES_PER_IP`,
  default 30) in una finestra di `LOGIN_THROTTLE_WINDOW_SECONDS` (default 900). Oltre un limite la risposta
  è "Troppi tentativi falliti" fino alla fine della finestra; un accesso riuscito azzera il contatore
  dell'account. `0` disattiva un limite. I contatori stanno in Redis; se Redis non risponde l'accesso
  funziona comunque.
- L'IP del client viene da `X-Forwarded-For`. `TRUSTED_PROXY_COUNT` è il numero di proxy che lo
  aggiornano: `1` con il solo Compose (il nginx del frontend), `2` dietro un reverse proxy sull'host
  ([capitolo 1](01-installation.md#dietro-un-reverse-proxy)). Troppo basso, tutti gli utenti condividono un
  solo contatore; troppo alto, un client può scegliersi l'IP.
- Un cambio password (Profilo, o `create-superadmin --reset-password`) disconnette tutte le altre sessioni
  di quell'utente.

## Chroma

Ogni progetto ha una collection di knowledge base, versionata e ricostruita automaticamente all'avvio di una simulazione
se il brief o il modello di embedding sono cambiati. Ogni simulazione ha una collection di memorie degli agenti
(`sim_<id>_memory`), eliminata quando la simulazione viene completata, non riesce o viene fermata; all'avvio il worker
riprova le eliminazioni non riuscite. Per rimuovere le collection lasciate dalle versioni precedenti, usa
`flask chroma-cleanup` (vedi il runbook più sotto).

## Monitoraggio

- `docker compose ps` e `docker compose logs -f backend worker` (log strutturati `event key=value`).
- `GET /api/health` sul backend risponde `{"status": "ok"}`.
- Flower, facoltativo: imposta `COMPOSE_PROFILES=monitoring` e `FLOWER_PASSWORD` in `.env`, esegui
  `docker compose up -d`, poi apri `http://127.0.0.1:5555` tramite un tunnel SSH.

## Runbook

Procedure passo per passo in [`docs/runbooks/`](../../runbooks/):

- [rebuild-images.md](../../runbooks/rebuild-images.md): ricostruire le immagini di backend, worker e Flower
  con un tag di rollback (dopo una modifica a `requirements.txt`, `constraints.txt` o al Dockerfile).
- [chroma-cleanup.md](../../runbooks/chroma-cleanup.md): eliminare le vecchie collection delle memorie degli agenti.
- [chroma-volume-migration.md](../../runbooks/chroma-volume-migration.md): spostare i dati di Chroma nel
  volume `/data` usato da Chroma 1.x (solo per le installazioni avviate prima di quel cambiamento).
- [deploy-file-ownership.md](../../runbooks/deploy-file-ownership.md): evitare file di proprietà di root nel checkout
  quando `./backend` è montato con bind mount.
