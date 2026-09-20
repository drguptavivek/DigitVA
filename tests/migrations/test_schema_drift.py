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

from app.schema_filters import _is_external_table_name, include_object
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
                # "heads" (plural), not the default "head": two uncommitted
                # migration heads sharing a committed parent is a normal,
                # correct state in a shared working tree (Migration Chaining
                # Policy rule 4), not a defect for this test to fail on.
                alembic_upgrade(revision="heads")
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

    def test_check_constraint_names_are_not_doubled_or_truncated(self):
        """Guard digitva-liu: no CHECK constraint name carries a doubled
        ``ck_<table>_`` prefix, and none hits Postgres's 63-character
        truncation point.

        ``compare_metadata`` above cannot catch this: alembic's autogenerate
        does not compare CHECK constraint names at all, only their SQL text,
        so a migrated database could carry a doubled or truncated name
        forever without this test noticing. Comparing model-rendered names
        against ``pg_constraint`` would not catch it either -- eleven of the
        fourteen models here used to declare the *already-doubled* name
        (digitva-liu notes), so the doubled name in the database was exactly
        what the model rendered, and such a comparison would pass while
        proving nothing. This asserts the shape directly instead: no
        ``ck_<table>_ck_<table>_`` substring, no 63-character name (how the
        four truncated ones acquired their hash suffix), and, only once the
        shape is known to be right, agreement in both directions between
        what the migrated database has and what ``db.metadata`` renders.
        """
        from app import db

        from tests.base import create_app_without_celery_takeover

        _admin_execute(f'DROP DATABASE IF EXISTS "{DRIFT_DB_NAME}"')
        _admin_execute(f'CREATE DATABASE "{DRIFT_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(DriftConfig)
            with app.app_context():
                alembic_upgrade(revision="heads")
                with db.engine.connect() as conn:
                    # conrelid::regclass gives the table each CHECK belongs to,
                    # so the doubled-prefix check does not have to guess where
                    # the table name ends and the discriminator begins.
                    rows = conn.execute(
                        sa.text(
                            "SELECT conrelid::regclass::text, conname FROM pg_constraint "
                            "WHERE contype = 'c' AND conname LIKE 'ck\\_%' ESCAPE '\\'"
                        )
                    ).all()
                db.engine.dispose()
        finally:
            _admin_execute(f'DROP DATABASE IF EXISTS "{DRIFT_DB_NAME}"')

        # celery_* tables (and their built-in "ck_celery_..._check" constraints)
        # are owned by celery-sqlalchemy-scheduler, not by this app's models --
        # see app/schema_filters.py's EXTERNAL_TABLE_PREFIXES.
        rows = [(table, conname) for table, conname in rows if not _is_external_table_name(table)]
        db_names = {conname for _table, conname in rows}

        doubled = sorted(
            conname
            for table, conname in rows
            if conname.count(f"ck_{table}_") > 1
        )
        self.assertEqual(
            doubled,
            [],
            f"CHECK constraint name(s) carry a doubled ck_<table>_ prefix: {doubled}",
        )

        at_limit = sorted(n for n in db_names if len(n) == 63)
        self.assertEqual(
            at_limit,
            [],
            f"CHECK constraint name(s) hit Postgres's 63-character truncation point: {at_limit}",
        )

        model_names = {
            constraint.name
            for table in db.metadata.tables.values()
            for constraint in table.constraints
            if isinstance(constraint, sa.CheckConstraint) and constraint.name
        }
        # Only the app's own tables carry the ck_ prefix; Postgres's and
        # celery's built-in CHECK constraints (cardinal_number_domain_check,
        # celery_*_check, ...) are not declared anywhere in db.metadata, so
        # they were already excluded by the "ck\\_%" filter above.
        self.assertEqual(
            db_names - model_names,
            set(),
            f"Database has ck_ constraint name(s) no model declares: {db_names - model_names}",
        )
        self.assertEqual(
            model_names - db_names,
            set(),
            f"Model declares ck_ constraint name(s) missing from the database: {model_names - db_names}",
        )
