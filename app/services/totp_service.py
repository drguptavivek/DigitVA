"""TOTP enrolment/verification and recovery codes.

Baseline: docs/policy/authentication-factors.md sections 4, 6, 7. TOTP
secrets are stored encrypted at rest (Fernet) under
``AUTH_FACTOR_ENCRYPTION_KEY``; recovery codes are stored only as keyed
HMAC-SHA256 hashes and shown to the caller exactly once, at generation time.

Replay protection stores the last accepted time step and rejects that step
or an earlier one, applied with an atomic conditional UPDATE so two
concurrent submissions of the same code cannot both be accepted (mirrors
the WebAuthn signature-counter update in app/routes/va_auth.py). Recovery
codes are consumed the same way: an atomic UPDATE ... WHERE used_at IS NULL.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import re
import secrets
import time
from datetime import date, datetime, timezone

import pyotp
import segno
import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import AuthRecoveryCode, AuthTotp, AuthWebauthnCredential

RECOVERY_CODE_COUNT = 10
# RFC 4648 base32 alphabet -- no ambiguous 0/1/8/9 to transcribe by hand.
_RECOVERY_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_ISSUER = "DigitVA"


class TotpEnrolmentError(ValueError):
    """Enrolment cannot proceed (e.g. TOTP is already confirmed)."""


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

def _fernet_key() -> bytes:
    """The Fernet key encrypting TOTP secrets: ``AUTH_FACTOR_ENCRYPTION_KEY``
    if set, else derived from ``SECRET_KEY`` for development/test
    convenience. Production requires ``AUTH_FACTOR_ENCRYPTION_KEY``
    explicitly (see app.create_app)."""
    configured = (current_app.config.get("AUTH_FACTOR_ENCRYPTION_KEY") or "").strip()
    if configured:
        return configured.encode("utf-8")
    secret = current_app.config["SECRET_KEY"]
    digest = hashlib.sha256(b"auth-factor:" + secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet():
    from cryptography.fernet import Fernet

    return Fernet(_fernet_key())


def _recovery_hmac_key() -> bytes:
    """Key for recovery-code hashes, derived from the same factor key under
    a distinct label so the two purposes never share key material."""
    return hashlib.sha256(_fernet_key() + b":recovery-code").digest()


def _encrypt(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def _decrypt(secret_encrypted: str) -> str:
    return _fernet().decrypt(secret_encrypted.encode("utf-8")).decode("utf-8")


# ---------------------------------------------------------------------------
# TOTP enrolment and verification
# ---------------------------------------------------------------------------

def has_confirmed_totp(user_id) -> bool:
    return bool(db.session.scalar(
        sa.select(sa.exists().where(
            AuthTotp.user_id == user_id, AuthTotp.confirmed_at.is_not(None)
        ))
    ))


def needs_second_factor(user) -> bool:
    """docs/policy/authentication-factors.md section 3: a confirmed TOTP
    enrolment (any role), or a privileged user (active admin or
    data_manager grant) holding any factor (passkey or confirmed TOTP)."""
    if has_confirmed_totp(user.user_id):
        return True
    if not (user.is_admin() or user.is_data_manager()):
        return False
    has_passkey = db.session.scalar(
        sa.select(sa.exists().where(AuthWebauthnCredential.user_id == user.user_id))
    )
    return bool(has_passkey)


def begin_enrolment(user) -> dict:
    """Start (or restart) TOTP enrolment: a fresh random secret stored
    encrypted in an unconfirmed row, replacing any unconfirmed row already
    there. Raises ``TotpEnrolmentError`` if TOTP is already confirmed --
    remove it first. Caller commits."""
    existing = db.session.get(AuthTotp, user.user_id)
    if existing is not None and existing.confirmed_at is not None:
        raise TotpEnrolmentError("TOTP is already enrolled; remove it before re-enrolling.")

    secret = pyotp.random_base32()
    encrypted = _encrypt(secret)
    if existing is not None:
        existing.secret_encrypted = encrypted
        existing.last_used_step = None
        existing.created_at = datetime.now(timezone.utc)
    else:
        db.session.add(AuthTotp(user_id=user.user_id, secret_encrypted=encrypted))
    db.session.flush()

    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=_ISSUER)
    return {"secret": secret, "provisioning_uri": uri}


def provisioning_qr_svg(uri: str) -> str:
    """Render a provisioning URI as an inline SVG QR code (segno, pure
    Python, no external service). Never logged; the secret itself is only
    ever returned in the enrolment response, not stored in plain text."""
    buf = io.BytesIO()
    segno.make(uri, error="m").save(buf, kind="svg", xmldecl=False, svgns=True, scale=4)
    return buf.getvalue().decode("utf-8")


def _totp_step(for_time: float, interval: int) -> int:
    return int(for_time) // interval


def _matched_step(secret: str, code: str, *, valid_window: int, for_time: float | None) -> int | None:
    """The time-step index the code matches, within ``valid_window`` steps of
    now (or ``for_time``), else None. pyotp.verify() only returns bool, so
    this recomputes the candidate codes itself to recover which step
    matched, for replay protection."""
    if not isinstance(code, str) or not code.strip():
        return None
    code = code.strip()
    totp = pyotp.TOTP(secret)
    base = for_time if for_time is not None else time.time()
    for offset in range(-valid_window, valid_window + 1):
        candidate = totp.at(base, counter_offset=offset)
        if hmac.compare_digest(candidate, code):
            return _totp_step(base, totp.interval) + offset
    return None


def confirm_enrolment(user, code: str, *, for_time: float | None = None) -> bool:
    """Confirm the pending enrolment with a valid code (+/-1 step of clock
    drift). Caller commits."""
    row = db.session.get(AuthTotp, user.user_id)
    if row is None or row.confirmed_at is not None:
        return False
    secret = _decrypt(row.secret_encrypted)
    step = _matched_step(secret, code, valid_window=1, for_time=for_time)
    if step is None:
        return False
    row.confirmed_at = datetime.now(timezone.utc)
    row.last_used_step = step
    return True


def verify(user, code: str, *, for_time: float | None = None) -> bool:
    """Verify a login-time TOTP code with replay protection: a code for the
    last accepted step or earlier is refused, and the update is atomic so a
    concurrent replay of the same code cannot also be accepted. Caller
    commits."""
    row = db.session.get(AuthTotp, user.user_id)
    if row is None or row.confirmed_at is None:
        return False
    secret = _decrypt(row.secret_encrypted)
    step = _matched_step(secret, code, valid_window=1, for_time=for_time)
    if step is None:
        return False
    if row.last_used_step is not None and step <= row.last_used_step:
        return False

    result = db.session.execute(
        sa.update(AuthTotp)
        .where(
            AuthTotp.user_id == user.user_id,
            sa.or_(AuthTotp.last_used_step.is_(None), AuthTotp.last_used_step < step),
        )
        .values(last_used_step=step)
    )
    if result.rowcount != 1:
        return False
    db.session.expire(row, ["last_used_step"])
    return True


def remove(user) -> None:
    """Delete the TOTP enrolment (confirmed or not). Caller commits."""
    db.session.execute(sa.delete(AuthTotp).where(AuthTotp.user_id == user.user_id))


# ---------------------------------------------------------------------------
# Recovery codes
# ---------------------------------------------------------------------------

def _generate_recovery_code() -> str:
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def _normalize_code(code: str) -> str:
    return re.sub(r"[\s-]", "", (code or "")).upper()


def _hash_code(normalized: str) -> str:
    return hmac.new(_recovery_hmac_key(), normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def has_recovery_codes(user_id) -> bool:
    return bool(db.session.scalar(
        sa.select(sa.exists().where(AuthRecoveryCode.user_id == user_id))
    ))


def remaining_recovery_code_count(user_id) -> int:
    return db.session.scalar(
        sa.select(sa.func.count())
        .select_from(AuthRecoveryCode)
        .where(AuthRecoveryCode.user_id == user_id, AuthRecoveryCode.used_at.is_(None))
    ) or 0


def generate_recovery_codes(user) -> list[str]:
    """Issue a fresh set of 10 codes, voiding any existing set. Returns the
    plaintext codes -- shown to the caller exactly once; only their keyed
    hash is stored. Caller commits."""
    db.session.execute(sa.delete(AuthRecoveryCode).where(AuthRecoveryCode.user_id == user.user_id))
    codes = [_generate_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    for code in codes:
        db.session.add(AuthRecoveryCode(
            user_id=user.user_id,
            code_hash=_hash_code(_normalize_code(code)),
        ))
    db.session.flush()
    return codes


def verify_recovery_code(user, code: str) -> bool:
    """Consume one unused recovery code atomically. Returns True exactly
    once per code. Caller commits."""
    normalized = _normalize_code(code)
    if not normalized:
        return False
    code_hash = _hash_code(normalized)
    row = db.session.scalar(
        sa.select(AuthRecoveryCode).where(
            AuthRecoveryCode.user_id == user.user_id,
            AuthRecoveryCode.code_hash == code_hash,
            AuthRecoveryCode.used_at.is_(None),
        )
    )
    if row is None:
        return False
    result = db.session.execute(
        sa.update(AuthRecoveryCode)
        .where(AuthRecoveryCode.id == row.id, AuthRecoveryCode.used_at.is_(None))
        .values(used_at=datetime.now(timezone.utc))
    )
    return result.rowcount == 1


# ---------------------------------------------------------------------------
# Enrolment enforcement window (section 6)
# ---------------------------------------------------------------------------

def enforcement_active() -> bool:
    """Whether ``AUTH_FACTOR_ENFORCE_FROM`` is set and its date has passed.
    Unset (the default) means no enforcement."""
    raw = (current_app.config.get("AUTH_FACTOR_ENFORCE_FROM") or "").strip()
    if not raw:
        return False
    try:
        enforce_from = date.fromisoformat(raw)
    except ValueError:
        return False
    return datetime.now(timezone.utc).date() >= enforce_from
