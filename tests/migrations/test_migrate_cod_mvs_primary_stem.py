"""Tests for migration c5e8a2f4b7d1 (digitva-443q): the COD snapshot and
detail MVs bucket ICD-11 finals by their recorded primary stem.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_migrate_cod_mvs_primary_stem.py -q
"""
import importlib.util
import unittest
from pathlib import Path

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_migration_cod_primary_stem"
PARENT_REVISION = "b8d4f2a6c1e9"
REVISION = "c5e8a2f4b7d1"
SNAPSHOT = "va_submission_cod_snapshot_mv"
DETAIL = "va_submission_cod_detail_mv"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations/versions/c5e8a2f4b7d1_cod_mvs_bucket_icd11_by_primary_stem.py"
)


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


def _migration_module():
    spec = importlib.util.spec_from_file_location("mig_c5e8a2f4b7d1", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CodMvsPrimaryStemMigrationTest(unittest.TestCase):
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
        # Runs first: return the session's connection so dispose can close it.
        self.addCleanup(db.session.remove)

    def _scalar(self, sql, **params):
        with self.db.engine.connect() as conn:
            return conn.execute(sa.text(sql), params).scalar()

    def _definition(self, view):
        return self._scalar("SELECT definition FROM pg_matviews WHERE matviewname = :v", v=view)

    def _indexes(self, view):
        with self.db.engine.connect() as conn:
            return sorted(conn.execute(
                sa.text("SELECT indexname FROM pg_indexes WHERE tablename = :v"), {"v": view}
            ).scalars())

    def _columns(self, view):
        with self.db.engine.connect() as conn:
            return list(conn.execute(sa.text(
                "SELECT attname FROM pg_attribute WHERE attrelid = to_regclass(:v) "
                "AND attnum > 0 AND NOT attisdropped ORDER BY attnum"
            ), {"v": view}).scalars())

    def test_round_trip(self):
        before = {view: (self._definition(view), self._indexes(view)) for view in (SNAPSHOT, DETAIL)}
        # The subject is present before it is changed.
        for view in (SNAPSHOT, DETAIL):
            self.assertIsNotNone(before[view][0], view)
            self.assertNotIn("primary_stem", before[view][0])
        self.assertNotIn("authoritative_icd11_stem", self._columns(SNAPSHOT))

        alembic_upgrade(revision=REVISION)
        for view in (SNAPSHOT, DETAIL):
            self.assertIn("primary_stem", self._definition(view), view)
            self.assertEqual(self._indexes(view), before[view][1], view)
        self.assertEqual(
            self._columns(SNAPSHOT)[-3:],
            ["coder_final_icd11_stem", "reviewer_final_icd11_stem", "authoritative_icd11_stem"],
        )
        self.assertIn("final_icd11", self._columns(DETAIL))
        # The unique index lets the refresh flows run concurrently.
        with self.db.engine.begin() as conn:
            conn.execute(sa.text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {SNAPSHOT}"))
            conn.execute(sa.text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {DETAIL}"))

        alembic_downgrade(revision=PARENT_REVISION)
        after = {view: (self._definition(view), self._indexes(view)) for view in (SNAPSHOT, DETAIL)}
        self.assertEqual(after, before)

    def test_frozen_sql_matches_the_builders(self):
        """The upgrade SQL is what ``ensure_submission_cod_snapshot_mv`` and
        the detail builder produce today, so a fresh and a migrated database
        agree."""
        from app.services.submission_analytics_mv import (
            build_submission_cod_detail_mv_sql,
            build_submission_cod_snapshot_mv_sql,
        )

        module = _migration_module()
        self.assertEqual(
            module.SNAPSHOT_MV_SQL_PRIMARY_STEM, build_submission_cod_snapshot_mv_sql(icd11_buckets=True)
        )
        self.assertEqual(
            module.COD_DETAIL_MV_SQL_PRIMARY_STEM, build_submission_cod_detail_mv_sql(include_icd11=True)
        )


if __name__ == "__main__":
    unittest.main()
