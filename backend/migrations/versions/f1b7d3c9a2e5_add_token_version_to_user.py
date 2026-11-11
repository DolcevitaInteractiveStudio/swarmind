"""add token_version to User

Login tokens carry the user's token_version ("tv" claim); a password change or reset increments it, so the
tokens issued before stop working. Existing users start at 0, the version of the tokens issued before this
migration (no "tv" claim): nobody is signed out by the upgrade.

Revision ID: f1b7d3c9a2e5
Revises: b5d2f8e41c73
Create Date: 2026-11-11 12:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'f1b7d3c9a2e5'
down_revision = 'b5d2f8e41c73'
branch_labels = None
depends_on = None


def upgrade():
    # Constant default: PostgreSQL adds the column without rewriting the table and fills existing rows with 0.
    # IF NOT EXISTS: db.create_all already creates the column on new databases (and on a backend restarted
    # before the upgrade)
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0")


def downgrade():
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS token_version")
