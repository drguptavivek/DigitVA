"""Tests for migration b8d4f2a6c1e9 (digitva-kmm2): ICD-11 2026-01 chapter 22
not selectable, KD3B.Z selectable, "Draft: " stripped from restriction notes.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_migrate_icd11_chapter_22_kd3b_z.py -q
"""
import unittest
from unittest import mock

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_migration_icd11_kmm2"
PARENT_REVISION = "c3f9a1d7e2b4"
REVISION = "b8d4f2a6c1e9"
AUDIT = "_mig_b8d4f2a6c1e9_icd11_policy"
FIELDS = "is_coding_selectable, sex_selectable, age_group_selectable, restriction_note"
SCOPE = "release = '2026-01' AND class_kind = 'category'"


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


class Icd11Kmm2MigrationTest(unittest.TestCase):
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

    def _row(self, code):
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                sa.text(f"SELECT {FIELDS} FROM mas_icd11_mms WHERE {SCOPE} AND code = :code"),
                {"code": code},
            ).all()
        self.assertEqual(len(rows), 1, code)
        return tuple(rows[0])

    def _counts(self):
        """(selectable, chapter 22 selectable, chapter 22 total, Draft notes)."""
        with self.db.engine.connect() as conn:
            return tuple(conn.execute(sa.text(
                "SELECT count(*) FILTER (WHERE is_coding_selectable IS TRUE), "
                "count(*) FILTER (WHERE chapter_no = '22' AND is_coding_selectable IS TRUE), "
                "count(*) FILTER (WHERE chapter_no = '22'), "
                "count(*) FILTER (WHERE restriction_note LIKE 'Draft: %') "
                f"FROM mas_icd11_mms WHERE {SCOPE}")).one())

    def _snapshot(self):
        with self.db.engine.connect() as conn:
            return conn.execute(sa.text(
                f"SELECT linearization_uri, {FIELDS}, policy_status FROM mas_icd11_mms "
                "ORDER BY release, linearization_uri"
            )).all()

    def _exec(self, sql, **params):
        with self.db.engine.begin() as conn:
            conn.execute(sa.text(sql), params)

    def test_round_trip(self):
        selectable, ch22_sel, ch22, drafts = self._counts()
        # The subject is present before it is changed.
        self.assertGreater(ch22, 0)
        self.assertEqual(ch22_sel, ch22)
        self.assertGreater(drafts, 0)
        self.assertEqual(self._row("NC72.Z"), (True, "both", "all", None))
        self.assertEqual(self._row("KD3B.Z"), (False, None, None, None))
        self.assertEqual(self._row("KD3B")[0], False)
        kd3b0_note = self._row("KD3B.0")[3]
        self.assertTrue(kd3b0_note.startswith("Draft: "))
        before = self._snapshot()

        alembic_upgrade(revision=REVISION)
        self.assertEqual(self._counts(), (selectable - ch22 + 1, 0, ch22, 0))
        self.assertEqual(self._row("NC72.Z"), (False, "both", "all", None))
        self.assertEqual(
            self._row("KD3B.Z"),
            (True, "both", "neonate_infant", "chapter 19 (KA-KD), neonates and infants"),
        )
        self.assertEqual(self._row("KD3B")[0], False)
        self.assertEqual(self._row("KD3B.0")[3], kd3b0_note[len("Draft: "):])
        self.assertEqual(self._scalar(f"SELECT count(*) FROM {AUDIT}"), ch22 + 1 + drafts)

        alembic_downgrade(revision=PARENT_REVISION)
        self.assertEqual(self._snapshot(), before)
        self.assertIsNone(self._scalar("SELECT to_regclass(:t)", t=AUDIT))

    def test_admin_edits_survive_upgrade_and_downgrade(self):
        self._exec(f"UPDATE mas_icd11_mms SET is_coding_selectable = FALSE WHERE {SCOPE} "
                   "AND code = 'NC72.0'")
        self._exec(f"UPDATE mas_icd11_mms SET restriction_note = 'Owner note' WHERE {SCOPE} "
                   "AND code = 'KD3B.1'")
        self.assertEqual(self._row("NC72.0")[0], False)
        alembic_upgrade(revision=REVISION)
        self.assertEqual(self._row("KD3B.1")[3], "Owner note")
        self.assertIsNone(self._scalar(f"SELECT id FROM {AUDIT} WHERE code IN ('NC72.0', 'KD3B.1')"))

        # An admin edit after the upgrade is not reverted by the downgrade.
        self._exec(f"UPDATE mas_icd11_mms SET is_coding_selectable = TRUE WHERE {SCOPE} "
                   "AND code = 'NC72.Z'")
        alembic_downgrade(revision=PARENT_REVISION)
        self.assertEqual(self._row("NC72.0")[0], False)
        self.assertEqual(self._row("KD3B.1")[3], "Owner note")
        self.assertEqual(self._row("NC72.Z")[0], True)
        self.assertEqual(self._row("NC72.1")[0], True)  # restored
        self.assertEqual(self._row("KD3B.Z"), (False, None, None, None))

    def test_final_save_validation_follows_the_new_policy(self):
        from app.services.icd11_mms_service import (
            validate_icd11_mms_coding_value_for_submission as validate,
        )

        def context(age_group):
            return mock.patch(
                "app.services.icd11_mms_service.coding_context_for_submission",
                return_value={"va_sid": "x", "age_group": age_group, "sex": "female"},
            )

        with context("adult"):
            validate("x", "NC72.Z")  # selectable before the change
        self.db.session.remove()
        alembic_upgrade(revision=REVISION)
        with context("adult"), self.assertRaisesRegex(ValueError, "NC72.Z is not selectable"):
            validate("x", "NC72.Z")
        with context("neonate"):
            validate("x", "KD3B.Z")
        with context("adult"), self.assertRaisesRegex(ValueError, "KD3B.Z is not selectable"):
            validate("x", "KD3B.Z")
        with context("neonate"), self.assertRaisesRegex(ValueError, "KD3B is not selectable"):
            validate("x", "KD3B")
