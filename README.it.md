# SwarMind

**Metti alla prova un messaggio prima di lanciarlo.** SwarMind simula come una popolazione di agenti AI,
costruita a partire dal tuo brief, reagisce a un rebranding, a un nuovo prezzo, al lancio di un prodotto
o a una comunicazione di crisi. Leggi il dibattito, vedi quali obiezioni emergono e come si diffondono,
e arrivi all'incontro con il cliente preparato ad affrontarle.

[English](README.md) · [Manuale](docs/manual/it/README.md) · [Licenza](LICENSE)

## Che cos'è, e che cosa non è

SwarMind **è** uno strumento di prova generale per consulenti, brand strategist e agenzie:

- fa emergere le obiezioni che una narrativa incontrerà, con le parole che le persone userebbero;
- mostra quali gruppi oppongono resistenza, quali argomenti reggono, come si spostano le posizioni nel corso di più round;
- produce un report strutturato che puoi ricondurre, post per post, al dibattito simulato.

SwarMind **non è** una previsione. Non prevede vendite, adozione o quote di mercato, e i suoi
numeri non sono risultati di un sondaggio. Gli agenti sono personas generate da un modello linguistico:
riflettono il tuo brief e le conoscenze del modello, con i bias di entrambi. Considera il risultato
un brainstorming strutturato di reazioni, mai una prova di come si comporterà il mercato reale.

## Funzionalità

- **Dal brief alla popolazione**: carica un brief (PDF, Word, testo, Markdown, JSON o CSV); SwarMind ne ricava un knowledge
  graph e una popolazione di personas che rappresentano gli stakeholder.
- **Dibattito su più round**: gli agenti pubblicano, rispondono e cambiano idea; un feed ordinato decide che cosa
  prende piede. I template aggiungono **voci critiche** (al massimo il 15% degli agenti), così le obiezioni
  non sono lasciate al caso.
- **Cinque template**: rebranding, lancio di prodotto, pricing B2B SaaS, comunicazione di crisi,
  validazione di una feature. Base in inglese con un livello di traduzione in italiano.
- **Report**: obiezioni principali, argomenti a favore, gruppi esposti, scenari e raccomandazioni,
  fondati sul brief e sui post degli agenti; consenso e confidenza calcolati dal codice, non dal
  modello; metriche del dibattito (polarizzazione, echo chamber, diversità informativa).
- **Chat con gli agenti ed esportazione in PDF**, secondo il piano.
- **Inglese e italiano** per l'interfaccia, gli agenti e il report.
- **Usa il tuo modello**: chiavi OpenRouter, Groq, OpenAI o Anthropic, conservate cifrate; modelli
  scelti per progetto e per simulazione.
- **Area di amministrazione**: utenti, piani e quote, simulazioni, audit log, sito e brand, una
  landing page pubblica facoltativa.

## Screenshot

<!-- Screenshots: add images under docs/images/ and reference them here. -->
_Dashboard · Feed della simulazione · Report · Knowledge graph · Admin_ (in arrivo)

## Avvio rapido (Docker)

Requisiti: Docker Engine 24+ con Compose v2, 4 core CPU e 8 GB di RAM consigliati, e una chiave API
per almeno un provider LLM.

```bash
git clone https://github.com/DolcevitaInteractiveStudio/swarmind.git swarmind
cd swarmind
./start.sh
```

`start.sh` crea `.env` a partire da `.env.example` con segreti casuali, costruisce le immagini e avvia i
servizi. La procedura manuale:

```bash
cp .env.example .env
# ENCRYPTION_KEY is required; generate one and paste it into .env:
python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
# also replace POSTGRES_PASSWORD, CHROMA_TOKEN and REDIS_PASSWORD with random values
docker compose up -d --build
```

Poi crea il primo amministratore (la password viene chiesta due volte):

```bash
docker compose exec backend flask --app run create-superadmin --email you@example.com
```

Apri <http://localhost:3000>, accedi, aggiungi la chiave di un provider in **Connessioni AI**, crea un progetto
da un brief e avvia una simulazione. Il [manuale](docs/manual/it/README.md) descrive ogni passaggio.

Tutte le porte sono legate a `127.0.0.1`. Per pubblicare SwarMind su un dominio, metti un reverse proxy con TLS
davanti alla porta 3000 e imposta `FRONTEND_URL`: vedi
[Installazione e reverse proxy](docs/manual/it/01-installation.md).

## Configurazione

Tutto si trova in `.env`; [`.env.example`](.env.example) documenta ogni impostazione. Le principali:

| Impostazione | Scopo |
|---|---|
| `ENCRYPTION_KEY` | Obbligatoria. Cifra le chiavi dei provider salvate. Fanne un backup; non cambiarla mai alla leggera |
| `SECRET_KEY` | Firma i token di accesso. Se vuota, viene derivata da `ENCRYPTION_KEY` |
| `POSTGRES_PASSWORD`, `CHROMA_TOKEN`, `REDIS_PASSWORD` | Credenziali dei servizi interni |
| `TRUSTED_PROXY_COUNT` | Proxy davanti al backend: `1` con il solo Compose, `2` dietro un reverse proxy sull'host |
| `LOGIN_MAX_FAILURES_PER_ACCOUNT`, `LOGIN_MAX_FAILURES_PER_IP` | Accessi falliti ammessi per account e per IP in 15 minuti |
| `FRONTEND_URL` | URL pubblico dell'app (origine per CORS e WebSocket) |
| `SIMULATION_DEFAULT_LANGUAGE` | `en` o `it` |
| `KB_EMBEDDING` | Vuota per multilingual-e5-small, `default` per il modello integrato di Chroma |
| `CONTACT_EMAIL`, `BILLING_ENABLED` | Contatto della landing page; pagine dei piani e della fatturazione |
| `GROQ_API_KEY` | Chiave di sistema facoltativa per gli utenti senza chiavi proprie |
| `GRAPH_SYSTEM_KEY_MONTHLY_LIMIT` | Costruzioni del grafo per utente e per mese con la chiave di sistema (default 20) |

## Provider LLM

Ogni utente collega i propri account in **Connessioni AI**: OpenRouter, Groq, OpenAI o
Anthropic. Le chiavi vengono cifrate con `ENCRYPTION_KEY` (Fernet) prima di essere salvate. I modelli si
scelgono per progetto (il modello *heavy*: knowledge graph, popolazione, report) e per simulazione
(il modello *agent* per le personas, il modello *fast* per i round del dibattito). Un buon punto di partenza:
un modello potente come `anthropic/claude-sonnet-4.5` come heavy e `google/gemini-2.5-flash` come fast,
entrambi tramite OpenRouter. Costi e trattamento dei dati sono quelli del provider che scegli: il brief e
il dibattito vengono inviati a lui.

## Aggiornamento

```bash
git pull
docker compose build
docker compose run --rm backend flask --app run db upgrade
docker compose up -d
```

Leggi prima [CHANGELOG.md](CHANGELOG.md) e fai un backup prima di aggiornare:
[Operazioni](docs/manual/it/08-operations.md).
Aggiornamento dalla 1.0.0: aggiungi `REDIS_PASSWORD` a `.env` ed esegui `docker compose up -d --no-deps redis`
prima delle migrazioni
([Operazioni](docs/manual/it/08-operations.md#aggiornamento-dalla-100-password-di-redis)).

## Documentazione

- [Manual (English)](docs/manual/en/README.md) · [Manuale (italiano)](docs/manual/it/README.md)
- [Runbook](docs/runbooks/) per le attività di manutenzione
- [Contribuire](CONTRIBUTING.md) · [Policy di sicurezza](SECURITY.md) · [Changelog](CHANGELOG.md)

## Licenza

Copyright (C) 2026 DolceVita Interactive Studio.

SwarMind è software libero: puoi ridistribuirlo e/o modificarlo nei termini della
[GNU Affero General Public License v3.0](LICENSE). Se esegui una versione modificata come servizio
di rete, devi offrirne il codice sorgente ai suoi utenti (AGPL-3.0, sezione 13). I componenti di terze parti
e le relative licenze sono elencati in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
