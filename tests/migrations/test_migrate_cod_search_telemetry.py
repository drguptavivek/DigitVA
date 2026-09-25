"""Migration b8f2d6a9c4e1: create cod_search_telemetry (create + downgrade).

digitva-zpe.3. Schema-only migration — no seed — so the assertions are about
structure: the table, its surface CHECK, and the two access indexes exist
after upgrade and are gone after downgrade.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_migrate_cod_search_telemetry.py -q
"""

import importlib.util
import unittest
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade
from sqlalchemy.exc import IntegrityError

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_migration_b8f2d6a9c4e1"
PARENT_REVISION = "e9d4b6f8a3c2"
REVISION_UNDER_TEST = "b8f2d6a9c4e1"
MIGRATION_FILE = f"{REVISION_UNDER_TEST}_add_cod_search_telemetry.py"
TABLE = "cod_search_telemetry"


def _repo_root():
    return Path(__file__).resolve().parents[2]


def _load_migration_module():
    path = _repo_root() / "migrations" / "versions" / MIGRATION_FILE
    spec = importlib.util.spec_from_file_location("_telemetry_under_test_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class MigrationConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(MIGRATION_DB_NAME).render_as_string(hide_password=False)


def _admin_execute(statement):
    engine = sa.create_engine(_server_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(sa.text(statement))
    finally:
        engine.dispose()


class CodSearchTelemetryMigrationTest(unittest.TestCase):
    def setUp(self):
        _admin_execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"')
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        self.addCleanup(lambda: _admin_execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"'))

        from tests.base import create_app_without_celery_takeover

        self.app = create_app_without_celery_takeover(MigrationConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        alembic_upgrade(revision=PARENT_REVISION)

        from app import db

        self.db = db
        self.addCleanup(db.engine.dispose)

    def _scalar(self, sql):
        with self.db.engine.connect() as conn:
            return conn.execute(sa.text(sql)).scalar()

    def _insert_row(self, surface="icd10_coding"):
        with self.db.engine.begin() as conn:
            conn.execute(
                sa.text(
                    f"INSERT INTO {TABLE} (search_id, surface, query_text) "
                    "VALUES (:search_id, :surface, :query_text)"
                ),
                {"search_id": str(uuid4()), "surface": surface, "query_text": "mi"},
            )

    def test_upgrade_creates_schema_and_downgrade_drops_it(self):
        self.assertIsNone(self._scalar(f"SELECT to_regclass('{TABLE}')"))

        alembic_upgrade(revision=REVISION_UNDER_TEST)
        self.assertIsNotNone(self._scalar(f"SELECT to_regclass('{TABLE}')"))

        # A valid row inserts with all defaults; the server fills id/timestamps.
        self._insert_row()
        self.assertEqual(self._scalar(f"SELECT count(*) FROM {TABLE}"), 1)
        self.assertEqual(self._scalar(f"SELECT result_count FROM {TABLE}"), 0)
        self.assertEqual(self._scalar(f"SELECT zero_results FROM {TABLE}"), False)
        self.assertIsNotNone(self._scalar(f"SELECT created_at FROM {TABLE}"))
        self.assertIsNotNone(self._scalar(f"SELECT id FROM {TABLE}"))

        # The surface CHECK rejects anything outside the two coding surfaces.
        with self.db.engine.begin() as conn:
            self.assertRaises(
                IntegrityError,
                conn.execute,
                sa.text(
                    f"INSERT INTO {TABLE} (search_id, surface, query_text) "
                    "VALUES (:search_id, 'icd9_coding', 'mi')"
                ),
                {"search_id": str(uuid4())},
            )

        # Both access indexes exist: retention prune (created_at) and the
        # choice linkage (search_id).
        self.assertEqual(
            self._scalar(
                "SELECT count(*) FROM pg_indexes "
                f"WHERE tablename = '{TABLE}' "
                "AND indexname IN ('ix_cod_search_telemetry_created_at', "
                "'ix_cod_search_telemetry_search_id')"
            ),
            2,
        )

        # Re-running the revision is a stamp no-op.
        alembic_upgrade(revision=REVISION_UNDER_TEST)
        self.assertEqual(self._scalar(f"SELECT count(*) FROM {TABLE}"), 1)

        alembic_downgrade(revision=PARENT_REVISION)
        self.assertIsNone(self._scalar(f"SELECT to_regclass('{TABLE}')"))

    def test_migration_chains_onto_the_committed_head_and_has_no_app_imports(self):
        module = _load_migration_module()
        self.assertEqual(module.down_revision, PARENT_REVISION)
        self.assertEqual(module.revision, REVISION_UNDER_TEST)
        source = (_repo_root() / "migrations" / "versions" / MIGRATION_FILE).read_text()
        self.assertNotIn("from app", source)
        self.assertNotIn("import app", source)


if __name__ == "__main__":
    unittest.main()
