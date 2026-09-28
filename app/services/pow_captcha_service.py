"""Local proof-of-work CAPTCHA — no third-party service.

Baseline: docs/policy/authentication-factors.md section 5. The server issues
a signed, time-boxed challenge; the browser finds a number whose SHA-256
digest (with the challenge's salt) has ``difficulty`` leading zero bits, in a
Web Worker (app/static/js/pow_captcha.js), and submits it with the email
step. ``verify_challenge`` checks the signature, the expiry, the solution,
and finally claims the challenge as spent — so a signature failure or a wrong
solution never burns the single use, and two concurrent submissions of the
same correct solution cannot both pass (only one wins the atomic cache add).

stdlib only, per the policy: hmac, hashlib, secrets, time.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

# 5-minute challenge lifetime (docs/policy/authentication-factors.md section 5).
CHALLENGE_TTL_SECONDS = 300


def _hmac_key() -> bytes:
    """The signing key: ``CAPTCHA_HMAC_KEY`` if set, else derived from
    ``SECRET_KEY`` for development/test convenience. Production requires
    ``CAPTCHA_HMAC_KEY`` explicitly (see create_app)."""
    from flask import current_app

    configured = (current_app.config.get("CAPTCHA_HMAC_KEY") or "").strip()
    if configured:
        return configured.encode("utf-8")
    secret = current_app.config["SECRET_KEY"]
    return hmac.new(secret.encode("utf-8"), b"pow-captcha", hashlib.sha256).digest()


def _difficulty() -> int:
    from flask import current_app

    return int(current_app.config.get("CAPTCHA_DIFFICULTY", 18))


def _signed_payload(salt: str, difficulty: int, expires: int) -> bytes:
    # Difficulty and expiry are part of the signed payload, so a client
    # cannot resubmit a genuine signature with a lowered difficulty or a
    # pushed-out expiry.
    return f"{salt}.{difficulty}.{expires}".encode("ascii")


def _sign(salt: str, difficulty: int, expires: int) -> str:
    return hmac.new(_hmac_key(), _signed_payload(salt, difficulty, expires), hashlib.sha256).hexdigest()


def issue_challenge() -> dict:
    """Issue a fresh, signed challenge for the browser to solve."""
    salt = secrets.token_hex(16)
    difficulty = _difficulty()
    expires = int(time.time()) + CHALLENGE_TTL_SECONDS
    return {
        "salt": salt,
        "difficulty": difficulty,
        "expires": expires,
        "signature": _sign(salt, difficulty, expires),
    }


def _meets_difficulty(digest: bytes, difficulty: int) -> bool:
    if difficulty <= 0:
        return True
    total_bits = len(digest) * 8
    if difficulty > total_bits:
        return False
    value = int.from_bytes(digest, "big")
    return (value >> (total_bits - difficulty)) == 0


def _used_key(salt: str) -> str:
    return f"pow_captcha_used:{salt}"


def verify_challenge(*, salt, difficulty, expires, signature, solution) -> bool:
    """Verify a solved challenge. Returns True exactly once per challenge.

    Order matters: signature, then expiry, then the solution itself (all
    side-effect-free), and only then the single-use claim — so a failed
    check never spends the challenge's one use, and a genuine race between
    two submissions of the same correct solution is resolved by the atomic
    cache add, not by this ordering.
    """
    if not isinstance(salt, str) or not salt or not isinstance(signature, str):
        return False
    try:
        difficulty = int(difficulty)
        expires = int(expires)
    except (TypeError, ValueError):
        return False

    expected_signature = _sign(salt, difficulty, expires)
    if not hmac.compare_digest(signature, expected_signature):
        return False

    if time.time() > expires:
        return False

    try:
        number = str(solution)
        # Reject anything that is not a plain-ish integer literal before it
        # ever reaches the digest, so an oversized payload cannot be forced
        # through hashlib.
        if not number or len(number) > 32 or not number.lstrip("-").isdigit():
            return False
    except Exception:
        return False

    digest = hashlib.sha256((salt + number).encode("utf-8")).digest()
    if not _meets_difficulty(digest, difficulty):
        return False

    from app import cache

    ttl = max(1, expires - int(time.time()))
    # add() is an atomic SETNX: True only for the first caller to claim this
    # salt, which is exactly the single-use gate the policy requires.
    return bool(cache.add(_used_key(salt), 1, timeout=ttl))
