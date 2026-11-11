"""Pool statici di nomi e cognomi per la generazione di personas con identita'
deterministicamente univoche.

Filosofia: il LLM e' bravo a costruire un personaggio coerente DATO un nome,
ma collassa su pochi nomi prototipici quando deve sceglierli. Pre-sampliamo
qui i nomi cosi' il LLM riceve "nome=Salvatore Pappalardo" come fatto e si
concentra sul background.

Per ora: italiano + inglese, statici, no dipendenze esterne.
Futuro: quando arriveranno brief in altre lingue (FR/ES/DE), valutare
faker library o pool curati per lingua. Aggiungere anche un campo
'language' al contratto PopulationSpec per renderlo esplicito invece
di doverlo dedurre.
"""
from __future__ import annotations

import random
from typing import Literal

Language = Literal["it", "en"]


# ── Italiano ──────────────────────────────────────────────────────────────

IT_FIRST_M = [
    # Nord
    "Marco", "Andrea", "Luca", "Matteo", "Davide", "Stefano", "Roberto",
    "Alberto", "Giorgio", "Paolo", "Fabio", "Enrico", "Federico", "Riccardo",
    "Michele", "Lorenzo", "Alessandro", "Tommaso", "Filippo", "Edoardo",
    # Centro
    "Maurizio", "Massimo", "Francesco", "Antonio", "Giuseppe", "Claudio",
    "Daniele", "Simone", "Gianluca", "Cristian", "Emanuele", "Leonardo",
    # Sud
    "Salvatore", "Vincenzo", "Ciro", "Pasquale", "Carmine", "Gennaro",
    "Domenico", "Rocco", "Nicola", "Raffaele", "Mario", "Tonino",
    "Alfredo", "Vito", "Cosimo", "Gaetano",
]

IT_FIRST_F = [
    # Nord
    "Giulia", "Sara", "Chiara", "Martina", "Federica", "Alessandra",
    "Silvia", "Laura", "Francesca", "Elena", "Valentina", "Cristina",
    "Beatrice", "Camilla", "Lucia", "Anna",
    # Centro
    "Manuela", "Roberta", "Monica", "Daniela", "Stefania", "Patrizia",
    "Loredana", "Antonella", "Simonetta",
    # Sud
    "Carmela", "Concetta", "Rosaria", "Annunziata", "Filomena", "Assunta",
    "Maria Grazia", "Pina", "Mariangela", "Rita",
]

IT_LAST = [
    # Nord
    "Brambilla", "Beretta", "Bellandi", "Brugnara", "Beltrami", "Bertoldi",
    "Bertolini", "Bergamaschi", "Crosetti", "Mazzoleni", "Peverelli",
    "Bertarelli", "Lampredi", "Riva", "Ferrari", "Conti", "Galli",
    "Mariani", "Colombo", "Bianchi",
    # Centro
    "Rossi", "Marchetti", "Romano", "Marini", "Ricci", "Bruno", "Gallo",
    "Costa", "Fontana", "Lombardi", "Moretti", "Barbieri",
    # Sud
    "Russo", "Esposito", "Pappalardo", "Marino", "Mangiaracina", "Parisi",
    "Lo Piccolo", "Punzo", "Giuffrida", "Catalano", "Giordano", "Capparelli",
    "Aiello", "Caruso", "Greco", "De Luca", "Vitale", "Costanzo",
    "La Rosa", "Lo Bianco", "D'Angelo", "Iannone", "Sorrentino",
]


# ── Inglese (US/UK mix) ───────────────────────────────────────────────────

EN_FIRST_M = [
    "James", "Robert", "John", "Michael", "David", "William", "Richard",
    "Thomas", "Christopher", "Daniel", "Matthew", "Anthony", "Mark",
    "Steven", "Andrew", "Kenneth", "Brian", "George", "Edward", "Ronald",
    "Timothy", "Jason", "Jeffrey", "Ryan", "Jacob", "Gary", "Nicholas",
    "Eric", "Jonathan", "Stephen", "Larry", "Justin", "Scott", "Brandon",
    "Frank", "Benjamin", "Gregory", "Samuel", "Patrick", "Alexander",
]

EN_FIRST_F = [
    "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara",
    "Susan", "Jessica", "Sarah", "Karen", "Nancy", "Lisa", "Margaret",
    "Betty", "Sandra", "Ashley", "Kimberly", "Emily", "Donna", "Michelle",
    "Carol", "Amanda", "Melissa", "Deborah", "Stephanie", "Rebecca",
    "Sharon", "Laura", "Cynthia", "Amy", "Kathleen", "Angela",
]

EN_LAST = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
]


# ── Detection lingua ──────────────────────────────────────────────────────

_IT_MARKERS = {
    "il", "la", "lo", "gli", "le", "di", "del", "della", "dei", "delle",
    "per", "con", "su", "tra", "fra", "che", "non", "sono", "una", "un",
    "anche", "essere", "avere", "molto", "questo", "questi", "ogni",
}
_EN_MARKERS = {
    "the", "of", "and", "or", "in", "to", "for", "with", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "this",
    "that", "these", "those", "from", "by", "at", "an", "a",
}


def detect_language(text: str) -> Language:
    """Heuristica semplice: conta markers comuni di entrambe le lingue
    nel testo dato, ritorna la dominante. Default: italiano (mercato target).
    """
    if not text:
        return "it"
    words = {w.lower().strip(".,;:!?'\"()") for w in text.split()}
    it_score = len(words & _IT_MARKERS)
    en_score = len(words & _EN_MARKERS)
    if en_score > it_score:
        return "en"
    return "it"


# ── Sampling ──────────────────────────────────────────────────────────────

def sample_names(
    n: int,
    language: Language = "it",
    female_ratio: float = 0.4,
    rng: random.Random | None = None,
) -> list[str]:
    """Pesca N nomi completi univoci dal pool della lingua specificata.

    Args:
        n: numero di nomi richiesti
        language: 'it' o 'en'
        female_ratio: proporzione di nomi femminili (default 0.4 = 40%)
        rng: random.Random per riproducibilita' (None = random globale)

    Returns:
        Lista di stringhe "Nome Cognome", tutte diverse fra loro.
        Se n eccede la combinatoria del pool, riempie con duplicati di
        cognome (mai di nome+cognome esatto).
    """
    rng = rng or random.Random()

    if language == "en":
        first_m, first_f, last = EN_FIRST_M, EN_FIRST_F, EN_LAST
    else:
        first_m, first_f, last = IT_FIRST_M, IT_FIRST_F, IT_LAST

    n_female = int(round(n * female_ratio))
    n_male = n - n_female

    # Pesca nomi (con replacement se necessario, ma combinati con cognomi
    # diversi per evitare collisioni complete)
    male_firsts = rng.sample(first_m, min(n_male, len(first_m)))
    female_firsts = rng.sample(first_f, min(n_female, len(first_f)))
    while len(male_firsts) < n_male:
        male_firsts.append(rng.choice(first_m))
    while len(female_firsts) < n_female:
        female_firsts.append(rng.choice(first_f))

    all_firsts = male_firsts + female_firsts
    rng.shuffle(all_firsts)

    # Cognomi: pesca senza ripetizione finche' possibile
    if n <= len(last):
        chosen_lasts = rng.sample(last, n)
    else:
        chosen_lasts = rng.sample(last, len(last))
        while len(chosen_lasts) < n:
            chosen_lasts.append(rng.choice(last))

    # Combina e dedup esatto (in casi limite)
    seen = set()
    result = []
    for f, l in zip(all_firsts, chosen_lasts):
        full = f"{f} {l}"
        if full in seen:
            # Cambia cognome al volo
            for alt in last:
                candidate = f"{f} {alt}"
                if candidate not in seen:
                    full = candidate
                    break
        seen.add(full)
        result.append(full)
    return result
