"""Pytest session configuration for DigitVA tests.

Runs before any test class is collected so that stale connections from
previous killed test runs cannot block the DROP TABLE / CREATE TABLE DDL
that setUpClass and tearDownClass rely on.
"""
import pytest
import sqlalchemy as sa


def pytest_configure(config):
    """Terminate all idle/aborted connections to the test database before
    the test session starts.  This prevents accumulated stale connections
    (e.g. from Ctrl-C kills) from holding schema locks that block DROP TABLE.
    """
    from config import TestConfig

    url = TestConfig.SQLALCHEMY_DATABASE_URI
    if not url or "test" not in str(url):
        # Safety check: never terminate connections on a non-test database.
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
        pass  # best-effort; do not abort collection if this fails
