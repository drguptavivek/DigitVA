"""Redis cache of a user's ResolvedGrants across requests (digitva-5hmc).

Policy: docs/policy/access-control-model.md, "Redis cache for grant
lookups". The cache is an accelerator, never the authority:

- Key ``<prefix>g:<user_id>:<global version>:<user version>``, 5-minute TTL
  (``AUTHZ_GRANT_CACHE_TTL_SECONDS``). Both versions are read *before* the
  database load and the entry is written under them, so a bump that lands
  during the load leaves the entry unreachable, never stale.
- ``<prefix>uv:<user_id>`` is bumped by any write to that user's grants, a
  status change or a session-version change (a factor or session reset):
  every ORM write is seen by the session hooks below, and ``invalidate``
  covers the Core statements. ``<prefix>gv`` is bumped by anything that can
  change many users' reach: a project's status, coding-scope settings or
  demo-training switch, a project-site, an org level or unit, a form's
  status (demo-training needs an active form). Bumps run after the commit,
  so no reader can repopulate a new version with pre-commit rows.
- The entry holds roles, scopes, project ids, unit depths and paths (unit
  codes) and project settings: no name, email, phone or submission data.
- Redis unavailable, or no Redis backend: the database answers that request
  (never more permissive). An entry that fails to parse is discarded. A
  bump lost while Redis is down is covered by the TTL.
- Every key carries an expiry (the version keys one day, see
  ``_VERSION_TTL_SECONDS``): Redis runs ``volatile-lru``, which only evicts
  keys that have one, so a TTL-less key here would be unevictable clutter.

Uses the Flask-Caching Redis client (``CACHE_REDIS_URL``) directly, with
JSON values: Flask-Caching would pickle them, and a cache entry is not
trusted enough to unpickle.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid

from flask import current_app, has_app_context
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models import (
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaUserAccessGrants,
    VaUsers,
)
from app.services.authz.grants import Grant, ProjectSettings, ResolvedGrants

log = logging.getLogger(__name__)

_FORMAT = 2
_PENDING_KEY = "digitva.authz.pending_bumps"

# Columns whose change can alter what a user's grants resolve to.
_USER_COLUMNS = ("user_status", "auth_session_version")
_GLOBAL_COLUMNS = {
    VaProjectMaster: ("project_status", "coding_scope_level_id",
                      "above_scope_coding_mode", "demo_training_enabled",
                      "self_coding_enabled", "web_intake_mode"),
    VaProjectSites: ("project_site_status", "project_id", "site_id"),
    VaForms: ("form_status", "project_id"),
    MasOrgUnit: None,   # any column: path, parent, level, is_active, project
    MasOrgLevel: None,
}


# A version key that expires or is evicted is re-seeded with a fresh random
# token (entry_key), so the expiry costs one database read, never a stale hit.
_VERSION_TTL_SECONDS = 24 * 60 * 60


def _client():
    """The Redis client, or None when the cache is off or not Redis."""
    if not has_app_context() or not current_app.config.get("AUTHZ_GRANT_CACHE_ENABLED"):
        return None
    from app import cache

    try:
        return getattr(cache.cache, "_write_client", None)
    except (KeyError, RuntimeError):
        return None


def _prefix() -> str:
    return current_app.config.get("AUTHZ_GRANT_CACHE_PREFIX", "digitva_authz:")


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------

def encode(resolved: ResolvedGrants) -> str:
    return json.dumps({
        "format": _FORMAT,
        "user_id": str(resolved.user_id),
        "is_admin": resolved.is_admin,
        "grants": [
            [g.role.value, g.scope_type.value, g.project_id, g.site_id,
             str(g.project_site_id) if g.project_site_id else None,
             str(g.org_unit_id) if g.org_unit_id else None,
             g.unit_depth, g.unit_path, g.virtual, g.opens_gate]
            for g in resolved.grants
        ],
        "projects": [
            [p.project_id, p.has_tree, p.scope_depth, p.above_mode, p.demo_training,
             p.self_coding]
            for p in resolved.projects.values()
        ],
    }, separators=(",", ":"))


def _text(value, *, optional: bool = True) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError("expected text")
    return value


def _int(value) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("expected an integer")
    return value


def _bool(value) -> bool:
    if not isinstance(value, bool):
        raise ValueError("expected a boolean")
    return value


def _uuid(value) -> uuid.UUID | None:
    return None if value is None else uuid.UUID(_text(value))


def decode(raw, user_id: uuid.UUID) -> ResolvedGrants:
    """The cached ResolvedGrants; ValueError for anything malformed."""
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("format") != _FORMAT:
        raise ValueError("unknown format")
    if _uuid(data["user_id"]) != user_id:
        raise ValueError("entry for another user")
    grants = tuple(
        Grant(
            role=VaAccessRoles(role), scope_type=VaAccessScopeTypes(scope),
            project_id=_text(project_id, optional=False), site_id=_text(site_id),
            project_site_id=_uuid(pair_id), org_unit_id=_uuid(unit_id),
            unit_depth=_int(depth), unit_path=_text(path), virtual=_bool(virtual),
            opens_gate=_bool(opens_gate),
        )
        for role, scope, project_id, site_id, pair_id, unit_id, depth, path, virtual, opens_gate
        in data["grants"]
    )
    projects = {}
    for project_id, has_tree, scope_depth, above_mode, demo, self_coding in data["projects"]:
        projects[_text(project_id, optional=False)] = ProjectSettings(
            project_id=project_id, has_tree=_bool(has_tree), scope_depth=_int(scope_depth),
            above_mode=_text(above_mode, optional=False), demo_training=_bool(demo),
            self_coding=_bool(self_coding),
        )
    return ResolvedGrants(
        user_id=user_id, is_admin=_bool(data["is_admin"]), grants=grants, projects=projects,
    )


# ---------------------------------------------------------------------------
# Read through
# ---------------------------------------------------------------------------

def load(user_id: uuid.UUID, resolve) -> ResolvedGrants:
    """*user_id*'s grants from the cache, else ``resolve(user_id)`` (stored)."""
    client = _client()
    if client is None:
        return resolve(user_id)
    prefix = _prefix()
    try:
        key = entry_key(client, prefix, user_id)
        if key is None:
            return resolve(user_id)
        raw = client.get(key)
    except Exception as exc:  # Redis down or a garbled version: the DB decides
        log.warning("authz grant cache unavailable, reading grants from the database: %s",
                    type(exc).__name__)
        return resolve(user_id)
    if raw is not None:
        try:
            return decode(raw, user_id)
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("authz grant cache entry discarded (unparsable): user=%s %s",
                        user_id, type(exc).__name__)
            _quietly(client.delete, key)
    resolved = resolve(user_id)
    ttl = int(current_app.config.get("AUTHZ_GRANT_CACHE_TTL_SECONDS", 300))
    _quietly(client.set, key, encode(resolved), ex=ttl)
    return resolved


def entry_key(client, prefix: str, user_id) -> str | None:
    """The entry key under the current global and per-user versions. A
    missing version (first use, expired, or evicted) is seeded with
    a fresh random token, never read as 0: a counter that restarted could
    match an older, more permissive entry. None if Redis would not keep one."""
    version_keys = (prefix + "gv", f"{prefix}uv:{user_id}")
    versions = client.mget(*version_keys)
    if None in versions:
        for name, value in zip(version_keys, versions):
            if value is None:
                client.set(name, secrets.token_hex(8), nx=True, ex=_VERSION_TTL_SECONDS)
        versions = client.mget(*version_keys)
        if None in versions:
            return None
    return f"{prefix}g:{user_id}:{_token(versions[0])}:{_token(versions[1])}"


def _token(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _quietly(call, *args, level=logging.WARNING, **kwargs) -> None:
    try:
        call(*args, **kwargs)
    except Exception as exc:
        log.log(level, "authz grant cache write failed: %s", type(exc).__name__)


# ---------------------------------------------------------------------------
# Invalidation: collected per session, bumped after its commit
# ---------------------------------------------------------------------------

def _pending(session) -> dict:
    return session.info.setdefault(_PENDING_KEY, {"users": set(), "global": False})


def defer_user_bump(session, user_id) -> None:
    _pending(session)["users"].add(user_id)


def defer_global_bump(session) -> None:
    _pending(session)["global"] = True


def _changed(obj, columns) -> bool:
    state = inspect(obj)
    names = columns or [attr.key for attr in state.mapper.column_attrs]
    return any(state.attrs[name].history.has_changes() for name in names)


@event.listens_for(Session, "after_flush")
def _collect(session, _flush_context):
    for obj in session.new | session.deleted:
        if isinstance(obj, VaUserAccessGrants):
            defer_user_bump(session, obj.user_id)
        elif isinstance(obj, tuple(_GLOBAL_COLUMNS)):
            defer_global_bump(session)
    for obj in session.dirty:
        if isinstance(obj, VaUserAccessGrants):
            defer_user_bump(session, obj.user_id)
        elif isinstance(obj, VaUsers):
            if _changed(obj, _USER_COLUMNS):
                defer_user_bump(session, obj.user_id)
        else:
            columns = next(
                (cols for model, cols in _GLOBAL_COLUMNS.items() if isinstance(obj, model)),
                False,
            )
            if columns is not False and _changed(obj, columns):
                defer_global_bump(session)


@event.listens_for(Session, "after_commit")
def _bump(session):
    pending = session.info.pop(_PENDING_KEY, None)
    if not pending or not (pending["users"] or pending["global"]):
        return
    client = _client()
    if client is None:
        return
    prefix = _prefix()
    # A bump replaces the version with a fresh random token (not INCR): an
    # evicted or restarted version can never line up with an old entry. A
    # lost bump leaves the old grants for at most the TTL, so it is an error.
    if pending["global"]:
        _quietly(client.set, prefix + "gv", secrets.token_hex(8),
                 ex=_VERSION_TTL_SECONDS, level=logging.ERROR)
    for user_id in pending["users"]:
        _quietly(client.set, f"{prefix}uv:{user_id}", secrets.token_hex(8),
                 ex=_VERSION_TTL_SECONDS, level=logging.ERROR)
