"""SwarMind — configurazione dall'ambiente (.env). Ogni variabile e' documentata in .env.example."""
import hashlib
import hmac
import os


def _bool_env(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _derived_secret_key(encryption_key: str) -> str:
    """SECRET_KEY quando .env non la imposta: derivata da ENCRYPTION_KEY (gia' casuale e obbligatoria).

    Etichetta fissa: cambiare ENCRYPTION_KEY cambia anche questa chiave (tutti i token JWT scadono).
    """
    return hmac.new(encryption_key.encode(), b"swarmind/flask-secret-key/v1", hashlib.sha256).hexdigest()


class Config:
    DEBUG = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024

    # Docker Compose imposta sempre DATABASE_URL (con la password di .env): questo default serve
    # solo a chi avvia il backend fuori da Compose, con un Postgres locale senza password
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql://swarmind@localhost:5432/swarmind"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 300}

    REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    # Failed password checks (login, password change) per window: per account and per client IP.
    # Over a limit the endpoint answers 429 until the window ends. 0 turns a limit off (core/login_throttle.py)
    LOGIN_THROTTLE_WINDOW_SECONDS  = int(os.environ.get("LOGIN_THROTTLE_WINDOW_SECONDS", "900"))
    LOGIN_MAX_FAILURES_PER_ACCOUNT = int(os.environ.get("LOGIN_MAX_FAILURES_PER_ACCOUNT", "5"))
    LOGIN_MAX_FAILURES_PER_IP      = int(os.environ.get("LOGIN_MAX_FAILURES_PER_IP", "30"))
    # Reverse proxies in front of the backend that append to X-Forwarded-For: 1 is the frontend's nginx
    # (Compose); 2 with a reverse proxy on the host in front of it. The client IP feeds the per-IP limit
    TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "1"))

    CHROMA_HOST = os.environ.get("CHROMA_HOST", "chroma")
    CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8000"))
    CHROMA_TOKEN = os.environ.get("CHROMA_TOKEN", "")
    # Il client HTTP di chromadb 1.0.21 non ha timeout: questi li mette memory/chroma_client.py.
    # Connessione e lettura HTTP: tengono vivo al massimo per questo tempo un thread su un Chroma bloccato
    CHROMA_CONNECT_TIMEOUT   = float(os.environ.get("CHROMA_CONNECT_TIMEOUT", "5"))
    CHROMA_READ_TIMEOUT      = float(os.environ.get("CHROMA_READ_TIMEOUT", "15"))
    # Tetto all'intera operazione chiamata dal loop della simulazione (embedding locale + HTTP).
    # Piu' basso della lettura HTTP: con Chroma bloccato scatta prima questo e il round prosegue
    CHROMA_MEMORY_OP_TIMEOUT = float(os.environ.get("CHROMA_MEMORY_OP_TIMEOUT", "10"))
    CHROMA_KB_OP_TIMEOUT     = float(os.environ.get("CHROMA_KB_OP_TIMEOUT", "10"))
    # Ricostruzione della KB durante il build del grafo (embedding di tutti i chunk)
    CHROMA_KB_INGEST_TIMEOUT = float(os.environ.get("CHROMA_KB_INGEST_TIMEOUT", "600"))
    # Dopo un timeout o un errore di rete le chiamate dal loop saltano Chroma per questo tempo
    CHROMA_COOLDOWN_SECONDS  = float(os.environ.get("CHROMA_COOLDOWN_SECONDS", "30"))

    _ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")
    if not _ENCRYPTION_KEY:
        raise ValueError(
            "ENCRYPTION_KEY environment variable is required. "
            "Set it to a Fernet-compatible key (32 url-safe base64 bytes). "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    ENCRYPTION_KEY = _ENCRYPTION_KEY
    # Firma i token JWT. Vuota in .env: derivata da ENCRYPTION_KEY (vedi _derived_secret_key)
    SECRET_KEY = os.environ.get("SECRET_KEY", "").strip() or _derived_secret_key(_ENCRYPTION_KEY)

    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    # Graph builds per user and per month on the system key (GROQ_API_KEY), for users with no provider key of
    # their own: with one, the build always uses it. -1 no limit, 0 never on the system key
    GRAPH_SYSTEM_KEY_MONTHLY_LIMIT = int(os.environ.get("GRAPH_SYSTEM_KEY_MONTHLY_LIMIT", "20"))
    GROQ_MODEL_HEAVY = os.environ.get("GROQ_MODEL_HEAVY", "llama-3.3-70b-versatile")
    GROQ_MODEL_AGENT = os.environ.get("GROQ_MODEL_AGENT", "openai/gpt-oss-20b")
    GROQ_MODEL_FAST  = os.environ.get("GROQ_MODEL_FAST",  "llama-3.1-8b-instant")

    DEFAULT_NUM_AGENTS = int(os.environ.get("DEFAULT_NUM_AGENTS", "100"))
    MAX_NUM_AGENTS     = int(os.environ.get("MAX_NUM_AGENTS", "2000"))
    DEFAULT_SIM_ROUNDS = int(os.environ.get("DEFAULT_SIM_ROUNDS", "30"))
    MAX_SIM_ROUNDS     = int(os.environ.get("MAX_SIM_ROUNDS", "500"))
    # Language of a new simulation when POST /simulation/create has no "language" (en|it).
    # Validated on use (core.i18n.configured_default_language): an invalid value means "en"
    SIMULATION_DEFAULT_LANGUAGE = os.environ.get("SIMULATION_DEFAULT_LANGUAGE", "en")
    AGENT_DIVERSITY_TEMPERATURE  = float(os.environ.get("AGENT_DIVERSITY_TEMPERATURE", "1.3"))
    OPINION_ENTROPY_THRESHOLD    = float(os.environ.get("OPINION_ENTROPY_THRESHOLD", "0.3"))
    AGENT_CONCURRENCY            = int(os.environ.get("AGENT_CONCURRENCY", "20"))
    STALE_SIMULATION_MINUTES     = int(os.environ.get("STALE_SIMULATION_MINUTES", "15"))

    REPORT_AGENT_MAX_TOOL_CALLS         = int(os.environ.get("REPORT_AGENT_MAX_TOOL_CALLS", "10"))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS  = int(os.environ.get("REPORT_AGENT_MAX_REFLECTION_ROUNDS", "3"))
    REPORT_AGENT_TEMPERATURE            = float(os.environ.get("REPORT_AGENT_TEMPERATURE", "0.4"))

    # Piani e quote restano attivi sempre (li gestisce l'admin). BILLING_ENABLED mostra agli utenti
    # le pagine "Piani" e "Fatturazione" e i link "Aggiorna piano": spento, l'app non parla di pagamenti.
    # Nessuna integrazione di pagamento nel codice: i campi stripe_* dei modelli restano per il futuro.
    BILLING_ENABLED = _bool_env("BILLING_ENABLED")

    # Contatto mostrato dalla landing (sezione Contatti e footer) finche' l'admin non lo cambia
    CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "").strip()

    BASE_DIR        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR        = os.path.join(BASE_DIR, "data")
    SIMULATIONS_DIR = os.path.join(DATA_DIR, "simulations")
    UPLOADS_DIR     = os.path.join(DATA_DIR, "uploads")

    # URL pubblico del frontend: unica origine ammessa da CORS e dal WebSocket
    FRONTEND_URL    = os.environ.get("FRONTEND_URL", "http://localhost:3000").rstrip("/")
