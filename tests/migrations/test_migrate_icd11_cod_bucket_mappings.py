"""Tests for migrations 62a637f5c38a (ICD classification on COD bucket
mappings) and 6c11b620f48f (seed WHO_2022_VA_2026's native ICD-11 rows).

Follows the throwaway-database shape from test_migrate_who_2026_annex.py: a
database of its own, built from nothing but the migration chain up to the
parent revision, never `minerva_test` or the dev `minerva`.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_migrate_icd11_cod_bucket_mappings.py -q
"""
import csv
import unittest
import uuid
from pathlib import Path

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import stamp as alembic_stamp
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_migration_62a637f5c38a"
PARENT_REVISION = "a4c7e2f9b1d6"
REVISION_UNDER_TEST = "62a637f5c38a"
SEED_REVISION = "6c11b620f48f"
SEED_CSV = (
    Path(__file__).resolve().parents[2]
    / "resource"
    / "who_2022_va_2026_icd11_native_mappings.csv"
)


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class MigrationConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(MIGRATION_DB_NAME).render_as_string(
        hide_password=False
    )


def _admin_execute(statement):
    engine = sa.create_engine(_server_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(sa.text(statement))
    finally:
        engine.dispose()


class Icd11CodBucketMappingsMigrationTest(unittest.TestCase):
    """Existing rows become ICD-10 untouched; an ICD-11 row may reuse a
    code string; downgrade refuses while ICD-11 rows exist and otherwise
    restores the old unique key."""

    def setUp(self):
        _admin_execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"')
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        self.addCleanup(
            lambda: _admin_execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"')
        )

        from tests.base import create_app_without_celery_takeover

        self.app = create_app_without_celery_takeover(MigrationConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)

        alembic_upgrade(revision=PARENT_REVISION)

        from app import db

        self.db = db
        self.addCleanup(db.engine.dispose)
        self.scheme_id, self.node_id, self.mapping_id = self._seed_icd10_mapping()

    def _seed_icd10_mapping(self):
        scheme_id, node_id, mapping_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        with self.db.engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO mas_cod_bucket_schemes (scheme_id, scheme_code, scheme_name, "
                    "mapping_version, is_active, created_at, updated_at) "
                    "VALUES (:id, 'MIG_712', 'Migration 712', 1, true, now(), now())"
                ),
                {"id": scheme_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO mas_cod_bucket_nodes (node_id, scheme_id, node_type, node_code, "
                    "node_label, sort_order, is_active, created_at, updated_at) "
                    "VALUES (:id, :scheme, 'field', 'f', 'Field', 1, true, now(), now())"
                ),
                {"id": node_id, "scheme": scheme_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO map_icd_cod_buckets (mapping_id, scheme_id, icd_code, node_id, "
                    "is_active, created_at, updated_at) "
                    "VALUES (:id, :scheme, 'A00', :node, true, now(), now())"
                ),
                {"id": mapping_id, "scheme": scheme_id, "node": node_id},
            )
        return scheme_id, node_id, mapping_id

    def _insert_mapping(self, conn, icd_code, classification):
        conn.execute(
            sa.text(
                "INSERT INTO map_icd_cod_buckets (mapping_id, scheme_id, icd_code, "
                "icd_classification, node_id, is_active, created_at, updated_at) "
                "VALUES (:id, :scheme, :code, :cls, :node, true, now(), now())"
            ),
            {"id": uuid.uuid4(), "scheme": self.scheme_id, "code": icd_code,
             "cls": classification, "node": self.node_id},
        )

    def _columns(self, table):
        return {column["name"] for column in sa.inspect(self.db.engine).get_columns(table)}

    def test_upgrade_marks_existing_rows_icd10_and_downgrade_is_guarded(self):
        self.assertNotIn("icd_classification", self._columns("map_icd_cod_buckets"))

        alembic_upgrade(revision=REVISION_UNDER_TEST)

        with self.db.engine.connect() as conn:
            classification = conn.execute(
                sa.text("SELECT icd_classification FROM map_icd_cod_buckets WHERE mapping_id = :id"),
                {"id": self.mapping_id},
            ).scalar_one()
            method = conn.execute(
                sa.text("SELECT icd11_method FROM mas_cod_bucket_schemes WHERE scheme_id = :id"),
                {"id": self.scheme_id},
            ).scalar_one()
        self.assertEqual(classification, "icd10")
        self.assertIsNone(method)

        with self.db.engine.begin() as conn:
            # Same code string, other classification: allowed by the new key.
            self._insert_mapping(conn, "a00", "icd11")
        with self.assertRaises(sa.exc.IntegrityError):
            with self.db.engine.begin() as conn:
                self._insert_mapping(conn, "a00", "icd10")
        with self.assertRaises(sa.exc.IntegrityError):
            with self.db.engine.begin() as conn:
                self._insert_mapping(conn, "B00", "icd9")
        with self.assertRaises(sa.exc.IntegrityError):
            with self.db.engine.begin() as conn:
                conn.execute(
                    sa.text("UPDATE mas_cod_bucket_schemes SET icd11_method = 'other'")
                )

        # flask_migrate logs the migration's RuntimeError and exits 1.
        with self.assertRaises(SystemExit):
            alembic_downgrade(revision=PARENT_REVISION)
        self.assertIn("icd_classification", self._columns("map_icd_cod_buckets"))

        with self.db.engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM map_icd_cod_buckets WHERE icd_classification = 'icd11'"))
        alembic_downgrade(revision=PARENT_REVISION)

        self.assertNotIn("icd_classification", self._columns("map_icd_cod_buckets"))
        self.assertNotIn("icd11_method", self._columns("mas_cod_bucket_schemes"))
        with self.assertRaises(sa.exc.IntegrityError):
            with self.db.engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO map_icd_cod_buckets (mapping_id, scheme_id, icd_code, node_id, "
                        "is_active, created_at, updated_at) "
                        "VALUES (:id, :scheme, 'a00', :node, true, now(), now())"
                    ),
                    {"id": uuid.uuid4(), "scheme": self.scheme_id, "node": self.node_id},
                )
        with self.db.engine.connect() as conn:
            kept = conn.execute(
                sa.text("SELECT icd_code FROM map_icd_cod_buckets WHERE mapping_id = :id"),
                {"id": self.mapping_id},
            ).scalar_one()
        self.assertEqual(kept, "A00")


class SeedWho2026Icd11MappingsMigrationTest(unittest.TestCase):
    """A fresh install gets every frozen row; a database that already has
    ICD-11 rows is left alone; downgrade removes exactly those rows."""

    def setUp(self):
        _admin_execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"')
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        self.addCleanup(
            lambda: _admin_execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"')
        )

        from tests.base import create_app_without_celery_takeover

        self.app = create_app_without_celery_takeover(MigrationConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)

        alembic_upgrade(revision=REVISION_UNDER_TEST)

        from app import db

        self.db = db
        self.addCleanup(db.engine.dispose)

    def _scheme_state(self):
        with self.db.engine.connect() as conn:
            return conn.execute(
                sa.text(
                    "SELECT s.icd11_method, s.mapping_version, "
                    "(SELECT count(*) FROM map_icd_cod_buckets m WHERE m.scheme_id = s.scheme_id "
                    " AND m.icd_classification = 'icd11') AS icd11_rows, "
                    "(SELECT count(*) FROM map_icd_cod_buckets m WHERE m.scheme_id = s.scheme_id "
                    " AND m.icd_classification = 'icd10') AS icd10_rows "
                    "FROM mas_cod_bucket_schemes s WHERE s.scheme_code = 'WHO_2022_VA_2026'"
                )
            ).mappings().one()

    def _fresh_stillbirth(self):
        """`vas_11_01` rows: label, parent node code, sort order, mapped code."""
        with self.db.engine.connect() as conn:
            return [
                tuple(row)
                for row in conn.execute(
                    sa.text(
                        "SELECT n.node_label, p.node_code, n.sort_order, m.icd_code "
                        "FROM mas_cod_bucket_nodes n "
                        "JOIN mas_cod_bucket_schemes s ON s.scheme_id = n.scheme_id "
                        "JOIN mas_cod_bucket_nodes p ON p.node_id = n.parent_node_id "
                        "LEFT JOIN map_icd_cod_buckets m ON m.node_id = n.node_id "
                        "WHERE s.scheme_code = 'WHO_2022_VA_2026' AND n.node_code = 'vas_11_01'"
                    )
                )
            ]

    def test_seed_matches_csv_is_idempotent_and_downgrades_cleanly(self):
        with SEED_CSV.open(newline="", encoding="utf-8") as handle:
            expected = sum(1 for row in csv.DictReader(handle) if row["scheme_code"] == "WHO_2022_VA_2026")
        self.assertGreater(expected, 0)
        before = self._scheme_state()
        self.assertEqual(before["icd11_rows"], 0)
        self.assertIsNone(before["icd11_method"])

        alembic_upgrade(revision=SEED_REVISION)

        seeded = self._scheme_state()
        self.assertEqual(seeded["icd11_rows"], expected)
        self.assertEqual(seeded["icd11_method"], "native")
        self.assertEqual(seeded["icd10_rows"], before["icd10_rows"])
        with self.db.engine.connect() as conn:
            dengue = conn.execute(
                sa.text(
                    "SELECT n.node_code, m.match_type FROM map_icd_cod_buckets m "
                    "JOIN mas_cod_bucket_nodes n ON n.node_id = m.node_id "
                    "WHERE m.icd_classification = 'icd11' AND m.icd_code = '1D20'"
                )
            ).one()
        self.assertEqual(tuple(dengue), ("vas_01_12", "range"))
        self.assertEqual(self._fresh_stillbirth(), [("Fresh stillbirth", "stillbirths", 48, "KD3B.1")])

        # Re-run the seed with the rows already present: nothing changes.
        alembic_stamp(revision=REVISION_UNDER_TEST)
        alembic_upgrade(revision=SEED_REVISION)
        self.assertEqual(self._scheme_state(), seeded)

        alembic_downgrade(revision=REVISION_UNDER_TEST)

        after = self._scheme_state()
        self.assertEqual(self._fresh_stillbirth(), [], "vas_11_01 goes once nothing maps to it")
        self.assertEqual(after["icd11_rows"], 0)
        self.assertIsNone(after["icd11_method"])
        self.assertEqual(after["icd10_rows"], before["icd10_rows"])
