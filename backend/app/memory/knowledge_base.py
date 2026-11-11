"""
KnowledgeBase — collection Chroma per-progetto con i chunk grezzi della KB.
Popolata da GraphBuilder.build(), interrogata da SimulationEngine._run_round().

Gli embedding li calcola kb_embedding (multilingual-e5-small, o quello di default di Chroma se il
modello non c'e'). Chroma lega l'embedding alla collection, quindi ogni versione di embedding ha la
sua: kb_project_<id> per quello di default, kb_project_<id>_emb<versione> per gli altri.
"""
from __future__ import annotations
import re

import structlog

from .chroma_client import get_chroma
from .kb_embedding import DEFAULT_EMBEDDING_VERSION, E5_EMBEDDING_VERSION, default_kb_embedder, get_kb_embedder

log = structlog.get_logger()

# Chunk della KB, separati da quelli dell'estrazione del grafo (CHUNK_SIZE_WORDS).
# L'embedding di default di Chroma legge solo i primi 256 token: su un brief italiano 120 parole
# italiane sono in media 252 token, 150 gia' 316 (un quinto del testo resterebbe senza vettore).
KB_CHUNK_WORDS = 120
KB_CHUNK_OVERLAP_WORDS = 20
# Da incrementare quando cambia il modo di costruire i chunk: lo spawn ricostruisce le KB piu' vecchie
KB_CHUNKING_VERSION = 2
# Il limite del server Chroma 1.0.21 e' 5461 record per chiamata
KB_INGEST_BATCH = 1000

# Budget del blocco KB nel prompt di decide_action. 650 caratteri sono il passo tra due chunk
# (100 parole): con la sovrapposizione ogni parte del brief puo' arrivare in un prompt.
KB_PROMPT_EXCERPTS = 3
KB_EXCERPT_MAX_CHARS = 650
KB_PROMPT_MAX_CHARS = 1600
KB_EXCERPT_SEPARATOR = "\n---\n"
# Segna un estratto tagliato a meta' frase
KB_EXCERPT_ELLIPSIS = "\u2026"
# Si taglia a fine frase solo se resta almeno questa quota del limite: una fine frase troppo presto
# butta testo utile (su un brief di prova, senza soglia, 2 fatti su 20 restavano fuori dal prompt)
KB_EXCERPT_MIN_SENTENCE_KEEP = 0.75
# Fine frase: . ! ? o \u2026, con eventuali virgolette o parentesi di chiusura, seguiti da uno spazio.
# Lo spazio dopo esclude decimali e indirizzi (3.5, www.example.com)
_SENTENCE_END = re.compile(r"[.!?\u2026][\"'\u00bb\u201d\u2019)\]]*(?=\s)")


def chunk_kb_text(text: str) -> list[str]:
    """Divide il testo in chunk di KB_CHUNK_WORDS parole sovrapposte."""
    words = text.split()
    step = KB_CHUNK_WORDS - KB_CHUNK_OVERLAP_WORDS
    chunks = []
    for start in range(0, len(words), step):
        chunks.append(" ".join(words[start : start + KB_CHUNK_WORDS]))
        if start + KB_CHUNK_WORDS >= len(words):
            break
    return chunks


def trim_kb_excerpt(text: str, cap: int) -> str:
    """Accorcia un chunk a cap caratteri al massimo, senza mai tagliare una parola.

    Taglia dopo l'ultima fine frase che ci sta, se tiene almeno KB_EXCERPT_MIN_SENTENCE_KEEP del
    limite; altrimenti dopo l'ultima parola intera e aggiunge KB_EXCERPT_ELLIPSIS.
    Se non ci sta nemmeno una parola ritorna "".
    """
    text = text.strip()
    if len(text) <= cap:
        return text
    # endpos cap + 1: la lookahead vede il carattere subito dopo il limite
    ends = [m.end() for m in _SENTENCE_END.finditer(text, 0, cap + 1) if m.end() <= cap]
    if ends and ends[-1] >= KB_EXCERPT_MIN_SENTENCE_KEEP * cap:
        return text[: ends[-1]]
    room = cap - len(KB_EXCERPT_ELLIPSIS)
    if room <= 0:
        return ""
    # L'ultimo spazio entro room + 1: se il carattere in posizione room e' uno spazio la parola prima resta intera
    last_space = re.search(r"\s\S*$", text[: room + 1])
    head = text[: last_space.start()].rstrip(" ,;:-\u2013\u2014") if last_space else ""
    return head + KB_EXCERPT_ELLIPSIS if head else ""


def format_kb_excerpts(chunks: list[str]) -> str:
    """Blocco KB per il prompt: i chunk nell'ordine di rilevanza, entro il budget di caratteri."""
    excerpts = []
    used = 0
    for chunk in chunks[:KB_PROMPT_EXCERPTS]:
        room = min(KB_EXCERPT_MAX_CHARS, KB_PROMPT_MAX_CHARS - used)
        if room <= 0:
            break
        excerpt = trim_kb_excerpt(chunk, room)
        if not excerpt:
            continue
        excerpts.append(excerpt)
        used += len(excerpt) + len(KB_EXCERPT_SEPARATOR)
    return KB_EXCERPT_SEPARATOR.join(excerpts)


class ProjectKnowledgeBase:
    def __init__(self, project_id: str, host: str = "localhost", port: int = 8000, token: str = ""):
        self.project_id = project_id
        self._client = get_chroma(host, port, token)
        # (collection, embedder) da leggere: si risolve al primo uso e di nuovo dopo un errore
        self._active = None

    def _collection_name(self, embedding_version: int) -> str:
        base = f"kb_project_{self.project_id}"
        return base if embedding_version == DEFAULT_EMBEDDING_VERSION else f"{base}_emb{embedding_version}"

    def _existing(self, embedder):
        from chromadb.errors import NotFoundError
        try:
            return self._client.get_collection(
                name=self._collection_name(embedder.version), embedding_function=embedder.chroma_ef
            )
        except NotFoundError:
            return None

    @staticmethod
    def _readable(coll, embedder) -> bool:
        """Le KB con l'embedding di default si leggono come sempre; le altre solo dopo il timbro di ingest_text."""
        if embedder.version == DEFAULT_EMBEDDING_VERSION:
            return True
        return (coll.metadata or {}).get("kb_embedding_version") == embedder.version

    def _resolve(self):
        """La KB da leggere: quella con l'embedding di questo processo se e' completa, altrimenti
        quella con l'embedding di default finche' la ricostruzione non finisce. None se non c'e'."""
        if self._active is None:
            embedder = get_kb_embedder()
            candidates = [embedder]
            if embedder.version != DEFAULT_EMBEDDING_VERSION:
                candidates.append(default_kb_embedder())
            for candidate in candidates:
                coll = self._existing(candidate)
                if coll is not None and self._readable(coll, candidate):
                    self._active = (coll, candidate)
                    break
        return self._active

    def count(self) -> int:
        """Numero di chunk presenti nella KB."""
        active = self._resolve()
        return active[0].count() if active else 0

    def chunking_version(self) -> int:
        """Versione dei chunk presenti. Le KB senza versione sono quelle da 3000 parole."""
        active = self._resolve()
        return (active[0].metadata or {}).get("kb_chunking_version", 1) if active else 1

    def embedding_version(self) -> int | None:
        """Versione dell'embedding della KB letta, None se non c'e' KB."""
        active = self._resolve()
        return active[1].version if active else None

    def is_current(self) -> bool:
        """True se la KB letta ha i chunk della versione attuale e l'embedding di questo processo."""
        active = self._resolve()
        if not active:
            return False
        coll, embedder = active
        return (embedder.version == get_kb_embedder().version
                and (coll.metadata or {}).get("kb_chunking_version", 1) >= KB_CHUNKING_VERSION)

    def ingest_text(self, text: str) -> int:
        """Ricostruisce la KB dal testo del progetto con l'embedding di questo processo. Ritorna i chunk.

        Con un embedding diverso da quello della KB attuale scrive in un'altra collection: chi legge
        resta sulla vecchia finche' la nuova non e' timbrata, poi la vecchia si cancella.
        """
        chunks = chunk_kb_text(text)
        embedder = get_kb_embedder()
        coll = self._client.get_or_create_collection(
            name=self._collection_name(embedder.version),
            metadata={"project_id": self.project_id, "type": "knowledge_base"},
            embedding_function=embedder.chroma_ef,
        )
        self._write_chunks(coll, embedder, chunks)
        # Per ultima: una ricostruzione interrotta resta "vecchia" e lo spawn dopo la riprende
        coll.modify(metadata={
            **(coll.metadata or {}),
            "kb_chunking_version": KB_CHUNKING_VERSION,
            "kb_chunk_words": KB_CHUNK_WORDS,
            "kb_chunk_overlap_words": KB_CHUNK_OVERLAP_WORDS,
            "kb_embedding_version": embedder.version,
            "kb_embedding": embedder.name,
        })
        self._active = None
        self._drop_other_collections(embedder.version)
        return len(chunks)

    def _write_chunks(self, coll, embedder, chunks: list[str]):
        """Sostituisce i chunk di una collection.

        Prima scrive i nuovi, poi cancella i vecchi: se l'embedding fallisce i vecchi restano.
        Gli id dipendono dalla posizione, cosi' due spawn concorrenti non duplicano i chunk.
        """
        previous_ids = coll.get(include=[])["ids"]
        ids = [f"chunk_{i}" for i in range(len(chunks))]
        metas = [{"project_id": self.project_id, "chunk_idx": i} for i in range(len(chunks))]
        for start in range(0, len(chunks), KB_INGEST_BATCH):
            end = start + KB_INGEST_BATCH
            coll.upsert(ids=ids[start:end], documents=chunks[start:end], metadatas=metas[start:end],
                        embeddings=embedder.embed_documents(chunks[start:end]))
        stale_ids = sorted(set(previous_ids) - set(ids))
        if stale_ids:
            coll.delete(ids=stale_ids)
        log.info("kb_ingested", project_id=self.project_id, chunks=len(chunks), embedding_version=embedder.version)

    def _drop_other_collections(self, keep_version: int):
        """Cancella le KB del progetto con un altro embedding: sono ferme al testo di prima."""
        from chromadb.errors import NotFoundError
        for version in sorted({DEFAULT_EMBEDDING_VERSION, E5_EMBEDDING_VERSION} - {keep_version}):
            name = self._collection_name(version)
            try:
                self._client.delete_collection(name=name)
                log.info("kb_old_collection_deleted", project_id=self.project_id, collection=name)
            except NotFoundError:
                pass
            except Exception as e:
                log.warning("kb_old_collection_delete_failed", project_id=self.project_id,
                            collection=name, error=str(e)[:300])

    def _query(self, texts: list[str], n: int) -> list[list[str]]:
        """Top-n documenti per ciascun testo, con l'embedding della KB letta.

        Se la collection letta sparisce (una ricostruzione l'ha sostituita) risolve di nuovo e riprova una volta.
        """
        for attempt in range(2):
            active = self._resolve()
            if not active:
                return [[] for _ in texts]
            coll, embedder = active
            try:
                count = coll.count()
                if count == 0:
                    return [[] for _ in texts]
                results = coll.query(
                    query_embeddings=embedder.embed_queries(texts),
                    n_results=min(n, count),
                    include=["documents"],
                )
                return results.get("documents") or [[] for _ in texts]
            except Exception:
                self._active = None
                if attempt:
                    raise
        return [[] for _ in texts]

    def retrieve(self, query: str, n: int = 3) -> list[str]:
        """Top-N chunk rilevanti per una query. Ritorna solo i testi."""
        try:
            return self._query([query], n)[0]
        except Exception as e:
            log.warning("kb_retrieve_error", project_id=self.project_id, error=str(e))
            return []

    def retrieve_for_agent(self, agent, topic: str, n_per_query: int = 3, final_n: int = 5) -> list[str]:
        """
        Retrieval multi-query differenziato per agente. Genera 3 query che riflettono
        angoli distinti della persona (ruolo, credenze, paure), le esegue, e aggrega
        i risultati con scoring basato su frequenza di apparizione.

        Questo massimizza la diversita' informativa: chunk che rispondono a piu' di
        una query (coerenti con piu' dimensioni dell'agente) hanno score piu' alto.

        Ritorna fino a `final_n` chunk unici, ordinati per rilevanza aggregata.
        """
        try:
            if self.count() == 0:
                return []
        except Exception as e:
            self._active = None
            log.warning("kb_count_error", project_id=self.project_id, error=str(e))
            return []

        persona = getattr(agent, "persona", None)
        if persona is None:
            return self.retrieve(topic, n=final_n)

        # Costruisci 3 query dai vari angoli della persona
        role = getattr(persona, "role", "") or ""
        background = (getattr(persona, "background", "") or "")[:200]
        beliefs = getattr(persona, "core_beliefs", []) or []
        fears = getattr(persona, "fears", []) or []
        motivations = getattr(persona, "motivations", []) or []

        beliefs_str = " ".join(beliefs[:3]) if beliefs else ""
        fears_str = " ".join(fears[:3]) if fears else " ".join(motivations[:3])

        queries = [
            f"{topic} {role} {background}".strip(),
            f"{topic} {beliefs_str}".strip() if beliefs_str else f"{topic} {role}".strip(),
            f"{topic} {fears_str}".strip() if fears_str else f"{topic} {role}".strip(),
        ]
        # Dedupe query identiche per evitare chiamate ridondanti
        seen_q = set()
        unique_queries = []
        for q in queries:
            key = q.lower()
            if key and key not in seen_q:
                seen_q.add(key)
                unique_queries.append(q)

        # Esegui le query in un'unica chiamata
        try:
            docs_lists = self._query(unique_queries, n_per_query)
        except Exception as e:
            log.warning("kb_multiquery_error", project_id=self.project_id, error=str(e))
            return self.retrieve(topic, n=final_n)

        # Score aggregato: doc presente in n query -> score n. A parita' di score, vince chi appare prima.
        score_map: dict[str, float] = {}
        first_pos: dict[str, int] = {}
        idx_counter = 0
        for query_docs in docs_lists:
            for pos, doc in enumerate(query_docs or []):
                if not doc:
                    continue
                score_map[doc] = score_map.get(doc, 0.0) + (1.0 / (pos + 1))  # reciprocal rank
                if doc not in first_pos:
                    first_pos[doc] = idx_counter
                    idx_counter += 1

        # Ordina per score desc, poi per ordine di apparizione asc
        sorted_docs = sorted(
            score_map.keys(),
            key=lambda d: (-score_map[d], first_pos[d]),
        )

        log.info("kb_retrieve_for_agent",
                 agent_id=getattr(agent, "agent_id", "?"),
                 queries=len(unique_queries),
                 unique_chunks=len(sorted_docs),
                 returned=min(len(sorted_docs), final_n))

        return sorted_docs[:final_n]
