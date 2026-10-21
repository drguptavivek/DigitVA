"""National identification number reduction (PII slice 1a).

Owner decision (docs/policy/pii-encryption-at-rest.md, decision 2 as revised
on 2026-10-21): the full Aadhaar or Virtual ID is never stored. ``Id10073``
("National identification number of deceased") keeps only its last
``NATIONAL_ID_KEEP_DIGITS`` digits, in one fixed-width form, whatever was
typed; no hash or index of the full number is kept. Free text that carries a
12-digit (Aadhaar) or 16-digit (VID) run is masked the same way per match;
``Id10070`` (death registration number) is a long-number field and is only
flagged, never rewritten.

Pure functions, no I/O. Every function is idempotent: the stored form never
matches the national-ID pattern again, so a rerun (or reducing both sides of
a fingerprint comparison) is a no-op.

Digits: Python's ``\\d`` is every Unicode decimal digit, so Devanagari,
Arabic-Indic and fullwidth digits are found as well. NFKC folds fullwidth
digits only (it leaves Devanagari and Arabic-Indic as they are), so the kept
digits are folded to ASCII with ``unicodedata.decimal`` instead.
"""

from __future__ import annotations

import re
import unicodedata

#: Digits of a national ID kept in the stored form (owner's choice: 3).
NATIONAL_ID_KEEP_DIGITS = 3
#: Width of the stored form; a 16-digit VID is stored at the same width.
NATIONAL_ID_STORED_WIDTH = 12
#: The masking character. Never a digit, so the stored form cannot match.
MASK_CHAR = "X"

#: The field that is national-ID class whatever it holds.
NATIONAL_ID_FIELD = "Id10073"
#: Long-number fields: a match is flagged for review, the value is kept.
FLAG_ONLY_FIELDS = frozenset({"Id10070"})
#: Payload keys never swept: ODK and app identifiers (UUIDs, unique ids) and
#: the ABHA fields, whose 14 digits written 2-4-4-4 hold a 4-4-4 run.
SKIP_FIELDS = frozenset({
    "KEY", "instanceID", "sid", "site_individual_id", "unique_id", "unique_id2",
    "death_register_id", "SubmitterID", "DeviceID", "instanceName", "form_def",
    "abha_number", "abha_address",
})

# The fingerprint's own null-like words (submission_payload_version_service).
_NOT_ANSWERED = frozenset({"na", "n/a", "none", "null"})

_SEP = r"[ \- ‐-―−　－]?"
# 12 digits in groups of four (optional single separator between groups),
# optionally a fourth group (16-digit VID). Not inside a longer token: not
# preceded by a word character or "-" (longer numbers, UUID segments such as
# an attachment id's last 12 digits) nor by "<digit>." (decimals), not
# followed by a word character or "-" (longer numbers, UUID groups) nor by
# ".<word char>" (decimals, file names like 1234...9012.jpg).
_NATIONAL_ID_RE = re.compile(
    rf"(?<![\w\-])(?<!\d\.)\d{{4}}{_SEP}\d{{4}}{_SEP}\d{{4}}(?:{_SEP}\d{{4}})?(?![\w\-])(?!\.\w)"
)


def _ascii_digits(text: str) -> str:
    """The decimal digits of *text*, in order, as ASCII."""
    return "".join(str(unicodedata.decimal(ch)) for ch in text if ch.isdecimal())


def _masked(digits: str) -> str:
    """The fixed-width stored form: mask then the last kept digits."""
    kept = digits[-NATIONAL_ID_KEEP_DIGITS:] if NATIONAL_ID_KEEP_DIGITS else ""
    return MASK_CHAR * (NATIONAL_ID_STORED_WIDTH - len(kept)) + kept


def is_reduced_national_id(value: str) -> bool:
    """True when *value* is already in the stored form."""
    head = NATIONAL_ID_STORED_WIDTH - NATIONAL_ID_KEEP_DIGITS
    tail = value[head:]
    return (
        len(value) == NATIONAL_ID_STORED_WIDTH
        and value[:head] == MASK_CHAR * head
        and tail.isascii()
        and (tail.isdigit() or set(tail) == {MASK_CHAR})
    )


def reduce_national_id_flagged(value: object) -> tuple[str | None, bool]:
    """``(stored form, needs review)`` for an ``Id10073`` answer.

    None, a blank string, a null-like word (``na``, ``n/a``, ``none``,
    ``null``) or only punctuation (``-``, ``"_"``) is "not answered": None,
    and the caller keeps the value as it is (it holds no number). Anything
    else becomes
    ``XXXXXXXXX`` plus its last 3 digits (``XXXXXXXXX123``). It needs review
    when it was not a 12- or 16-digit number: fewer than 3 digits are masked
    entirely (``XXXXXXXXXXXX``), junk with digits keeps its last 3. Applied to
    a value already in the stored form it returns it unchanged, unflagged.
    """
    if value is None or isinstance(value, bool):
        return None, False
    text = str(value).strip()
    if text.casefold() in _NOT_ANSWERED or not any(ch.isalnum() for ch in text):
        return None, False
    if is_reduced_national_id(text):
        return text, False
    digits = _ascii_digits(unicodedata.normalize("NFKC", text))
    well_formed = len(digits) in (12, 16) and looks_like_national_id(text)
    if len(digits) < NATIONAL_ID_KEEP_DIGITS:
        return MASK_CHAR * NATIONAL_ID_STORED_WIDTH, True
    return _masked(digits), not well_formed


def reduce_national_id(value: object) -> str | None:
    """The stored form of an ``Id10073`` answer (``reduce_national_id_flagged``)."""
    return reduce_national_id_flagged(value)[0]


def looks_like_national_id(text: object) -> bool:
    """True when *text* holds a 12-digit (Aadhaar) or 16-digit (VID) run,
    groups of four optionally separated by one space or hyphen. A 10-digit
    phone, an 11-, 13-, 14- or 15-digit number and a decimal do not match."""
    return isinstance(text, str) and _NATIONAL_ID_RE.search(text) is not None


def redact_national_id_digits(text: str) -> tuple[str, bool]:
    """``(text with each national-ID run masked, found)``. Each match becomes
    the stored form (all but its last 3 digits masked); the rest of the text
    is untouched. Text without a match is returned as is."""
    if not isinstance(text, str):
        return text, False
    new_text, count = _NATIONAL_ID_RE.subn(lambda m: _masked(_ascii_digits(m.group(0))), text)
    return new_text, bool(count)


def redact_payload_national_ids(payload: dict | None) -> tuple[dict | None, list[str]]:
    """``(payload with national IDs reduced, flagged field ids)``.

    ``Id10073`` is reduced at any depth; every other string value is swept
    with ``redact_national_id_digits`` except ``SKIP_FIELDS``; a match in a
    ``FLAG_ONLY_FIELDS`` field is flagged and kept. Flagged ids are the
    fields a reviewer should look at (logged as ids only, never values).
    Returns a new dict when anything changed, else *payload* itself.
    """
    if not isinstance(payload, dict):
        return payload, []
    flagged: list[str] = []
    result = _redact_value(payload, None, flagged)
    return result, flagged


def _redact_value(value, key, flagged: list[str]):
    if isinstance(value, dict):
        changed = False
        out = {}
        for child_key, child in value.items():
            new = _redact_value(child, child_key, flagged)
            changed = changed or new is not child
            out[child_key] = new
        return out if changed else value
    if isinstance(value, list):
        out = [_redact_value(item, key, flagged) for item in value]
        return out if any(a is not b for a, b in zip(out, value)) else value
    if key == NATIONAL_ID_FIELD:
        if value is None or isinstance(value, bool):
            return value
        reduced, needs_review = reduce_national_id_flagged(value)
        if needs_review:
            flagged.append(key)
        if reduced is None or reduced == value:
            return value
        return reduced
    if not isinstance(value, str) or key in SKIP_FIELDS:
        return value
    if key in FLAG_ONLY_FIELDS:
        if looks_like_national_id(value):
            flagged.append(key)
        return value
    new_text, found = redact_national_id_digits(value)
    if found:
        flagged.append(str(key))
        return new_text
    return value
