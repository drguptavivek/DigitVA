"""Migration a3c9e1f7b2d4: ICD-10 Q00-Q99 selectable at all ages."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import db
from tests.base import BaseTestCase

_PATH = Path(__file__).resolve().parents[2] / "migrations/versions/a3c9e1f7b2d4_icd10_congenital_anomalies_all_ages.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("q_all_ages", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IcdTenCongenitalAllAgesMigrationTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.migration = _load_migration()
        # Q21 selectable neonate-only; Q22 set by an admin to child; P95 not a Q code.
        for code, age in (("Q21", "neonate"), ("Q22", "child"), ("P95", "neonate")):
            db.session.execute(
                sa.text(
                    "INSERT INTO mas_icd10_2019_2 (code, title, node_type, semantic_level, sort_order, "
                    "has_children, is_leaf, is_three_character_code, is_detailed_code, "
                    "age_group_selectable, is_coding_selectable, sex_selectable, policy_status, "
                    "source_version, is_active, created_at, updated_at) VALUES (:code, :code, "
                    "'category', 'category', 0, false, true, true, false, :age, true, 'both', "
                    "'reviewed', 'test', true, now(), now()) ON CONFLICT DO NOTHING"
                ),
                {"code": code, "age": age},
            )
        db.session.flush()

    def _run(self, step):
        connection = db.session.connection()
        with Operations.context(MigrationContext.configure(connection)):
            getattr(self.migration, step)()

    def _age(self, code):
        return db.session.execute(
            sa.text("SELECT age_group_selectable FROM mas_icd10_2019_2 WHERE code = :code"),
            {"code": code},
        ).scalar_one()

    def test_upgrade_downgrade_and_rerun(self):
        self.assertEqual(self._age("Q21"), "neonate")
        self._run("upgrade")
        self.assertEqual(self._age("Q21"), "all")
        self.assertEqual(self._age("Q22"), "child")
        self.assertEqual(self._age("P95"), "neonate")
        self._run("upgrade")
        self.assertEqual(self._age("Q21"), "all")
        self._run("downgrade")
        self.assertEqual(self._age("Q21"), "neonate")
        self.assertEqual(self._age("Q22"), "child")
