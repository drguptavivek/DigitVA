"""Issue, revoke, list and authenticate ICD-11 client API tokens (digitva-ddpf).

Policy: docs/policy/icd11-client-api.md. A token is
``dvicd_<key_id>_<secret>``: ``key_id`` is 12 hex characters (public, shown to
admins), ``secret`` 43 urlsafe characters (256 bits). Only the SHA-256 digest
of the whole token is stored. Nothing here logs, stores or returns a token
after issuance.

Every request reads the client row afresh, so a revocation made by any
worker refuses the very next request on every other one.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db
from app.models import AuthIcd11ApiClient, AuthSecurityEvent, VaUsers
from app.services.device.tokens import hash_token

PATH_PREFIX = "/api/icd11-client/"
SCOPES = ("icd11:search", "icd11:lookup", "icd11:postcoordination", "icd11:validate")
DEFAULT_EXPIRES_IN_DAYS = 90
MAX_EXPIRES_IN_DAYS = 365
#: Throttle for last_used_at writes, as LAST_SEEN_INTERVAL for device sessions.
LAST_USED_INTERVAL = timedelta(seconds=60)
#: The admin list is a handful of applications; this bounds it regardless.
LIST_LIMIT = 200

# One anchored pattern: the secret's urlsafe alphabet includes "_".
_TOKEN_RE = re.compile(r"^dvicd_([0-9a-f]{12})_([A-Za-z0-9_-]{43})$")


class Icd11ClientInputError(ValueError):
    """Bad issuance input; ``field`` names the input to fix."""

    def __init__(self, message: str, field: str):
        super().__init__(message)
        self.field = field


class Icd11ClientNotFound(LookupError):
    """No client has this id."""


class Icd11ClientAuthError(Exception):
    """A refused client request: ``code`` is the API's error code."""

    def __init__(self, code: str, status: int, message: str):
        super().__init__(message)
        self.code = code
        self.status = status


def _now() -> datetime:
    return datetime.now(UTC)


def bearer_token(request) -> str | None:
    """The token of an ``Authorization: Bearer`` header (scheme any case), else None."""
    scheme, _sep, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip()


def key_id_of(token: str | None) -> str | None:
    """The key id of a well-formed token, else None. Proves nothing about validity."""
    match = _TOKEN_RE.fullmatch(token or "")
    return match.group(1) if match else None


def _validated(name, scopes, expires_in_days) -> tuple[str, list[str], int]:
    name = name.strip() if isinstance(name, str) else ""
    if not 1 <= len(name) <= 120:
        raise Icd11ClientInputError("Name must be 1 to 120 characters.", "name")
    if (
        not isinstance(scopes, list)
        or not scopes
        or not all(isinstance(scope, str) and scope in SCOPES for scope in scopes)
    ):
        raise Icd11ClientInputError("Choose one or more valid scopes.", "scopes")
    if expires_in_days is None:
        expires_in_days = DEFAULT_EXPIRES_IN_DAYS
    if (
        isinstance(expires_in_days, bool)
        or not isinstance(expires_in_days, int)
        or not 1 <= expires_in_days <= MAX_EXPIRES_IN_DAYS
    ):
        raise Icd11ClientInputError(
            f"Expiry must be a whole number of days from 1 to {MAX_EXPIRES_IN_DAYS}.",
            "expires_in_days",
        )
    # Deduplicated, in SCOPES order.
    return name, [scope for scope in SCOPES if scope in scopes], expires_in_days


def issue_client(name, scopes, expires_in_days, actor) -> tuple[AuthIcd11ApiClient, str]:
    """Create a client and its token. The token is returned here only.

    Raises ``Icd11ClientInputError`` (with ``field``) on bad input. Adds the
    row and its ``icd11_client_issued`` audit event; the caller commits.
    """
    name, scopes, expires_in_days = _validated(name, scopes, expires_in_days)
    key_id = secrets.token_hex(6)
    token = f"dvicd_{key_id}_{secrets.token_urlsafe(32)}"
    row = AuthIcd11ApiClient(
        id=uuid.uuid4(),
        name=name,
        key_id=key_id,
        token_sha256=hash_token(token),
        scopes=scopes,
        expires_at=_now() + timedelta(days=expires_in_days),
        created_by=actor.user_id,
        created_at=_now(),
    )
    db.session.add(row)
    db.session.add(AuthSecurityEvent(
        user_id=None,
        actor_user_id=actor.user_id,
        event_type="icd11_client_issued",
        detail={
            "client_id": str(row.id),
            "key_id": key_id,
            "name": name,
            "scopes": scopes,
            "expires_at": row.expires_at.isoformat(),
        },
    ))
    db.session.flush()
    return row, token


def revoke_client(client_id, actor) -> AuthIcd11ApiClient:
    """Revoke a client; idempotent (a revoked client is returned unchanged).

    Raises ``Icd11ClientNotFound`` for an unknown id. The caller commits.
    """
    row = db.session.get(AuthIcd11ApiClient, client_id, with_for_update=True)
    if row is None:
        raise Icd11ClientNotFound(str(client_id))
    if row.revoked_at is not None:
        return row
    row.revoked_at = _now()
    row.revoked_by = actor.user_id
    db.session.add(AuthSecurityEvent(
        user_id=None,
        actor_user_id=actor.user_id,
        event_type="icd11_client_revoked",
        detail={"client_id": str(row.id), "key_id": row.key_id, "name": row.name},
    ))
    db.session.flush()
    return row


def _status(revoked_at, expires_at, now) -> str:
    if revoked_at is not None:
        return "revoked"
    if expires_at <= now:
        return "expired"
    return "active"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_client(row: AuthIcd11ApiClient, created_by_name=None, revoked_by_name=None) -> dict:
    """The admin view of a client. Never the verifier."""
    return {
        "id": str(row.id),
        "name": row.name,
        "key_id": row.key_id,
        "scopes": list(row.scopes),
        "status": _status(row.revoked_at, row.expires_at, _now()),
        "created_at": _iso(row.created_at),
        "created_by": created_by_name,
        "expires_at": _iso(row.expires_at),
        "last_used_at": _iso(row.last_used_at),
        "revoked_at": _iso(row.revoked_at),
        "revoked_by": revoked_by_name,
    }


def describe_client(row: AuthIcd11ApiClient) -> dict:
    """``serialize_client`` for one row, with the admins' names."""
    def name(user_id):
        user = db.session.get(VaUsers, user_id) if user_id else None
        return user.name if user else None

    return serialize_client(row, name(row.created_by), name(row.revoked_by))


def list_clients() -> dict:
    """Clients newest first, at most ``LIST_LIMIT``, with the creating and
    revoking admins' names (one query). ``truncated`` says more exist."""
    creator = so.aliased(VaUsers)
    revoker = so.aliased(VaUsers)
    rows = db.session.execute(
        sa.select(AuthIcd11ApiClient, creator.name, revoker.name)
        .join(creator, creator.user_id == AuthIcd11ApiClient.created_by)
        .outerjoin(revoker, revoker.user_id == AuthIcd11ApiClient.revoked_by)
        .order_by(AuthIcd11ApiClient.created_at.desc(), AuthIcd11ApiClient.id.desc())
        .limit(LIST_LIMIT + 1)
    ).all()
    return {
        "clients": [serialize_client(row, created, revoked) for row, created, revoked in rows[:LIST_LIMIT]],
        "truncated": len(rows) > LIST_LIMIT,
    }


def authenticate(request) -> AuthIcd11ApiClient:
    """The live client named by the request's bearer token.

    Raises ``Icd11ClientAuthError``: ``INVALID_TOKEN`` (missing, malformed,
    unknown; a malformed token is refused before any database read),
    ``TOKEN_REVOKED`` or ``TOKEN_EXPIRED``, all 401. Updates ``last_used_at``
    at most once per ``LAST_USED_INTERVAL`` and commits that write.
    """
    token = bearer_token(request)
    if key_id_of(token) is None:
        raise Icd11ClientAuthError("INVALID_TOKEN", 401, "A valid ICD-11 client token is required.")
    # populate_existing: a fresh read even when the session already holds the row.
    row = db.session.scalar(
        sa.select(AuthIcd11ApiClient)
        .where(AuthIcd11ApiClient.token_sha256 == hash_token(token))
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise Icd11ClientAuthError("INVALID_TOKEN", 401, "A valid ICD-11 client token is required.")
    if row.revoked_at is not None:
        raise Icd11ClientAuthError("TOKEN_REVOKED", 401, "This ICD-11 client token was revoked.")
    now = _now()
    if row.expires_at <= now:
        raise Icd11ClientAuthError("TOKEN_EXPIRED", 401, "This ICD-11 client token has expired.")
    if row.last_used_at is None or now - row.last_used_at > LAST_USED_INTERVAL:
        row.last_used_at = now
        db.session.commit()
    return row


def require_scope(client: AuthIcd11ApiClient, scope: str) -> None:
    """Raise ``INSUFFICIENT_SCOPE`` (403) unless the client holds ``scope``."""
    if scope not in client.scopes:
        raise Icd11ClientAuthError(
            "INSUFFICIENT_SCOPE", 403, "This token does not allow this operation."
        )
