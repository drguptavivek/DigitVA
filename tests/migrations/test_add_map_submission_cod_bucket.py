"""``d3c8e5a1f7b4`` adds ``map_submission_cod_bucket`` and the scheme stamp.

Builds a throwaway database from the migration chain, upgrades to the revision,
checks the table, its key, its foreign keys' delete rules and its indexes, and
the nullable ``mas_cod_bucket_schemes.reporting_rows_built_at``; then downgrades
one step and checks both are gone. Steps back with ``-1`` so re-chaining the
revision onto another parent does not touch this test.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \\
        tests/migrations/test_add_map_submission_cod_bucket.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_codmat_mig"
REVISION = "d3c8e5a1f7b4"
TABLE = "map_submission_cod_bucket"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class CodBucketRowsMigrationConfig(TestConfig):
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


class CodBucketRowsMigrationTest(unittest.TestCase):
    def test_upgrade_creates_the_table_and_stamp_and_downgrade_drops_them(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(CodBucketRowsMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                self.assertIn(TABLE, inspector.get_table_names())
                stamp = {c["name"]: c for c in inspector.get_columns("mas_cod_bucket_schemes")}
                self.assertTrue(stamp["reporting_rows_built_at"]["nullable"])

                columns = {c["name"]: c for c in inspector.get_columns(TABLE)}
                self.assertTrue(columns["node_id"]["nullable"])
                self.assertFalse(columns["is_reportable"]["nullable"])
                self.assertIn("event_date", columns)
                self.assertEqual(
                    inspector.get_pk_constraint(TABLE)["constrained_columns"],
                    ["va_sid", "scheme_id", "age_band_id"],
                )
                rules = {
                    fk["referred_table"]: fk["options"].get("ondelete")
                    for fk in inspector.get_foreign_keys(TABLE)
                }
                self.assertEqual(rules, {
                    "va_submissions": "CASCADE",
                    "mas_cod_bucket_schemes": "CASCADE",
                    "mas_cod_bucket_scheme_age_bands": "CASCADE",
                    "mas_cod_bucket_nodes": "SET NULL",
                })
                indexes = {
                    row.indexname: row.indexdef
                    for row in db.session.execute(
                        sa.text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = :t"),
                        {"t": TABLE},
                    )
                }
                self.assertIn("WHERE is_reportable", indexes["ix_map_submission_cod_bucket_report"])
                self.assertIn("INCLUDE", indexes["ix_map_submission_cod_bucket_report"])
                self.assertIn("WHERE is_reportable", indexes["ix_map_submission_cod_bucket_unit"])
                self.assertIn("ix_map_submission_cod_bucket_scheme_band", indexes)
                self.assertIn("ix_map_submission_cod_bucket_node", indexes)
                db.session.remove()

                alembic_downgrade(revision="-1")
                inspector = sa.inspect(db.engine)
                self.assertNotIn(TABLE, inspector.get_table_names())
                self.assertNotIn(
                    "reporting_rows_built_at",
                    {c["name"] for c in inspector.get_columns("mas_cod_bucket_schemes")},
                )
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
