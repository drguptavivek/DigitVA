"""Attachment storage-name helpers."""

from __future__ import annotations

import os
import uuid


_LEGACY_MIGRATION_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def legacy_attachment_storage_name(va_sid: str, filename: str) -> str:
    """Return the deterministic opaque storage name used for legacy migration."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".amr":
        ext = ".mp3"
    return uuid.uuid5(_LEGACY_MIGRATION_NS, f"{va_sid}:{filename}").hex + ext
