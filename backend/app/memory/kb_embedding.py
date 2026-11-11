"""
Embedding della KB di progetto.

La KB usa intfloat/multilingual-e5-small quantizzato int8 (ONNX), eseguito con onnxruntime e
tokenizers, gia' installati con chromadb: nessuna dipendenza nuova e nessun torch in memoria.
Su 20 domande italiane di un brief reale trova il chunk giusto tra i primi 3 in 19 casi,
contro 11 dell'embedding di default di Chroma (all-MiniLM-L6-v2, pensato per l'inglese).

I file del modello si scaricano una volta sola nella cache Hugging Face (~/.cache/huggingface,
volume hf_cache) a un commit fissato. Se mancano e non si possono scaricare la KB usa l'embedding
di default e registra kb_embedding_fallback: la simulazione continua.
Con KB_EMBEDDING=default nell'ambiente si usa sempre quello di default.

La memoria degli agenti non passa di qui e resta sull'embedding di default di Chroma.
"""
from __future__ import annotations
import os
import threading
import time

import structlog

log = structlog.get_logger()

E5_REPO = "intfloat/multilingual-e5-small"
# Commit fissato: i file sono quelli su cui e' stato misurato il retrieval, e con un commit
# la cache risponde senza chiamate di rete
E5_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
E5_MODEL_FILE = "onnx/model_qint8_avx512_vnni.onnx"
E5_TOKENIZER_FILE = "onnx/tokenizer.json"
E5_MAX_TOKENS = 512
# Batch piccoli: onnxruntime tiene la memoria del batch piu' grande visto. Su Linux con 4 testi
# per batch il processo cresce di ~455 MB (tokenizer ~280, modello ~130), con 16 di ~545 MB
E5_BATCH = 4
# e5 e' addestrato con questi prefissi: senza, il retrieval peggiora
E5_QUERY_PREFIX = "query: "
E5_PASSAGE_PREFIX = "passage: "

# Versione dell'embedding salvata nei metadati della KB: 1 e' quello di default di Chroma.
# Ogni versione ha la sua collection, perche' Chroma lega l'embedding alla collection.
DEFAULT_EMBEDDING_VERSION = 1
E5_EMBEDDING_VERSION = 2
# Dopo un fallimento il processo riprova a caricare il modello dopo questo intervallo
E5_RETRY_SECONDS = 600


class DefaultKbEmbedder:
    """L'embedding di default di Chroma (all-MiniLM-L6-v2), uguale per documenti e query."""

    version = DEFAULT_EMBEDDING_VERSION
    name = "chroma-default-all-MiniLM-L6-v2"

    def __init__(self):
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        # Passato anche a Chroma quando apre la collection, come fa il resto del codice
        self.chroma_ef = DefaultEmbeddingFunction()

    def embed_documents(self, texts: list[str]) -> list:
        return list(self.chroma_ef(texts))

    def embed_queries(self, texts: list[str]) -> list:
        return list(self.chroma_ef(texts))


class E5KbEmbedder:
    """multilingual-e5-small int8 su onnxruntime: mean pooling sui token, vettori normalizzati."""

    version = E5_EMBEDDING_VERSION
    name = f"{E5_REPO}@{E5_REVISION[:7]}:{E5_MODEL_FILE}"
    # Gli embedding li calcola questa classe: Chroma non deve calcolarne altri
    chroma_ef = None

    def __init__(self, model_path: str, tokenizer_path: str):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(tokenizer_path)
        tokenizer.enable_truncation(max_length=E5_MAX_TOKENS)
        pad_id = tokenizer.token_to_id("<pad>")
        tokenizer.enable_padding(pad_id=1 if pad_id is None else pad_id, pad_token="<pad>")
        self._tokenizer = tokenizer
        options = ort.SessionOptions()
        options.log_severity_level = 3
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(model_path, sess_options=options, providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}

    def _embed(self, texts: list[str], prefix: str) -> list[list[float]]:
        import numpy as np
        vectors = []
        for start in range(0, len(texts), E5_BATCH):
            encoded = self._tokenizer.encode_batch([prefix + t for t in texts[start:start + E5_BATCH]])
            ids = np.array([e.ids for e in encoded], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self._session.run(None, feed)[0]
            pooled = (hidden * mask[..., None]).sum(axis=1) / np.maximum(mask.sum(axis=1, keepdims=True), 1)
            pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            vectors.extend(pooled.astype(np.float32).tolist())
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, E5_PASSAGE_PREFIX)

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, E5_QUERY_PREFIX)


def _e5_files() -> tuple[str, str]:
    """Percorsi locali dei file del modello. Il primo uso li scarica (circa 135 MB)."""
    from huggingface_hub import hf_hub_download
    model = hf_hub_download(E5_REPO, E5_MODEL_FILE, revision=E5_REVISION)
    tokenizer = hf_hub_download(E5_REPO, E5_TOKENIZER_FILE, revision=E5_REVISION)
    return model, tokenizer


_lock = threading.Lock()
_state: dict = {"pid": None, "e5": None, "default": None, "failed_at": None}


def default_kb_embedder() -> DefaultKbEmbedder:
    """L'embedder di default, uno per processo."""
    with _lock:
        _reset_after_fork()
        if _state["default"] is None:
            _state["default"] = DefaultKbEmbedder()
        return _state["default"]


def get_kb_embedder():
    """L'embedder della KB per questo processo: e5 se disponibile, altrimenti quello di default.

    Il modello si carica al primo uso in ogni processo (i figli del worker non lo ereditano).
    Se non si carica si registra kb_embedding_fallback e si riprova dopo E5_RETRY_SECONDS.
    """
    if os.environ.get("KB_EMBEDDING", "").strip().lower() == "default":
        return default_kb_embedder()
    with _lock:
        _reset_after_fork()
        if _state["e5"] is not None:
            return _state["e5"]
        failed_at = _state["failed_at"]
        if failed_at is None or time.monotonic() - failed_at >= E5_RETRY_SECONDS:
            started = time.monotonic()
            try:
                _state["e5"] = E5KbEmbedder(*_e5_files())
                _state["failed_at"] = None
                log.info("kb_embedding_loaded", model=E5KbEmbedder.name,
                         seconds=round(time.monotonic() - started, 1))
                return _state["e5"]
            except Exception as e:
                _state["failed_at"] = time.monotonic()
                log.warning("kb_embedding_fallback", model=E5KbEmbedder.name, fallback=DefaultKbEmbedder.name,
                            retry_in_seconds=E5_RETRY_SECONDS, error=f"{type(e).__name__}: {str(e)[:300]}")
    return default_kb_embedder()


def _reset_after_fork():
    """Una sessione onnxruntime non va usata dopo un fork: ogni processo carica la sua."""
    pid = os.getpid()
    if _state["pid"] != pid:
        _state.update(pid=pid, e5=None, default=None, failed_at=None)
