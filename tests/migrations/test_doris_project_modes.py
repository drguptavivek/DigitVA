"""Migration coverage for project COD modes and final DORIS payload columns."""

import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

DATABASE = "minerva_test_doris_modes"
PARENT = "d9e0f1a2b3c4"
REVISION = "c7a4e2d9f1b6"


def _url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class DorisModeMigrationConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _url(DATABASE).render_as_string(hide_password=False)


def _admin(*statements):
    engine = sa.create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            for statement in statements:
                connection.execute(sa.text(statement))
    finally:
        engine.dispose()


def _drop_database():
    _admin(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{DATABASE}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{DATABASE}"',
    )


class DorisProjectModesMigrationTest(unittest.TestCase):
    def test_upgrade_preserves_rows_and_adds_guarded_nullable_payloads(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin(f'CREATE DATABASE "{DATABASE}"')
        try:
            app = create_app_without_celery_takeover(DorisModeMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PARENT)
                db.session.execute(
                    sa.text(
                        "INSERT INTO va_project_master (project_id, project_name, "
                        "project_nickname, project_status, project_registered_at, "
                        "project_updated_at) VALUES "
                        "('DRSM01', 'Existing', 'Existing', 'active', now(), now())"
                    )
                )
                db.session.commit()

                alembic_upgrade(revision=REVISION)
                row = db.session.execute(
                    sa.text(
                        "SELECT masked_cod_required, cod_entry_mode "
                        "FROM va_project_master WHERE project_id = 'DRSM01'"
                    )
                ).one()
                self.assertEqual(row, (True, "simple"))

                inspector = sa.inspect(db.engine)
                expected = {
                    "va_immediate_cod",
                    "immediate_icd11_provenance",
                    "va_other_conditions",
                    "doris_certificate",
                    "doris_result",
                    "codedit_result",
                    "cod_entry_mode_snapshot",
                }
                for table in (
                    "va_final_assessments",
                    "va_reviewer_final_assessments",
                ):
                    columns = {column["name"]: column for column in inspector.get_columns(table)}
                    self.assertTrue(expected <= columns.keys())
                    self.assertTrue(all(columns[name]["nullable"] for name in expected))

                for statement in (
                    "UPDATE va_project_master SET cod_entry_mode = 'invalid' "
                    "WHERE project_id = 'DRSM01'",
                    "UPDATE va_project_master SET cod_entry_mode = 'doris', "
                    "masked_cod_required = true, icd_classification = 'icd11' "
                    "WHERE project_id = 'DRSM01'",
                    "UPDATE va_project_master SET cod_entry_mode = 'doris', "
                    "masked_cod_required = false, icd_classification = 'selectable' "
                    "WHERE project_id = 'DRSM01'",
                ):
                    with self.assertRaises(sa.exc.IntegrityError):
                        db.session.execute(sa.text(statement))
                        db.session.commit()
                    db.session.rollback()

                db.session.remove()
                alembic_downgrade(revision=PARENT)
                project_columns = {
                    column["name"]
                    for column in sa.inspect(db.engine).get_columns("va_project_master")
                }
                self.assertNotIn("masked_cod_required", project_columns)
                self.assertNotIn("cod_entry_mode", project_columns)
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
