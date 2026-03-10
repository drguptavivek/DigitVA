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
    cache_path = os.path.join(
        current_app.config.get("APP_RESOURCE"), "pyodk", "odk_cache.toml"
    )

    if project_id:
        client = _client_from_db(project_id, cache_path)
        if client is not None:
            return client

    return _client_from_toml(cache_path)


def _client_from_db(project_id: str, cache_path: str) -> Client | None:
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

        return _build_client(conn.base_url, username, password, cache_path)

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
    base_url: str, username: str, password: str, cache_path: str
) -> Client:
    """Build a pyODK Client from credentials without a persistent config file.

    Uses pyodk's internal objectify_config() to construct the Config object
    in memory, then injects it onto the Client instance after the object is
    created — bypassing the file-read in Client.__init__ via a temp file that
    exists only for the duration of construction.

    Falls back to a tempfile-only approach if the internal API changes.
    """
    import tempfile
    import toml
    from pyodk._utils import config as pyodk_config

    config_dict = {
        "central": {
            "base_url": base_url,
            "username": username,
            "password": password,
        }
    }

    # Write a short-lived temp file (owner-read-only) so Client.__init__ can
    # parse it. We delete it immediately after the Client is constructed; pyodk
    # stores the parsed Config in memory and never re-reads the file.
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
    try:
        toml.dump(config_dict, tmp)
        tmp.flush()
        os.chmod(tmp.name, 0o600)
        tmp.close()
        client = Client(config_path=tmp.name, cache_path=cache_path)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    # Overwrite the config object with one built directly from the dict so that
    # the in-memory representation is canonical and no file path is retained.
    try:
        client.config = pyodk_config.objectify_config(config_dict)
    except Exception:
        pass  # already constructed from the correct values above

    return client
