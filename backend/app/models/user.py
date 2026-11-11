import enum
import uuid
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash, check_password_hash
from .base import db


class Role(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(255), nullable=False, default="")
    role = db.Column(db.Enum(Role), nullable=False, default=Role.USER)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_verified = db.Column(db.Boolean, nullable=False, default=False)
    verification_token = db.Column(db.String(255), nullable=True)
    reset_token = db.Column(db.String(255), nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)
    avatar_url = db.Column(db.String(512), nullable=True)
    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    subscription = db.relationship("Subscription", back_populates="user", uselist=False, cascade="all, delete-orphan")
    projects = db.relationship("Project", back_populates="user", lazy="dynamic", cascade="all, delete-orphan")
    audit_logs = db.relationship("AuditLog", back_populates="user", lazy="dynamic", cascade="all, delete-orphan")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role in (Role.ADMIN, Role.SUPERADMIN)

    @property
    def is_superadmin(self) -> bool:
        return self.role == Role.SUPERADMIN

    def to_dict(self, include_private: bool = False) -> dict:
        data = {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role.value,
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "avatar_url": self.avatar_url,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat(),
            "subscription": self.subscription.to_dict() if self.subscription else None,
        }
        if include_private:
            data["verification_token"] = self.verification_token
        return data

    def __repr__(self):
        return f"<User {self.email} ({self.role.value})>"
