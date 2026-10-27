"""Slide-to-slot puzzle CAPTCHA for the public contact form — no third-party
service.

Baseline: docs/policy/public-privacy-and-data-requests.md section 7. The page
draws an animal silhouette with a slot cut out at a random position and a
slider that moves a matching piece along the track
(app/templates/va_frontpages/_slide_captcha.html, app/static/js/
slide_captcha.js). The browser submits the final position plus coarse drag
telemetry; ``verify_challenge`` accepts a position within ``TOLERANCE`` of the
slot after a plausible drag.

The target never travels in the token: the only value the client sends back
is an opaque random id, and the target lives in the cache under that id. The
slot is necessarily drawn in the picture; what this stops is a client reading
or forging the answer from the token. Unlike pow_captcha_service, any attempt
spends the challenge (right or wrong), so the slot cannot be found by
stepping through positions; the page renders a fresh puzzle after an error.

All geometry is in SVG viewBox units, so the tolerance does not depend on how
large the picture is drawn. stdlib only: secrets.
"""

from __future__ import annotations

import re
import secrets

# 5-minute challenge lifetime, as the proof-of-work CAPTCHA.
CHALLENGE_TTL_SECONDS = 300

# Picture and piece size in viewBox units; the slider runs 0..TRACK.
WIDTH = 320
HEIGHT = 160
PIECE = 44
TRACK = WIDTH - PIECE

TOLERANCE = 6
MIN_DURATION_MS = 300
MIN_MOVES = 3

ANIMALS = ("cat", "elephant", "fish", "bird")

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def _key(challenge_id: str) -> str:
    return f"slide_captcha:{challenge_id}"


def _used_key(challenge_id: str) -> str:
    return f"slide_captcha_used:{challenge_id}"


def issue_challenge() -> dict:
    """Issue a fresh puzzle and keep its target server side.

    Returns ``challenge_id`` (the only value the form sends back), ``animal``
    and the slot's drawing position ``slot_x``/``slot_y`` for the server-side
    render. The slot never starts under the piece (x 0) so an untouched
    slider cannot pass.
    """
    from app import cache

    challenge_id = secrets.token_urlsafe(16)
    lowest = PIECE + 16
    slot_x = lowest + secrets.randbelow(TRACK - 8 - lowest + 1)
    slot_y = 16 + secrets.randbelow(HEIGHT - PIECE - 32 + 1)
    cache.set(_key(challenge_id), slot_x, timeout=CHALLENGE_TTL_SECONDS)
    return {
        "challenge_id": challenge_id,
        "animal": secrets.choice(ANIMALS),
        "slot_x": slot_x,
        "slot_y": slot_y,
    }


def _as_int(value, low: int, high: int) -> int | None:
    text = str(value if value is not None else "").strip()
    if not text or len(text) > 9 or not (text.isascii() and text.isdigit()):
        return None
    number = int(text)
    return number if low <= number <= high else None


def verify_challenge(*, challenge_id, x, duration_ms, moves) -> bool:
    """True exactly once per challenge, for a position within ``TOLERANCE``
    of the slot after at least ``MIN_DURATION_MS`` and ``MIN_MOVES`` moves.

    Malformed input is refused before the cache is touched. An unknown or
    expired id is refused. Otherwise the challenge is claimed with an atomic
    cache add (two concurrent submissions cannot both pass) and deleted, and
    only then compared, so a wrong answer spends it too.
    """
    from app import cache

    if not isinstance(challenge_id, str) or not _ID_RE.match(challenge_id):
        return False
    x = _as_int(x, 0, TRACK)
    duration_ms = _as_int(duration_ms, 0, CHALLENGE_TTL_SECONDS * 1000)
    moves = _as_int(moves, 0, 100000)
    if x is None or duration_ms is None or moves is None:
        return False

    target = cache.get(_key(challenge_id))
    if target is None:
        return False
    if not cache.add(_used_key(challenge_id), 1, timeout=CHALLENGE_TTL_SECONDS):
        return False
    cache.delete(_key(challenge_id))

    return (
        abs(x - int(target)) <= TOLERANCE
        and duration_ms >= MIN_DURATION_MS
        and moves >= MIN_MOVES
    )
