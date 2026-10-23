"""``c5e7a9b1d3f6`` replaces an INVALID leftover of its index (bead digitva-hbrs).

A cancelled CREATE INDEX CONCURRENTLY leaves an invalid index of that name;
``if_not_exists`` would keep it, and alembic re-runs the revision because it
was never stamped. Runs the revision's ``upgrade`` against a scratch database
holding only a minimal ``va_submissions``, with the index forced invalid.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_form_org_unit_index_invalid_leftover.py -q
"""
import importlib.util
import unittest
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from config import TestConfig

# Its own database, dropped and recreated here.
DB_NAME = "minerva_test_form_org_idx_guard"
INDEX = "ix_va_submissions_form_org_unit"
MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations/versions/c5e7a9b1d3f6_add_va_submissions_form_org_unit_index.py"
)


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


def _admin_execute(*statements):
    engine = sa.create_engine(_server_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for statement in statements:
                conn.execute(sa.text(statement))
    finally:
        engine.dispose()


def _drop_database():
    _admin_execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{DB_NAME}"',
    )


def _run_upgrade(engine):
    spec = importlib.util.spec_from_file_location("c5e7a9b1d3f6", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.connect() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()


class FormOrgUnitIndexInvalidLeftoverTest(unittest.TestCase):
    def test_upgrade_replaces_an_invalid_leftover_and_keeps_a_valid_index(self):
        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        engine = sa.create_engine(_server_url(DB_NAME), isolation_level="AUTOCOMMIT")
        try:
            def index_row():
                with engine.connect() as conn:
                    return conn.execute(sa.text(
                        "SELECT indisvalid, indexrelid FROM pg_index"
                        " WHERE indexrelid = to_regclass(:n)"
                    ), {"n": INDEX}).first()

            with engine.connect() as conn:
                conn.execute(sa.text(
                    "CREATE TABLE va_submissions (va_form_id text, org_unit_id text)"
                ))
                conn.execute(sa.text(
                    f"CREATE INDEX {INDEX} ON va_submissions (va_form_id, org_unit_id)"
                ))
                conn.execute(sa.text(
                    "UPDATE pg_index SET indisvalid = false"
                    " WHERE indexrelid = to_regclass(:n)"
                ), {"n": INDEX})
            leftover = index_row()
            self.assertFalse(leftover.indisvalid, "the fixture must start invalid")

            _run_upgrade(engine)
            rebuilt = index_row()
            self.assertTrue(rebuilt.indisvalid)
            self.assertNotEqual(rebuilt.indexrelid, leftover.indexrelid, "leftover was kept")

            # A valid index is left alone: a re-run does not rebuild it.
            _run_upgrade(engine)
            self.assertEqual(index_row().indexrelid, rebuilt.indexrelid)
        finally:
            engine.dispose()
            _drop_database()
