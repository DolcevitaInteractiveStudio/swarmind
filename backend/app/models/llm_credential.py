"""
Credenziali LLM per utente.

Ogni utente (piano Pro/Enterprise) può salvare le proprie chiavi API
per i provider supportati. Le chiavi sono cifrate a riposo con Fernet.

Provider supportati:
  anthropic   → Claude (claude-3-5-sonnet, claude-3-haiku, ...)
  openai      → ChatGPT (gpt-4o, gpt-4o-mini, ...)
  groq        → Groq Cloud (llama-3.3-70b, mixtral, ...)
  openrouter  → OpenRouter (accesso a 200+ modelli)
"""
import uuid
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from flask import current_app
from .base import db


SUPPORTED_PROVIDERS = {
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "openai_compatible": True,
        "models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ],
        "docs_url": "https://console.groq.com/keys",
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "base_url": "https://api.anthropic.com",
        "openai_compatible": False,
        "models": [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ],
        "docs_url": "https://console.anthropic.com/account/keys",
    },
    "openai": {
        "label": "OpenAI ChatGPT",
        "base_url": "https://api.openai.com/v1",
        "openai_compatible": True,
        "models": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "o1-mini",
        ],
        "docs_url": "https://platform.openai.com/api-keys",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "openai_compatible": True,
        "models": [
            "meta-llama/llama-3.3-70b-instruct",
            "google/gemini-2.0-flash-001",
            "mistralai/mistral-large",
            "anthropic/claude-sonnet-4-6",
            "deepseek/deepseek-chat-v3-0324",
        ],
        "docs_url": "https://openrouter.ai/keys",
    },
}


def _fernet() -> Fernet:
    key = current_app.config.get("ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("ENCRYPTION_KEY not set in config")
    return Fernet(key.encode() if isinstance(key, str) else key)


class LLMCredential(db.Model):
    __tablename__ = "llm_credentials"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    provider = db.Column(db.String(50), nullable=False)   # groq | anthropic | openai | openrouter
    label = db.Column(db.String(100), nullable=False, default="")  # nome custom utente
    encrypted_api_key = db.Column(db.Text, nullable=False)
    # modello preferito scelto dall'utente per heavy/agent/fast tier
    model_heavy = db.Column(db.String(100), nullable=True)
    model_agent = db.Column(db.String(100), nullable=True)
    model_fast = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)   # testata con una chiamata ping
    last_used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref=db.backref("llm_credentials", lazy="dynamic", cascade="all, delete-orphan"))

    __table_args__ = (
        db.UniqueConstraint("user_id", "provider", "label", name="uq_user_provider_label"),
    )

    # ── Cifratura ──────────────────────────────────────────────────────────

    def set_api_key(self, raw_key: str):
        """Cifra e salva la chiave API."""
        self.encrypted_api_key = _fernet().encrypt(raw_key.encode()).decode()

    def get_api_key(self) -> str:
        """Decifra e restituisce la chiave API."""
        return _fernet().decrypt(self.encrypted_api_key.encode()).decode()

    # ── Serializzazione ────────────────────────────────────────────────────

    def to_dict(self, include_key: bool = False) -> dict:
        meta = SUPPORTED_PROVIDERS.get(self.provider, {})
        data = {
            "id": self.id,
            "provider": self.provider,
            "provider_label": meta.get("label", self.provider),
            "label": self.label,
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "models": meta.get("models", []),
            "model_heavy": self.model_heavy or (meta.get("models") or [None])[0],
            "model_agent": self.model_agent or (meta.get("models") or [None])[0],
            "model_fast": self.model_fast or (meta.get("models") or [None])[-1],
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "created_at": self.created_at.isoformat(),
            # Mostra solo gli ultimi 4 caratteri della chiave
            "api_key_hint": f"{'*' * 12}{self.get_api_key()[-4:]}" if not include_key else None,
        }
        if include_key:
            data["api_key"] = self.get_api_key()
        return data
