"""Audit trail writer for auth_security_events.

Baseline: docs/policy/authentication-factors.md section 9. ``detail`` must
stay small and non-secret -- never a credential ID in full, a public key, a
TOTP secret, a challenge or an IP address.
"""

from __future__ import annotations

import uuid

from app import db
from app.models import AuthSecurityEvent


def record_security_event(
    *,
    user_id: uuid.UUID | None,
    event_type: str,
    actor_user_id: uuid.UUID | None = None,
    detail: dict | None = None,
) -> None:
    db.session.add(
        AuthSecurityEvent(
            user_id=user_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            detail=detail,
        )
    )


def credential_id_prefix(credential_id: bytes) -> str:
    """First 4 bytes of a credential ID as hex (<=8 chars), for audit detail
    only -- never the full ID (section 9)."""
    return credential_id[:4].hex()
