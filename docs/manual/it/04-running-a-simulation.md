# 4. Eseguire una simulazione

[Indice del manuale](README.md) · Precedente: [Progetti e brief](03-projects-and-briefs.md) · Successivo: [Leggere il report](05-reading-the-report.md)

Apri un progetto il cui grafo è stato costruito e scegli **Nuova simulazione**.

## Impostazioni

| Impostazione | Che cosa fa |
|---|---|
| **Nome** e **Domanda da verificare** | Ciò a cui il report deve rispondere, per esempio "Gli abbonati di lunga data accetteranno il nuovo prezzo?" |
| **Template** | Facoltativo. Aggiunge voci critiche, sezioni obbligatorie del report e istruzioni per un tipo di test ([capitolo 6](06-templates.md)) |
| **Agenti** | Dimensione della popolazione (predefinita 100, limitata dal tuo piano) |
| **Round** | Durata del dibattito (predefinita 30, limitata dal tuo piano) |
| **Lingua** | Inglese o italiano: lingua dei post degli agenti e del report. Per impostazione predefinita è la lingua dell'interfaccia |
| **Modelli** | Modello *agent* (scrive le personas) e modello *fast* (ogni post). Il modello heavy viene dal progetto |
| **Piattaforma** | Tono del luogo simulato: social media, forum, finanziario o politico |
| **Voci critiche** | Facoltative, definite da te: una per riga nel formato `Name - Role`, per esempio `Procurement lead - Cuts every SaaS budget` |

Creare una simulazione consuma una simulazione della tua quota mensile. Se non riesce durante la creazione degli agenti
o durante i round (non per un'interruzione manuale né per un report non riuscito), la quota viene restituita.

## Che cosa succede

1. **Popolazione.** A partire dal brief, una fase demografica propone segmenti di stakeholder (da 4 a 8) con
   la loro quota della popolazione; per ogni agente viene scritta una persona, entro le caratteristiche del suo segmento.
   Queste quote dei segmenti sono una scelta progettuale della simulazione, **non pesi di mercato**.
2. **Voci critiche.** Le personas avversarie del template e le tue si uniscono alla popolazione, fino al
   **15% degli agenti** (`max_adversarial_share`). Se sono di più, viene mantenuta una selezione casuale
   riproducibile e il report lo segnala in appendice. Senza un template, il brief può
   proporre fino a 3 voci critiche per occupare i posti liberi. Le voci critiche sono etichettate come tali
   e sono **escluse dal consenso**.
3. **Round.** A ogni round un campione di agenti legge un feed ordinato in base a un hot score (prima i post recenti e
   coinvolgenti), insieme alle proprie memorie e alle parti rilevanti del brief, e decide
   che cosa fare: scrivere un post, commentare, votare o condividere, a seconda della piattaforma. Le voci critiche possono scrivere al massimo il 25% dei post, così
   non possono soffocare il dibattito. Ogni 3 round gli agenti aggiornano la propria opinione e la loro **posizione** (stance) sul
   cambiamento da verificare (a favore/support, neutrale/neutral, contrario/oppose) viene misurata di nuovo.
4. **Report.** Un agente di report interroga il feed, intervista gli agenti e scrive il report; il codice
   poi calcola i numeri e controlla il testo ([capitolo 5](05-reading-the-report.md)).

L'avanzamento è visibile in tempo reale nella pagina della simulazione (round, post, polarizzazione ed entropia per round). Puoi
**fermare** una simulazione; una simulazione fermata non ha report.

## Scegliere agenti e round

- La confidenza del report è limitata dal campione: con meno di 20 agenti, 5 round o 50 post
  è al massimo **Bassa**; con meno di 50 agenti, 10 round o 200 post al massimo **Media**.
- Per una prima lettura di un brief, da 30 a 50 agenti e 10 round bastano per vedere le obiezioni principali.
- Per un report da mostrare a un cliente, usa almeno 50 agenti e 10 round, ed esegui la
  simulazione più di una volta (vedi [variabilità tra esecuzioni](05-reading-the-report.md#variabilità-tra-esecuzioni)).
- Costi e tempi crescono con agenti × round: ogni agente attivo fa una chiamata al modello fast per
  round.

## Dopo la simulazione

- **Feed**: ogni post e risposta, per round e per agente.
- **Agenti**: personas, segmento, storico delle posizioni.
- **Grafo**: il knowledge graph del brief.
- **Report**: vedi il [capitolo 5](05-reading-the-report.md). Esportazione in Markdown o PDF (Pro ed
  Enterprise).
- **Chat**: chiedi a un agente perché ha cambiato idea, oppure fai una domanda all'agente di report (Pro ed
  Enterprise). Le risposte vengono dalla persona e dal report, nella lingua della simulazione.

Quando una simulazione termina (completata, non riuscita o fermata) le memorie dei suoi agenti vengono eliminate da Chroma;
post, agenti e report restano.
