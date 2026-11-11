"""
Piani SaaS e relative quote.

Free      → 1 simulazione/mese, 50 agenti, 20 round, solo Groq
Pro       → 20 simulazioni/mese, 500 agenti, 200 round, tutti i provider
Enterprise→ illimitato, 2000 agenti, 500 round, tutti i provider + supporto
"""
import uuid
import enum
from datetime import datetime, timezone

import structlog
from sqlalchemy import text

from .base import db
from .usage_period import as_utc, to_db, usage_period_start

log = structlog.get_logger()


class PlanTier(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class SubStatus(str, enum.Enum):
    ACTIVE = "active"
    TRIALING = "trialing"
    PAST_DUE = "past_due"
    CANCELED = "canceled"


class Plan(db.Model):
    __tablename__ = "plans"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), unique=True, nullable=False)
    tier = db.Column(db.Enum(PlanTier), nullable=False, default=PlanTier.FREE)
    price_monthly = db.Column(db.Float, nullable=False, default=0.0)
    price_yearly = db.Column(db.Float, nullable=False, default=0.0)
    stripe_price_id_monthly = db.Column(db.String(255), nullable=True)
    stripe_price_id_yearly = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Quote numeriche
    max_simulations_per_month = db.Column(db.Integer, nullable=False, default=1)
    max_agents = db.Column(db.Integer, nullable=False, default=50)
    max_rounds = db.Column(db.Integer, nullable=False, default=20)
    max_projects = db.Column(db.Integer, nullable=False, default=3)
    max_file_size_mb = db.Column(db.Integer, nullable=False, default=5)

    # Providers LLM consentiti (JSON list)
    allowed_providers = db.Column(db.JSON, nullable=False,
                                  default=lambda: ["groq"])

    # Feature flags
    can_use_custom_api_keys = db.Column(db.Boolean, default=False)
    can_export_report = db.Column(db.Boolean, default=False)
    can_chat_with_agents = db.Column(db.Boolean, default=False)
    priority_queue = db.Column(db.Boolean, default=False)

    subscriptions = db.relationship("Subscription", back_populates="plan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "tier": self.tier.value,
            "price_monthly": self.price_monthly,
            "price_yearly": self.price_yearly,
            "limits": {
                "simulations_per_month": self.max_simulations_per_month,
                "agents": self.max_agents,
                "rounds": self.max_rounds,
                "projects": self.max_projects,
                "file_size_mb": self.max_file_size_mb,
            },
            "allowed_providers": self.allowed_providers,
            "features": {
                "custom_api_keys": self.can_use_custom_api_keys,
                "export_report": self.can_export_report,
                "chat_with_agents": self.can_chat_with_agents,
                "priority_queue": self.priority_queue,
            },
        }


class Subscription(db.Model):
    __tablename__ = "subscriptions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    plan_id = db.Column(db.String(36), db.ForeignKey("plans.id"), nullable=False)
    status = db.Column(db.Enum(SubStatus), nullable=False, default=SubStatus.ACTIVE)
    stripe_subscription_id = db.Column(db.String(255), nullable=True)
    stripe_customer_id = db.Column(db.String(255), nullable=True)
    current_period_start = db.Column(db.DateTime, nullable=True)
    current_period_end = db.Column(db.DateTime, nullable=True)
    canceled_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # Contatori uso corrente (reset ogni mese)
    simulations_used_this_month = db.Column(db.Integer, default=0)
    usage_reset_at = db.Column(db.DateTime, nullable=True)
    # Graph builds on the shared system key in the quota period that starts at graph_system_builds_period
    # (GRAPH_SYSTEM_KEY_MONTHLY_LIMIT, api/graph.py). An older period counts as zero
    graph_system_builds_used = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    graph_system_builds_period = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", back_populates="subscription")
    plan = db.relationship("Plan", back_populates="subscriptions")

    def to_dict(self) -> dict:
        self.refresh_usage_period()
        return {
            "id": self.id,
            "status": self.status.value,
            "plan": self.plan.to_dict() if self.plan else None,
            "current_period_end": self.current_period_end.isoformat()
                if self.current_period_end else None,
            "simulations_used_this_month": self.simulations_used_this_month,
        }

    def usage_period_start(self, now: datetime | None = None) -> datetime:
        return usage_period_start(self.stripe_subscription_id, self.current_period_start,
                                  self.current_period_end, now)

    def refresh_usage_period(self, now: datetime | None = None) -> bool:
        """Azzera il contatore se usage_reset_at e' prima dell'inizio del periodo corrente.

        Una sola volta per periodo anche con richieste concorrenti: la riga si blocca con FOR UPDATE
        e si ricontrolla usage_reset_at. Il reset gira in una transazione sua, cosi' non conferma
        modifiche in sospeso del chiamante. Il nuovo valore sono le simulazioni del periodo
        corrente non rimborsate: 0 al cambio di periodo, il conteggio reale la prima volta (righe
        con usage_reset_at vuoto, contatore mai azzerato). True se il contatore e' stato azzerato.
        """
        period_start = self.usage_period_start(now)
        last_reset = as_utc(self.usage_reset_at)
        if self.id is None or (last_reset is not None and last_reset >= period_start):
            return False
        try:
            with db.engine.begin() as conn:
                conn.execute(text("SET LOCAL lock_timeout = '5s'"))
                row = conn.execute(
                    text("SELECT simulations_used_this_month, usage_reset_at FROM subscriptions "
                         "WHERE id = :id FOR UPDATE"),
                    {"id": self.id},
                ).first()
                if row is None:
                    return False
                old_count, locked_reset = row
                if locked_reset is not None and as_utc(locked_reset) >= period_start:
                    reset = False  # azzerato da una richiesta concorrente
                else:
                    new_count = conn.execute(
                        text("SELECT count(*) FROM simulations WHERE user_id = :user_id "
                             "AND created_at >= :period_start AND quota_refunded IS NOT TRUE"),
                        {"user_id": self.user_id, "period_start": to_db(period_start)},
                    ).scalar()
                    conn.execute(
                        text("UPDATE subscriptions SET simulations_used_this_month = :n, "
                             "usage_reset_at = :period_start WHERE id = :id"),
                        {"n": new_count, "period_start": to_db(period_start), "id": self.id},
                    )
                    reset = True
        except Exception as e:
            log.warning("quota_period_reset_failed", user_id=self.user_id, subscription_id=self.id,
                        period_start=period_start.isoformat(), error=str(e)[:300])
            return False
        # Ricarica i due campi dalla sessione del chiamante (anche se il reset l'ha fatto un altro)
        if self in db.session:
            db.session.expire(self, ["simulations_used_this_month", "usage_reset_at"])
        if reset:
            log.info("quota_period_reset", user_id=self.user_id, subscription_id=self.id,
                     old_count=old_count, new_count=new_count,
                     previous_reset_at=as_utc(locked_reset).isoformat() if locked_reset else None,
                     period_start=period_start.isoformat())
        return reset

    def has_quota(self) -> bool:
        """True se l'utente ha ancora simulazioni disponibili questo mese."""
        self.refresh_usage_period()
        if self.plan.max_simulations_per_month == -1:
            return True  # illimitato
        return self.simulations_used_this_month < self.plan.max_simulations_per_month

    def provider_allowed(self, provider: str) -> bool:
        return provider in (self.plan.allowed_providers or [])
