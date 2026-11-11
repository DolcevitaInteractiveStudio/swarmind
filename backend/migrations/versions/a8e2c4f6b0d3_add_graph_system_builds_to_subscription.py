"""add graph_system_builds to Subscription

Graph builds that run on the shared system key (GROQ_API_KEY) are counted per user and per quota period,
up to GRAPH_SYSTEM_KEY_MONTHLY_LIMIT. graph_system_builds_period is the start of the period the counter
belongs to: a counter of an older period starts again from zero at the next build.

Revision ID: a8e2c4f6b0d3
Revises: f1b7d3c9a2e5
Create Date: 2026-11-11 15:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'a8e2c4f6b0d3'
down_revision = 'f1b7d3c9a2e5'
branch_labels = None
depends_on = None


def upgrade():
    # Constant default: no table rewrite on PostgreSQL, existing subscriptions start at 0.
    # IF NOT EXISTS: db.create_all already creates the columns on new databases
    op.execute("ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS graph_system_builds_used INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS graph_system_builds_period TIMESTAMP WITHOUT TIME ZONE")


def downgrade():
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS graph_system_builds_period")
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS graph_system_builds_used")
