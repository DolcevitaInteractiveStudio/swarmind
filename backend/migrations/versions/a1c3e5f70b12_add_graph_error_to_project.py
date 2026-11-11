"""add graph_error to Project

Revision ID: a1c3e5f70b12
Revises: 40d02a160e4f
Create Date: 2026-11-03 16:30:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'a1c3e5f70b12'
down_revision = '40d02a160e4f'
branch_labels = None
depends_on = None


def upgrade():
    # IF NOT EXISTS: db.create_all crea gia' la colonna sui database nuovi
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS graph_error TEXT")


def downgrade():
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS graph_error")
