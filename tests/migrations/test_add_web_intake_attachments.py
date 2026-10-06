"""``g4k8p2t6x1b5`` adds va_web_intake_attachments (digitva-ej1).

Builds a throwaway database at the previous head, upgrades, and checks the
table's shape: the (draft, client attachment id) primary key that makes an
upload idempotent, the foreign key to the draft and the unique storage name.
Then downgrades and checks the table is gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_web_intake_attachments.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_ejone_mig"

PREVIOUS_HEAD = "g3k7n1s5v9y2"
REVISION = "g4k8p2t6x1b5"
TABLE = "va_web_intake_attachments"
UNIQUE_INDEX = "uq_va_web_intake_attachments_storage_name"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class AttachmentsMigrationConfig(TestConfig):
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


class WebIntakeAttachmentsMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_table_shape_and_downgrade(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(AttachmentsMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self.assertNotIn(TABLE, sa.inspect(db.engine).get_table_names())

                alembic_upgrade(revision=REVISION)
                db.session.remove()
                inspector = sa.inspect(db.engine)
                self.assertIn(TABLE, inspector.get_table_names())
                self.assertEqual(
                    inspector.get_pk_constraint(TABLE)["constrained_columns"],
                    ["draft_id", "client_attachment_id"],
                )
                fks = inspector.get_foreign_keys(TABLE)
                self.assertEqual([(fk["referred_table"], fk["constrained_columns"]) for fk in fks],
                                 [("va_web_intake_drafts", ["draft_id"])])
                unique = {i["name"]: i for i in inspector.get_indexes(TABLE)}
                self.assertTrue(unique[UNIQUE_INDEX]["unique"])
                self.assertEqual(unique[UNIQUE_INDEX]["column_names"], ["storage_name"])
                not_null = {c["name"] for c in inspector.get_columns(TABLE) if not c["nullable"]}
                self.assertEqual(
                    not_null,
                    {"draft_id", "client_attachment_id", "filename", "storage_name", "store_state",
                     "mime_type", "size_bytes", "sha256", "created_at"},
                )

                alembic_downgrade(revision=PREVIOUS_HEAD)
                db.session.remove()
                self.assertNotIn(TABLE, sa.inspect(db.engine).get_table_names())
                db.engine.dispose()
        finally:
            _drop_database()
