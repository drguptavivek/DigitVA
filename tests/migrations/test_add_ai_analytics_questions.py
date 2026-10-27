"""``a9e4c7f2b3d6`` adds the AI analytics questions schema (digitva-qwvt).

Builds a throwaway database from the migration chain, upgrades to the
revision, checks the reader role, ``digitva_ai_run`` and both tables, runs the
upgrade's role DDL a second time (another database or worker already made
the role), then downgrades one step: tables and function go, the
cluster-wide role (and its temp_file_limit grant) stays.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_ai_analytics_questions.py -q
"""
import importlib.util
import pathlib
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_ai_mig"
REVISION = "a9e4c7f2b3d6"
TABLES = ("va_ai_saved_queries", "va_ai_query_audit_log")


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class AiQuestionsMigrationConfig(TestConfig):
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


def _migration_module():
    path = next(pathlib.Path(__file__).resolve().parents[2].glob(f"migrations/versions/{REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location("ai_questions_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AiQuestionsMigrationTest(unittest.TestCase):
    def test_upgrade_creates_role_function_and_tables_and_downgrade_keeps_the_role(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(AiQuestionsMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                for table in TABLES:
                    self.assertIn(table, inspector.get_table_names())
                self.assertEqual(
                    {fk["referred_table"] for table in TABLES for fk in inspector.get_foreign_keys(table)},
                    {"va_users"},
                )
                index_columns = {
                    ix["name"]: ix["column_names"] for ix in inspector.get_indexes("va_ai_query_audit_log")
                }
                self.assertEqual(
                    index_columns["ix_va_ai_query_audit_log_user_id_created_at"], ["user_id", "created_at"]
                )

                audit_columns = {c["name"] for c in inspector.get_columns("va_ai_query_audit_log")}
                self.assertTrue({"provider", "model"} <= audit_columns)

                with db.engine.connect() as conn:
                    function = conn.execute(sa.text(
                        "SELECT proowner::regrole::text, prosecdef, proconfig FROM pg_proc"
                        " WHERE proname = 'digitva_ai_run'"
                    )).one()
                    self.assertEqual(tuple(function[:2]), ("digitva_ai_reader", True))
                    self.assertIn("work_mem=16MB", function[2])
                    self.assertIn("temp_file_limit=256MB", function[2])
                    self.assertTrue(conn.execute(sa.text(
                        "SELECT has_parameter_privilege('digitva_ai_reader', 'temp_file_limit', 'SET')"
                    )).scalar_one())
                    self.assertTrue(conn.execute(sa.text(
                        "SELECT pg_has_role(current_user, 'digitva_ai_reader', 'MEMBER')"
                    )).scalar_one())
                    self.assertFalse(conn.execute(sa.text(
                        "SELECT rolcanlogin FROM pg_roles WHERE rolname = 'digitva_ai_reader'"
                    )).scalar_one())
                    # A second run (another database, a parallel worker) is a no-op.
                    conn.execute(sa.text(_migration_module().READER_SETUP_SQL))
                    conn.rollback()
                db.session.remove()

                alembic_downgrade(revision="-1")
                names = sa.inspect(db.engine).get_table_names()
                for table in TABLES:
                    self.assertNotIn(table, names)
                with db.engine.connect() as conn:
                    self.assertIsNone(conn.execute(sa.text(
                        "SELECT to_regprocedure('digitva_ai_run(text, integer)')"
                    )).scalar_one())
                    self.assertEqual(conn.execute(sa.text(
                        "SELECT count(*) FROM pg_roles WHERE rolname = 'digitva_ai_reader'"
                    )).scalar_one(), 1)
                    self.assertTrue(conn.execute(sa.text(
                        "SELECT has_parameter_privilege('digitva_ai_reader', 'temp_file_limit', 'SET')"
                    )).scalar_one())
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()

    def test_upgrade_without_privileges_skips_the_reader_and_keeps_the_tables(self):
        """A non-superuser app user (staging): no error, tables yes, function no."""
        from app import db
        from tests.base import create_app_without_celery_takeover

        plain = "ai_mig_plain"
        _drop_database()
        _admin_execute(f"DROP ROLE IF EXISTS {plain}")
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(AiQuestionsMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision="c5e8a2f4b7d1")
                db.session.remove()
                db.engine.dispose()
            owner = sa.engine.make_url(AiQuestionsMigrationConfig.SQLALCHEMY_DATABASE_URI).username
            _admin_execute(f"CREATE ROLE {plain} LOGIN PASSWORD 'plain'")
            engine = sa.create_engine(
                _server_url(MIGRATION_DB_NAME), isolation_level="AUTOCOMMIT"
            )
            with engine.connect() as conn:
                # REASSIGN OWNED refuses the owner's system-required objects.
                conn.execute(sa.text(f"GRANT CREATE ON SCHEMA public TO {plain}"))
                conn.execute(sa.text(
                    "DO $$ DECLARE r record; BEGIN FOR r IN SELECT c.relname, c.relkind FROM pg_class c"
                    " JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public'"
                    " AND c.relkind IN ('r','m','v') AND c.relowner = (SELECT oid FROM pg_roles"
                    f" WHERE rolname = '{owner}') LOOP EXECUTE format('ALTER %s %I OWNER TO {plain}',"
                    " CASE r.relkind WHEN 'm' THEN 'MATERIALIZED VIEW'"
                    " WHEN 'v' THEN 'VIEW' ELSE 'TABLE' END, r.relname); END LOOP; END $$"
                ))
            engine.dispose()

            class PlainConfig(TestConfig):
                SQLALCHEMY_DATABASE_URI = (
                    _server_url(MIGRATION_DB_NAME).set(username=plain, password="plain")
                    .render_as_string(hide_password=False)
                )

            app = create_app_without_celery_takeover(PlainConfig)
            with app.app_context():
                self.assertFalse(db.session.execute(sa.text(
                    "SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar_one())
                alembic_upgrade(revision=REVISION)
                db.session.remove()
                names = sa.inspect(db.engine).get_table_names()
                for table in TABLES:
                    self.assertIn(table, names)
                with db.engine.connect() as conn:
                    self.assertIsNone(conn.execute(sa.text(
                        "SELECT to_regprocedure('digitva_ai_run(text, integer)')"
                    )).scalar_one())
                db.session.remove()
                alembic_downgrade(revision="-1")
                for table in TABLES:
                    self.assertNotIn(table, sa.inspect(db.engine).get_table_names())
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()
            _admin_execute(f"DROP ROLE IF EXISTS {plain}")


if __name__ == "__main__":
    unittest.main()
