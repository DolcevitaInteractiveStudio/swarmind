"""add coded error detail to Simulation and Project

Revision ID: e8a4c2f6b9d1
Revises: d7f3b9a1c2e4
Create Date: 2026-11-10 12:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'e8a4c2f6b9d1'
down_revision = 'd7f3b9a1c2e4'
branch_labels = None
depends_on = None


def upgrade():
    # Failure/stop messages as a code + params (simulation/lifecycle.py), rendered when read in the
    # language of the request. Nullable: rows written before keep only their stored text, which the
    # API keeps showing. IF NOT EXISTS: db.create_all already creates them on a new database.
    op.execute("ALTER TABLE simulations ADD COLUMN IF NOT EXISTS error_detail JSON")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS graph_error_detail JSON")


def downgrade():
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS graph_error_detail")
    op.execute("ALTER TABLE simulations DROP COLUMN IF EXISTS error_detail")
