"""Migration b5d2f8e41c73 (site_settings) up and down on PostgreSQL.

Skipped unless SWARMIND_TEST_PG_URL points to an empty PostgreSQL database the test may write to:
  SWARMIND_TEST_PG_URL=postgresql://user:pw@localhost:5432/swarmind_test python -m pytest tests/test_site_migration.py
"""
import os

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import pytest
from sqlalchemy import exc, inspect, text

PG_URL = os.environ.get("SWARMIND_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="SWARMIND_TEST_PG_URL not set")

PREVIOUS = "e8a4c2f6b9d1"
# The current head of the migrations (create_app stamps it on a new database); b5d2f8e41c73 is site_settings
HEAD = "f1b7d3c9a2e5"


def schema(conn):
    columns = conn.execute(text(
        "SELECT column_name, data_type, is_nullable, column_default, character_maximum_length "
        "FROM information_schema.columns WHERE table_name = 'site_settings' ORDER BY column_name")).all()
    constraints = conn.execute(text(
        "SELECT conname, contype, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid = 'site_settings'::regclass ORDER BY conname")).all()
    return [tuple(c) for c in columns], [tuple(c) for c in constraints]


def version(conn):
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


@pytest.fixture()
def app():
    from app import MIGRATIONS_DIR, create_app
    from app.config import Config
    from app.models import db

    class PgConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = PG_URL

    application = create_app(PgConfig)   # fresh database: create_all + stamp head
    application.config["MIGRATIONS_DIR"] = str(MIGRATIONS_DIR)
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()
        with db.engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


def test_upgrade_downgrade_upgrade(app):
    from flask_migrate import downgrade, stamp, upgrade
    from app.models import db

    directory = app.config["MIGRATIONS_DIR"]
    with app.app_context():
        with db.engine.connect() as conn:
            assert version(conn) == HEAD
            expected = schema(conn)          # what db.create_all builds from the model

        # Production before this deploy: schema at the previous head, no site_settings
        with db.engine.begin() as conn:
            conn.execute(text("DROP TABLE site_settings"))
        stamp(directory=directory, revision=PREVIOUS)

        upgrade(directory=directory)
        with db.engine.connect() as conn:
            assert version(conn) == HEAD
            assert schema(conn) == expected, "migration and model define different tables"

        # The model works on the migrated table; the singleton constraint holds
        with db.engine.begin() as conn:
            conn.execute(text("INSERT INTO site_settings (id, landing_enabled, revision) VALUES (1, true, 0)"))
        with pytest.raises(exc.IntegrityError):
            with db.engine.begin() as conn:
                conn.execute(text("INSERT INTO site_settings (id, landing_enabled, revision) VALUES (2, true, 0)"))

        downgrade(directory=directory, revision=PREVIOUS)
        with db.engine.connect() as conn:
            assert version(conn) == PREVIOUS
            assert not inspect(conn).has_table("site_settings")
            assert inspect(conn).has_table("users")     # nothing else touched

        upgrade(directory=directory)
        with db.engine.connect() as conn:
            assert version(conn) == HEAD and schema(conn) == expected


def test_upgrade_when_startup_created_the_table_first(app):
    """Backend restarted before `flask db upgrade`: create_all made the table, the migration is a no-op."""
    from flask_migrate import stamp, upgrade
    from app.models import db

    directory = app.config["MIGRATIONS_DIR"]
    with app.app_context():
        with db.engine.connect() as conn:
            expected = schema(conn)
        stamp(directory=directory, revision=PREVIOUS)
        upgrade(directory=directory)
        with db.engine.connect() as conn:
            assert version(conn) == HEAD and schema(conn) == expected


def test_settings_roundtrip_on_postgres(app):
    """JSON columns keep the validated document as saved."""
    from app.api.site import load_document
    from app.core import site_settings as ss
    from app.models import SiteSettings, db

    with app.app_context():
        doc = ss.default_document()
        doc["content"]["it"]["hero"]["title"] = "Perché è così: «virgolette» ✓"
        db.session.add(SiteSettings(id=1, landing_enabled=True, branding=doc["branding"],
                                    content=doc["content"], revision=3))
        db.session.commit()
        db.session.expire_all()
        loaded, revision = load_document()
        assert revision == 3 and loaded["landing_enabled"] is True
        assert loaded["content"]["it"]["hero"]["title"] == "Perché è così: «virgolette» ✓"
