"""Migration c5a8d2e7f1b4: create and seed mas_icd_search_terms.

Throwaway database built from the migration chain only, like
test_migrate_va_cause_definitions.py. Row counts are read from the seed CSV
at test time (the CSV grows with the vocabulary), never hard-coded.
"""
import csv
import importlib.util
import unittest
from pathlib import Path

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_migration_c5a8d2e7f1b4"
PARENT_REVISION = "a3c9e1f7b2d4"
REVISION_UNDER_TEST = "c5a8d2e7f1b4"
MIGRATION_FILE = f"{REVISION_UNDER_TEST}_add_mas_icd_search_terms.py"
TABLE = "mas_icd_search_terms"


def _repo_root():
    return Path(__file__).resolve().parents[2]


def _seed_row_count():
    with (_repo_root() / "resource" / "icd_search_vocabulary_seed.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        return len([row for row in csv.DictReader(handle) if row.get("term_normalized")])


def _load_migration_module():
    path = _repo_root() / "migrations" / "versions" / MIGRATION_FILE
    spec = importlib.util.spec_from_file_location("_under_test_migration", path)
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


class IcdSearchVocabularyMigrationTest(unittest.TestCase):
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

    def test_upgrade_seeds_once_and_downgrade_drops(self):
        self.assertIsNone(self._scalar(f"SELECT to_regclass('{TABLE}')"))

        alembic_upgrade(revision=REVISION_UNDER_TEST)
        expected_rows = _seed_row_count()
        self.assertGreater(expected_rows, 0)
        self.assertEqual(self._scalar(f"SELECT count(*) FROM {TABLE}"), expected_rows)
        # Stable spot checks from the reviewed seed (clinician shorthand).
        self.assertEqual(
            self._scalar(
                f"SELECT icd_code FROM {TABLE} WHERE term_normalized = 'cva' "
                "AND icd_classification = 'icd10'"
            ),
            "I64",
        )
        self.assertGreater(
            self._scalar(
                f"SELECT count(*) FROM {TABLE} WHERE term_normalized = 'cva' "
                "AND icd_classification = 'icd11'"
            ),
            0,
        )
        self.assertEqual(
            self._scalar(f"SELECT count(*) FROM {TABLE} WHERE is_active IS NOT TRUE"), 0
        )
        self.assertEqual(
            self._scalar(
                f"SELECT count(*) FROM {TABLE} WHERE icd_classification NOT IN ('icd10', 'icd11')"
            ),
            0,
        )

        # A second upgrade is a no-op: the revision is stamped.
        alembic_upgrade(revision=REVISION_UNDER_TEST)
        self.assertEqual(self._scalar(f"SELECT count(*) FROM {TABLE}"), expected_rows)

        # The guard itself: an admin-curated table is never re-seeded. A
        # partly-emptied table stays as the admin left it.
        self.db.engine.dispose()
        admin_execute = sa.create_engine(
            _server_url(MIGRATION_DB_NAME), isolation_level="AUTOCOMMIT"
        )
        try:
            with admin_execute.connect() as conn:
                kept = conn.execute(
                    sa.text(f"SELECT count(*) FROM {TABLE}")
                ).scalar()
                conn.execute(
                    sa.text(
                        f"DELETE FROM {TABLE} WHERE term_id IN "
                        f"(SELECT term_id FROM {TABLE} ORDER BY term_normalized LIMIT {kept - 1})"
                    )
                )
                remaining = conn.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar()
                inserted = _load_migration_module()._seed_if_empty(conn)
        finally:
            admin_execute.dispose()
        self.assertEqual(inserted, 0)
        self.assertEqual(remaining, 1)

        alembic_downgrade(revision=PARENT_REVISION)
        self.assertIsNone(self._scalar(f"SELECT to_regclass('{TABLE}')"))


if __name__ == "__main__":
    unittest.main()
