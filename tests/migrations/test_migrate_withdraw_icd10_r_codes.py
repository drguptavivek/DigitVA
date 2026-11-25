"""Tests for migration 1f037b4717e4 (ICD-10 R00-R94 withdrawn from coding,
R50 and R54 kept; digitva-82l9).

Policy: docs/policy/who-2022-icd10-coding-allowability.md, "Symptom and sign
codes are withdrawn from coding". Same throwaway-database shape as
test_migrate_owner_decisions_15_16_17.py: a database of its own, built from
nothing but the migration chain, so search and save are checked against the
catalogue the chain really produces.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_migrate_withdraw_icd10_r_codes.py -q
"""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import stamp as alembic_stamp
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_migration_withdraw_icd10_r_codes"
PARENT_REVISION = "a7d3e9c5b2f1"
REVISION = "1f037b4717e4"
MIGRATION_FILE = (
    Path(__file__).resolve().parents[2]
    / "migrations" / "versions" / "1f037b4717e4_withdraw_icd10_r00_r94_symptom_codes.py"
)
WITHDRAWN = ("R06", "R10", "R17", "R56", "R57")
KEPT = ("R50", "R54", "R95", "R96", "R99")
ADULT_MALE = {"va_sid": "va-test", "age_group": "adult", "sex": "male"}


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


def _load_module():
    spec = importlib.util.spec_from_file_location("withdraw_icd10_r_codes", MIGRATION_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WithdrawIcd10RCodesMigrationTest(unittest.TestCase):
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
        self.addCleanup(db.session.remove)
        self.module = _load_module()

    def _selectable(self, codes):
        with self.db.engine.connect() as conn:
            return dict(
                conn.execute(
                    sa.text(
                        "SELECT code, is_coding_selectable FROM mas_icd10_2019_2 WHERE code IN :codes"
                    ).bindparams(sa.bindparam("codes", expanding=True)),
                    {"codes": list(codes)},
                ).all()
            )

    def _r_rows(self):
        with self.db.engine.connect() as conn:
            return {
                row.code: (row.is_coding_selectable, row.sex_selectable, row.age_group_selectable)
                for row in conn.execute(
                    sa.text(
                        "SELECT code, is_coding_selectable, sex_selectable, age_group_selectable "
                        "FROM mas_icd10_2019_2 WHERE code LIKE 'R%'"
                    )
                )
            }

    def _set_policy(self, code, selectable, sex=None, age=None):
        """An admin edit, the way the ICD-10 policy editor stores it."""
        with self.db.engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE mas_icd10_2019_2 SET is_coding_selectable = :selectable, "
                    "sex_selectable = :sex, age_group_selectable = :age WHERE code = :code"
                ),
                {"code": code, "selectable": selectable, "sex": sex, "age": age},
            )

    def _search_codes(self, query):
        from app.services.icd10_2019_2_service import search_icd10_2019_2_coding_choices_for_policy

        self.db.session.remove()
        return {
            row["icd_code"]
            for row in search_icd10_2019_2_coding_choices_for_policy(query, age_group="adult", sex="male")
        }

    def _accepts(self, code):
        from app.services.icd10_2019_2_service import (
            validate_icd10_2019_2_coding_value_for_submission,
        )

        self.db.session.remove()
        # No submission in a migration-only database; the age/sex context is
        # all the validator reads from it.
        with patch(
            "app.services.icd10_2019_2_service.coding_context_for_submission", return_value=ADULT_MALE
        ):
            try:
                validate_icd10_2019_2_coding_value_for_submission("va-test", f"{code} title")
            except ValueError:
                return False
        return True

    def _bucket_rows(self, code):
        with self.db.engine.connect() as conn:
            return conn.execute(
                sa.text(
                    "SELECT n.node_code, m.is_active FROM map_icd_cod_buckets m "
                    "JOIN mas_cod_bucket_nodes n ON n.node_id = m.node_id "
                    "JOIN mas_cod_bucket_schemes s ON s.scheme_id = m.scheme_id "
                    "WHERE s.scheme_code = 'WHO_2022_VA_2026' AND m.icd_classification = 'icd10' "
                    "AND m.icd_code = :code"
                ),
                {"code": code},
            ).all()

    def test_embedded_families_are_the_catalogue_r00_r94_minus_r50_r54(self):
        with self.db.engine.connect() as conn:
            catalogue = set(
                conn.execute(
                    sa.text(
                        "SELECT DISTINCT three_character_code FROM mas_icd10_2019_2 "
                        "WHERE is_active AND three_character_code BETWEEN 'R00' AND 'R94' "
                        "AND three_character_code NOT IN ('R50', 'R54')"
                    )
                ).scalars()
            )
        families = self.module.WITHDRAWN_FAMILIES
        self.assertEqual(len(families), 85)
        self.assertEqual(len(set(families)), 85)
        self.assertEqual(set(families), catalogue)
        self.assertFalse({"R50", "R54", "R95", "R96", "R97", "R98", "R99"} & set(families))

    def test_upgrade_withdraws_r00_r94_from_search_and_save_and_keeps_r50_r54_r95_r99(self):
        self._set_policy("R10.4", True, "both", "all")  # an admin-enabled subcode
        before = self._selectable(WITHDRAWN + KEPT + ("R10.4",))
        self.assertEqual(set(before), set(WITHDRAWN + KEPT + ("R10.4",)))
        self.assertTrue(all(before.values()))
        self.assertIn("R10", self._search_codes("R10"))
        self.assertIn("R10.4", self._search_codes("abdominal pain"))
        self.assertTrue(self._accepts("R10"))
        bucket_before = self._bucket_rows("R10")
        self.assertEqual(bucket_before, [("vas_06_01", True)])

        alembic_upgrade(revision=REVISION)

        after = self._selectable(WITHDRAWN + KEPT + ("R10.4",))
        for code in WITHDRAWN + ("R10.4",):
            self.assertIs(after[code], False, code)
        for code in KEPT:
            self.assertIs(after[code], True, code)

        self.assertNotIn("R10", self._search_codes("R10"))
        self.assertFalse({"R10", "R10.4"} & self._search_codes("abdominal pain"))
        self.assertIn("R54", self._search_codes("R54"))
        self.assertIn("R99", self._search_codes("R99"))
        self.assertFalse(self._accepts("R10"))
        self.assertFalse(self._accepts("R10.4"))
        self.assertTrue(self._accepts("R54"))

        self.assertEqual(self._bucket_rows("R10"), bucket_before, "bucket rows untouched")

    def test_downgrade_restores_exactly_what_upgrade_changed(self):
        self._set_policy("R10.4", True, "both", "all")  # admin-enabled subcode
        self._set_policy("R06", False, "both", "all")  # admin-disabled before upgrade
        before = self._r_rows()
        self.assertIs(before["R10.1"][0], False, "a never-selectable subcode")

        alembic_upgrade(revision=REVISION)
        upgraded = self._r_rows()

        # Rerun is a no-op.
        alembic_stamp(revision=PARENT_REVISION)
        alembic_upgrade(revision=REVISION)
        self.assertEqual(self._r_rows(), upgraded)

        # An admin re-enables a withdrawn code for one sex after the upgrade.
        self._set_policy("R17", True, "female", "adult")

        alembic_downgrade(revision=PARENT_REVISION)
        reverted = self._r_rows()
        self.assertEqual(reverted["R17"], (True, "female", "adult"), "admin edit survives")
        reverted["R17"] = before["R17"]
        self.assertEqual(reverted, before)
        self.assertIs(reverted["R06"][0], False, "pre-upgrade admin disable stays")
        self.assertIs(reverted["R10.1"][0], False, "never-selectable subcode stays off")
        self.assertIs(reverted["R10.4"][0], True)
        with self.db.engine.connect() as conn:
            self.assertIsNone(
                conn.execute(sa.text("SELECT to_regclass('_mig_1f037b4717e4_withdrawn')")).scalar()
            )
