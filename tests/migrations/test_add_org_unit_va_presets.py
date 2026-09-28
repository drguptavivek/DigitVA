"""Migration coverage for the per-unit VA question presets table (digitva-dhc)."""

import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

DATABASE = "minerva_test_org_unit_va_presets"
PARENT = "c1d5e9a2f7b4"
REVISION = "b1f4d8a6c9e2"
NEW_TABLE = "map_org_unit_va_presets"


def _url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class OrgUnitVaPresetsMigrationConfig(TestConfig):
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


def _table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def _columns(db, table):
    return {
        name: (data_type, nullable)
        for name, data_type, nullable in db.session.execute(
            sa.text(
                "SELECT column_name, data_type, is_nullable FROM "
                "information_schema.columns WHERE table_name = :table"
            ),
            {"table": table},
        ).all()
    }


class OrgUnitVaPresetsMigrationTest(unittest.TestCase):
    def test_upgrade_adds_table_and_downgrade_reverts(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin(f'CREATE DATABASE "{DATABASE}"')
        try:
            app = create_app_without_celery_takeover(OrgUnitVaPresetsMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PARENT)
                tables = _table_names(db.engine)
                self.assertNotIn(NEW_TABLE, tables)
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                tables = _table_names(db.engine)
                self.assertIn(NEW_TABLE, tables)
                columns = _columns(db, NEW_TABLE)
                self.assertEqual(columns["org_unit_id"], ("uuid", "NO"))
                self.assertEqual(columns["hiv_mortality"], ("character varying", "YES"))
                self.assertEqual(columns["malaria_mortality"], ("character varying", "YES"))
                self.assertEqual(columns["updated_at"], ("timestamp with time zone", "NO"))
                self.assertEqual(columns["updated_by_user_id"], ("uuid", "YES"))

                # CHECK constraint rejects an out-of-set value.
                unit_id = db.session.execute(
                    sa.text("SELECT org_unit_id FROM mas_org_unit LIMIT 1")
                ).scalar()
                if unit_id is not None:
                    with self.assertRaises(sa.exc.IntegrityError):
                        db.session.execute(
                            sa.text(
                                "INSERT INTO map_org_unit_va_presets "
                                "(org_unit_id, hiv_mortality, updated_at) "
                                "VALUES (:unit_id, 'bogus', now())"
                            ),
                            {"unit_id": unit_id},
                        )
                        db.session.commit()
                    db.session.rollback()
                db.session.remove()

                alembic_downgrade(revision=PARENT)
                tables = _table_names(db.engine)
                self.assertNotIn(NEW_TABLE, tables)
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
