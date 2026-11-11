"""
SwarMind Agent Memory — ChromaDB-backed episodic + semantic memory.

Una collection Chroma per simulazione (sim_<id>_memory), condivisa dagli agenti: ogni record ha
agent_id e round nei metadati e ogni lettura filtra per agent_id. Prima c'era una collection per
agente: ~20 collection nuove per simulazione, mai cancellate (255 sul server a novembre 2026).
Le collection per agente delle simulazioni vecchie non le legge piu' nessuno dopo il run (report e
chat usano i campi della persona): non si migrano, si cancellano con flask chroma-cleanup.
Memory is persisted across simulation rounds.
Retrieval uses semantic similarity (embeddings).

La memoria non e' essenziale: ogni chiamata a Chroma passa da run_chroma (in un thread, con un tetto
di tempo) e, se fallisce o scade, si registra memory_store_failed / memory_read_failed e l'agente
prosegue senza memoria per quella chiamata. L'embedding (stessa funzione di default di Chroma) si
calcola prima, in un pool a parte: il tetto di tempo misura solo Chroma, non la CPU.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import chromadb
import structlog

from ..config import Config
from .chroma_client import ChromaSkipped, chroma_available, error_text, get_chroma, run_chroma

log = structlog.get_logger()

_WRITE_OPS = ("store", "seed")

# Embedding locale (CPU) fuori dal tetto di tempo delle chiamate a Chroma: il timeout e la pausa dopo
# un errore devono dire se Chroma risponde, non quanto e' carica la CPU.
# Stesso modello e stesso codice dell'embedding di default di Chroma (DefaultEmbeddingFunction chiama
# ONNXMiniLM_L6_V2), ma un'istanza sola: in chromadb 1.0.21 DefaultEmbeddingFunction crea un
# ONNXMiniLM_L6_V2 nuovo a ogni chiamata e ricarica tokenizer e sessione onnxruntime (~0,65 s, quasi
# tutti con il GIL preso: il loop della simulazione restava fermo anche con l'embedding in un thread).
# Due thread: onnxruntime usa gia' tutti i core, in parallelo le chiamate si rallentano soltanto.
EMBED_THREADS = 2
# Tetto di sicurezza: l'embedding locale non si blocca, ma una CPU satura non deve fermare un agente
EMBED_TIMEOUT_SECONDS = 60

_embed_lock = threading.Lock()
_embed_state: dict = {"pid": None, "function": None, "executor": None}


def _embed_state_for_process() -> dict:
    """Stato di questo processo (con _embed_lock preso). Dopo un fork si riparte da zero: la sessione
    onnxruntime e i thread del padre non si usano nel figlio."""
    if _embed_state["pid"] != os.getpid():
        _embed_state.update(pid=os.getpid(), function=None, executor=None)
    return _embed_state


def _embedding_function():
    """Il modello dell'embedding di default di Chroma, un'istanza per processo. Sincrona: l'import e
    il modello si caricano nei thread di embedding, mai nel loop."""
    with _embed_lock:
        state = _embed_state_for_process()
        if state["function"] is None:
            from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
            state["function"] = ONNXMiniLM_L6_V2()
        return state["function"]


def _embed_executor() -> ThreadPoolExecutor:
    with _embed_lock:
        state = _embed_state_for_process()
        if state["executor"] is None:
            state["executor"] = ThreadPoolExecutor(max_workers=EMBED_THREADS, thread_name_prefix="embed")
        return state["executor"]


def _embed_sync(documents: list[str]) -> list:
    return _embedding_function()(documents)


async def _embed(documents: list[str]) -> list:
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(loop.run_in_executor(_embed_executor(), _embed_sync, documents),
                                  EMBED_TIMEOUT_SECONDS)


def memory_collection_name(simulation_id: str) -> str:
    """Collection della memoria di una simulazione."""
    return f"sim_{simulation_id}_memory"


# Collection per simulazione gia' aperte da questo processo: gli agenti di un run ne condividono una
_collections: dict[str, chromadb.Collection] = {}
_collections_lock = threading.Lock()
_collections_pid: int | None = None


def _simulation_collection(simulation_id: str) -> chromadb.Collection:
    """Sincrona (thread di run_chroma). Crea la collection al primo uso, una volta sola per processo."""
    global _collections_pid
    with _collections_lock:
        if _collections_pid != os.getpid():
            _collections.clear()
            _collections_pid = os.getpid()
        collection = _collections.get(simulation_id)
        if collection is None:
            # Embedding di default di Chroma, come le collection per agente di prima. I vettori di
            # add e query li calcola _embed con lo stesso modello
            collection = get_chroma().get_or_create_collection(
                name=memory_collection_name(simulation_id),
                metadata={"simulation_id": simulation_id, "type": "agent_memory"},
            )
            _collections[simulation_id] = collection
        return collection


def forget_simulation_collection(simulation_id: str) -> None:
    """Dimentica la collection aperta (dopo averla cancellata)."""
    with _collections_lock:
        _collections.pop(simulation_id, None)


def _round_of(meta: dict) -> float:
    """Round di una memoria; senza round (o non numerico) viene prima di tutte."""
    try:
        return float(meta.get("round"))
    except (TypeError, ValueError):
        return -1.0


class AgentMemory:
    """
    Persistent vector memory for a single agent.

    Two memory types:
      episodic  — specific events/actions from simulation rounds
      semantic  — general knowledge / beliefs (from persona + graph)
    """

    def __init__(self, agent_id: str, simulation_id: str):
        self.agent_id = agent_id
        self.simulation_id = simulation_id
        self._collection_name = memory_collection_name(simulation_id)

    def _get_collection(self) -> chromadb.Collection:
        """Sincrona: gira nel thread di run_chroma."""
        return _simulation_collection(self.simulation_id)

    def _where(self) -> dict:
        return {"agent_id": self.agent_id}

    async def _run(self, op: str, fn, default, *args):
        """fn(*args) su Chroma entro CHROMA_MEMORY_OP_TIMEOUT; se fallisce registra l'errore e ritorna default."""
        started = time.monotonic()
        try:
            return await run_chroma(f"memory_{op}", fn, *args, timeout=Config.CHROMA_MEMORY_OP_TIMEOUT)
        except Exception as e:
            event = "memory_store_failed" if op in _WRITE_OPS else "memory_read_failed"
            # Con Chroma in pausa ogni chiamata salta subito: una riga per chiamata solo in debug
            emit = log.debug if isinstance(e, ChromaSkipped) else log.warning
            emit(event, agent=self.agent_id, simulation_id=self.simulation_id, op=op,
                 error=error_text(e), ms=round((time.monotonic() - started) * 1000))
            return default

    def _meta(self, timestamp: float, extra: dict | None) -> dict:
        return {
            "agent_id": self.agent_id,
            "simulation_id": self.simulation_id,
            "timestamp": timestamp,
            **(extra or {}),
        }

    def _add_sync(self, documents: list[str], metadatas: list[dict], embeddings: list) -> list[str]:
        ids = [str(uuid.uuid4()) for _ in documents]
        self._get_collection().add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
        return ids

    async def _add(self, op: str, documents: list[str], metadatas: list[dict]) -> list[str] | None:
        """Embedding nel pool locale, poi la scrittura su Chroma con il suo timeout. None se fallisce."""
        if not chroma_available():
            # Chroma in pausa: inutile calcolare l'embedding
            return await self._run(op, self._add_sync, None, documents, metadatas, [])
        started = time.monotonic()
        try:
            embeddings = await _embed(documents)
        except Exception as e:
            log.warning("memory_store_failed", agent=self.agent_id, simulation_id=self.simulation_id,
                        op=f"{op}_embedding", error=error_text(e), ms=round((time.monotonic() - started) * 1000))
            return None
        return await self._run(op, self._add_sync, None, documents, metadatas, embeddings)

    async def store(self, content: str, metadata: dict | None = None) -> str | None:
        """Store a memory entry. Returns the memory ID, None if Chroma failed."""
        ids = await self._add("store", [content], [self._meta(time.time(), metadata)])
        return ids[0] if ids else None

    def _retrieve_sync(self, query_embedding, n: int) -> list[dict]:
        collection = self._get_collection()
        # count() conta tutta la simulazione: i record dell'agente si contano con il filtro
        count = len(collection.get(where=self._where(), include=[])["ids"])
        if count == 0:
            return []
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n, count),
            where=self._where(),
            include=["documents", "metadatas", "distances"],
        )
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]
        return [
            {"content": doc, "metadata": meta, "relevance": 1 - dist}
            for doc, meta, dist in zip(docs, metas, dists)
        ]

    async def retrieve(self, query: str, n: int = 5) -> list[dict]:
        """Semantic similarity search — returns most relevant memories."""
        if not chroma_available():
            return await self._run("retrieve", self._retrieve_sync, [], None, n)
        try:
            query_embedding = (await _embed([query]))[0]
        except Exception as e:
            log.warning("memory_read_failed", agent=self.agent_id, simulation_id=self.simulation_id,
                        op="retrieve_embedding", error=error_text(e), ms=0)
            return []
        return await self._run("retrieve", self._retrieve_sync, [], query_embedding, n)

    def _recent_sync(self, n: int) -> list[dict]:
        # Tutti i record dell'agente: un get con limit ritorna i primi salvati, non gli ultimi
        results = self._get_collection().get(where=self._where(), include=["documents", "metadatas"])
        combined = [
            (doc, meta or {}) for doc, meta in zip(results["documents"], results["metadatas"])
        ]
        combined.sort(key=lambda x: (_round_of(x[1]), x[1].get("timestamp", 0)), reverse=True)
        return [{"content": doc, "metadata": meta} for doc, meta in combined[:n]]

    async def get_recent(self, n: int = 5) -> list[dict]:
        """The N most recent memories, newest first: by round, then by timestamp within a round."""
        return await self._run("get_recent", self._recent_sync, [], n)

    async def seed_from_persona(self, persona_summary: str, beliefs: list[str]) -> bool:
        """Pre-populate semantic memory with persona knowledge. True se salvata.

        Una sola scrittura per agente. I timestamp crescono di 1 ms come quando ogni seed era una
        scrittura a se': get_recent li ordina come prima (l'ultima credenza per prima).
        """
        documents = [f"My background and personality: {persona_summary}"]
        documents += [f"I strongly believe: {belief}" for belief in beliefs]
        now = time.time()
        metadatas = [
            self._meta(now + i * 0.001, {"type": "semantic", "round": 0}) for i in range(len(documents))
        ]
        return await self._add("seed", documents, metadatas) is not None


# Compatibilita': knowledge_base e altri importavano get_chroma da qui
__all__ = ["AgentMemory", "get_chroma"]
