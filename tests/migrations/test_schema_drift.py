"""Guard against model-vs-schema drift.

The rest of the suite builds its schema with ``db.create_all()``, so it can never
notice that a migration and a model disagree. This test builds a throwaway
database with ``flask db upgrade`` alone and asserts that Alembic's autogenerate
comparison against ``db.metadata`` produces nothing.

It is the automated form of::

    docker compose exec -T minerva_app_service uv run flask db check

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_schema_drift.py -q
"""
import unittest

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from flask_migrate import upgrade as alembic_upgrade

from app.schema_filters import include_object
from config import TestConfig

# A database of its own, built from nothing but the migration chain. Kept clear of
# every database the suite or the developer uses: it is dropped and recreated here.
DRIFT_DB_NAME = "minerva_test_drift"


def _server_url(database):
    """Swap the database name in the test URL, keeping host/user/password."""
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(
        database=database
    )


class DriftConfig(TestConfig):
    """TestConfig pointed at the throwaway migration-built database."""

    SQLALCHEMY_DATABASE_URI = _server_url(DRIFT_DB_NAME).render_as_string(
        hide_password=False
    )


def _admin_execute(statement):
    """Run one CREATE/DROP DATABASE statement outside a transaction."""
    engine = sa.create_engine(
        _server_url("postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with engine.connect() as conn:
            conn.execute(sa.text(statement))
    finally:
        engine.dispose()


class SchemaDriftTest(unittest.TestCase):
    """`flask db upgrade` output must match the models exactly."""

    def test_migrations_match_models(self):
        # Deliberate exception to test-harness rule 2 (no second Flask app): the
        # Alembic env needs an app whose db is bound to the throwaway database,
        # and this test never touches the shared session schema.
        from app import db

        from tests.base import create_app_without_celery_takeover

        _admin_execute(f'DROP DATABASE IF EXISTS "{DRIFT_DB_NAME}"')
        _admin_execute(f'CREATE DATABASE "{DRIFT_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(DriftConfig)
            with app.app_context():
                alembic_upgrade()
                with db.engine.connect() as conn:
                    context = MigrationContext.configure(
                        conn,
                        opts={
                            "include_object": include_object,
                            "compare_type": False,
                        },
                    )
                    diffs = compare_metadata(context, db.metadata)
                db.engine.dispose()
        finally:
            _admin_execute(f'DROP DATABASE IF EXISTS "{DRIFT_DB_NAME}"')

        self.assertEqual(
            diffs,
            [],
            "Models and migrations disagree. Run `flask db check` and fix the "
            f"models (the database is the truth):\n{diffs}",
        )
