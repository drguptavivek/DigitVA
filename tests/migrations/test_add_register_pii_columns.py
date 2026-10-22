"""``e5a2c7b9d3f1`` adds the sealed-personal-data columns to
``va_death_register`` and ``map_case_transitions`` (PII slice 2, T1).

Builds a throwaway database at the previous head with two cases, upgrades,
checks the presence-flag fill, the rewritten identity and location CHECKs
(a stripped row passes, an unflagged one fails) and the indexes, then checks
the downgrade refuses while a row is sealed and restores the old schema once
it is not.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_register_pii_columns.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
DB_NAME = "minerva_test_register_pii_mig"

PREVIOUS_HEAD = "d4f1b8c2a6e9"
REVISION = "e5a2c7b9d3f1"
NEW_COLUMNS = {
    "pii_sealed", "pii_dek_wrapped", "pii_key_id", "pii_blind_key_id", "pii_sealed_at",
    "informant_phone_bidx", "informant_phone_2_bidx", "abha_number_bidx", "abha_address_bidx",
    "has_deceased_name", "has_informant_phone", "has_informant_phone_2", "has_location",
}
NEW_INDEXES = {
    "ix_va_death_register_project_informant_phone_bidx",
    "ix_va_death_register_project_informant_phone_2_bidx",
    "ix_va_death_register_project_abha_number_bidx",
    "ix_va_death_register_project_abha_address_bidx",
    "ix_va_death_register_pii_key",
}

_INSERT = """
INSERT INTO va_death_register (
    death_id, project_id, site_id, death_number, unique_id, deceased_name, deceased_sex,
    date_of_death, informant_phone, latitude, longitude, captured_at, status, source,
    registered_by, created_at, updated_at, has_deceased_name, has_location, accuracy_m
) VALUES (
    :id, 'P', 'S', :n, :uid, :name, :sex, :dod, :phone, :lat, :lon, :cap, :status, 'register',
    gen_random_uuid(), now(), '2020-01-01T00:00:00Z', :has_name, :has_loc, :acc
)
"""


# The same row before the flag columns exist.
_OLD_INSERT = (
    _INSERT.replace(", has_deceased_name, has_location, accuracy_m", "").replace(", :has_name, :has_loc, :acc", "")
)


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class RegisterPiiMigrationConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(DB_NAME).render_as_string(hide_password=False)


def _admin_execute(*statements):
    engine = sa.create_engine(_server_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for statement in statements:
                conn.execute(sa.text(statement))
    finally:
        engine.dispose()


def _drop_database():
    _admin_execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{DB_NAME}"',
    )


class AddRegisterPiiColumnsMigrationTest(unittest.TestCase):
    def test_upgrade_fills_flags_rewrites_checks_and_downgrade_guards_sealed_rows(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        def columns():
            names = {c["name"] for c in sa.inspect(db.engine).get_columns("va_death_register")}
            audit = {c["name"] for c in sa.inspect(db.engine).get_columns("map_case_transitions")}
            return names, audit

        def run(sql, **params):
            return db.session.execute(sa.text(sql), params)

        def insert(n, **over):
            sql = _INSERT if over.pop("flags", False) else _OLD_INSERT
            values = {
                "id": f"00000000-0000-0000-0000-00000000000{n}", "n": n, "uid": f"U{n}",
                "name": None, "sex": "female", "dod": "2020-01-01", "phone": None, "lat": None,
                "lon": None, "cap": None, "status": "registered",
                "has_name": False, "has_loc": False, "acc": None,
            }
            values.update(over)
            run(sql, **values)

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(RegisterPiiMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self.assertFalse(NEW_COLUMNS & columns()[0])
                # No foreign-key fixtures: this test is about the new columns.
                run("SET session_replication_role = replica")
                insert(1, name="Asha", phone="9876543210", lat=10.5, lon=20.5, cap="2020-01-01T00:00:00Z")
                insert(2, status="draft_identity")
                db.session.commit()

                alembic_upgrade(revision=REVISION)
                db.session.remove()
                register_columns, audit_columns = columns()
                self.assertTrue(NEW_COLUMNS <= register_columns)
                self.assertTrue({"changes_dek_wrapped", "changes_key_id"} <= audit_columns)
                rows = {
                    row.unique_id: row for row in run(
                        "SELECT unique_id, has_deceased_name, has_informant_phone, has_informant_phone_2, "
                        "has_location, updated_at FROM va_death_register"
                    )
                }
                self.assertEqual(
                    tuple(rows["U1"][1:5]), (True, True, False, True))
                self.assertEqual(tuple(rows["U2"][1:5]), (False, False, False, False))
                # The fill is a schema change, not an edit of the case.
                self.assertEqual(rows["U1"].updated_at.year, 2020)
                indexes = {i["name"] for i in sa.inspect(db.engine).get_indexes("va_death_register")}
                self.assertTrue(NEW_INDEXES <= indexes)

                # A stripped row (plaintext NULL, flags true) passes both CHECKs; a row whose
                # name is NULL without the flag, or a fix flagged absent, does not.
                run("SET session_replication_role = replica")
                with self.assertRaises(sa.exc.IntegrityError):
                    insert(3, flags=True)  # NULL name, no flag -> identity CHECK
                db.session.rollback()
                run("SET session_replication_role = replica")
                insert(4, flags=True, has_name=True, has_loc=True, cap="2020-01-01T00:00:00Z", acc=5)
                db.session.commit()
                run("SET session_replication_role = replica")
                with self.assertRaises(sa.exc.IntegrityError):
                    run("UPDATE va_death_register SET has_location = false WHERE unique_id = 'U4'")
                db.session.rollback()

                # Downgrade refuses while a row is sealed...
                run("SET session_replication_role = replica")
                run("UPDATE va_death_register SET pii_sealed = '{}'::jsonb WHERE unique_id = 'U4'")
                db.session.commit()
                db.session.remove()
                # (flask-migrate turns the migration's RuntimeError into an exit.)
                with self.assertRaises((RuntimeError, SystemExit)):
                    alembic_downgrade(revision=PREVIOUS_HEAD)
                db.session.remove()
                self.assertTrue(NEW_COLUMNS <= columns()[0])

                # ...and restores the old schema (and the old CHECKs) otherwise.
                run("SET session_replication_role = replica")
                run("UPDATE va_death_register SET pii_sealed = NULL WHERE unique_id = 'U4'")
                run("DELETE FROM va_death_register WHERE unique_id = 'U4'")
                db.session.commit()
                db.session.remove()
                alembic_downgrade(revision=PREVIOUS_HEAD)
                db.session.remove()
                register_columns, audit_columns = columns()
                self.assertFalse(NEW_COLUMNS & register_columns)
                self.assertFalse({"changes_dek_wrapped", "changes_key_id"} & audit_columns)
                checks = {
                    row.conname: row.condef for row in run(
                        "SELECT conname, pg_get_constraintdef(oid) AS condef FROM pg_constraint "
                        "WHERE conrelid = 'va_death_register'::regclass AND contype = 'c'"
                    )
                }
                self.assertIn("deceased_name IS NOT NULL", checks["ck_va_death_register_identity"])
                self.assertNotIn("has_location", checks["ck_va_death_register_location_all_or_none"])
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertTrue(NEW_COLUMNS <= columns()[0])
                db.engine.dispose()
        finally:
            _drop_database()


class DowngradeGuardMessageTest(unittest.TestCase):
    def test_refuses_while_rows_are_sealed_and_says_why(self):
        import importlib.util
        import pathlib
        from unittest import mock

        path = (
            pathlib.Path(__file__).resolve().parents[2]
            / "migrations" / "versions" / "e5a2c7b9d3f1_add_register_pii_columns.py"
        )
        spec = importlib.util.spec_from_file_location("register_pii_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with mock.patch.object(module, "op") as op:
            op.get_bind.return_value.execute.return_value.scalar.return_value = 2
            with self.assertRaises(RuntimeError) as raised:
                module.downgrade()
        self.assertIn("sealed personal data", str(raised.exception))
        self.assertFalse(op.drop_column.called)


if __name__ == "__main__":
    unittest.main()
