"""
pyODK client setup.

Looks up the ODK connection for the given project from the database,
decrypts the credentials, and returns a ready-to-use pyodk Client.

Falls back to the legacy TOML file if no database connection is configured
for the project (backward compatibility during migration).
"""

import os
from flask import current_app
from pyodk.client import Client


def va_odk_clientsetup(project_id: str | None = None) -> Client:
    """Return an authenticated pyODK Client for *project_id*.

    Resolution order:
    1. DB-configured connection mapped to project_id (preferred).
    2. Legacy odk_config.toml (fallback for unmapped projects).

    Raises Exception on failure.
    """
    pyodk_dir = os.path.join(current_app.config.get("APP_RESOURCE"), "pyodk")

    if project_id:
        client = _client_from_db(project_id, pyodk_dir)
        if client is not None:
            return client

    # Legacy fallback uses a shared cache (single TOML connection).
    cache_path = os.path.join(pyodk_dir, "odk_cache.toml")
    return _client_from_toml(cache_path)


def _client_from_db(project_id: str, pyodk_dir: str) -> Client | None:
    """Return a Client built from the DB-stored connection, or None if not found."""
    try:
        import sqlalchemy as sa
        from app import db
        from app.models.map_project_odk import MapProjectOdk
        from app.models.mas_odk_connections import MasOdkConnections
        from app.models.va_selectives import VaStatuses
        from app.utils.credential_crypto import decrypt_credential, get_odk_pepper

        row = db.session.scalar(
            sa.select(MapProjectOdk).where(MapProjectOdk.project_id == project_id)
        )
        if row is None:
            return None

        conn = db.session.get(MasOdkConnections, row.connection_id)
        if conn is None or conn.status != VaStatuses.active:
            return None

        pepper = get_odk_pepper()
        username = decrypt_credential(conn.username_enc, conn.username_salt, pepper)
        password = decrypt_credential(conn.password_enc, conn.password_salt, pepper)

        # Each connection gets its own cache file so concurrent calls to
        # different ODK servers never overwrite each other's auth token.
        cache_path = os.path.join(
            pyodk_dir, f"odk_cache_{conn.connection_id}.toml"
        )
        return _build_client(conn.base_url, username, password, pyodk_dir, cache_path)

    except Exception as exc:
        raise Exception(
            f"pyODK DB client setup failed for project '{project_id}': {exc}"
        ) from exc


def _client_from_toml(cache_path: str) -> Client:
    """Return a Client built from the legacy TOML config file."""
    config_path = os.path.join(
        current_app.config.get("APP_RESOURCE"), "pyodk", "odk_config.toml"
    )
    try:
        return Client(config_path=config_path, cache_path=cache_path)
    except Exception as exc:
        raise Exception(f"pyODK TOML client setup failed: {exc}") from exc


def _build_client(
    base_url: str, username: str, password: str, pyodk_dir: str, cache_path: str
) -> Client:
    """Build a pyODK Client from credentials using an explicit Session.

    Client.__init__ unconditionally calls config.read_config() even when a
    session is supplied — the config is parsed but not used for API calls when
    session= is provided. We point config_path at a shared stub file (no
    credentials) so no sensitive data is written to disk.

    Each caller supplies a connection-specific cache_path so concurrent calls
    to different ODK servers never overwrite each other's auth token.
    """
    import toml
    from pyodk._utils.session import Session as PyOdkSession

    # Stub config — placeholder values, never used for API calls.
    # Shared across all DB-backed connections; contains no credentials.
    stub_path = os.path.join(pyodk_dir, "odk_stub_config.toml")
    if not os.path.exists(stub_path):
        os.makedirs(pyodk_dir, exist_ok=True)
        with open(stub_path, "w") as f:
            toml.dump(
                {"central": {"base_url": "https://stub", "username": "stub", "password": "stub"}},
                f,
            )
        os.chmod(stub_path, 0o600)

    session = PyOdkSession(
        base_url=base_url,
        api_version="v1",
        username=username,
        password=password,
        cache_path=cache_path,
    )
    return Client(config_path=stub_path, session=session)
