"""Health checks for a split production deployment: TLS certificate expiry and
the S3 attachment store's credentials and bucket access.

Four kinds of certificate matter there: the app's own HTTPS certificate, the
database certificate the server actually presents, each certificate in the
database trust bundle, and the public Let's Encrypt certificate on the reverse
proxy. The S3 store, when it is the selected attachment store, gets a short
access probe. ``certificate_report()`` reads or probes each one and returns a
row per check. Dev and single-host production have none of them, so every check
degrades to ``not_configured`` and never raises.

The admin panel calls ``certificate_report()`` live and stores the result with
``store_report()``. The admin banner and the daily task read the stored copy
only, so an ordinary page load never touches the network.

Baseline: docs/policy/tls-certificate-monitoring.md.
"""

from __future__ import annotations

import logging
import socket
import ssl
import struct
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import NamedTuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import NameOID
from flask import current_app
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.services.attachment_store import STORE_SERVER_SIDE_ENCRYPTION, get_attachment_store
from config import ATTACHMENT_STORE_S3, _parse_public_url

log = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 3
# PostgreSQL SSLRequest: length 8, then the magic code 80877103 (1234.5679).
SSL_REQUEST = struct.pack("!ii", 8, 80877103)
CACHE_KEY = "tls_health:last"
# A day plus slack, so one missed daily run does not blank the banner.
CACHE_TTL_SECONDS = 26 * 60 * 60
ATTENTION_STATUSES = frozenset({"due", "urgent", "expired", "error"})
VERIFY_SSLMODES = frozenset({"verify-ca", "verify-full"})
S3_CREDENTIAL_CODES = frozenset(
    {"InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken", "InvalidToken"}
)
S3_PROBE_PREFIX = "health/probe-"
# Plain HTTPS requests of the public-access check (presigned and unsigned GETs).
S3_PUBLIC_PROBE_TIMEOUT_SECONDS = 5


class _Context(NamedTuple):
    now: datetime
    warn_days: int
    urgent_days: int


def status_for_days(days_left: int, warn_days: int, urgent_days: int) -> str:
    """Map days until expiry to a status. Boundaries are inclusive: a
    certificate with exactly ``warn_days`` left is already ``due``."""
    if days_left < 0:
        return "expired"
    if days_left <= urgent_days:
        return "urgent"
    if days_left <= warn_days:
        return "due"
    return "ok"


def needs_attention(rows: list[dict]) -> bool:
    """True when any row is due, urgent, expired or failed a verification."""
    return any(row["status"] in ATTENTION_STATUSES for row in rows)


def certificate_report() -> list[dict]:
    """Live expiry rows for every certificate this deployment should have.

    Each row carries key, label, source (a path or host:port, never a URL with
    credentials), subject_cn, sans, not_after (aware UTC or None), days_left,
    status and detail (a fixed phrase, never a raw exception message). Never
    raises: a check that fails unexpectedly becomes an ``error`` row.
    """
    ctx = _Context(
        now=datetime.now(UTC),
        warn_days=current_app.config["TLS_EXPIRY_WARN_DAYS"],
        urgent_days=current_app.config["TLS_EXPIRY_URGENT_DAYS"],
    )
    rows = []
    rows += _checked(lambda: [_app_https_row(ctx)], "app_https", "App HTTPS certificate")
    rows += _checked(lambda: _database_rows(ctx), "db_presented", "PostgreSQL certificate")
    rows += _checked(lambda: [_public_https_row(ctx)], "public_https", "Public HTTPS certificate")
    rows += _checked(lambda: _s3_rows(ctx), "s3_store", "Attachment store (S3)")
    return rows


def store_report(rows: list[dict]) -> None:
    """Cache the report for the banner and the daily task. Failure is logged,
    not raised: a cache outage must not break the panel that just rendered."""
    from app import cache

    payload = [
        {
            **row,
            "sans": list(row["sans"]),
            "not_after": row["not_after"].isoformat() if row["not_after"] else None,
        }
        for row in rows
    ]
    try:
        cache.set(CACHE_KEY, payload, timeout=CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001 - see docstring
        log.warning("TLS health report could not be cached")


def banner_rows() -> list[dict] | None:
    """The cached rows that need attention, or None when there are none or no
    report has been stored. Reads the cache only; never probes the network."""
    from app import cache

    try:
        rows = cache.get(CACHE_KEY)
    except Exception:  # noqa: BLE001 - a banner must never break the admin index
        log.warning("TLS health report could not be read from the cache")
        return None
    if not rows or not needs_attention(rows):
        return None
    return [row for row in rows if row["status"] in ATTENTION_STATUSES]


def _checked(build, key: str, label: str) -> list[dict]:
    try:
        return build()
    except Exception:  # noqa: BLE001 - a status page must never raise
        log.warning("TLS check failed unexpectedly: %s", key)
        return [_failed_row(key, label, "", "error", "check failed")]


def _app_https_row(ctx: _Context) -> dict:
    path = current_app.config["APP_TLS_CERT_FILE"]
    label = "App HTTPS certificate"
    try:
        certs = _read_pem(path)
    except FileNotFoundError:
        return _failed_row("app_https", label, path, "not_configured", "certificate file not found")
    except (OSError, ValueError):
        return _failed_row(
            "app_https", label, path, "error", "certificate file could not be parsed"
        )
    return _cert_row("app_https", label, path, certs[0], ctx)


def _database_rows(ctx: _Context) -> list[dict]:
    try:
        url = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
    except ArgumentError:
        url = None
    sslmode = _query_value(url, "sslmode")
    trust_path = _query_value(url, "sslrootcert")
    verifying = sslmode in VERIFY_SSLMODES

    trust_certs, trust_failure = _load_trust(trust_path)
    rows = [_presented_row(ctx, url, verifying, trust_certs, trust_failure)]
    rows += _trust_rows(ctx, trust_path, trust_certs, trust_failure)
    return rows


def _presented_row(ctx, url, verifying, trust_certs, trust_failure) -> dict:
    key, label = "db_presented", "PostgreSQL certificate as presented"
    if not verifying:
        return _failed_row(key, label, "", "not_configured", "sslmode does not verify the server")
    if url is None or not url.host:
        return _failed_row(key, label, "", "not_configured", "no TCP host in the database URL")

    port = url.port or 5432
    source = f"{url.host}:{port}"
    cert, failure = _presented_certificate(url.host, port)
    if cert is None:
        status, detail = failure
        return _failed_row(key, label, source, status, detail)
    if trust_certs is None:
        status, detail = trust_failure
        return {**_cert_row(key, label, source, cert, ctx), "status": status, "detail": detail}

    presented_fp = cert.fingerprint(hashes.SHA256())
    if presented_fp not in {c.fingerprint(hashes.SHA256()) for c in trust_certs}:
        # Rotation done in the wrong order: the server presents a certificate
        # the app's trust bundle does not yet contain.
        return {
            **_cert_row(key, label, source, cert, ctx),
            "status": "error",
            "detail": "presented certificate is not in the trust bundle",
        }
    return _cert_row(key, label, source, cert, ctx)


def _presented_certificate(host: str, port: int):
    """Return ``(certificate, None)``, or ``(None, (status, detail))``.

    Sends only the PostgreSQL SSLRequest and then a TLS handshake that does not
    verify: libpq does the trust check, this only reads what the server shows.
    No credential is sent.
    """
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT_SECONDS) as sock:
            sock.sendall(SSL_REQUEST)
            if sock.recv(1) != b"S":
                return None, ("error", "server does not offer TLS")
            try:
                with context.wrap_socket(sock, server_hostname=host) as tls:
                    der = tls.getpeercert(binary_form=True)
            except ssl.SSLError:
                return None, ("error", "TLS handshake failed")
    except OSError:
        return None, ("unreachable", "connection failed")
    if not der:
        return None, ("error", "no certificate presented")
    try:
        return x509.load_der_x509_certificate(der), None
    except ValueError:
        return None, ("error", "certificate could not be parsed")


def _load_trust(trust_path: str):
    """Return ``(certs, None)`` or ``(None, (status, detail))`` for the bundle."""
    if not trust_path:
        return None, ("not_configured", "sslrootcert is not set")
    try:
        return _read_pem(trust_path), None
    except FileNotFoundError:
        return None, ("not_configured", "trust bundle file not found")
    except (OSError, ValueError):
        return None, ("error", "trust bundle could not be parsed")


def _trust_rows(ctx, trust_path, trust_certs, trust_failure) -> list[dict]:
    label = "PostgreSQL trust bundle"
    if trust_certs is None:
        status, detail = trust_failure
        return [_failed_row("db_trust_1", label, trust_path, status, detail)]
    total = len(trust_certs)
    rows = []
    for index, cert in enumerate(trust_certs, start=1):
        row_label = f"{label} ({index} of {total})"
        if total > 1:
            row_label += ", rotation in progress"
        rows.append(_cert_row(f"db_trust_{index}", row_label, trust_path, cert, ctx))
    return rows


def _public_https_row(ctx: _Context) -> dict:
    key, label = "public_https", "Public HTTPS certificate"
    host = _parse_public_url(current_app.config.get("PUBLIC_BASE_URL", "")).hostname
    if not host:
        return _failed_row(key, label, "", "not_configured", "PUBLIC_BASE_URL is not set")

    source = f"{host}:443"
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=PROBE_TIMEOUT_SECONDS) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
    except ssl.SSLCertVerificationError:
        return _failed_row(key, label, source, "error", "certificate did not verify")
    except ssl.SSLError:
        return _failed_row(key, label, source, "error", "TLS handshake failed")
    except OSError:
        return _failed_row(key, label, source, "unreachable", "connection failed")
    try:
        cert = x509.load_der_x509_certificate(der)
    except ValueError:
        return _failed_row(key, label, source, "error", "certificate could not be parsed")
    return _cert_row(key, label, source, cert, ctx)


class _ProbeNotDeleted(Exception):
    """The S3 probe object was written but its delete failed."""


def _s3_rows(ctx: _Context) -> list[dict]:
    """Credentials, bucket access, listing and a write probe of the S3 store.

    Steps run in order and stop at the first failure; the later steps are
    still listed, as ``not_configured``, so the panel keeps a stable set of rows.
    Each step is one S3 call. The access step lists (``MaxKeys=1``) rather
    than HEADs the bucket: a listing error carries S3's error code, so a bad key
    reads "credentials rejected", not a bare 403. An unreachable endpoint costs
    the store client's connect timeout x attempts (attachment_store._s3_client).
    """
    store = get_attachment_store()
    if store.name != ATTACHMENT_STORE_S3:
        return [_failed_row("s3_store", "Attachment store (S3)", "", "not_configured", "")]

    source = f"s3://{store.bucket}/{store.key_prefix}"
    steps = [
        (
            "s3_access",
            "S3 credentials and bucket access",
            lambda: store.client.list_objects_v2(
                Bucket=store.bucket, Prefix=store.key_prefix, MaxKeys=1
            ),
        ),
        ("s3_write", "S3 write, read and delete", lambda: _probe_write(store)),
        (
            "s3_public",
            "S3 public access blocked (presigned links only)",
            lambda: _probe_write(store, check=_check_presigned_only),
        ),
    ]
    rows = []
    failed = False
    for key, label, check in steps:
        if failed:
            rows.append(
                _failed_row(
                    key, label, source, "not_configured", "skipped after an earlier failure"
                )
            )
            continue
        status, detail = _s3_step(key, check)
        failed = status != "ok"
        rows.append(_failed_row(key, label, source, status, detail))
    return rows


def _probe_write(store, check=None) -> None:
    """Put, HEAD and delete one empty object under ``<prefix>health/``.

    The put uses the same server-side encryption as uploads. ``check``, when
    given, runs against the probe's key before the delete. The delete runs in
    ``finally`` once the put has succeeded, so a failed HEAD or check cannot
    leave the probe behind; a failed delete raises ``_ProbeNotDeleted``, which
    wins over any earlier error so that a leftover object is never silent.
    """
    absolute = store.absolute_key(f"{S3_PROBE_PREFIX}{uuid.uuid4().hex}")
    store.client.put_object(
        Bucket=store.bucket,
        Key=absolute,
        Body=b"",
        ServerSideEncryption=STORE_SERVER_SIDE_ENCRYPTION,
    )
    try:
        store.client.head_object(Bucket=store.bucket, Key=absolute)
        if check is not None:
            check(store, absolute)
    finally:
        try:
            store.client.delete_object(Bucket=store.bucket, Key=absolute)
        except Exception as exc:  # noqa: BLE001 - mapped to a fixed phrase in _s3_step
            raise _ProbeNotDeleted() from exc


class _PublicAccess(Exception):
    """The bucket answered an unsigned request; carries the fixed detail."""


class _PresignedRefused(Exception):
    """A presigned link to the probe object did not return it."""


def _check_presigned_only(store, key: str) -> None:
    """Objects are reachable only through a presigned link (owner, 2026-10-14).

    Proves behaviour, not configuration, so it needs no extra IAM action: the
    probe's presigned URL must return 200, the same URL without its signature
    must be refused, and so must an unsigned listing of the bucket. The URLs
    hold no credentials worth hiding (the signature expires in 60 s) and are
    never logged or returned.
    """
    signed = store.client.generate_presigned_url(
        "get_object", Params={"Bucket": store.bucket, "Key": key}, ExpiresIn=60
    )
    if _http_status(signed) != 200:
        raise _PresignedRefused()
    unsigned = signed.split("?", 1)[0]
    if _http_status(unsigned) < 400:
        raise _PublicAccess("objects are publicly readable")
    bucket_url = unsigned[: -len(key)] if unsigned.endswith(key) else unsigned.rsplit("/", 1)[0] + "/"
    if _http_status(f"{bucket_url}?list-type=2&max-keys=1") < 400:
        raise _PublicAccess("bucket is publicly listable")


def _http_status(url: str) -> int:
    """Status of a plain GET; network failures propagate as URLError/OSError."""
    try:
        with urllib.request.urlopen(url, timeout=S3_PUBLIC_PROBE_TIMEOUT_SECONDS) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _s3_step(key: str, check) -> tuple[str, str]:
    """Run one S3 step and map its failure to ``(status, fixed detail)``.

    Only the access step reads a bare 404 as "bucket not found". Raw exception
    text is never returned.
    """
    from botocore.exceptions import (
        ClientError,
        ConnectTimeoutError,
        EndpointConnectionError,
        HTTPClientError,
    )

    try:
        check()
    except _ProbeNotDeleted:
        return "error", "probe object could not be deleted"
    except _PublicAccess as exc:
        return "error", str(exc)
    except _PresignedRefused:
        return "error", "presigned link did not return the object"
    except (urllib.error.URLError, TimeoutError, OSError):
        return "unreachable", "S3 endpoint unreachable"
    except ClientError as exc:
        return _s3_client_error(exc, access_step=key == "s3_access")
    except (EndpointConnectionError, ConnectTimeoutError, HTTPClientError):
        # HTTPClientError covers read timeouts and dropped connections: a
        # transient network fault, not a credential problem, so no email.
        # An SSLError is not here on purpose: that is a real fault.
        return "unreachable", "S3 endpoint unreachable"
    except Exception:  # noqa: BLE001 - a status page must never raise
        log.warning("S3 health check failed at %s", key)
        return "error", "S3 check failed"
    return "ok", ""


def _s3_client_error(exc, *, access_step: bool) -> tuple[str, str]:
    error = exc.response.get("Error", {})
    code = error.get("Code", "")
    http_status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    if code in S3_CREDENTIAL_CODES:
        return "error", "credentials rejected"
    if code == "NoSuchBucket" or (access_step and http_status == 404):
        return "error", "bucket not found"
    if code == "RequestTimeTooSkewed":
        return "error", "server clock is out of sync"
    if code == "AccessDenied" or http_status == 403:
        return "error", "access denied (check the IAM policy for this bucket and prefix)"
    return "error", "S3 check failed"


def _read_pem(path: str) -> list[x509.Certificate]:
    """Every certificate in a PEM file, in file order. Raises FileNotFoundError,
    OSError or ValueError; callers map those to a row status."""
    with open(path, "rb") as fh:
        return x509.load_pem_x509_certificates(fh.read())


def _query_value(url, key: str) -> str:
    if url is None:
        return ""
    value = url.query.get(key, "")
    # A repeated query key comes back as a tuple; the last one wins, as libpq's.
    if isinstance(value, tuple):
        value = value[-1] if value else ""
    return value


def _cert_row(key: str, label: str, source: str, cert: x509.Certificate, ctx: _Context) -> dict:
    not_after = cert.not_valid_after_utc
    days_left = int((not_after - ctx.now).total_seconds() // 86400)
    return {
        "key": key,
        "label": label,
        "source": source,
        "subject_cn": _common_name(cert),
        "sans": _sans(cert),
        "not_after": not_after,
        "days_left": days_left,
        "status": status_for_days(days_left, ctx.warn_days, ctx.urgent_days),
        "detail": "",
    }


def _failed_row(key: str, label: str, source: str, status: str, detail: str) -> dict:
    return {
        "key": key,
        "label": label,
        "source": source,
        "subject_cn": "",
        "sans": [],
        "not_after": None,
        "days_left": None,
        "status": status,
        "detail": detail,
    }


def _common_name(cert: x509.Certificate) -> str:
    names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    return names[0].value if names else ""


def _sans(cert: x509.Certificate) -> list[str]:
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return []
    return [str(name.value) for name in ext.value]
