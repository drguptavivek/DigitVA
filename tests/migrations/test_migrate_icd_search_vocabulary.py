"""Migration c5a8d2e7f1b4: create and seed mas_icd_search_terms.

Throwaway database built from the migration chain only, like
test_migrate_va_cause_definitions.py. Row counts are read from the seed CSV
at test time (the CSV grows with the vocabulary), never hard-coded.
"""
import csv
import importlib.util
import unittest
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_migration_c5a8d2e7f1b4"
PARENT_REVISION = "a3c9e1f7b2d4"
REVISION_UNDER_TEST = "c5a8d2e7f1b4"
MIGRATION_FILE = f"{REVISION_UNDER_TEST}_add_mas_icd_search_terms.py"
RECONCILE_REVISION = "e9d4b6f8a3c2"
CAPTURE_TABLE = "_mig_e9d4b6f8a3c2_inserted"
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

    def test_reconcile_adds_only_missing_links(self):
        alembic_upgrade(revision=REVISION_UNDER_TEST)
        full_count = _seed_row_count()
        # A database seeded before the seed grew: delete the rows the
        # reconcile migration exists to restore, and hand-edit one survivor
        # the way an admin would.
        gone = ("cor pulmonale", "uremia", "assault", "drowning", "blood cancer",
                "drug reaction", "disseminated tuberculosis")
        with self.db.engine.begin() as conn:
            conn.execute(
                sa.text(
                    f"DELETE FROM {TABLE} WHERE term_normalized IN :gone"
                ).bindparams(sa.bindparam("gone", expanding=True)),
                {"gone": gone},
            )
            conn.execute(
                sa.text(
                    f"UPDATE {TABLE} SET note = 'admin note', source = 'admin' "
                    "WHERE term_normalized = 'cva' AND icd_classification = 'icd10'"
                )
            )
            survivors = conn.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar()

        alembic_upgrade(revision=RECONCILE_REVISION)
        self.assertEqual(self._scalar(f"SELECT count(*) FROM {TABLE}"), full_count)
        # the admin edit survives untouched
        self.assertEqual(
            self._scalar(
                f"SELECT note FROM {TABLE} WHERE term_normalized = 'cva' "
                "AND icd_classification = 'icd10'"
            ),
            "admin note",
        )
        # the assault icd11 counterpart (PF2Z) is part of the restore
        self.assertEqual(
            self._scalar(
                f"SELECT icd_code FROM {TABLE} WHERE term_normalized = 'assault' "
                "AND icd_classification = 'icd11'"
            ),
            "PF2Z",
        )

        alembic_downgrade(revision=REVISION_UNDER_TEST)
        # exactly the reconcile insertions are removed; the survivors (and
        # the admin edit) stay
        self.assertEqual(
            self._scalar(f"SELECT count(*) FROM {TABLE}"),
            survivors,
        )
        self.assertIsNone(self._scalar(f"SELECT to_regclass('{CAPTURE_TABLE}')"))


class SortOrderReconcileMigrationTest(unittest.TestCase):
    """Migration fdb562cccac4: add sort_order and reconcile the seed
    (digitva-3t2). Same throwaway-database pattern as the class above, one
    revision later, seeded up to its parent so the column and reconcile
    logic run against a realistic pre-existing table.
    """

    MIGRATION_DB_NAME = "minerva_test_migration_fdb562cccac4"
    PARENT_REVISION = "f2b7c9e4a1d8"
    REVISION_UNDER_TEST = "fdb562cccac4"
    INSERTED_TABLE = "_mig_fdb562cccac4_inserted"
    SORT_ORDER_TABLE = "_mig_fdb562cccac4_sort_order"
    DEACTIVATED_TABLE = "_mig_fdb562cccac4_deactivated"

    def setUp(self):
        _admin_execute(f'DROP DATABASE IF EXISTS "{self.MIGRATION_DB_NAME}"')
        _admin_execute(f'CREATE DATABASE "{self.MIGRATION_DB_NAME}"')
        self.addCleanup(
            lambda: _admin_execute(f'DROP DATABASE IF EXISTS "{self.MIGRATION_DB_NAME}"')
        )

        db_name = self.MIGRATION_DB_NAME

        class _Config(TestConfig):
            SQLALCHEMY_DATABASE_URI = _server_url(db_name).render_as_string(
                hide_password=False
            )

        from tests.base import create_app_without_celery_takeover

        self.app = create_app_without_celery_takeover(_Config)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        # The parent chain seeds from the CURRENT (live) CSV -- already the
        # full reconciled set this pass ships, so it already excludes the
        # 43 policy-dead keys and already contains the 120 new links.
        alembic_upgrade(revision=self.PARENT_REVISION)

        from app import db

        self.db = db
        self.addCleanup(db.engine.dispose)

    def _scalar(self, sql, params=None):
        with self.db.engine.connect() as conn:
            return conn.execute(sa.text(sql), params or {}).scalar()

    def _execute(self, sql, params=None):
        with self.db.engine.begin() as conn:
            conn.execute(sa.text(sql), params or {})

    def test_reconcile_readds_missing_links_sets_sort_order_and_deactivates_dead_keys(self):
        # Simulate a database seeded before this pass: delete one of the
        # newly-added links, and hand-insert two dead-key rows the way an
        # older install would still carry them (this pass's seed never
        # inserts them, since the live CSV it reads no longer has them).
        self._execute(
            f"DELETE FROM {TABLE} WHERE term_normalized = 'blood cancer' "
            "AND icd_classification = 'icd10'"
        )
        seed_sourced_dead_key_id = str(uuid.uuid4())
        admin_sourced_dead_key_id = str(uuid.uuid4())
        now_sql = "now()"
        self._execute(
            f"INSERT INTO {TABLE} (term_id, term, term_normalized, icd_classification, "
            f"icd_code, source, is_active, created_at, updated_at) VALUES "
            f"(:id, 'CCF', 'ccf', 'icd10', 'I50', 'seed_used_cod', true, {now_sql}, {now_sql})",
            {"id": seed_sourced_dead_key_id},
        )
        self._execute(
            f"INSERT INTO {TABLE} (term_id, term, term_normalized, icd_classification, "
            f"icd_code, source, is_active, created_at, updated_at) VALUES "
            f"(:id, 'HHD', 'hhd', 'icd10', 'I11', 'admin', true, {now_sql}, {now_sql})",
            {"id": admin_sourced_dead_key_id},
        )
        # An admin-edited row this pass's reconcile must leave alone.
        self._execute(
            "UPDATE mas_icd_search_terms SET note = 'admin note' "
            "WHERE term_normalized = 'cva' AND icd_classification = 'icd10'"
        )

        alembic_upgrade(revision=self.REVISION_UNDER_TEST)

        # (b) the deleted new link is restored.
        self.assertEqual(
            self._scalar(
                f"SELECT count(*) FROM {TABLE} WHERE term_normalized = 'blood cancer' "
                "AND icd_classification = 'icd10'"
            ),
            1,
        )
        # (c) "head injury" (icd10) gets its reviewed sort_order: the
        # traffic bucket (V89.2) lists before the fall bucket (W19). TB no
        # longer works as this example -- this pass narrows it to a single
        # target (A16), so there is nothing left to order among.
        self.assertEqual(
            self._scalar(
                f"SELECT sort_order FROM {TABLE} WHERE term_normalized = 'head injury' "
                "AND icd_classification = 'icd10' AND icd_code = 'V89.2'"
            ),
            1,
        )
        self.assertEqual(
            self._scalar(
                f"SELECT sort_order FROM {TABLE} WHERE term_normalized = 'head injury' "
                "AND icd_classification = 'icd10' AND icd_code = 'W19'"
            ),
            2,
        )
        # every other row keeps the column default.
        self.assertEqual(
            self._scalar(
                f"SELECT sort_order FROM {TABLE} WHERE term_normalized = 'cva' "
                "AND icd_classification = 'icd10'"
            ),
            100,
        )
        # the admin edit survives.
        self.assertEqual(
            self._scalar(
                f"SELECT note FROM {TABLE} WHERE term_normalized = 'cva' "
                "AND icd_classification = 'icd10'"
            ),
            "admin note",
        )
        # (d) the seed-sourced dead key is deactivated, the admin-sourced
        # one at the same key is left alone.
        self.assertFalse(
            self._scalar(
                f"SELECT is_active FROM {TABLE} WHERE term_id = :id",
                {"id": seed_sourced_dead_key_id},
            )
        )
        self.assertTrue(
            self._scalar(
                f"SELECT is_active FROM {TABLE} WHERE term_id = :id",
                {"id": admin_sourced_dead_key_id},
            )
        )

        alembic_downgrade(revision=self.PARENT_REVISION)

        # downgrade reverses exactly what this migration did.
        self.assertTrue(
            self._scalar(
                f"SELECT is_active FROM {TABLE} WHERE term_id = :id",
                {"id": seed_sourced_dead_key_id},
            )
        )
        self.assertTrue(
            self._scalar(
                f"SELECT is_active FROM {TABLE} WHERE term_id = :id",
                {"id": admin_sourced_dead_key_id},
            )
        )
        self.assertEqual(
            self._scalar(
                f"SELECT count(*) FROM {TABLE} WHERE term_normalized = 'blood cancer' "
                "AND icd_classification = 'icd10'"
            ),
            0,
        )
        self.assertIsNone(
            self._scalar(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'mas_icd_search_terms' AND column_name = 'sort_order'"
            )
        )
        for capture_table in (
            self.INSERTED_TABLE,
            self.SORT_ORDER_TABLE,
            self.DEACTIVATED_TABLE,
        ):
            self.assertIsNone(self._scalar(f"SELECT to_regclass('{capture_table}')"))

    def test_second_upgrade_is_idempotent(self):
        alembic_upgrade(revision=self.REVISION_UNDER_TEST)
        before = self._scalar(f"SELECT count(*) FROM {TABLE}")

        alembic_upgrade(revision=self.REVISION_UNDER_TEST)

        self.assertEqual(self._scalar(f"SELECT count(*) FROM {TABLE}"), before)


class TuberculosisVocabularyReconcileMigrationTest(unittest.TestCase):
    MIGRATION_DB_NAME = "minerva_test_migration_b7e2a9c4d6f1"
    PARENT_REVISION = "a5f7c3d92b18"
    REVISION_UNDER_TEST = "b7e2a9c4d6f1"
    MIGRATION_FILE = f"{REVISION_UNDER_TEST}_reconcile_tuberculosis_vocabulary.py"
    CAPTURE_TABLE = "_mig_b7e2a9c4d6f1_inserted"

    def setUp(self):
        _admin_execute(f'DROP DATABASE IF EXISTS "{self.MIGRATION_DB_NAME}"')
        _admin_execute(f'CREATE DATABASE "{self.MIGRATION_DB_NAME}"')
        self.addCleanup(
            lambda: _admin_execute(
                f'DROP DATABASE IF EXISTS "{self.MIGRATION_DB_NAME}"'
            )
        )

        db_name = self.MIGRATION_DB_NAME

        class _Config(TestConfig):
            SQLALCHEMY_DATABASE_URI = _server_url(db_name).render_as_string(hide_password=False)

        from tests.base import create_app_without_celery_takeover

        self.app = create_app_without_celery_takeover(_Config)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        alembic_upgrade(revision=self.PARENT_REVISION)

        from app import db

        self.db = db
        self.addCleanup(db.engine.dispose)

    def _scalar(self, sql, params=None):
        with self.db.engine.connect() as conn:
            return conn.execute(sa.text(sql), params or {}).scalar()

    def _execute(self, sql, params=None):
        with self.db.engine.begin() as conn:
            conn.execute(sa.text(sql), params or {})

    def _load_migration(self):
        path = _repo_root() / "migrations" / "versions" / self.MIGRATION_FILE
        spec = importlib.util.spec_from_file_location("_under_test_tuberculosis_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_fresh_chain_and_reconcile_upgrade_have_exact_downgrades(self):
        migration = self._load_migration()
        with (_repo_root() / "resource" / "icd_search_vocabulary_seed.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            seed_rows = [
                (
                    row["term"].strip(),
                    row["term_normalized"].strip(),
                    row["icd_classification"].strip(),
                    row["icd_code"].strip(),
                    row["source"].strip(),
                    row["note"].strip(),
                    int((row.get("sort_order") or "").strip() or 100),
                )
                for row in csv.DictReader(handle)
                if row["term_normalized"].strip() == "tuberculosis"
            ]
        self.assertEqual(set(migration.TUBERCULOSIS_ROWS), set(seed_rows))

        # Earlier migrations consume the current CSV on a fresh chain, so
        # this revision must not claim rows written by those older revisions.
        for classification, code in (("icd10", "A16"), ("icd11", "1B10.Z")):
            self.assertEqual(
                self._scalar(
                    f"SELECT count(*) FROM {TABLE} WHERE term_normalized = :term "
                    "AND icd_classification = :classification AND icd_code = :code",
                    {"term": "tuberculosis", "classification": classification, "code": code},
                ),
                1,
            )
        alembic_upgrade(revision=self.REVISION_UNDER_TEST)
        self.assertEqual(self._scalar(f"SELECT count(*) FROM {self.CAPTURE_TABLE}"), 0)
        alembic_downgrade(revision=self.PARENT_REVISION)
        self.assertEqual(
            self._scalar(f"SELECT count(*) FROM {TABLE} WHERE term_normalized = 'tuberculosis'"), 2
        )
        self.assertIsNone(self._scalar(f"SELECT to_regclass('{self.CAPTURE_TABLE}')"))

        # Simulate a deployed database that predates this seed addition. Keep
        # an administrator-owned exact key to prove reconciliation respects it.
        self._execute(
            f"DELETE FROM {TABLE} WHERE "
            "(term_normalized = 'tuberculosis' AND icd_classification = 'icd10' "
            "AND icd_code = 'A16') OR "
            "(term_normalized = 'tuberculosis' AND icd_classification = 'icd11' "
            "AND icd_code = '1B10.Z')"
        )
        admin_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        self._execute(
            f"INSERT INTO {TABLE} (term_id, term, term_normalized, icd_classification, "
            "icd_code, source, note, sort_order, is_active, created_at, updated_at) "
            "VALUES (:term_id, 'tuberculosis', 'tuberculosis', 'icd10', 'A16', "
            "'admin', 'keep this edit', 7, false, :now, :now)",
            {"term_id": admin_id, "now": now},
        )

        alembic_upgrade(revision=self.REVISION_UNDER_TEST)

        self.assertEqual(self._scalar(f"SELECT count(*) FROM {self.CAPTURE_TABLE}"), 1)
        inserted_id = self._scalar(f"SELECT term_id FROM {self.CAPTURE_TABLE}")
        self.assertEqual(
            self._scalar(
                f"SELECT icd_code FROM {TABLE} WHERE term_id = :term_id",
                {"term_id": inserted_id},
            ),
            "1B10.Z",
        )
        admin_row = self._scalar(
            f"SELECT note || '|' || source || '|' || is_active::text || '|' || sort_order "
            f"FROM {TABLE} WHERE term_id = :term_id",
            {"term_id": admin_id},
        )
        self.assertEqual(admin_row, "keep this edit|admin|false|7")

        alembic_downgrade(revision=self.PARENT_REVISION)

        self.assertEqual(
            self._scalar(
                f"SELECT count(*) FROM {TABLE} WHERE term_normalized = 'tuberculosis' "
                "AND icd_classification = 'icd10' AND icd_code = 'A16'"
            ),
            1,
        )
        self.assertEqual(
            self._scalar(
                f"SELECT count(*) FROM {TABLE} WHERE term_normalized = 'tuberculosis' "
                "AND icd_classification = 'icd11' AND icd_code = '1B10.Z'"
            ),
            0,
        )
        self.assertEqual(
            str(
                self._scalar(
                    f"SELECT term_id FROM {TABLE} WHERE term_normalized = 'tuberculosis' "
                    "AND icd_classification = 'icd10' AND icd_code = 'A16'"
                )
            ),
            admin_id,
        )
        self.assertIsNone(self._scalar(f"SELECT to_regclass('{self.CAPTURE_TABLE}')"))


if __name__ == "__main__":
    unittest.main()
