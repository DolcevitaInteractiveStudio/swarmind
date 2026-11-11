# 7. Admin panel, sito e brand, landing page

[Indice del manuale](README.md) · Precedente: [Template](06-templates.md) · Successivo: [Operazioni](08-operations.md)

Apri l'**Admin panel** dalla barra laterale (solo admin e superadmin).

## Dashboard, utenti, simulazioni, audit log

- **Dashboard**: utenti, simulazioni del mese in corso, simulazioni in esecuzione, distribuzione dei piani.
- **Utenti**: ricerca, creazione, cambio di ruolo e di piano, sospensione e riattivazione. Un superadmin può anche
  eliminare un utente e **accedere come** quell'utente (una sessione temporanea di un'ora) per vedere ciò che vede lui.
- **Piani** (superadmin): limiti e funzionalità di ciascun piano, vedi il [capitolo 2](02-first-admin-and-providers.md#piani-e-quote).
- **Simulazioni**: tutte le simulazioni di tutti gli utenti, con stato ed errori.
- **Audit log**: accessi, modifiche a utenti e piani, impersonificazioni, modifiche al sito, azioni da CLI come
  `create-superadmin`. Per le modifiche al sito vengono registrati solo i campi modificati, non i loro valori.

## Sito e brand (superadmin)

**Admin panel → Sito e brand** controlla l'aspetto dell'app e la landing page pubblica facoltativa.
Le modifiche vengono validate dal server, salvate con un numero di revisione (due amministratori non possono sovrascrivere
a vicenda le proprie modifiche senza accorgersene) e registrate nell'audit log.

### Brand

- **Nome del prodotto**, mostrato nella barra laterale, nella scheda del browser e nella landing.
- **Loghi** per il tema scuro e per quello chiaro, e una **favicon**. Le immagini caricate vengono controllate e
  ricodificate dal server; i limiti di dimensione sono indicati accanto a ciascun campo.
- **Colori**: primario e accento per ciascun tema. L'editor avvisa quando un colore non raggiunge
  il contrasto WCAG AA.

### Landing page

La landing page è **disattivata** per impostazione predefinita: chi visita `/` vede la pagina di accesso. Quando è attiva, `/`
mostra la landing ai visitatori che non hanno effettuato l'accesso.

Il contenuto si modifica separatamente per l'inglese e per l'italiano:

- **Apertura**: titolo, sottotitolo, immagine facoltativa, invito all'azione principale e secondario.
- **Sezioni**, ciascuna disattivabile o riordinabile: valore, come funziona, casi d'uso, risultati,
  open source (link al repository, link alla documentazione, licenza, comandi di installazione), contatti.
- **Piè di pagina**: nome dell'azienda (se vuoto, compare il nome del prodotto), email di contatto, URL dell'informativa privacy e dei termini.
- **SEO**: titolo della pagina, descrizione, immagine per i social.

Il testo predefinito descrive SwarMind come uno stress test per le narrative. La sezione contatti e
l'indirizzo del piè di pagina partono da `CONTACT_EMAIL` in `.env`; senza di esso la sezione contatti parte disattivata.
Usa **Anteprima** per vedere le modifiche non salvate, poi **Salva**. Controlla ogni link e indirizzo prima di attivare
la landing: è pubblica.

I link accettano solo `https://`, `http://`, `mailto:`, percorsi del sito (`/login`) e ancore (`#contact`).
