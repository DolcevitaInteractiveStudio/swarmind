# 5. Leggere il report

[Indice del manuale](README.md) · Precedente: [Eseguire una simulazione](04-running-a-simulation.md) · Successivo: [Template](06-templates.md)

Il report viene scritto da un modello linguistico e poi **controllato e completato dal codice**: ogni numero
che misura la simulazione (consenso, confidenza, metriche del dibattito, conteggi per segmento) è calcolato in modo
deterministico, non scritto dal modello. Questo capitolo spiega come leggere quei numeri e
che cosa non possono dirti.

## Che cos'è il report

Una lettura strutturata di un dibattito simulato, costruito a partire dal tuo brief. Ti dice quali obiezioni
sono emerse, quali argomenti hanno retto, quali gruppi hanno opposto resistenza e come si sono spostate le posizioni. **Non è una
previsione**: gli agenti sono personas generate da un modello linguistico, il campione è piccolo e le percentuali descrivono la
popolazione simulata, mai il mercato reale.

## Ancoraggio ai fatti: da dove vengono

Il report ragiona solo a partire dal brief, dai post degli agenti e dai dati calcolati dal sistema:

- un numero, una data, un importo o il nome di un'azienda che non compare né nel brief né nei post viene rimosso
  dalle sezioni di analisi;
- un'affermazione fatta da un agente viene mantenuta ma attribuita ("secondo <agente>"): l'opinione di un agente non è
  una prova;
- le quote dei segmenti nella popolazione non vengono mai presentate come pesi di mercato.

Se il report sembra generico, di solito il brief è troppo povero ([capitolo 3](03-projects-and-briefs.md#scrivere-un-brief-completo)).

## Posizione e convinzione: due cose diverse

- La **posizione** (stance) indica *da che parte sta* l'agente rispetto al cambiamento da verificare: **a favore** (support), **neutrale** (neutral) o
  **contrario** (oppose). Viene misurata quando l'agente viene creato e ogni 3 round. Una risposta poco chiara conta
  come neutrale e viene segnalata.
- La **convinzione** (`opinion_strength`, da 0 a 1) è *quanto fortemente* l'agente sostiene la propria opinione, qualunque
  essa sia.

Un agente può essere fortemente convinto e neutrale, oppure debolmente convinto e contrario. Il report non chiama mai
"consenso" una convinzione uniforme: la chiama **omogeneità della convinzione** (alta quando la varianza
è sotto 0,05, media sotto 0,15, bassa negli altri casi).

## Consenso

Il consenso è l'accordo sulla **posizione** tra gli **agenti naturali** (le voci critiche sono escluse,
a meno che non sia stato misurato nessun agente naturale):

| Consenso | Quota di agenti sulla posizione finale più frequente |
|---|---|
| Alto | 75% o più |
| Medio | da 50% a meno di 75% |
| Basso | sotto il 50%, **oppure qualsiasi parità** tra due posizioni |

"Maggioranza" si usa solo sopra il 50%; al 50% o meno il report dice "maggioranza relativa".

Lo **spostamento** è la quota di agenti misurati almeno due volte la cui posizione è cambiata: stabile sotto il 15%,
moderato dal 15%, ampio dal 35%; ma "ampio" richiede almeno 10 agenti rimisurati (con meno agenti,
uno solo determina la lettura, che viene limitata a moderato).

**Per segmento**, le percentuali vengono mostrate solo per i segmenti con almeno 3 agenti; i segmenti più piccoli
mostrano conteggi ("1 su 1 contrario").

## La confidenza e i limiti dovuti al campione

La riga di confidenza in cima alla sezione *Valutazione della Confidenza* è scritta dal codice; il
modello non può modificarla. Combina due elementi.

1. **Stabilità del risultato**, a partire dalla posizione:
   - **Bassa**: il consenso è basso, oppure lo spostamento è ampio;
   - **Alta**: il consenso è alto, lo spostamento è stabile e sono stati rimisurati almeno 10 agenti;
   - **Media**: in tutti gli altri casi.
2. **Un limite dovuto alla dimensione del campione**, perché una simulazione piccola non può sostenere un'affermazione forte:

   | Campione | Confidenza massima |
   |---|---|
   | meno di 20 agenti, **oppure** meno di 5 round, **oppure** meno di 50 post | Bassa (mostrata come "indicativa") |
   | meno di 50 agenti, **oppure** meno di 10 round, **oppure** meno di 200 post | Media |
   | più grande | nessun limite |

Il livello finale è il più basso dei due. La riga indica il campione e il motivo di un eventuale limite.
La confidenza non è calibrata su risultati reali: dice quanto è stabile il risultato *all'interno della
simulazione*, non quanto è probabile che accada.

## Voci critiche e quota avversaria

I template (e tu) aggiungono voci critiche, personas costruite per sollevare obiezioni. Sono limitate al 15%
degli agenti e al 25% dei post, sono elencate separatamente nel report e non contano nel
consenso. Se alcune sono state escluse per rispettare il limite, l'appendice lo segnala.

Leggi le loro obiezioni come una checklist di attacchi a cui il tuo messaggio deve sopravvivere, non come una misura di quanto
siano diffusi quegli attacchi.

## Dinamiche del dibattito

La sezione *Dinamiche del Dibattito* si apre con una tabella calcolata dal sistema (senza alcun modello),
seguita da una breve lettura.

| Metrica | Che cosa misura | Lettura |
|---|---|---|
| **Delta di polarizzazione** | Variazione della polarizzazione della **convinzione** (non della posizione) dal primo all'ultimo round; polarizzazione per round = min(1, 4 × varianza della convinzione) | sopra +0,15 (o con un forte aumento relativo): polarizzazione attiva; sotto −0,05: depolarizzazione; altrimenti stabile. ±0,05 è rumore |
| **Indice di echo chamber** | Similarità media dei post all'interno di ciascun round (embedding delle frasi) | sopra 0,70: echo chamber; sopra 0,50: dibattito parziale; altrimenti silos paralleli. Se il modello di embedding non è disponibile, si usa in alternativa la sovrapposizione delle parole con soglie 0,30 / 0,15, e il report lo segnala |
| **Diversità informativa** | Variazione del numero di parole chiave distinte per round, seconda metà rispetto alla prima | sotto −30%: collasso rapido; sotto −10%: convergenza graduale; sopra +20%: diversità in crescita; altrimenti stabile |

Queste metriche richiedono almeno 2 o 3 round. Descrivono la conversazione simulata; non sono
trasferibili ai social network reali.

## Perché gli scenari non hanno percentuali

Il report classifica gli scenari solo come **più plausibile**, **plausibile** o **meno plausibile**, con al
massimo uno "più plausibile". Le probabilità vengono rimosse dal codice anche se il modello le scrive:
su qualche centinaio di post scritti da modelli linguistici, una cifra come "62%" è falsa precisione.

Quando la confidenza è Bassa e il consenso non è alto (o la posizione non è stata misurata), nessuno scenario può essere
definito "più plausibile", e il report aggiunge una nota.

Le percentuali che descrivono i dati ("il 40% degli agenti è contrario") restano: contano ciò che è avvenuto nella simulazione,
non predicono.

## Variabilità tra esecuzioni

Due simulazioni dello stesso brief non daranno report identici. Gli agenti vengono campionati a caso a
ogni round e le personas vengono scritte con una temperatura alta, di proposito, per mantenere la popolazione
varia. Con campioni piccoli un solo agente sposta la distribuzione di diversi punti: con meno di 20
agenti, un singolo agente vale più di 5 punti.

In pratica:

- fidati più delle **obiezioni e degli argomenti che ritornano** da un'esecuzione all'altra che di qualsiasi singolo numero;
- prima di un incontro con un cliente, esegui la stessa configurazione due o tre volte e confronta la distribuzione
  delle posizioni e le obiezioni principali;
- cambia una cosa alla volta (template, modelli, brief) quando confronti le esecuzioni.

## Struttura del report

Sezioni tipiche: sintesi, obiezioni principali, argomenti a favore, segmenti esposti, le
sezioni obbligatorie del template, dinamiche del dibattito, scenari, raccomandazioni, valutazione della confidenza e
un'appendice con i parametri dell'esecuzione (agenti, round, modelli, template, voci critiche,
troncamenti). Esporta in Markdown o PDF con i pulsanti sopra il report (Pro ed Enterprise).
