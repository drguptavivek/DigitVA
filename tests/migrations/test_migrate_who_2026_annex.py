"""Tests for migration c5f2a8d1e9b3 (adopt WHO 2026 annex ICD-10 ranges).

Follows the throwaway-database shape from test_schema_drift.py: a database
of its own, built from nothing but the migration chain up to the revision
under test, never `minerva_test` or the dev `minerva`.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_migrate_who_2026_annex.py -q
"""
import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# A database of its own, dropped and recreated here, distinct from the one
# test_schema_drift.py uses.
MIGRATION_DB_NAME = "minerva_test_migration_c5f2a8d1e9b3"

PARENT_REVISION = "a40c38e73af4"
REVISION_UNDER_TEST = "c5f2a8d1e9b3"

MIGRATION_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "c5f2a8d1e9b3_adopt_who_2026_annex_icd10_ranges.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "who_2026_annex_migration", MIGRATION_MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(
        database=database
    )


class DriftConfig(TestConfig):
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


class Who2026AnnexMigrationTest(unittest.TestCase):
    """`flask icd10 policy-import` and `flask cod-buckets
    import-who-2022-va-2026` are the operator commands this migration
    replays for a fresh database, so it must produce the same effect: mark
    the artifact's added codes selectable without clobbering an admin's own
    edits, and create the WHO_2022_VA_2026 scheme without duplicating it.
    """

    def setUp(self):
        _admin_execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"')
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        self.addCleanup(
            lambda: _admin_execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"')
        )

        from tests.base import create_app_without_celery_takeover

        self.app = create_app_without_celery_takeover(DriftConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)

        alembic_upgrade(revision=PARENT_REVISION)

        from app import db

        self.db = db
        self.addCleanup(db.engine.dispose)

        self._seed_icd10_row(code="G43", is_coding_selectable=False)
        self._seed_icd10_row(
            code="G44",
            is_coding_selectable=True,
            sex_selectable="male",
            age_group_selectable="adult",
            restriction_note="Admin-reviewed: male adults only",
        )
        self._seed_icd10_row(code="A00", is_coding_selectable=False)

    def _reflect(self, name):
        return sa.Table(name, sa.MetaData(), autoload_with=self.db.engine)

    def _seed_icd10_row(self, *, code, is_coding_selectable, sex_selectable=None, age_group_selectable=None, restriction_note=None):
        # Revision a40c38e73af4 already carries the real ICD-10 master data
        # (migration d6e7f8a9b0c1 seeds it), so the codes under test already
        # exist -- set up their "before" policy state with an UPDATE rather
        # than colliding on the primary key with an INSERT.
        table = self._reflect("mas_icd10_2019_2")
        now = datetime.now(timezone.utc)
        with self.db.engine.begin() as conn:
            result = conn.execute(
                table.update()
                .where(table.c.code == code)
                .values(
                    is_coding_selectable=is_coding_selectable,
                    sex_selectable=sex_selectable,
                    age_group_selectable=age_group_selectable,
                    restriction_note=restriction_note,
                    updated_at=now,
                )
            )
            if result.rowcount == 0:
                raise AssertionError(f"expected seed code {code} to already exist from master data")

    def _icd10_row(self, code):
        table = self._reflect("mas_icd10_2019_2")
        with self.db.engine.connect() as conn:
            return conn.execute(
                sa.select(table).where(table.c.code == code)
            ).mappings().first()

    def test_added_code_that_was_not_selectable_is_marked_selectable(self):
        # Present first: G43 really is not selectable before the migration.
        before = self._icd10_row("G43")
        self.assertIs(before["is_coding_selectable"], False)

        alembic_upgrade(revision=REVISION_UNDER_TEST)

        after = self._icd10_row("G43")
        self.assertIs(after["is_coding_selectable"], True)
        self.assertEqual(after["sex_selectable"], "both")
        self.assertEqual(after["age_group_selectable"], "all")

    def test_added_code_with_an_existing_admin_override_is_left_untouched(self):
        before = self._icd10_row("G44")
        self.assertIs(before["is_coding_selectable"], True)
        self.assertEqual(before["sex_selectable"], "male")

        alembic_upgrade(revision=REVISION_UNDER_TEST)

        after = self._icd10_row("G44")
        self.assertIs(after["is_coding_selectable"], True)
        self.assertEqual(after["sex_selectable"], "male")
        self.assertEqual(after["age_group_selectable"], "adult")
        self.assertEqual(after["restriction_note"], "Admin-reviewed: male adults only")

    def test_code_not_in_the_added_codes_list_is_left_untouched(self):
        before = self._icd10_row("A00")
        self.assertIs(before["is_coding_selectable"], False)

        alembic_upgrade(revision=REVISION_UNDER_TEST)

        after = self._icd10_row("A00")
        self.assertIs(after["is_coding_selectable"], False)

    def test_creates_the_who_2022_va_2026_scheme_with_nodes_and_mappings(self):
        schemes = self._reflect("mas_cod_bucket_schemes")
        with self.db.engine.connect() as conn:
            existing = conn.execute(
                sa.select(sa.func.count()).select_from(schemes).where(
                    schemes.c.scheme_code == "WHO_2022_VA_2026"
                )
            ).scalar()
        self.assertEqual(existing, 0, "scheme must not exist before the migration")

        alembic_upgrade(revision=REVISION_UNDER_TEST)

        nodes = self._reflect("mas_cod_bucket_nodes")
        mappings = self._reflect("map_icd_cod_buckets")
        with self.db.engine.connect() as conn:
            scheme_row = conn.execute(
                sa.select(schemes).where(schemes.c.scheme_code == "WHO_2022_VA_2026")
            ).mappings().first()
            self.assertIsNotNone(scheme_row)

            node_count = conn.execute(
                sa.select(sa.func.count()).select_from(nodes).where(
                    nodes.c.scheme_id == scheme_row["scheme_id"]
                )
            ).scalar()
            mapping_count = conn.execute(
                sa.select(sa.func.count()).select_from(mappings).where(
                    mappings.c.scheme_id == scheme_row["scheme_id"]
                )
            ).scalar()
        self.assertGreater(node_count, 0)
        self.assertGreater(mapping_count, 0)

    def test_rerunning_is_idempotent_for_both_selectable_codes_and_the_scheme(self):
        alembic_upgrade(revision=REVISION_UNDER_TEST)

        schemes = self._reflect("mas_cod_bucket_schemes")
        with self.db.engine.connect() as conn:
            scheme_count_1 = conn.execute(
                sa.select(sa.func.count()).select_from(schemes).where(
                    schemes.c.scheme_code == "WHO_2022_VA_2026"
                )
            ).scalar()
            scheme_id_1 = conn.execute(
                sa.select(schemes.c.scheme_id).where(
                    schemes.c.scheme_code == "WHO_2022_VA_2026"
                )
            ).scalar()

        # Replay the same two idempotent steps the migration's upgrade()
        # runs, directly against a connection -- the migration's downgrade()
        # is a deliberate no-op (see its docstring), so there is no alembic
        # "downgrade then upgrade again" path to re-trigger this.
        module = _load_migration_module()
        with self.db.engine.begin() as conn:
            module._apply_selectable_codes(conn)
            module._create_scheme_if_missing(conn, datetime.now(timezone.utc))

        with self.db.engine.connect() as conn:
            scheme_count_2 = conn.execute(
                sa.select(sa.func.count()).select_from(schemes).where(
                    schemes.c.scheme_code == "WHO_2022_VA_2026"
                )
            ).scalar()
            scheme_id_2 = conn.execute(
                sa.select(schemes.c.scheme_id).where(
                    schemes.c.scheme_code == "WHO_2022_VA_2026"
                )
            ).scalar()

        self.assertEqual(scheme_count_1, 1)
        self.assertEqual(scheme_count_2, 1, "re-running must not duplicate the scheme")
        self.assertEqual(scheme_id_1, scheme_id_2)

        # And the admin override from setUp must still be intact.
        after = self._icd10_row("G44")
        self.assertEqual(after["sex_selectable"], "male")
