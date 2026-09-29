"""Tests for migration a7c3e9f1b5d2 (signed-off ICD-11 coding-selectability
policy, release 2026-01).

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_migrate_icd11_policy_signoff.py -q
"""
import importlib.util
import json
import unittest
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_migration_icd11_policy_signoff"
PARENT_REVISION = "d3a9c5e1f7b2"
REVISION = "a7c3e9f1b5d2"
REPO = Path(__file__).resolve().parents[2]
MIGRATION_FILE = REPO / "migrations" / "versions" / "a7c3e9f1b5d2_icd11_policy_signoff_2026_09_29.py"
FROZEN = REPO / "resource" / "icd11_mms_2026_01_policy_signoff_2026_09_29.json"
ARTIFACT = (
    REPO / "docs" / "icd-causegrp-mappings" / "migration-artifacts"
    / "who-2022-icd11-policy-draft-2026-09-24" / "who_2022_icd11_mms_2026_01_policy_draft.json"
)
FIELDS = "is_coding_selectable, sex_selectable, age_group_selectable, restriction_note, policy_status"


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


class Icd11PolicySignoffMigrationTest(unittest.TestCase):
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

    def _row(self, code):
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                sa.text(f"SELECT {FIELDS} FROM mas_icd11_mms WHERE release = '2026-01' "
                        "AND code = :code AND is_active AND class_kind = 'category'"),
                {"code": code},
            ).all()
        self.assertEqual(len(rows), 1, code)
        return tuple(rows[0])

    def _counts(self):
        with self.db.engine.connect() as conn:
            return tuple(conn.execute(sa.text(
                "SELECT count(*) FILTER (WHERE is_coding_selectable IS TRUE), "
                "count(*) FILTER (WHERE is_coding_selectable IS FALSE), "
                "count(*) FILTER (WHERE is_coding_selectable IS NULL), "
                "count(*) FILTER (WHERE policy_status = 'reviewed') "
                "FROM mas_icd11_mms WHERE release = '2026-01' AND is_active "
                "AND class_kind = 'category'")).one())

    def _snapshot(self):
        with self.db.engine.connect() as conn:
            return conn.execute(sa.text(
                f"SELECT linearization_uri, {FIELDS} FROM mas_icd11_mms ORDER BY linearization_uri"
            )).all()

    def _set(self, code, selectable, status="unreviewed"):
        with self.db.engine.begin() as conn:
            conn.execute(sa.text(
                "UPDATE mas_icd11_mms SET is_coding_selectable = :s, policy_status = :st "
                "WHERE release = '2026-01' AND code = :c"), {"s": selectable, "st": status, "c": code})

    def test_round_trip_real_codes_and_counts(self):
        selectable, not_sel, null, reviewed = self._counts()
        self.assertEqual((selectable, not_sel, reviewed), (0, 0, 0))
        self.assertGreater(null, 16387)
        before = self._snapshot()

        alembic_upgrade(revision=REVISION)
        selectable, not_sel, null, reviewed = self._counts()
        self.assertEqual(selectable, 16387)
        self.assertEqual((null, reviewed), (0, selectable + not_sel))
        self.assertEqual(self._row("KA20")[:3], (True, "both", "neonate_infant"))
        self.assertEqual(self._row("1C15")[0], True)
        self.assertEqual(self._row("GA10")[:2], (True, "female"))
        self.assertEqual(self._row("GA90")[:2], (True, "male"))
        self.assertEqual(self._row("GB20")[:2], (True, "both"))
        self.assertEqual(self._row("RA02")[0], True)
        self.assertEqual(self._row("RA04"), (False, None, None, None, "reviewed"))
        self.assertEqual(self._row("KD3B"), (False, None, None, None, "reviewed"))
        with self.db.engine.connect() as conn:
            x_rows = conn.execute(sa.text(
                "SELECT DISTINCT is_coding_selectable FROM mas_icd11_mms WHERE release = '2026-01' "
                "AND chapter_no = 'X' AND class_kind = 'category' AND is_active")).all()
        self.assertEqual(x_rows, [(False,)])

        alembic_downgrade(revision=PARENT_REVISION)
        self.assertEqual(self._snapshot(), before)

    def test_admin_edit_survives_and_rerun_is_noop(self):
        self._set("GA10", True, "reviewed")      # admin-reviewed, other values
        self._set("RA04", True)                   # partially edited, not never-reviewed
        alembic_upgrade(revision=REVISION)
        self.assertEqual(self._row("GA10")[:2], (True, None))
        self.assertEqual(self._row("RA04")[0], True)
        self.assertEqual(self._row("RA04")[4], "unreviewed")
        self.assertEqual(self._row("GA90")[:2], (True, "male"))

        alembic_downgrade(revision=PARENT_REVISION)
        # edited rows are not touched by the downgrade either
        self.assertEqual(self._row("GA10")[:2], (True, None))
        self.assertEqual(self._row("GA90")[0], None)
        alembic_upgrade(revision=REVISION)
        self.assertEqual(self._row("GA90")[:2], (True, "male"))
        # rerunning upgrade over the migrated state changes nothing
        migrated = self._snapshot()
        module = _load_module()
        with self.db.engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                module.upgrade()
        self.assertEqual(self._snapshot(), migrated)

    def test_already_imported_row_is_left_alone(self):
        """Dev shape: policy imported, status still unreviewed -> no-op."""
        with self.db.engine.begin() as conn:
            conn.execute(sa.text(
                "UPDATE mas_icd11_mms SET is_coding_selectable = FALSE WHERE release = '2026-01'"))
        before = self._snapshot()
        alembic_upgrade(revision=REVISION)
        self.assertEqual(self._snapshot(), before)


def _load_module():
    spec = importlib.util.spec_from_file_location("icd11_policy_signoff", MIGRATION_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrozenPolicyTest(unittest.TestCase):
    def test_frozen_copy_is_byte_equal_to_the_docs_artifact(self):
        self.assertEqual(FROZEN.read_bytes(), ARTIFACT.read_bytes())

    def test_frozen_items_are_unique_and_selectable(self):
        data = json.loads(FROZEN.read_text(encoding="utf-8"))
        uris = [item["linearization_uri"] for item in data["items"]]
        self.assertEqual(len(uris), 16387)
        self.assertEqual(len(set(uris)), len(uris))
        self.assertTrue(all(item["is_coding_selectable"] is True for item in data["items"]))
        self.assertEqual(_load_module()._load_arrays()["uris"], uris)
