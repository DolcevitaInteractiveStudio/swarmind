import uuid
import enum
from datetime import datetime, timezone
from app.core.i18n import coded_message, request_language
from .base import db

# Same limit as simulation/lifecycle.py for the rendered failure messages
_MAX_MESSAGE_CHARS = 400


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    source_filename = db.Column(db.String(512), nullable=True)
    source_file_path = db.Column(db.String(512), nullable=True)
    graph_built = db.Column(db.Boolean, default=False)
    graph_task_id = db.Column(db.String(255), nullable=True)
    num_entities = db.Column(db.Integer, default=0)
    num_relations = db.Column(db.Integer, default=0)
    # Motivo per cui il grafo non e' stato costruito (il progetto non ha un campo status)
    graph_error = db.Column(db.Text, nullable=True)
    # Lo stesso motivo come codice + parametri (lifecycle), reso alla lettura nella lingua della
    # richiesta. NULL nelle righe scritte prima: si mostra graph_error
    graph_error_detail = db.Column(db.JSON, nullable=True)

    # Configurazione LLM del progetto (usato per build grafo, spawn agenti, report)
    # Le simulazioni ereditano questi valori se non specificano override
    llm_provider = db.Column(db.String(50), nullable=True)
    llm_credential_id = db.Column(db.String(36), db.ForeignKey("llm_credentials.id"), nullable=True)
    model_heavy = db.Column(db.String(100), nullable=True)
    model_agent = db.Column(db.String(100), nullable=True)
    model_fast = db.Column(db.String(100), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", back_populates="projects")
    simulations = db.relationship("Simulation", back_populates="project", lazy="dynamic", cascade="all, delete-orphan")
    llm_credential = db.relationship("LLMCredential", foreign_keys=[llm_credential_id])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source_filename": self.source_filename,
            "graph_built": self.graph_built,
            "num_entities": self.num_entities,
            "num_relations": self.num_relations,
            "graph_error": self.graph_error and coded_message(
                request_language(), self.graph_error_detail, self.graph_error, max_chars=_MAX_MESSAGE_CHARS),
            "simulations_count": self.simulations.count(),
            "llm_provider": self.llm_provider,
            "llm_credential_id": self.llm_credential_id,
            "model_heavy": self.model_heavy,
            "model_agent": self.model_agent,
            "model_fast": self.model_fast,
            "created_at": self.created_at.isoformat(),
        }


class SimulationStatus(str, enum.Enum):
    PENDING = "pending"
    BUILDING_GRAPH = "building_graph"
    SPAWNING_AGENTS = "spawning_agents"
    RUNNING = "running"
    GENERATING_REPORT = "generating_report"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


def _template_name(template_id: str | None) -> str | None:
    if not template_id:
        return None
    from app.templates import get_registry
    # Il nome nella lingua di chi legge (UI), non in quella della simulazione
    template = get_registry().get(template_id, request_language())
    return template["name"] if template else template_id


PHASE_BY_STATUS = {
    SimulationStatus.BUILDING_GRAPH: "graph",
    SimulationStatus.SPAWNING_AGENTS: "spawn",
    SimulationStatus.RUNNING: "rounds",
    SimulationStatus.GENERATING_REPORT: "report",
}


class Simulation(db.Model):
    __tablename__ = "simulations"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = db.Column(db.String(36), db.ForeignKey("projects.id"), nullable=False, index=True)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)

    name = db.Column(db.String(255), nullable=False, default="Simulation")
    topic = db.Column(db.Text, nullable=False)
    prediction_requirement = db.Column(db.Text, nullable=False)
    platform_type = db.Column(db.String(50), default="social_media")
    # Language of agent posts and of the report (en|it). Rows created before the column: "it"
    language = db.Column(db.String(8), nullable=False, default="en", server_default="en")

    # Configurazione LLM scelta dall'utente
    llm_provider = db.Column(db.String(50), nullable=False, default="groq")
    llm_credential_id = db.Column(db.String(36), db.ForeignKey("llm_credentials.id"), nullable=True)
    model_heavy = db.Column(db.String(100), nullable=True)
    model_agent = db.Column(db.String(100), nullable=True)
    model_fast = db.Column(db.String(100), nullable=True)

    # Parametri simulazione
    num_agents = db.Column(db.Integer, default=100)
    num_rounds = db.Column(db.Integer, default=30)

    # Template di simulazione (opzionale, es. b2b_saas_pricing)
    template_id = db.Column(db.String(100), nullable=True)
    # Voci critiche custom fornite dall'utente (lista di dict con nome/ruolo)
    custom_adversaries = db.Column(db.JSON, nullable=True)

    # Stato
    status = db.Column(db.Enum(SimulationStatus), default=SimulationStatus.PENDING)
    celery_task_id = db.Column(db.String(255), nullable=True)
    current_round = db.Column(db.Integer, default=0)
    total_posts = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text, nullable=True)
    # error_message come codice + parametri (lifecycle), reso alla lettura nella lingua della
    # richiesta. NULL nelle righe scritte prima: si mostra error_message
    error_detail = db.Column(db.JSON, nullable=True)
    # Quota restituita per una simulazione fallita (lifecycle.refund_quota): mai due volte
    quota_refunded = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    quota_refund_reason = db.Column(db.String(32), nullable=True)

    # Metriche finali
    final_entropy = db.Column(db.Float, nullable=True)
    final_polarization = db.Column(db.Float, nullable=True)
    confidence_score = db.Column(db.Float, nullable=True)

    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    project = db.relationship("Project", back_populates="simulations")
    llm_credential = db.relationship("LLMCredential", foreign_keys=[llm_credential_id])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "topic": self.topic,
            "prediction_requirement": self.prediction_requirement,
            "platform_type": self.platform_type,
            "language": self.language,
            "llm_provider": self.llm_provider,
            "model_heavy": self.model_heavy,
            "model_agent": self.model_agent,
            "model_fast": self.model_fast,
            "num_agents": self.num_agents,
            "num_rounds": self.num_rounds,
            "template_id": self.template_id,
            "template_name": _template_name(self.template_id),
            "custom_adversaries": self.custom_adversaries,
            "status": self.status.value,
            "quota_refunded": bool(self.quota_refunded),
            "phase": PHASE_BY_STATUS.get(self.status),
            "current_round": self.current_round,
            "total_rounds": self.num_rounds,
            "total_posts": self.total_posts,
            "error_message": self.error_message and coded_message(
                request_language(), self.error_detail, self.error_message, max_chars=_MAX_MESSAGE_CHARS),
            "final_entropy": self.final_entropy,
            "final_polarization": self.final_polarization,
            "confidence_score": self.confidence_score,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat(),
        }
