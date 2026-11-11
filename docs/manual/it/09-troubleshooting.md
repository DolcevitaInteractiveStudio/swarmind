# 9. Risoluzione dei problemi

[Indice del manuale](README.md) · Precedente: [Operazioni](08-operations.md)

Parti da `docker compose ps` e `docker compose logs --tail 200 backend worker`.

## Avvio

| Sintomo | Causa e soluzione |
|---|---|
| `required variable POSTGRES_PASSWORD is missing a value` (o `CHROMA_TOKEN`) | `.env` manca o è incompleto. Esegui `cp .env.example .env` e compilalo |
| Il backend termina con `ENCRYPTION_KEY environment variable is required` | Imposta `ENCRYPTION_KEY` in `.env` (il comando per generarla è in `.env.example`), poi `docker compose up -d` |
| `env file .env not found` | Esegui Compose dalla cartella del checkout, dopo aver creato `.env` |
| Chroma resta `unhealthy` | Guarda `docker compose logs chroma`. Troppo pochi file aperti: il file Compose imposta `ulimits.nofile` a 65536, verifica che il daemon Docker lo consenta |
| Postgres: `password authentication failed` dopo aver cambiato `POSTGRES_PASSWORD` | La password viene impostata solo quando si crea il volume; cambiala anche nel database ([Operazioni](08-operations.md#cambiare-i-segreti)) |
| Flower si riavvia con `Set FLOWER_PASSWORD in .env` | Imposta `FLOWER_PASSWORD`, oppure togli `monitoring` da `COMPOSE_PROFILES` |

## Accesso e browser

| Sintomo | Causa e soluzione |
|---|---|
| Non esiste ancora nessun account | Crea il superadmin: `docker compose exec backend flask --app run create-superadmin --email …` |
| Password del superadmin dimenticata | Stesso comando con `--reset-password` |
| Tutti disconnessi dopo un aggiornamento | `SECRET_KEY` (o `ENCRYPTION_KEY`, quando `SECRET_KEY` è vuota) è cambiata: accedi di nuovo |
| Le chiamate API non riescono con errori CORS, oppure l'avanzamento non si aggiorna mai | `FRONTEND_URL` non corrisponde all'indirizzo nel browser (schema, host e porta). Correggilo ed esegui `docker compose up -d backend` |
| Manca l'avanzamento in tempo reale dietro un proxy | Il proxy non lascia passare gli upgrade WebSocket su `/socket.io/` ([reverse proxy](01-installation.md#dietro-un-reverse-proxy)) |
| Il caricamento non riesce con errore 413 | Il reverse proxy limita la dimensione delle richieste: aumenta `client_max_body_size` (nginx) o `request_body max_size` (Caddy) |

## Provider e simulazioni

| Sintomo | Causa e soluzione |
|---|---|
| "Le chiavi API personalizzate sono disponibili dal piano Pro" | L'utente ha il piano Free: assegna Pro o Enterprise, oppure modifica il piano Free (Admin panel → Piani) |
| La chiave di un provider smette di funzionare dopo un ripristino | `.env` è stato ripristinato con una `ENCRYPTION_KEY` diversa: ripristina quella originale oppure chiedi agli utenti di ricollegare le proprie chiavi |
| La costruzione del grafo non riesce: il documento non contiene testo leggibile | PDF scansionato senza livello di testo: esegui prima l'OCR oppure carica il testo |
| La simulazione non riesce per un errore del provider (credito, limite di richieste, modello non trovato) | Il messaggio nella simulazione riporta la risposta del provider. Controlla il credito e il nome del modello, poi riesegui; una simulazione non riuscita restituisce la sua quota |
| Una simulazione risulta in esecuzione all'infinito dopo un crash | All'avvio il worker chiude le simulazioni senza un task attivo più vecchie di `STALE_SIMULATION_MINUTES`: `docker compose restart worker` |
| Riga di log `kb_embedding_fallback` | Non è stato possibile scaricare il modello e5 (nessun accesso a Hugging Face). Consenti l'HTTPS in uscita, oppure imposta `KB_EMBEDDING=default` |
| La metrica di echo chamber riporta `fallback_jaccard` | Il modello ONNX di Chroma non è stato caricato (download bloccato); la metrica ripiega sulla sovrapposizione delle parole |

## Ottenere aiuto

Cerca tra le issue del repository, poi aprine una indicando la versione o il commit di SwarMind, i passaggi
e le righe di log rilevanti (togli chiavi, email e contenuti del brief). Problemi di sicurezza: vedi
[SECURITY.md](../../../SECURITY.md).
