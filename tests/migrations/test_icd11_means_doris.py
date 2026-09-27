"""Migration coverage for ICD-11-means-DORIS and the retired 'selectable'
classification (digitva-0n3 phase 1)."""

import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

DATABASE = "minerva_test_icd11_doris"
PARENT = "c7a4e2d9f1b6"
REVISION = "a3f7c1d8e5b2"


def _url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class Icd11DorisMigrationConfig(TestConfig):
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


def _insert_project(db, project_id, icd_classification, cod_entry_mode, masked_cod_required):
    db.session.execute(
        sa.text(
            "INSERT INTO va_project_master (project_id, project_name, "
            "project_nickname, project_status, project_registered_at, "
            "project_updated_at, icd_classification, cod_entry_mode, "
            "masked_cod_required) VALUES "
            "(:project_id, :project_id, :project_id, 'active', now(), now(), "
            ":icd_classification, :cod_entry_mode, :masked_cod_required)"
        ),
        {
            "project_id": project_id,
            "icd_classification": icd_classification,
            "cod_entry_mode": cod_entry_mode,
            "masked_cod_required": masked_cod_required,
        },
    )


class Icd11MeansDorisMigrationTest(unittest.TestCase):
    def test_upgrade_rewrites_rows_and_downgrade_restores_old_checks(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin(f'CREATE DATABASE "{DATABASE}"')
        try:
            app = create_app_without_celery_takeover(Icd11DorisMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PARENT)

                # selectable/simple: moves to icd10/simple.
                _insert_project(db, "SEL001", "selectable", "simple", True)
                # icd11/simple masked: moves to icd11/doris.
                _insert_project(db, "M11001", "icd11", "simple", True)
                # icd11/doris unmasked: already legal, untouched.
                _insert_project(db, "U11001", "icd11", "doris", False)
                # icd10/simple: untouched.
                _insert_project(db, "ICD100", "icd10", "simple", True)
                db.session.commit()

                alembic_upgrade(revision=REVISION)

                rows = {
                    project_id: (icd_classification, cod_entry_mode)
                    for project_id, icd_classification, cod_entry_mode in db.session.execute(
                        sa.text(
                            "SELECT project_id, icd_classification, cod_entry_mode "
                            "FROM va_project_master WHERE project_id IN "
                            "('SEL001', 'M11001', 'U11001', 'ICD100')"
                        )
                    ).all()
                }
                self.assertEqual(rows["SEL001"], ("icd10", "simple"))
                self.assertEqual(rows["M11001"], ("icd11", "doris"))
                self.assertEqual(rows["U11001"], ("icd11", "doris"))
                self.assertEqual(rows["ICD100"], ("icd10", "simple"))

                for statement in (
                    "UPDATE va_project_master SET icd_classification = 'icd11', "
                    "cod_entry_mode = 'simple' WHERE project_id = 'ICD100'",
                    "UPDATE va_project_master SET icd_classification = 'icd10', "
                    "cod_entry_mode = 'doris' WHERE project_id = 'ICD100'",
                    "UPDATE va_project_master SET icd_classification = 'selectable' "
                    "WHERE project_id = 'ICD100'",
                ):
                    with self.assertRaises(sa.exc.IntegrityError):
                        db.session.execute(sa.text(statement))
                        db.session.commit()
                    db.session.rollback()

                db.session.remove()
                alembic_downgrade(revision=PARENT)

                rows = {
                    project_id: (icd_classification, cod_entry_mode, masked_cod_required)
                    for project_id, icd_classification, cod_entry_mode, masked_cod_required in db.session.execute(
                        sa.text(
                            "SELECT project_id, icd_classification, cod_entry_mode, "
                            "masked_cod_required FROM va_project_master WHERE project_id IN "
                            "('SEL001', 'M11001', 'U11001', 'ICD100')"
                        )
                    ).all()
                }
                # The masked icd11/doris row (legal only under the new CHECK)
                # is moved back to simple, the old CHECK's only home for it.
                self.assertEqual(rows["M11001"], ("icd11", "simple", True))
                # Unmasked icd11/doris was already legal under the old CHECK.
                self.assertEqual(rows["U11001"], ("icd11", "doris", False))

                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(
                        sa.text(
                            "UPDATE va_project_master SET cod_entry_mode = 'doris', "
                            "masked_cod_required = true WHERE project_id = 'ICD100'"
                        )
                    )
                    db.session.commit()
                db.session.rollback()

                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
