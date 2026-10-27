"""``f3d9b5c7a2e4`` adds ``mas_consent_notice_versions.source`` and the bundle identity.

Builds a throwaway database from the migration chain, upgrades to the
revision, checks the columns, the check constraint and the two partial unique
keys (project notices by version and language, standalone texts by hash),
then downgrades one step and checks the original unique key is back.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_consent_notice_source.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_notice_source_mig"
REVISION = "f3d9b5c7a2e4"
TABLE = "mas_consent_notice_versions"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class NoticeSourceMigrationConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(MIGRATION_DB_NAME).render_as_string(hide_password=False)


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
        f"WHERE datname = '{MIGRATION_DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"',
    )


def _indexes(db):
    return {i["name"]: i for i in sa.inspect(db.engine).get_indexes(TABLE)}


class NoticeSourceMigrationTest(unittest.TestCase):
    def test_upgrade_adds_source_and_partial_keys_and_downgrade_restores_the_key(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(NoticeSourceMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                columns = {c["name"]: c for c in inspector.get_columns(TABLE)}
                self.assertFalse(columns["source"]["nullable"])
                self.assertIn("project", columns["source"]["default"])
                self.assertTrue(columns["bundle_version"]["nullable"])
                self.assertTrue(columns["bundle_sha256"]["nullable"])
                self.assertIn("ck_mas_consent_notice_versions_source",
                              {c["name"] for c in inspector.get_check_constraints(TABLE)})
                self.assertNotIn("uq_mas_consent_notice_versions_project_version_language",
                                 {u["name"] for u in inspector.get_unique_constraints(TABLE)})
                indexes = _indexes(db)
                project = indexes["uq_mas_consent_notice_versions_project_notice"]
                standalone = indexes["uq_mas_consent_notice_versions_standalone_text"]
                self.assertEqual((project["column_names"], project["unique"]),
                                 (["project_id", "version", "language"], True))
                self.assertEqual((standalone["column_names"], standalone["unique"]),
                                 (["project_id", "language", "text_sha256"], True))
                self.assertIn("project", project["dialect_options"]["postgresql_where"])
                self.assertIn("standalone", standalone["dialect_options"]["postgresql_where"])
                db.session.remove()

                alembic_downgrade(revision="-1")
                inspector = sa.inspect(db.engine)
                self.assertNotIn("source", {c["name"] for c in inspector.get_columns(TABLE)})
                self.assertIn("uq_mas_consent_notice_versions_project_version_language",
                              {u["name"] for u in inspector.get_unique_constraints(TABLE)})
                self.assertNotIn("uq_mas_consent_notice_versions_standalone_text", _indexes(db))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
