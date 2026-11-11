"""add site_settings (landing page, branding)

Revision ID: b5d2f8e41c73
Revises: e8a4c2f6b9d1
Create Date: 2026-11-10 18:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'b5d2f8e41c73'
down_revision = 'e8a4c2f6b9d1'
branch_labels = None
depends_on = None


def upgrade():
    # One row (id = 1), written on the first save from the admin area: until then the API serves
    # the defaults in code (core/site_settings.py), with the landing off.
    # IF NOT EXISTS: db.create_all at startup creates the same table on a new database, or if the
    # backend restarts before this migration runs. Same definition as models/site.py.
    op.execute("""
        CREATE TABLE IF NOT EXISTS site_settings (
            id INTEGER NOT NULL,
            landing_enabled BOOLEAN NOT NULL,
            branding JSON,
            content JSON,
            revision INTEGER NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE,
            updated_by VARCHAR(36),
            CONSTRAINT site_settings_pkey PRIMARY KEY (id),
            CONSTRAINT site_settings_singleton CHECK (id = 1),
            CONSTRAINT site_settings_updated_by_fkey FOREIGN KEY (updated_by)
                REFERENCES users (id) ON DELETE SET NULL
        )
    """)


def downgrade():
    # Uploaded images stay on the uploads volume (data/uploads/site): delete them by hand if needed
    op.execute("DROP TABLE IF EXISTS site_settings")
