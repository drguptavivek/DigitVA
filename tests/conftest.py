"""Pytest session configuration for DigitVA tests.

Schema lifecycle (session-scoped, not per-class):
  - pytest_sessionstart: create app, create schema once for the whole session
  - pytest_sessionfinish: drop schema, dispose engine

Per-class setup (BaseTestCase.setUpClass) re-uses the session schema and
only re-seeds base fixtures.  No drop_all/create_all per class — that was
the main source of swap pressure on resource-constrained machines.

Per-test isolation uses an external transaction: each test gets its own
connection with an outer transaction that is rolled back in tearDown, and the
scoped session joins it via SAVEPOINT (see base.py setUp/tearDown).
"""
import os
import re

import pytest
import sqlalchemy as sa

# Arbitrary constant: serialises CREATE DATABASE across xdist workers.
_CREATE_DB_LOCK_KEY = 74_201_901


def _is_xdist_controller(config):
    """True in the process that hands tests to xdist workers (-n N, N > 0).

    The controller runs no tests, so it must not create, clean or drop any
    database: the workers own theirs. Without xdist, or with -n0, this is
    False and the session runs exactly as a serial run always has."""
    return not hasattr(config, "workerinput") and bool(
        getattr(config.option, "numprocesses", None)
    )


def _use_worker_database(worker_id):
    """Point TestConfig at <base>_<worker_id>, creating that database if absent.

    Each xdist worker gets its own database so the session schema, the
    stale-connection cleanup and drop_all never cross workers. The migration
    tests derive their throwaway URLs from TestConfig, so they follow."""
    from config import TestConfig

    base = sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI)
    name = f"{base.database}_{worker_id}"
    # CREATE DATABASE cannot bind an identifier; allow only a plain name.
    if not re.fullmatch(r"[A-Za-z0-9_]+", name) or "test" not in name:
        raise pytest.UsageError(f"refusing per-worker test database name {name!r}")

    maintenance = sa.create_engine(
        base.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with maintenance.connect() as conn:
            conn.execute(sa.text("SELECT pg_advisory_lock(:k)"), {"k": _CREATE_DB_LOCK_KEY})
            try:
                exists = conn.execute(
                    sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
                ).scalar()
                if not exists:
                    conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
            finally:
                conn.execute(
                    sa.text("SELECT pg_advisory_unlock(:k)"), {"k": _CREATE_DB_LOCK_KEY}
                )
    finally:
        maintenance.dispose()

    url = base.set(database=name).render_as_string(hide_password=False)
    TestConfig.SQLALCHEMY_DATABASE_URI = url
    TestConfig.CELERY = {**TestConfig.CELERY, "beat_dburi": url}
    os.environ["TEST_DATABASE_URL"] = url


_WIRE_SAFE = (str, int, float, bool, type(None))


@pytest.hookimpl(wrapper=True)
def pytest_report_to_serializable(report):
    """Make subTest(...) parameters serialisable for xdist.

    A worker ships each subtest report to the controller through execnet,
    which refuses enums, UUIDs and Decimals; tests pass those as subTest
    params freely. Only the copy on the wire changes (to its repr)."""
    data = yield
    context = (data or {}).get("_subtest.context")
    if context and context.get("kwargs"):
        context["kwargs"] = {
            key: value if isinstance(value, _WIRE_SAFE) else repr(value)
            for key, value in context["kwargs"].items()
        }
    return data


def pytest_configure(config):
    """Terminate stale connections to the test database before collection."""
    if _is_xdist_controller(config):
        # xdist's default "load" splits one file across workers, but each
        # migration test module creates and drops a fixed-name database, so
        # a file must stay on one worker. loadfile also keeps a class's
        # setUpClass fixtures from being rebuilt on every worker.
        if config.option.dist == "load":
            config.option.dist = "loadfile"
        # A crashed worker (usually the container's memory limit) must fail
        # the run: by default xdist respawns workers and can exit 0 with
        # "no tests ran".
        if config.option.maxworkerrestart is None:
            config.option.maxworkerrestart = 0
        return

    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    if worker_id:
        _use_worker_database(worker_id)

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

    if _is_xdist_controller(session.config):
        return

    from config import TestConfig
    from sqlalchemy.exc import ProgrammingError
    from app import create_app, db

    _session_app = create_app(TestConfig)
    _session_ctx = _session_app.app_context()
    _session_ctx.push()

    # Swap in the session class that honours an explicitly bound connection, so
    # BaseTestCase.setUp can join the scoped session to a per-test transaction.
    from tests.base import install_external_transaction_session

    install_external_transaction_session()

    # Drop materialized views that block drop_all
    for mv in (
        "va_submission_cod_detail_mv",
        "va_submission_analytics_demographics_mv",
        "va_submission_analytics_core_mv",
        "va_submission_analytics_mv",
    ):
        db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
    db.session.commit()

    # va_icd_codes carries a trigram index (see migration d0e1f2a3b4c6), so the
    # extension must exist before create_all builds the schema.
    db.session.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    # mas_org_unit.path is an ltree column (see migration c8d2e4f6a1b3).
    db.session.execute(sa.text("CREATE EXTENSION IF NOT EXISTS ltree"))
    # The web intake death-register number sequence is standalone DDL created by
    # migration e5f6a7b8c9d1; create_all/drop_all neither create nor drop it.
    from app.models.va_web_intake import DEATH_NUMBER_SEQUENCE

    db.session.execute(
        sa.text(f"CREATE SEQUENCE IF NOT EXISTS {DEATH_NUMBER_SEQUENCE} START 1")
    )
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


@pytest.fixture(autouse=True)
def _no_real_icd11_titles():
    """Coding screens title their quick-use choices from the local WHO ICD-11 API.
    No test may reach that container or the shared cache: WHO answers nothing,
    so the page shows codes alone. Tests that assert titles patch the lookup again."""
    from unittest import mock

    class _NoCache:
        def get(self, key):
            return None

        def set(self, key, value, timeout=None):
            return None

    with mock.patch("app.services.icd11_titles.cache", _NoCache()), mock.patch(
        "app.services.icd11_titles.get_icd11_codeinfo", return_value=None
    ):
        yield


@pytest.fixture(autouse=True)
def _no_real_smartva_queue():
    """A completed interview queues SmartVA after commit; no test may reach
    the broker the dev worker also reads. Tests that assert the queueing
    patch ``.delay`` again inside the test."""
    from unittest import mock

    from app.tasks.sync_tasks import run_smartva_for_submission

    # Patch the task behind the shared_task proxy: the proxy resolves through
    # the current Celery app, which can differ at teardown (class teardown pops
    # the app context first), so a patch on the proxy cannot be undone.
    with mock.patch.object(run_smartva_for_submission._get_current_object(), "delay"):
        yield
