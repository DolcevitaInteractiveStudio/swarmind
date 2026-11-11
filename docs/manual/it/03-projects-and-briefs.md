# 3. Progetti e brief

[Indice del manuale](README.md) · Precedente: [Primo amministratore e provider](02-first-admin-and-providers.md) · Successivo: [Eseguire una simulazione](04-running-a-simulation.md)

Un **progetto** corrisponde a un brief: il documento che descrive che cosa vuoi verificare. Ogni simulazione
del progetto parte dallo stesso brief e dallo stesso knowledge graph.

## Creare un progetto

**Progetti → Nuovo progetto**:

1. **Nome** e **argomento** (l'oggetto della simulazione).
2. **Documento sorgente**: PDF, DOCX, TXT, MD, JSON o CSV, fino alla dimensione dei file prevista dal tuo piano.
3. **LLM**: una delle tue connessioni AI, e il modello *heavy* per il progetto (grafo, popolazione,
   report). "Default sistema (Groq)" compare solo quando il server ha una chiave di sistema.

Se non è disponibile alcun provider (nessuna chiave di sistema e nessuna tua connessione), la pagina ti chiede di
collegarne prima uno in **Connessioni AI**; non viene caricato nulla finché non lo fai.

Dopo il caricamento SwarMind:

- estrae il testo (PDF: solo il livello di testo, le pagine scansionate non vengono lette; DOCX: i paragrafi);
- costruisce un **knowledge graph** di entità e relazioni con il modello heavy, in blocchi di circa
  3.000 parole;
- salva il testo in una **knowledge base** (Chroma), suddiviso in blocchi da 120 parole, che gli agenti e
  il report interrogano durante la simulazione.

La pagina del progetto mostra l'avanzamento. Se la costruzione non riesce, l'errore ne indica il motivo (chiave non valida, credito
esaurito, modello non trovato, limite di richieste, errore del provider). Risolvi la causa e usa **Ricostruisci grafo**; durante la
ricostruzione il grafo precedente viene mantenuto.

## Scrivere un brief completo

Il report **cita solo fatti presenti nel brief o in ciò che hanno scritto gli agenti**. Numeri, nomi,
date e importi che non compaiono da nessuna parte vengono rimossi dall'analisi, oppure attribuiti all'agente che
li ha pronunciati. Un brief povero produce un report povero e generico; un brief completo dà agli agenti materiale reale su cui
discutere e al report fatti reali da citare.

Un buon brief contiene:

- **L'oggetto**: azienda, prodotto o servizio, e che cosa cambia esattamente (nuovo nome, nuovo prezzo,
  lancio, comunicazione). Enuncia in una frase il cambiamento da verificare.
- **I fatti**: prezzi, date, funzionalità, che cosa resta invariato, che cosa ottengono i clienti. Gli agenti possono reagire solo
  a ciò che sanno.
- **Il mercato**: chi sono i clienti, i segmenti, i concorrenti e i loro prezzi, il contesto
  (normativa, notizie recenti).
- **Il messaggio**: il testo vero e proprio, i claim o la comunicazione che vuoi verificare, parola per parola.
- **Rischi noti e domande aperte**: che cosa ti preoccupa; il report li andrà a cercare.
- **Che cosa vuoi sapere**: la decisione che la simulazione deve supportare.

Scrivi in prosa semplice; titoli ed elenchi aiutano. Più documenti brevi possono essere uniti in un unico file.
Togli ciò che non sei autorizzato a inviare al tuo provider LLM: l'intero brief gli viene inviato.

## Progetti e piani

Il numero di progetti e la dimensione massima dei file dipendono dal piano (Free: 3 progetti, 5 MB; Pro:
20, 50 MB; Enterprise: illimitati, 500 MB). Eliminare un progetto elimina le sue simulazioni.
