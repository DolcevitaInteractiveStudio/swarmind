"""add quota_refunded to Simulation

Revision ID: c4e8a2d61f97
Revises: a1c3e5f70b12
Create Date: 2026-11-08 12:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'c4e8a2d61f97'
down_revision = 'a1c3e5f70b12'
branch_labels = None
depends_on = None


def upgrade():
    # IF NOT EXISTS: db.create_all crea gia' le colonne sui database nuovi
    op.execute("ALTER TABLE simulations ADD COLUMN IF NOT EXISTS quota_refunded BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE simulations ADD COLUMN IF NOT EXISTS quota_refund_reason VARCHAR(32)")


def downgrade():
    op.execute("ALTER TABLE simulations DROP COLUMN IF EXISTS quota_refund_reason")
    op.execute("ALTER TABLE simulations DROP COLUMN IF EXISTS quota_refunded")
