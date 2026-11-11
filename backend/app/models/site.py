"""Site settings: one row (id = 1) with the landing switch, the branding and the landing content.

The document stored here is always the output of core.site_settings.validate_document. An empty
table, or a NULL column, means "the defaults in code" (core.site_settings.default_document).
"""
from datetime import datetime, timezone

from .base import db

SITE_SETTINGS_ID = 1


class SiteSettings(db.Model):
    __tablename__ = "site_settings"
    __table_args__ = (db.CheckConstraint("id = 1", name="site_settings_singleton"),)

    id = db.Column(db.Integer, primary_key=True, autoincrement=False)
    landing_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # {"product_name", "logo": {"dark", "light"}, "favicon", "colors": {"dark": {"primary", "accent"}, "light": {...}}}
    branding = db.Column(db.JSON, nullable=True)
    # {"en": {...}, "it": {...}}: hero, sections, footer, seo per locale
    content = db.Column(db.JSON, nullable=True)
    # Incremented on every save: a save based on an older revision is refused (two admins editing)
    revision = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))
    updated_by = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
