"""Payload split and the one version fingerprint (PII slice 1b).

Policy: docs/policy/pii-encryption-at-rest.md, "Fingerprint and change
detection". The sealed set of a payload (``pii_field_registry.sealed_field_ids``
for its form type) moves out of ``payload_data`` into
``map_payload_version_pii``; every "same payload?" decision must then be made
by ``version_fingerprint`` on BOTH sides, or a stripped stored payload compared
with a full incoming one reads as a change on every sync.

Algorithm (pinned by tests/services/test_payload_pii_split.py):

1. ``split_payload``: national IDs reduced first
   (``redact_payload_national_ids``: ``Id10073`` to its stored form, other
   strings swept, ``Id10070`` flagged only); top-level keys in the sealed set
   go to ``pii``, the rest to ``stripped``.
2. ``pii_digest(pii)`` = ``hex(HMAC-SHA-256(subkey("payload-fp"),
   canonical_json(normalised pii)))``. Each value is normalised like the
   payload fingerprint (``normalize_payload_for_fingerprint``) and a value
   that normalises to null is left out, so absent, ``null``, ``""``,
   whitespace and ``na`` digest alike. ``Id10073`` enters as ``{"last3":
   <kept digits or null>, "present": true}`` and is left out when not
   answered (OD1: a changed number with the same last 3 is not a change).
3. ``version_fingerprint(stripped, pii_digest)`` = ``hex(SHA-256(
   canonical_json({"payload": normalize_payload_for_fingerprint(stripped),
   "pii": pii_digest})))``. ``canonical_json`` is ``json.dumps(sort_keys=True,
   separators=(",", ":"), ensure_ascii=True)``, as
   ``canonical_payload_fingerprint``.

So ``fingerprint_of(full_payload)`` equals ``version_fingerprint`` of the
stored stripped payload and the side row's ``pii_digest``, and comparing
never decrypts. Pure apart from the keyring (``pii_crypto.subkey``): the
caller passes the sealed set. A stored side row carries the set its digest
was computed under (``sealed_ids``), and a comparison against it splits both
sides on that set (``comparison_ids``), never on today's registry.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

from app.services.submission_payload_version_service import normalize_payload_for_fingerprint
from app.utils import pii_crypto
from app.utils.national_id import (
    NATIONAL_ID_FIELD,
    NATIONAL_ID_KEEP_DIGITS,
    redact_payload_national_ids,
    reduce_national_id,
)

PII_DIGEST_CLASS = "payload-fp"


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class PayloadSplit:
    """``stripped`` (payload minus the sealed set), ``pii`` (the sealed
    fields as stored, national ID reduced), ``review_flags`` (field ids the
    national-ID sweep flagged) and ``pii_digest``."""

    stripped: dict
    pii: dict
    review_flags: list
    pii_digest: str

    @property
    def fingerprint(self) -> str:
        return version_fingerprint(self.stripped, self.pii_digest)


def split_payload(payload: dict | None, sealed_ids: frozenset[str]) -> PayloadSplit:
    """Split *payload* on the top-level keys in *sealed_ids* (the dev data
    holds no sealed key below the top level). A new dict on each side; the
    input is not changed."""
    reduced, flags = redact_payload_national_ids(payload or {})
    stripped = {key: value for key, value in reduced.items() if key not in sealed_ids}
    pii = {key: value for key, value in reduced.items() if key in sealed_ids}
    return PayloadSplit(stripped, pii, flags, pii_digest(pii))


def join_payload(stripped: dict | None, pii: dict | None) -> dict:
    """The inverse of ``split_payload``: ``join_payload(s.stripped, s.pii)``
    is the (reduced) payload. A sealed value wins over a stale copy still in
    an unstripped payload."""
    return {**(stripped or {}), **(pii or {})}


def _national_id_entry(value) -> dict | None:
    reduced = reduce_national_id(value)
    if reduced is None:
        return None
    tail = reduced[-NATIONAL_ID_KEEP_DIGITS:]
    return {"last3": tail if tail.isdigit() else None, "present": True}


def pii_digest(pii: dict) -> str:
    """The keyed digest of the sealed fields (one per version, so it shows no
    per-field equality across records). See the module docstring."""
    normalised = {}
    swept = normalize_payload_for_fingerprint(pii or {})
    for key, value in (pii or {}).items():
        entry = _national_id_entry(value) if key == NATIONAL_ID_FIELD else swept.get(key)
        if entry is not None:
            normalised[key] = entry
    return hmac.new(
        pii_crypto.subkey(PII_DIGEST_CLASS), _canonical_json(normalised).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def version_fingerprint(stripped: dict | None, digest: str) -> str:
    """The only payload fingerprint once the split is live; the stored
    ``payload_fingerprint`` is its value."""
    body = {"payload": normalize_payload_for_fingerprint(stripped or {}), "pii": digest}
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def fingerprint_of(payload: dict | None, sealed_ids: frozenset[str]) -> str:
    """``version_fingerprint`` of a full (unsplit) payload."""
    return split_payload(payload, sealed_ids).fingerprint


def comparison_ids(side_row, sealed_ids: frozenset[str]) -> frozenset[str]:
    """The sealed set a comparison against a stored version splits on: the
    side row's own ``sealed_ids`` (the set its digest was computed under),
    else *sealed_ids* (today's registry, for a version not yet split). So an
    ``is_pii`` toggle after the split never reads as a change."""
    return frozenset(side_row.sealed_ids) if side_row is not None else sealed_ids


def stored_fingerprint(payload_data: dict | None, side_row, sealed_ids: frozenset[str]) -> str:
    """The fingerprint of a stored version without decrypting: its payload
    minus the side row's own sealed set plus the side row's digest. Without a
    side row (not yet backfilled) the stored payload still holds its PII and
    is split here on *sealed_ids*."""
    if side_row is None:
        return fingerprint_of(payload_data, sealed_ids)
    ids = comparison_ids(side_row, sealed_ids)
    stripped = {key: value for key, value in (payload_data or {}).items() if key not in ids}
    return version_fingerprint(stripped, side_row.pii_digest)


def same_content(payload: dict | None, version, side_row, sealed_ids: frozenset[str]) -> bool:
    """True when the full incoming *payload* carries the same content as the
    stored *version* (with its ``map_payload_version_pii`` row, or None).
    Both sides are split on one set (``comparison_ids``)."""
    ids = comparison_ids(side_row, sealed_ids)
    return fingerprint_of(payload, ids) == stored_fingerprint(version.payload_data, side_row, ids)
