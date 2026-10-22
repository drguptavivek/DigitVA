"""``a7d3e9b2c4f6`` adds ``va_bundle_ingests`` and ``map_bundle_records``
(bead digitva-gb8w.2).

Builds a throwaway database at the previous head, upgrades, checks the
tables, the unique ``bundle_id`` and the indexes, refuses a downgrade while
an ingest is recorded, then downgrades and checks they are gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_bundle_ingests.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

DB_NAME = "minerva_test_bundle_ingests_mig"
PREVIOUS_HEAD = "f3a9c6d2e1b7"
REVISION = "a7d3e9b2c4f6"
TABLES = {"va_bundle_ingests", "map_bundle_records"}
_IDS = {
    "user": "00000000-0000-4000-8000-000000000001",
    "device": "00000000-0000-4000-8000-0000000000aa",
    "config": "00000000-0000-4000-8000-0000000000bb",
    "bundle": "00000000-0000-4000-8000-0000000000cc",
}


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class BundleIngestsConfig(TestConfig):
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


_SEED = (
    "INSERT INTO va_users (user_id, name, email, vacode_language, timezone, vacode_formcount, permission,"
    " password, landing_page, pw_reset_t_and_c, email_verified, user_status, user_created_at, user_updated_at,"
    " auth_session_version) VALUES (:user, 'User', 'u@mig.test', '{}', 'Asia/Kolkata', 0, '{}', 'x', 'home',"
    " false, true, 'active', now(), now(), 0)",
    "INSERT INTO va_project_master (project_id, project_code, project_name, project_nickname, project_status,"
    " project_registered_at, project_updated_at) VALUES ('MIG01', 'MIG01', 'Migration', 'MIG01', 'active',"
    " now(), now())",
    "INSERT INTO auth_devices (device_id, project_id, name, platform, secret_hash, enrolled_at,"
    " revoked_compromised) VALUES (:device, 'MIG01', 'Station', 'desktop', repeat('a', 64), now(), false)",
    "INSERT INTO auth_station_configs (config_id, device_id, issued_at, expires_at, issued_by, signed_text,"
    " text_sha256) VALUES (:config, :device, now(), now(), :user, 'x', repeat('0', 64))",
)
_INGEST = (
    "INSERT INTO va_bundle_ingests (bundle_id, device_id, project_id, bundle_seq, manifest_sha256,"
    " station_config_id, kem_key_id, uploader_user_id, channel, created_at, received_at, status)"
    " VALUES (:bundle, :device, 'MIG01', 1, repeat('0', 64), :config, 'k1', :user, 'browser', now(), now(),"
    " 'processed')"
)


class BundleIngestsMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_adds_and_downgrade_removes(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(BundleIngestsConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                self.assertTrue(TABLES <= set(inspector.get_table_names()))
                self.assertEqual(inspector.get_pk_constraint("va_bundle_ingests")["constrained_columns"],
                                 ["bundle_id"])
                self.assertTrue({"ix_va_bundle_ingests_device_received", "ix_va_bundle_ingests_device_seq"}
                                <= {i["name"] for i in inspector.get_indexes("va_bundle_ingests")})
                self.assertIn("ix_map_bundle_records_death_applied",
                              {i["name"] for i in inspector.get_indexes("map_bundle_records")})
                for statement in (*_SEED, _INGEST):
                    db.session.execute(sa.text(statement), _IDS)
                db.session.commit()
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.execute(sa.text(_INGEST), _IDS)
                db.session.rollback()
                db.session.remove()
                # flask_migrate turns the migration's RuntimeError into SystemExit.
                with self.assertRaises(SystemExit):
                    alembic_downgrade(revision=PREVIOUS_HEAD)
                db.session.remove()
                db.session.execute(sa.text("DELETE FROM va_bundle_ingests"))
                db.session.commit()
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertFalse(TABLES & set(sa.inspect(db.engine).get_table_names()))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()
