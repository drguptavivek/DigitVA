"""ODK Central as the ingest and repair source for original attachments.

Phase 4a of ``docs/planning/s3-attachment-plan.md``. DigitVA serves attachments
from its own store; this module is how that store gets filled when it misses.
It turns one attachment row into an authenticated, bounded, streamed request to
the ODK Central connection that owns it, and classifies what comes back. It
makes no authorization decision and renders no response: the attachment service
calls it after the route has authorized the user, and turns the result into
bytes plus a stored object, or a controlled failure.

Scope rules that are not negotiable here:

* the connection is resolved through the attachment's own project mapping.
  There is no global or default Central connection — an unmapped or inactive
  project fails closed (plan, *Connection and project/form/site scope*);
* redirects are observed rather than followed by ``requests``
  (plan Finding 3). A redirect back to the same Central origin is followed
  server-side; anything pointing elsewhere is rejected, because this
  deployment runs Central without S3 and therefore has no redirect allowlist;
* ODK credentials live on the Central origin only. Since only same-origin
  redirects are followed, no request ever carries them off that origin;
* URLs, query strings, headers, credentials, and bodies are never logged.

Policy baseline: ``docs/policy/attachment-storage.md``.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote, urljoin, urlsplit

import requests
import sqlalchemy as sa
from flask import current_app

from app import db
from app.models.map_project_odk import MapProjectOdk
from app.models.mas_odk_connections import MasOdkConnections
from app.models.va_forms import VaForms
from app.models.va_selectives import VaStatuses
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.models.va_submissions import VaSubmissions
from app.services.attachment_service import (
    SOURCE_AVAILABLE,
    SOURCE_ERROR,
    SOURCE_ERROR_AUTH,
    SOURCE_ERROR_INVALID_REDIRECT,
    SOURCE_ERROR_NOT_FOUND,
    SOURCE_ERROR_THROTTLED,
    SOURCE_ERROR_TRANSIENT,
    SOURCE_ERROR_UNKNOWN,
    SOURCE_MISSING,
    AttachmentRecord,
    safe_mime_type,
)
from app.services.odk_connection_guard_service import (
    OdkConnectionCooldownError,
    OdkRequestSlotBusyError,
    guarded_odk_call,
)
from app.services.odk_review_service import resolve_odk_instance_id

log = logging.getLogger(__name__)

# Fetch outcomes. Everything except OK maps to a source error category that is
# stored on the row; OK is the only one that carries a streamable response.
FETCH_OK = "ok"
FETCH_NOT_FOUND = "not_found"
FETCH_AUTH = "auth"
FETCH_THROTTLED = "throttled"
FETCH_TRANSIENT = "transient"
FETCH_INVALID_REDIRECT = "invalid_redirect"
FETCH_UNCONFIGURED = "unconfigured"   # no active mapped connection: fail closed
FETCH_UNKNOWN = "unknown"

_OUTCOME_ERROR_CODES = {
    FETCH_NOT_FOUND: SOURCE_ERROR_NOT_FOUND,
    FETCH_AUTH: SOURCE_ERROR_AUTH,
    FETCH_THROTTLED: SOURCE_ERROR_THROTTLED,
    FETCH_TRANSIENT: SOURCE_ERROR_TRANSIENT,
    FETCH_INVALID_REDIRECT: SOURCE_ERROR_INVALID_REDIRECT,
    FETCH_UNCONFIGURED: SOURCE_ERROR_AUTH,
    FETCH_UNKNOWN: SOURCE_ERROR_UNKNOWN,
}

# Central answers a deprecated instance id with a 301 to the canonical
# submission-version URL (plan Finding 3). Only these statuses are considered
# redirects at all; any other 3xx is rejected.
_FOLLOWABLE_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECT_HOPS = 3


@dataclass(frozen=True)
class CentralSource:
    """Everything needed to address one attachment on its owning Central."""

    connection_id: uuid.UUID
    base_url: str
    odk_project_id: str
    odk_form_id: str
    instance_id: str
    filename: str
    client: object

    @property
    def attachment_path(self) -> str:
        """Relative Central attachment path, percent-encoded per path segment."""
        return (
            f"projects/{quote(str(self.odk_project_id), safe='')}"
            f"/forms/{quote(self.odk_form_id, safe='')}"
            f"/submissions/{quote(self.instance_id, safe='')}"
            f"/attachments/{quote(self.filename, safe='')}"
        )


@dataclass(frozen=True)
class CentralFetch:
    """One classified attempt at Central. Only ``FETCH_OK`` carries bytes."""

    outcome: str
    response: requests.Response | None = None
    mime_type: str | None = None
    content_length: int | None = None
    redirect_followed: bool = False

    @property
    def ok(self) -> bool:
        return self.outcome == FETCH_OK

    @property
    def error_code(self) -> str | None:
        return _OUTCOME_ERROR_CODES.get(self.outcome)


# ---------------------------------------------------------------------------
# Connection resolution
# ---------------------------------------------------------------------------

# One pyODK client per connection per thread. Sync uses the same shape
# (thread-local client, reused across submissions) so a request never pays for
# an authentication handshake it can avoid, and no requests.Session is shared
# between threads.
_thread_state = threading.local()


def _client_for_connection(conn: MasOdkConnections):
    import os

    from app.utils.va_odk.va_odk_01_clientsetup import client_from_connection

    clients = getattr(_thread_state, "clients", None)
    if clients is None:
        clients = {}
        _thread_state.clients = clients
    client = clients.get(conn.connection_id)
    if client is None:
        pyodk_dir = os.path.join(current_app.config.get("APP_RESOURCE"), "pyodk")
        client = client_from_connection(conn, pyodk_dir)
        clients[conn.connection_id] = client
    return client


def resolve_source(record: AttachmentRecord) -> CentralSource | None:
    """Resolve an attachment row to its owning Central connection, or None.

    ``None`` means *fail closed*: the submission, its form, its project
    mapping, or the connection is missing or inactive. Callers must not fall
    back to any other connection — an attachment is only ever fetched from the
    server its own project is mapped to.
    """
    row = db.session.execute(
        sa.select(
            VaForms.odk_project_id,
            VaForms.odk_form_id,
            MasOdkConnections,
        )
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(MapProjectOdk, MapProjectOdk.project_id == VaForms.project_id)
        .join(
            MasOdkConnections,
            MasOdkConnections.connection_id == MapProjectOdk.connection_id,
        )
        .where(
            VaSubmissions.va_sid == record.va_sid,
            MasOdkConnections.status == VaStatuses.active,
        )
    ).first()
    if row is None:
        log.warning(
            "attachment source: no active mapped ODK connection for sid=%s form=%s",
            record.va_sid,
            record.va_form_id,
        )
        return None

    conn = row.MasOdkConnections
    return CentralSource(
        connection_id=conn.connection_id,
        base_url=conn.base_url,
        odk_project_id=row.odk_project_id,
        odk_form_id=row.odk_form_id,
        # Same derivation the review path uses: the local sid is the ODK
        # instance id plus the "-<form_id>" suffix.
        instance_id=resolve_odk_instance_id(record.va_sid),
        filename=record.filename,
        client=_client_for_connection(conn),
    )


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme.lower(), parts.netloc.lower()


def _request_timeout() -> tuple[float, float]:
    config = current_app.config
    return (
        float(config.get("ATTACHMENT_FETCH_CONNECT_TIMEOUT_SECONDS", 5)),
        float(config.get("ATTACHMENT_FETCH_READ_TIMEOUT_SECONDS", 30)),
    )


def _max_slot_wait() -> float:
    return float(
        current_app.config.get("ATTACHMENT_FETCH_MAX_SLOT_WAIT_SECONDS", 1)
    )


def _classify_status(status_code: int) -> str:
    if status_code in (404, 410):
        return FETCH_NOT_FOUND
    if status_code in (401, 403):
        return FETCH_AUTH
    if status_code == 429:
        return FETCH_THROTTLED
    if status_code >= 500:
        return FETCH_TRANSIENT
    return FETCH_UNKNOWN


def _close(response) -> None:
    if response is not None and hasattr(response, "close"):
        try:
            response.close()
        except Exception:  # pragma: no cover - close must never mask an outcome
            log.debug("attachment source: upstream close failed", exc_info=True)


def _resolved_mime_type(record: AttachmentRecord, response) -> str | None:
    """Prefer Central's type; fall back to the stored original's (Finding 9).

    Central can sign a literal ``"null"`` content type, and the DigitVA row
    carries a validated type for the original, so an unusable upstream value is
    replaced rather than forwarded to a browser.
    """
    upstream = safe_mime_type(response.headers.get("Content-Type"))
    if upstream:
        return upstream
    return safe_mime_type(record.source_mime_type) or safe_mime_type(record.mime_type)


def _content_length(response) -> int | None:
    raw = response.headers.get("Content-Length")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def fetch(record: AttachmentRecord) -> CentralFetch:
    """Fetch one original from Central and classify the result.

    Streams (``stream=True``) so the body is never read into memory here, and
    observes redirects (``allow_redirects=False``) instead of letting Requests
    follow them. A successful result hands the caller an open response; the
    caller owns closing it. Every other outcome closes what it opened.
    """
    source = resolve_source(record)
    if source is None:
        return CentralFetch(outcome=FETCH_UNCONFIGURED)

    session = source.client.session
    # pyODK's Session resolves relative paths against its own normalised
    # base_url; the connection's base_url is the fallback for anything else.
    session_base = getattr(session, "base_url", None) or source.base_url
    base_origin = _origin(session_base)
    timeout = _request_timeout()
    max_wait = _max_slot_wait()

    url = source.attachment_path
    redirect_followed = False

    try:
        for _ in range(MAX_REDIRECT_HOPS + 1):
            request_url = url
            response = guarded_odk_call(
                lambda: session.get(
                    request_url,
                    stream=True,
                    allow_redirects=False,
                    timeout=timeout,
                ),
                client=source.client,
                max_wait_seconds=max_wait,
            )

            if response.status_code == 200:
                return CentralFetch(
                    outcome=FETCH_OK,
                    response=response,
                    mime_type=_resolved_mime_type(record, response),
                    content_length=_content_length(response),
                    redirect_followed=redirect_followed,
                )

            if 300 <= response.status_code < 400:
                location = response.headers.get("Location") or ""
                # Resolve against the absolute URL actually requested, so a
                # relative Location cannot escape the Central origin.
                absolute = urljoin(urljoin(session_base, request_url), location)
                _close(response)
                if (
                    response.status_code not in _FOLLOWABLE_REDIRECT_STATUSES
                    or not location
                    or _origin(absolute) != base_origin
                ):
                    log.warning(
                        "attachment source: rejected redirect status=%s for sid=%s",
                        response.status_code,
                        record.va_sid,
                    )
                    return CentralFetch(outcome=FETCH_INVALID_REDIRECT)
                url = absolute
                redirect_followed = True
                continue

            outcome = _classify_status(response.status_code)
            _close(response)
            log.warning(
                "attachment source: central status=%s outcome=%s sid=%s",
                response.status_code,
                outcome,
                record.va_sid,
            )
            return CentralFetch(outcome=outcome, redirect_followed=redirect_followed)

        log.warning(
            "attachment source: redirect chain exceeded %s hops for sid=%s",
            MAX_REDIRECT_HOPS,
            record.va_sid,
        )
        return CentralFetch(outcome=FETCH_INVALID_REDIRECT)

    except OdkRequestSlotBusyError:
        # Pacing contention on the request path is a throttle, not a stall.
        return CentralFetch(outcome=FETCH_THROTTLED)
    except OdkConnectionCooldownError:
        return CentralFetch(outcome=FETCH_TRANSIENT)
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        log.warning(
            "attachment source: transport failure for sid=%s", record.va_sid,
        )
        return CentralFetch(outcome=FETCH_TRANSIENT)
    except Exception:
        # Message text can carry a URL or payload fragment, so it is not logged.
        log.warning(
            "attachment source: unexpected failure for sid=%s", record.va_sid,
        )
        return CentralFetch(outcome=FETCH_UNKNOWN)


# ---------------------------------------------------------------------------
# State recording
# ---------------------------------------------------------------------------

def record_fetch_state(record: AttachmentRecord, result: CentralFetch) -> None:
    """Persist what this attempt proved about the source, and commit.

    The write is one statement in its own short transaction and is committed
    **before** any byte is streamed, so no transaction is ever held open across
    a response body.

    Rules (docs/policy/attachment-storage.md):

    * success -> ``available``, ``source_verified_at`` now, error cleared, and
      the validated original MIME stored;
    * not-found -> ``missing`` plus ``not_found``. ``source_verified_at`` is
      *not* moved: it records the last observed **content** response;
    * every other failure records the error category only. A row that is
      already ``available`` stays ``available`` — a timeout does not unprove an
      earlier successful delivery — and ``source_verified_at`` is left alone so
      an old observation is never restamped as current.
    """
    now = datetime.now(timezone.utc)
    if result.ok:
        values = {
            "source_state": SOURCE_AVAILABLE,
            "source_verified_at": now,
            "source_error_code": None,
            "source_mime_type": result.mime_type,
        }
    elif result.outcome == FETCH_NOT_FOUND:
        values = {
            "source_state": SOURCE_MISSING,
            "source_error_code": SOURCE_ERROR_NOT_FOUND,
        }
    else:
        values = {
            "source_state": sa.case(
                (
                    VaSubmissionAttachments.source_state == SOURCE_AVAILABLE,
                    SOURCE_AVAILABLE,
                ),
                else_=SOURCE_ERROR,
            ),
            "source_error_code": result.error_code or SOURCE_ERROR_UNKNOWN,
        }

    db.session.execute(
        sa.update(VaSubmissionAttachments)
        .where(
            VaSubmissionAttachments.va_sid == record.va_sid,
            VaSubmissionAttachments.filename == record.filename,
        )
        .values(**values)
    )
    db.session.commit()
