"""add language to Simulation

Revision ID: d7f3b9a1c2e4
Revises: c4e8a2d61f97
Create Date: 2026-11-09 12:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'd7f3b9a1c2e4'
down_revision = 'c4e8a2d61f97'
branch_labels = None
depends_on = None


def upgrade():
    # Existing simulations were generated in Italian. IF NOT EXISTS: db.create_all already creates
    # the column (default 'en') on a new database.
    op.execute("ALTER TABLE simulations ADD COLUMN IF NOT EXISTS language VARCHAR(8) NOT NULL DEFAULT 'it'")
    # New rows: the API always sends a value; the server default only covers other writers
    op.execute("ALTER TABLE simulations ALTER COLUMN language SET DEFAULT 'en'")


def downgrade():
    op.execute("ALTER TABLE simulations DROP COLUMN IF EXISTS language")
