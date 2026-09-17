"""DigitVA's attachment object store.

DigitVA keeps its own permanent copy of every attachment — the originals ODK
Central holds and the MP3 derivatives DigitVA makes from ``.amr`` narration —
and that copy is the read path. This module is the only place that knows where
those bytes physically live.

Two backends implement the same small interface:

``LocalAttachmentStore``
    Files under ``APP_DATA/<form_id>/media/``. The historical behaviour; still
    the store for development, the test suite, and every deployment that has
    not cut over.

``S3AttachmentStore``
    A private DigitVA-owned bucket. Objects are written with
    ``Cache-Control: private, no-store`` and SSE-S3 at rest, and are delivered
    as short-lived presigned redirects — see ``attachment_service.deliver()``.

The backend is selected once from ``ATTACHMENT_STORE`` and nothing above this
module branches on it except delivery, which must choose between sending a
file and issuing a redirect.

The S3 backend also exposes ``put_key``/``head_key``/``get_key``/``delete_key``
for callers that address an object by a key of their own rather than by an
attachment row: the SmartVA run archive under the ``smartva_runs/`` prefix of
the same bucket, and the database backups under ``db-backups/``. Those objects
are never presigned and never served.

Policy baseline: ``docs/policy/attachment-storage.md``.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import dataclass
from typing import Protocol

from flask import current_app

from config import ATTACHMENT_STORE_LOCAL, ATTACHMENT_STORE_S3

log = logging.getLogger(__name__)

# Object metadata written on every upload. The browser must not persist PHI
# bytes, and the presigned URL repeats these so a stale object still serves
# with the right policy.
STORE_CACHE_CONTROL = "private, no-store"
STORE_CONTENT_DISPOSITION = "inline"
STORE_SERVER_SIDE_ENCRYPTION = "AES256"

# Fallback when a row carries no usable MIME. Never the literal "null".
DEFAULT_CONTENT_TYPE = "application/octet-stream"

# Bytes moved per read when copying a stream into the store; nothing is ever
# buffered whole.
STORE_CHUNK_SIZE = 64 * 1024


class StoredObject(Protocol):
    """What the store needs to address one attachment.

    ``attachment_service.AttachmentRecord`` satisfies this; so does any small
    stand-in built by sync or the CLI tools. Keeping it structural is what lets
    this module stay free of a dependency on the attachment service.
    """

    va_form_id: str
    storage_name: str | None
    local_path: str | None


@dataclass(frozen=True)
class StoreTarget:
    """Minimal addressable object for callers that hold no full record.

    Sync, the cleanup of superseded objects, and the CLI cutover tools all know
    the form and the storage name but not the rest of an ``AttachmentRecord``.
    """

    va_form_id: str
    storage_name: str | None
    local_path: str | None = None


class AttachmentStoreError(RuntimeError):
    """A store operation failed. Detail goes to the log, not to a caller."""


# ---------------------------------------------------------------------------
# Local files
# ---------------------------------------------------------------------------

class LocalAttachmentStore:
    """Attachment objects as files under ``APP_DATA/<form_id>/media/``."""

    name = ATTACHMENT_STORE_LOCAL

    @property
    def key_prefix(self) -> str:
        return ""

    def key_for(self, record: StoredObject) -> str | None:
        """``<form_id>/media/<storage_name>`` — the path relative to APP_DATA."""
        if not record.storage_name:
            return None
        return f"{record.va_form_id}/media/{record.storage_name}"

    def media_dir(self, record: StoredObject) -> str:
        return os.path.realpath(
            os.path.join(current_app.config["APP_DATA"], record.va_form_id, "media")
        )

    def open_local_path(self, record: StoredObject) -> str | None:
        """Return the stored file's path, or None when the store has no object.

        Resolution order is the one in the policy: the opaque ``storage_name``
        under the form's media directory first, then the legacy ``local_path``.
        Both must resolve inside that directory, so a row pointing anywhere
        else is a miss rather than an arbitrary file read.
        """
        media_dir = self.media_dir(record)
        candidates = []
        if record.storage_name:
            candidates.append(os.path.join(media_dir, record.storage_name))
        if record.local_path:
            candidates.append(record.local_path)
        for candidate in candidates:
            resolved = os.path.realpath(candidate)
            if not resolved.startswith(media_dir + os.sep):
                continue
            if os.path.isfile(resolved):
                return resolved
        return None

    def exists(self, record: StoredObject) -> bool:
        return self.open_local_path(record) is not None

    def put(self, record: StoredObject, source, *, content_type: str | None) -> str:
        """Store one object from a file path or an iterable of byte chunks.

        Written to a temporary name in the same directory and renamed only
        after the last chunk, so a failed or abandoned write can never leave a
        partial object or one that looks complete. ``content_type`` is carried
        on the row, not on the file, so it is accepted and ignored here.
        """
        key = self.key_for(record)
        if key is None:
            raise AttachmentStoreError("Cannot store an object without a storage_name.")
        media_dir = self.media_dir(record)
        os.makedirs(media_dir, exist_ok=True)
        target = os.path.join(media_dir, record.storage_name)
        tmp_path = os.path.join(media_dir, f".tmp_{uuid.uuid4().hex}")
        try:
            with open(tmp_path, "wb") as handle:
                for chunk in _iter_source_chunks(source):
                    handle.write(chunk)
            os.replace(tmp_path, target)
        except Exception:
            _remove_quietly(tmp_path)
            raise
        return target

    def presigned_url(self, record: StoredObject, *, content_type, filename) -> str | None:
        """Local files are served by the app, never by a redirect."""
        return None

    def delete(self, record: StoredObject) -> bool:
        """Remove the stored object. Explicit tooling only — never delivery."""
        path = self.open_local_path(record)
        if path is None:
            return False
        return _remove_quietly(path)


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------

_s3_client_lock = threading.Lock()
_s3_clients: dict[tuple, object] = {}


def _s3_client(endpoint_url: str, region: str, access_key: str, secret_key: str):
    """One boto3 client per (endpoint, region, key) per process.

    botocore clients are thread-safe for the calls made here, and building one
    parses the bundled endpoint data — far too expensive to repeat per request.
    """
    cache_key = (endpoint_url, region, access_key)
    client = _s3_clients.get(cache_key)
    if client is not None:
        return client
    with _s3_client_lock:
        client = _s3_clients.get(cache_key)
        if client is None:
            import boto3
            from botocore.config import Config as BotoConfig

            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=BotoConfig(
                    signature_version="s3v4",
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
            _s3_clients[cache_key] = client
    return client


def reset_s3_clients() -> None:
    """Drop the cached clients. Tests only — moto replaces the transport."""
    with _s3_client_lock:
        _s3_clients.clear()


class S3AttachmentStore:
    """Attachment objects in a private DigitVA-owned bucket.

    Every object is written with ``Cache-Control: private, no-store``,
    ``Content-Disposition: inline`` and SSE-S3, so the policy holds even when
    an object is fetched by a presigned URL that this process did not sign.
    """

    name = ATTACHMENT_STORE_S3

    def __init__(self, *, bucket: str, prefix: str, expiry_seconds: int, client):
        self.bucket = bucket
        self.key_prefix = prefix or ""
        self.expiry_seconds = expiry_seconds
        self.client = client

    def key_for(self, record: StoredObject) -> str | None:
        """``<S3_PREFIX><form_id>/media/<storage_name>``.

        None for a legacy row with no ``storage_name``: such a row has no
        object in this store and must never be presigned.
        """
        if not record.storage_name:
            return None
        return f"{self.key_prefix}{record.va_form_id}/media/{record.storage_name}"

    def open_local_path(self, record: StoredObject) -> str | None:
        """Nothing is on this app server's disk. Always None."""
        return None

    def exists(self, record: StoredObject) -> bool:
        key = self.key_for(record)
        if key is None:
            return False
        return self.head(key) is not None

    def head(self, key: str) -> dict | None:
        """HEAD one key: its metadata, or None when it is not there.

        A transport or permission failure is logged and reported as absent, so
        delivery falls through to its ordinary miss handling instead of raising
        a 500 at a coder.
        """
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status in (403, 404):
                return None
            log.warning("attachment store: HEAD failed status=%s", status)
            return None
        except BotoCoreError:
            log.warning("attachment store: HEAD failed", exc_info=True)
            return None

    def put(self, record: StoredObject, source, *, content_type: str | None) -> str:
        """Upload one object from a file path or a readable binary stream.

        ``put_object`` is atomic: the key either becomes the complete new
        object or is left as it was, so a failed upload never leaves a partial
        object behind. Memory stays bounded because botocore reads the handle
        in chunks rather than materialising the body.
        """
        key = self.key_for(record)
        if key is None:
            raise AttachmentStoreError("Cannot store an object without a storage_name.")
        return self._put_absolute(key, source, content_type)

    # -- Keyed access -----------------------------------------------------
    #
    # The methods above address one attachment through a ``StoredObject``. The
    # four below address an arbitrary object by a store-relative key, so that
    # a caller holding a key of its own — the SmartVA run archive under
    # ``smartva_runs/``, the database backups under ``db-backups/`` — reuses
    # this bucket, client and object policy instead of building a second S3
    # client. They are S3-only on purpose: nothing archives to the local store.

    def absolute_key(self, key: str) -> str:
        """``<S3_PREFIX><key>`` — a store-relative key made bucket-absolute."""
        return f"{self.key_prefix}{key}"

    def put_key(self, key: str, source, *, content_type: str | None) -> str:
        """Upload one object at a store-relative key. Returns the absolute key."""
        return self._put_absolute(self.absolute_key(key), source, content_type)

    def head_key(self, key: str) -> dict | None:
        """HEAD one store-relative key: its metadata, or None when absent."""
        return self.head(self.absolute_key(key))

    def get_key(self, key: str, dest_path: str) -> int:
        """Stream one store-relative key to a local path. Returns bytes written.

        Chunked through the botocore streaming body so a multi-gigabyte object
        never lands in memory, and written to a neighbouring temporary name
        that is renamed only after the last chunk, so an interrupted download
        can never leave a file that looks complete.
        """
        from botocore.exceptions import BotoCoreError, ClientError

        absolute = self.absolute_key(key)
        tmp_path = f"{dest_path}.part_{uuid.uuid4().hex}"
        written = 0
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=absolute)
            with open(tmp_path, "wb") as handle:
                for chunk in response["Body"].iter_chunks(STORE_CHUNK_SIZE):
                    handle.write(chunk)
                    written += len(chunk)
            os.replace(tmp_path, dest_path)
        except (BotoCoreError, ClientError) as exc:
            _remove_quietly(tmp_path)
            log.warning("attachment store: GET failed")
            raise AttachmentStoreError("Attachment store read failed.") from exc
        except Exception:
            _remove_quietly(tmp_path)
            raise
        return written

    def delete_key(self, key: str) -> bool:
        """Remove one store-relative key. Explicit tooling only."""
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self.client.delete_object(Bucket=self.bucket, Key=self.absolute_key(key))
        except (BotoCoreError, ClientError) as exc:
            raise AttachmentStoreError("Attachment store delete failed.") from exc
        return True

    def _put_absolute(self, key: str, source, content_type: str | None) -> str:
        from botocore.exceptions import BotoCoreError, ClientError

        extra = {
            "ContentType": content_type or DEFAULT_CONTENT_TYPE,
            "CacheControl": STORE_CACHE_CONTROL,
            "ContentDisposition": STORE_CONTENT_DISPOSITION,
            "ServerSideEncryption": STORE_SERVER_SIDE_ENCRYPTION,
        }
        try:
            if isinstance(source, (str, os.PathLike)):
                with open(source, "rb") as handle:
                    self.client.put_object(Bucket=self.bucket, Key=key, Body=handle, **extra)
            elif hasattr(source, "read"):
                self.client.put_object(Bucket=self.bucket, Key=key, Body=source, **extra)
            else:
                raise AttachmentStoreError(
                    "S3 uploads need a file path or a readable stream, not an iterator."
                )
        except (BotoCoreError, ClientError) as exc:
            log.warning("attachment store: PUT failed")
            raise AttachmentStoreError("Attachment store write failed.") from exc
        return key

    def presigned_url(self, record: StoredObject, *, content_type, filename) -> str | None:
        """Sign a short-lived GET for one object.

        The response headers the client will see are fixed inside the
        signature, so a signed URL cannot be replayed with a different type or
        disposition. The URL is returned to the caller for one redirect and is
        never stored, cached or logged.
        """
        from botocore.exceptions import BotoCoreError, ClientError

        key = self.key_for(record)
        if key is None:
            return None
        params = {
            "Bucket": self.bucket,
            "Key": key,
            "ResponseContentType": content_type or DEFAULT_CONTENT_TYPE,
            "ResponseContentDisposition": f'inline; filename="{filename}"',
            "ResponseCacheControl": STORE_CACHE_CONTROL,
        }
        try:
            return self.client.generate_presigned_url(
                "get_object", Params=params, ExpiresIn=self.expiry_seconds
            )
        except (BotoCoreError, ClientError):
            log.warning("attachment store: could not sign a URL for form=%s", record.va_form_id)
            return None

    def delete(self, record: StoredObject) -> bool:
        """Remove one object. Explicit tooling only — never delivery or sync."""
        from botocore.exceptions import BotoCoreError, ClientError

        key = self.key_for(record)
        if key is None:
            return False
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise AttachmentStoreError("Attachment store delete failed.") from exc
        return True

    def iter_keys(self, prefix: str | None = None):
        """Yield every key under the store prefix, one page at a time.

        Used by the integrity script. Paginated so a bucket with millions of
        objects never lands in memory at once.
        """
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=self.bucket, Prefix=prefix if prefix is not None else self.key_prefix
        ):
            for item in page.get("Contents", []):
                yield item["Key"], item.get("Size"), (item.get("ETag") or "").strip('"')


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def build_attachment_store(config):
    """Build the store the given config selects. Validated at app startup."""
    store_name = (config.get("ATTACHMENT_STORE") or ATTACHMENT_STORE_LOCAL).strip().lower()
    if store_name != ATTACHMENT_STORE_S3:
        return LocalAttachmentStore()
    return S3AttachmentStore(
        bucket=config["S3_BUCKET"],
        prefix=config.get("S3_PREFIX") or "",
        expiry_seconds=int(config["ATTACHMENT_PRESIGN_EXPIRY_SECONDS"]),
        client=_s3_client(
            config["S3_SERVER"],
            config["S3_REGION"],
            config["S3_ACCESS_KEY_ID"],
            config["S3_SECRET_ACCESS_KEY"],
        ),
    )


def get_attachment_store():
    """The selected store for the current app, built once per app.

    Cached on ``app.extensions`` rather than in a module global so that a test
    that flips ``ATTACHMENT_STORE`` on its own app gets its own store.
    """
    app = current_app._get_current_object()
    store = app.extensions.get("attachment_store")
    wanted = (app.config.get("ATTACHMENT_STORE") or ATTACHMENT_STORE_LOCAL).strip().lower()
    if store is None or store.name != wanted:
        store = build_attachment_store(app.config)
        app.extensions["attachment_store"] = store
    return store


def s3_public_origins(config) -> list[str]:
    """Origins a presigned attachment redirect can land on.

    The browser applies ``img-src``/``media-src`` to the *final* URL of a
    redirect, so the content security policy has to name the bucket's origins
    or every attachment silently fails to render. Both addressing styles are
    listed because botocore picks one per endpoint.
    """
    from urllib.parse import urlparse

    server = (config.get("S3_SERVER") or "").strip()
    bucket = (config.get("S3_BUCKET") or "").strip()
    if not server:
        return []
    parsed = urlparse(server if "//" in server else f"https://{server}")
    if not parsed.scheme or not parsed.netloc:
        return []
    origins = [f"{parsed.scheme}://{parsed.netloc}"]
    if bucket:
        origins.append(f"{parsed.scheme}://{bucket}.{parsed.netloc}")
    return origins


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_source_chunks(source):
    """Yield bounded byte chunks from a path, a readable stream, or an iterable."""
    if isinstance(source, (str, os.PathLike)):
        with open(source, "rb") as handle:
            while True:
                chunk = handle.read(STORE_CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk
    elif hasattr(source, "read"):
        while True:
            chunk = source.read(STORE_CHUNK_SIZE)
            if not chunk:
                return
            yield chunk
    else:
        yield from source


def _remove_quietly(path: str | None) -> bool:
    if not path:
        return False
    try:
        os.remove(path)
    except FileNotFoundError:
        return False
    except OSError:
        log.warning("attachment store: could not remove a temporary file", exc_info=True)
        return False
    return True
