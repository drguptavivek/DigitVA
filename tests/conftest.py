"""Pytest session configuration for DigitVA tests.

Schema lifecycle (session-scoped, not per-class):
  - pytest_sessionstart: create app, create schema once for the whole session
  - pytest_sessionfinish: drop schema, dispose engine

Per-class setup (BaseTestCase.setUpClass) re-uses the session schema and
only re-seeds base fixtures.  No drop_all/create_all per class — that was
the main source of swap pressure on resource-constrained machines.

Per-test isolation is still via savepoint rollback (see base.py setUp/tearDown).
"""
import pytest
import sqlalchemy as sa


def pytest_configure(config):
    """Terminate stale connections to the test database before collection."""
    from config import TestConfig

    url = TestConfig.SQLALCHEMY_DATABASE_URI
    if not url or "test" not in str(url):
        return

    try:
        engine = sa.create_engine(url, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "  AND pid <> pg_backend_pid()"
                )
            )
        engine.dispose()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Session-scoped schema: create once, drop once
# ---------------------------------------------------------------------------

_session_app = None
_session_ctx = None


def get_session_app():
    """Return the session-scoped Flask app created by pytest_sessionstart."""
    return _session_app


def pytest_sessionstart(session):
    """Create the test schema once for the entire pytest session."""
    global _session_app, _session_ctx

    from config import TestConfig
    from sqlalchemy.exc import ProgrammingError
    from app import create_app, db

    _session_app = create_app(TestConfig)
    _session_ctx = _session_app.app_context()
    _session_ctx.push()

    # Drop materialized views that block drop_all
    for mv in (
        "va_submission_cod_detail_mv",
        "va_submission_analytics_demographics_mv",
        "va_submission_analytics_core_mv",
        "va_submission_analytics_mv",
    ):
        db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
    db.session.commit()

    # Ensure named enums exist before create_all
    from app.models import VaStatuses, VaAllocation, VaUsernotesFor, VaAccessRoles, VaAccessScopeTypes

    enum_defs = {
        "status_enum": [m.value for m in VaStatuses],
        "allocation_enum": [m.value for m in VaAllocation],
        "usernote_enum": [m.value for m in VaUsernotesFor],
        "access_role_enum": [m.value for m in VaAccessRoles],
        "access_scope_enum": [m.value for m in VaAccessScopeTypes],
    }
    for table in db.Model.metadata.tables.values():
        for column in table.columns:
            col_type = getattr(column, "type", None)
            if isinstance(col_type, sa.Enum) and col_type.name in enum_defs:
                col_type.create_type = False

    for enum_name, values in enum_defs.items():
        quoted = ", ".join(f"'{v}'" for v in values)
        db.session.execute(sa.text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_type t
                    JOIN pg_namespace n ON n.oid = t.typnamespace
                    WHERE t.typname = '{enum_name}' AND n.nspname = current_schema()
                ) THEN
                    CREATE TYPE {enum_name} AS ENUM ({quoted});
                END IF;
            END $$;
            """
        ))
    db.session.commit()

    try:
        db.drop_all()
    except ProgrammingError:
        db.session.rollback()

    db.create_all()
    db.session.commit()


def pytest_sessionfinish(session, exitstatus):
    """Drop the test schema after the entire pytest session."""
    global _session_app, _session_ctx

    if _session_app is None:
        return

    from sqlalchemy.exc import ProgrammingError
    from app import db

    db.session.remove()

    for mv in (
        "va_submission_cod_detail_mv",
        "va_submission_analytics_demographics_mv",
        "va_submission_analytics_core_mv",
        "va_submission_analytics_mv",
    ):
        try:
            db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    try:
        db.drop_all()
    except ProgrammingError:
        db.session.rollback()

    db.engine.dispose()

    if _session_ctx:
        _session_ctx.pop()
