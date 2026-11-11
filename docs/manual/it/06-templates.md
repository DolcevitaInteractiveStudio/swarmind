# 6. Template

[Indice del manuale](README.md) · Precedente: [Leggere il report](05-reading-the-report.md) · Successivo: [Admin panel](07-admin-site-landing.md)

Un template adatta una simulazione a un tipo di test. Aggiunge tre **voci critiche**, **sezioni del report**
obbligatorie e istruzioni per il report. Senza template ("simulazione generica") la
popolazione e fino a tre voci critiche vengono ricavate solo dal brief.

## I cinque template

| Template | Usalo per verificare | Sezioni obbligatorie (oltre a *Dinamiche del Dibattito*) |
|---|---|---|
| `brand_rebranding`: Rebranding e ponte generazionale | Il riposizionamento di un brand storico senza perdere i clienti fedeli | coerenza con l'heritage, ponte generazionale, risonanza emotiva, vulnerabilità della narrativa, rischi di amplificazione, risposta competitiva |
| `product_launch`: Prelaunch feedback e obiezioni | La reazione del mercato a un nuovo prodotto prima che qualcuno l'abbia provato | gap nel messaggio, rischi di posizionamento, segnali di adozione early, risposta competitiva |
| `b2b_saas_pricing`: Test pricing B2B SaaS | Le obiezioni degli acquirenti aziendali a un prezzo, e le leve di negoziazione | analisi delle obiezioni, razionalizzazioni degli acquirenti, resistenza per segmento, leve di pricing |
| `crisis_comms`: Come reagisce il pubblico a una comunicazione negativa | Una comunicazione di crisi prima che venga diffusa | vulnerabilità della narrativa, risonanza emotiva, rischi di amplificazione, percorso di recupero della fiducia |
| `feature_validation`: Vale la pena costruirla? | Se gli utenti adotterebbero davvero una feature al posto delle soluzioni alternative che usano oggi | gravità del problema, analisi dei workaround, frizione di adozione, costo opportunità |

Ogni template limita le voci critiche al 15% degli agenti e al 25% dei post.

## Struttura di un template

I template sono file YAML in `backend/app/templates/simulations/`:

- `<id>.yml`, in inglese, contiene tutto: id, nome, descrizione, versione, `max_adversarial_share`,
  `adversarial_post_share_cap`, il testo segnaposto della domanda, le entità consigliate, tre
  `adversarial_personas` (ciascuna con una `key` stabile, nome, ruolo, background, credenze, paure,
  stile comunicativo, convinzione e stato emotivo) e `report_focus` (`mandatory_sections`,
  `extra_instructions`).
- `locales/it/<id>.yml` contiene solo i campi traducibili in italiano (nome, descrizione,
  testo segnaposto, entità consigliate, istruzioni aggiuntive e, per ogni persona: nome, ruolo, background,
  credenze, paure, motivazioni), con la calibrazione sul mercato italiano. Viene sovrapposto alla
  base inglese; numeri e struttura vengono sempre dalla base.

All'interno di `extra_instructions`, fai riferimento a una persona con `{persona:<key>}`: viene sostituito dal
nome della persona nella lingua della simulazione. Una simulazione usa il template nella propria lingua;
l'interfaccia elenca i template nella lingua dell'interfaccia.

## Modificare o aggiungere un template

1. Copia un template esistente, assegnagli un nuovo `id` (il nome del file) e modificalo. Mantienilo generico: niente
   brand, clienti o persone reali.
2. Aggiungi il livello italiano in `locales/it/<id>.yml` con le stesse chiavi delle personas.
3. Le nuove sezioni obbligatorie richiedono una definizione in `backend/app/report/sections.py`.
4. Valida:

   ```bash
   docker compose exec backend python -m app.templates.validate
   ```

   Controlla i campi obbligatori, l'unicità delle chiavi delle personas, i riferimenti alle personas e che ogni livello di traduzione
   esista, abbia le stesse chiavi e contenga solo campi traducibili. Stampa una riga `ERROR` per ogni
   problema ed esce con codice 1.
5. Riavvia: `docker compose restart backend worker`.
