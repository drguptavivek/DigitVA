"""WebAuthn (passkey) registration and authentication ceremonies.

Baseline: docs/policy/authentication-factors.md section 2. Thin wrapper
around ``webauthn`` (py_webauthn): builds registration/authentication
options, stores the one outstanding challenge server-side in the session,
and verifies the browser's response.

User verification is REQUIRED at both ceremonies. Registration asks for a
discoverable credential (``residentKey: "required"``) so sign-in never needs
``allowCredentials`` and therefore cannot reveal which accounts have
passkeys (docs/policy section 1). The user handle is a stable opaque value
(the user's UUID bytes), never the email.

Challenges are base64url strings in the session (Flask-Session's storage is
not guaranteed to round-trip raw bytes), one outstanding at a time, expiring
after ``CHALLENGE_TTL`` and consumed on first use, success or failure. An
atomic Redis marker makes that single-use claim hold across concurrent workers.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta

from flask import current_app, session
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url, options_to_json_dict
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

CHALLENGE_TTL = timedelta(minutes=5)
CHALLENGE_REDIS_PREFIX = "webauthn_challenge_used:"

REGISTRATION_SESSION_KEY = "webauthn_registration"
AUTHENTICATION_SESSION_KEY = "webauthn_authentication"

log = logging.getLogger(__name__)


class PasskeyVerificationError(Exception):
    """A registration or authentication ceremony failed verification."""


def _rp_id() -> str:
    return current_app.config["WEBAUTHN_RP_ID"]


def _rp_name() -> str:
    return current_app.config["WEBAUTHN_RP_NAME"]


def _origin() -> str:
    return current_app.config["WEBAUTHN_ORIGIN"]


def _now() -> datetime:
    return datetime.now(UTC)


def _store_challenge(session_key: str, challenge: bytes, *, email: str | None = None) -> None:
    state = {
        "challenge": bytes_to_base64url(challenge),
        "issued_at": _now().isoformat(),
    }
    if email is not None:
        state["email"] = email
    # Flask sessions do not detect in-place dict mutation -- assign the key
    # itself so the session is marked modified.
    session[session_key] = state


def _consume_challenge(session_key: str) -> dict | None:
    """Pop and return the stored challenge state if present and not expired.

    Consumed unconditionally (success or failure) so a challenge is never
    reusable, per docs/policy/authentication-factors.md section 1.
    """
    state = session.get(session_key)
    if not isinstance(state, dict) or not state.get("challenge") or not state.get("issued_at"):
        return None
    try:
        issued_at = datetime.fromisoformat(state["issued_at"])
        if issued_at.tzinfo is None:
            return None
        issued_at = issued_at.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return None
    now = _now()
    if issued_at > now or now - issued_at > CHALLENGE_TTL:
        return None

    # The Flask session is copied into each concurrent request. Claim the
    # challenge in Redis before removing it from the request-local copy, so
    # two workers cannot both verify the same assertion.
    try:
        from app import cache

        digest = hashlib.sha256(state["challenge"].encode("ascii")).hexdigest()
        # Flask-Caching's add() is an atomic SETNX and keeps this marker for
        # the full challenge lifetime, even when claimed near expiry.
        claimed = cache.add(
            f"{CHALLENGE_REDIS_PREFIX}{session_key}:{digest}",
            1,
            timeout=max(1, int(CHALLENGE_TTL.total_seconds())),
        )
    except Exception as exc:  # Redis failure must fail closed for passkey auth.
        log.warning("WebAuthn challenge claim unavailable: %s", type(exc).__name__)
        return None
    if not claimed:
        return None
    session.pop(session_key, None)
    return state


def build_registration_options(user, *, existing_credential_ids: list[bytes]):
    """Options for ``navigator.credentials.create()`` to register a passkey
    for ``user``. Excludes the user's existing credentials."""
    options = generate_registration_options(
        rp_id=_rp_id(),
        rp_name=_rp_name(),
        user_id=user.user_id.bytes,
        # A mobile-only account has no email; its number names the passkey on
        # the person's own device (never sent anywhere else).
        user_name=user.email or user.mobile_login or str(user.user_id),
        user_display_name=user.name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=cred_id) for cred_id in existing_credential_ids
        ],
    )
    _store_challenge(REGISTRATION_SESSION_KEY, options.challenge)
    return options_to_json_dict(options)


def verify_registration(credential: dict):
    """Verify a registration response. Raises ``PasskeyVerificationError`` on
    any failure (bad challenge, wrong origin/RP ID, missing UV, malformed
    response). Returns the library's ``VerifiedRegistration`` on success."""
    state = _consume_challenge(REGISTRATION_SESSION_KEY)
    if state is None:
        raise PasskeyVerificationError("No outstanding registration challenge.")
    try:
        return verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(state["challenge"]),
            expected_rp_id=_rp_id(),
            expected_origin=_origin(),
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError) as exc:
        raise PasskeyVerificationError(str(exc)) from exc


def build_authentication_options():
    """Options for ``navigator.credentials.get()``. No ``allowCredentials``
    and nothing user-derived: identical for every email, known or not, so
    the response cannot reveal which accounts have passkeys."""
    options = generate_authentication_options(
        rp_id=_rp_id(),
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _store_challenge(AUTHENTICATION_SESSION_KEY, options.challenge)
    return options_to_json_dict(options)


def verify_authentication(credential: dict, *, credential_public_key: bytes):
    """Verify an authentication response against a stored credential's public
    key. Signature-counter policy is intentionally NOT enforced here --
    pass ``credential_current_sign_count=0`` so the library never raises for
    it, and let the caller apply docs/policy/authentication-factors.md
    section 2's "counter 0/0 is fine, non-zero stored that doesn't increase
    is a regression" rule itself against the returned ``new_sign_count``."""
    state = _consume_challenge(AUTHENTICATION_SESSION_KEY)
    if state is None:
        raise PasskeyVerificationError("No outstanding authentication challenge.")
    try:
        return verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(state["challenge"]),
            expected_rp_id=_rp_id(),
            expected_origin=_origin(),
            credential_public_key=credential_public_key,
            credential_current_sign_count=0,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError) as exc:
        raise PasskeyVerificationError(str(exc)) from exc


def clear_authentication_challenge() -> None:
    session.pop(AUTHENTICATION_SESSION_KEY, None)


def clear_registration_challenge() -> None:
    session.pop(REGISTRATION_SESSION_KEY, None)
