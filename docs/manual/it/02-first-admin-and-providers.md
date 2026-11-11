# 2. Primo amministratore, utenti e provider LLM

[Indice del manuale](README.md) · Precedente: [Installazione](01-installation.md) · Successivo: [Progetti e brief](03-projects-and-briefs.md)

## Creare il superadmin

La registrazione pubblica è disattivata: ogni account viene creato da un amministratore. Il primo si crea dalla
riga di comando:

```bash
docker compose exec backend flask --app run create-superadmin --email you@example.com --name "Your Name"
```

La password viene chiesta due volte e non viene mai mostrata (almeno 8 caratteri). Per le installazioni automatizzate,
mettila in una variabile d'ambiente e passa il nome della variabile:

```bash
docker compose exec -e ADMIN_PASSWORD='…' backend \
  flask --app run create-superadmin --email you@example.com --password-env ADMIN_PASSWORD
```

Il superadmin riceve il piano Enterprise. Password dimenticata? Esegui lo stesso comando con
`--reset-password`. Ogni esecuzione viene registrata nell'audit log.

## Ruoli

| Ruolo | Può |
|---|---|
| user | Progetti, simulazioni, report, le proprie connessioni AI |
| admin | In più l'admin panel: utenti (creare, modificare, sospendere), simulazioni di tutti, audit log |
| superadmin | In più piani, eliminazione di utenti, accesso come un altro utente (impersonificazione), Sito e brand |

## Aggiungere utenti

**Admin panel → Utenti → Nuovo utente**: email, password iniziale, piano e ruolo. Chiedi alla persona di cambiare
la password dal proprio profilo.

## Piani e quote

Al primo avvio vengono creati tre piani. Un superadmin può modificarli (**Admin panel → Piani**):

| | Free | Pro | Enterprise |
|---|---|---|---|
| Simulazioni al mese | 1 | 20 | illimitate |
| Agenti per simulazione | 50 | 500 | 2000 |
| Round per simulazione | 20 | 200 | 500 |
| Progetti | 3 | 20 | illimitati |
| Dimensione dei file | 5 MB | 50 MB | 500 MB |
| Chiavi API proprie | no | sì | sì |
| Esportazione PDF, chat con gli agenti | no | sì | sì |

Le quote si applicano sempre, che le pagine di fatturazione siano visibili o no. In un'installazione self-hosted per un solo team,
assegna agli utenti il piano Pro o Enterprise, oppure modifica il piano Free. **Un utente Free non può aggiungere chiavi API**:
senza una chiave di sistema (`GROQ_API_KEY`) un utente di questo tipo non può eseguire simulazioni.

Non c'è alcuna integrazione di pagamento. `BILLING_ENABLED=true` in `.env` mostra agli utenti le pagine dei prezzi e
della fatturazione e i link "Aggiorna piano"; con il valore predefinito `false` l'app non parla mai di
pagamenti e i piani sono gestiti solo dagli amministratori.

## Collegare un provider LLM

Ogni utente collega i propri account in **Connessioni AI**:

1. Scegli un provider: **OpenRouter** (molti modelli con una sola chiave), **Groq**, **OpenAI** o **Anthropic**.
2. Incolla la chiave API e seleziona **Connetti**; **Testa connessione** la verifica presso il provider.
3. La chiave viene cifrata con `ENCRYPTION_KEY` (Fernet: AES-128 con firma HMAC-SHA256) prima di
   essere salvata, e non viene mai scritta nei log.

I modelli si scelgono in seguito:

- per **progetto**, il modello *heavy*: knowledge graph, popolazione di personas, report. Usa un modello
  potente (per esempio `anthropic/claude-sonnet-4.5` tramite OpenRouter);
- per **simulazione**, il modello *agent* (scrive le personas) e il modello *fast* (ogni post di
  ogni round, di gran lunga la maggior parte delle chiamate). Funziona bene un modello veloce ed economico che scriva bene nella
  lingua della simulazione, per esempio `google/gemini-2.5-flash` tramite OpenRouter.

Tutto ciò che carichi e ogni post simulato vengono inviati al provider che scegli, secondo i suoi termini
e i suoi prezzi. Verifica entrambi prima di caricare brief riservati.

### Chiave di sistema (facoltativa)

`GROQ_API_KEY` in `.env` viene usata per ogni utente che non ha collegato una chiave propria, con i
modelli indicati in `GROQ_MODEL_HEAVY`, `GROQ_MODEL_AGENT` e `GROQ_MODEL_FAST`. Lasciala vuota se ogni utente
deve usare la propria chiave. In quel caso "Default sistema (Groq)" non viene proposto, e un utente senza
connessione vede un invito ad aprire **Connessioni AI**: non si possono creare progetti né simulazioni
finché non viene collegata una chiave.

La costruzione del knowledge graph (caricamento e ricostruzione di un progetto) usa sempre la chiave
dell'utente quando ne ha una. Con la chiave di sistema ogni utente può costruire al massimo
`GRAPH_SYSTEM_KEY_MONTHLY_LIMIT` grafi al mese (default 20, stesso periodo mensile della quota di simulazioni;
`-1` nessun limite, `0` mai con la chiave di sistema). Oltre il limite il caricamento viene rifiutato con un
messaggio che rimanda a **Connessioni AI**.
