"""Public contact form: hold a message until the sender confirms by email,
then deliver it once to ``PUBLIC_CONTACT_EMAIL``.

Baseline: docs/policy/public-privacy-and-data-requests.md section 7. The
pending message sits in the application cache for 24 hours, keyed by the
SHA-256 of a random token so the store never holds a live link; the emailed
link carries only the token. Logs name the event, the topic and a keyed hash
of the sender's address, never the name, address or message.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets

from flask import current_app

from app.services import email_service

log = logging.getLogger(__name__)

PENDING_TTL_SECONDS = 24 * 60 * 60

# secrets.token_urlsafe(32) is 43 characters.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _pending_key(token: str) -> str:
    return f"contact_pending:{_token_digest(token)}"


def _claimed_key(token: str) -> str:
    return f"contact_claimed:{_token_digest(token)}"


def sender_hash(email: str) -> str:
    """A short keyed hash of the address, for log correlation only."""
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    normalized = (email or "").strip().lower().encode("utf-8")
    return hmac.new(secret, normalized, hashlib.sha256).hexdigest()[:12]


def _valid_token(token) -> bool:
    return isinstance(token, str) and bool(_TOKEN_RE.match(token))


def start(*, name: str, email: str, topic: str, topic_label: str, message: str) -> None:
    """Hold the message and email the sender a confirmation link. Says
    nothing about whether a send was attempted: the caller answers every
    valid submission the same way."""
    from app import cache

    token = secrets.token_urlsafe(32)
    cache.set(
        _pending_key(token),
        {"name": name, "email": email, "topic": topic, "topic_label": topic_label, "message": message},
        timeout=PENDING_TTL_SECONDS,
    )
    email_service.send_contact_confirmation_email(email, token)
    log.info("contact_form event=submitted topic=%s sender=%s", topic, sender_hash(email))


def is_pending(token) -> bool:
    """True when the link still holds an unconfirmed message."""
    from app import cache

    return _valid_token(token) and cache.get(_pending_key(token)) is not None


def confirm(token) -> bool:
    """Deliver the held message once. False, delivering nothing, for a
    malformed, unknown, expired or already used token, or when
    ``PUBLIC_CONTACT_EMAIL`` is unset (the message then stays held until it
    expires). The atomic cache add means two concurrent confirms cannot both
    deliver."""
    from app import cache

    if not _valid_token(token):
        return False
    to = (current_app.config.get("PUBLIC_CONTACT_EMAIL") or "").strip()
    if not to:
        return False
    pending = cache.get(_pending_key(token))
    if not pending:
        return False
    if not cache.add(_claimed_key(token), 1, timeout=PENDING_TTL_SECONDS):
        return False
    cache.delete(_pending_key(token))
    email_service.send_contact_message(
        to=to,
        reply_to=pending["email"],
        name=pending["name"],
        topic_label=pending["topic_label"],
        message=pending["message"],
    )
    log.info(
        "contact_form event=delivered topic=%s sender=%s",
        pending["topic"],
        sender_hash(pending["email"]),
    )
    return True
