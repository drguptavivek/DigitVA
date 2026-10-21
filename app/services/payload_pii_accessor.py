"""Read and write the sealed PII of a payload version (PII slice 1b).

Policy: docs/policy/pii-encryption-at-rest.md, "Payload design". The only
code that touches ``map_payload_version_pii``. Part II-A: every payload
writer reaches ``put_pii`` through
``submission_payload_version_service.write_payload_version`` when
``PAYLOAD_PII_SPLIT_ENABLED`` is on; part II-B switches the readers
(docs/kb/pii-slice-1b.md). Values are sealed as JSON text so a ``null`` or a
number comes back as it went in. The caller owns the transaction and the
authorization check; nothing here logs a value.
"""

from __future__ import annotations

import json

from flask import current_app

from app import db
from app.models.map_payload_version_pii import TABLE_NAME, MapPayloadVersionPii
from app.services.payload_pii_split import (
    join_payload,
    pii_digest,
    split_payload,
    version_fingerprint,
)
from app.utils import pii_crypto
from app.utils.national_id import redact_payload_national_ids

ABHA_NUMBER_DIGITS = 14


def _version_id(version):
    if version.payload_version_id is None:
        raise ValueError("The payload version has no id yet; flush it first.")
    return version.payload_version_id


def get_side_row(version, *, session=None) -> MapPayloadVersionPii | None:
    return (session or db.session).get(MapPayloadVersionPii, _version_id(version))


def _open_row(row) -> dict:
    """The opened fields of side *row*. Under the current blind key the
    opened fields must digest to the stored ``pii_digest`` (one HMAC): a blob
    and a digest from two different writes (a tampered or half-restored row)
    fail like any other open, naming the row id only."""
    version_id = row.payload_version_id
    opened = pii_crypto.open_record(
        row.sealed, row.dek_wrapped, table=TABLE_NAME, row_id=version_id.bytes, row_ref=str(version_id)
    )
    pii = {field: json.loads(text) for field, text in opened.items()}
    if row.blind_key_id == pii_crypto.blind_key_id() and pii_digest(pii) != row.pii_digest:
        raise pii_crypto.PiiCryptoError(f"Sealed record {version_id} does not match its digest.")
    return pii


def get_pii(version) -> dict:
    """The opened sealed fields of *version* (``{}`` without a side row).
    One DEK unwrap per version per request (``pii_crypto`` DEK cache)."""
    _version_id(version)
    row = get_side_row(version)
    return {} if row is None else _open_row(row)


def get_full_payload(version) -> dict:
    """``payload_data`` with the sealed fields joined back in."""
    return join_payload(version.payload_data, get_pii(version))


def _abha_number_bidx(value) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isascii() and ch.isdigit())
    if len(digits) != ABHA_NUMBER_DIGITS:
        return None
    return pii_crypto.class_index("abha_number", digits)


def _abha_address_bidx(value) -> str | None:
    text = str(value).strip().lower() if isinstance(value, str) else ""
    return pii_crypto.class_index("abha_address", text) if text else None


def split_enabled() -> bool:
    """``PAYLOAD_PII_SPLIT_ENABLED``: payload writes store the sealed set
    here and compare by ``version_fingerprint`` (part II-A)."""
    return bool(current_app.config.get("PAYLOAD_PII_SPLIT_ENABLED"))


def side_row_current(row, split, sealed_ids: frozenset[str]) -> bool:
    """True when side *row* already stores what *split* (on *sealed_ids*)
    would write: same digest under the current blind key, same sealed set,
    no new review flag. Then a write can keep the row as it is (no fresh
    DEK, no KEM wrap, no UPDATE). No decrypt."""
    return (
        row is not None
        and row.pii_digest == split.pii_digest
        and row.blind_key_id == pii_crypto.blind_key_id()
        and frozenset(row.sealed_ids or ()) == sealed_ids
        and set(split.review_flags) <= set(row.review_flags or ())
    )


def put_pii(
    version, pii: dict, flags, *, sealed_ids: frozenset[str], invalidate_cache: bool = True, session=None,
) -> MapPayloadVersionPii:
    """Seal *pii* under a fresh DEK and insert or replace the side row of
    *version*, with its digest, the sealed set it was split on
    (*sealed_ids*, stored as ``sealed_ids``), ABHA indexes and *flags*
    (field ids, added to any already stored). The
    national ID is reduced again here, so a full number never reaches the
    blob whoever calls. Does not touch ``payload_data``. Drops the
    submission's rendered section cache unless *invalidate_cache* is False
    (a bulk job flushes the whole cache once instead). *session*: a
    dedicated session the version lives in (the demo reset), else
    ``db.session``."""
    session = session or db.session
    version_id = _version_id(version)
    pii, swept = redact_payload_national_ids(pii or {})
    sealed, dek_wrapped, key_id = pii_crypto.seal_record(
        {field: json.dumps(value) for field, value in pii.items()},
        table=TABLE_NAME,
        row_id=version_id.bytes,
    )
    row = get_side_row(version, session=session)
    if row is None:
        row = MapPayloadVersionPii(payload_version_id=version_id)
        session.add(row)
    row.va_sid = version.va_sid
    row.sealed = sealed
    row.dek_wrapped = dek_wrapped
    row.key_id = key_id
    row.pii_digest = pii_digest(pii)
    row.sealed_ids = sorted(sealed_ids)
    row.abha_number_bidx = _abha_number_bidx(pii.get("abha_number"))
    row.abha_address_bidx = _abha_address_bidx(pii.get("abha_address"))
    row.blind_key_id = pii_crypto.blind_key_id()
    # Kept across rewrites: a rerun sees the already-reduced value and would
    # not flag it again.
    row.review_flags = sorted(set(row.review_flags or ()) | set(flags or ()) | set(swept))
    session.flush()
    from app.services.submission_payload_version_service import note_side_row_written

    note_side_row_written()
    if invalidate_cache:
        # Imported here: case_content_service imports the version service,
        # which imports this module inside its write function.
        from app.services.case_content_service import invalidate_section_data_cache

        invalidate_section_data_cache(version.va_sid)
    return row


def strip_version(version, sealed_ids: frozenset[str], *, invalidate_cache: bool = True) -> MapPayloadVersionPii:
    """Move the sealed set of *version* into its side row and store the
    stripped payload with its ``version_fingerprint``. Idempotent: it splits
    the joined payload (side row opened), so a rerun on a stripped version
    keeps every sealed value."""
    split = split_payload(get_full_payload(version), sealed_ids)
    row = put_pii(version, split.pii, split.review_flags, sealed_ids=sealed_ids, invalidate_cache=invalidate_cache)
    version.payload_data = split.stripped
    version.payload_fingerprint = version_fingerprint(split.stripped, row.pii_digest)
    return row


def recompute_digest(version, row, sealed_ids: frozenset[str]) -> None:
    """Recompute side *row*'s keyed values under the CURRENT blind key after
    a ``PII_BLIND_INDEX_KEY`` rotation: ``pii_digest`` and both ABHA indexes
    from the opened fields, ``blind_key_id``, and the version's
    ``payload_fingerprint``. The blob and its wrapped DEK stay byte-identical
    (no re-seal). The digest is not checked on open (it is under the old key
    by definition). *sealed_ids* is the row's own set. The caller owns the
    transaction."""
    version_id = row.payload_version_id
    opened = pii_crypto.open_record(
        row.sealed, row.dek_wrapped, table=TABLE_NAME, row_id=version_id.bytes, row_ref=str(version_id)
    )
    pii = {field: json.loads(text) for field, text in opened.items()}
    row.pii_digest = pii_digest(pii)
    row.abha_number_bidx = _abha_number_bidx(pii.get("abha_number"))
    row.abha_address_bidx = _abha_address_bidx(pii.get("abha_address"))
    row.blind_key_id = pii_crypto.blind_key_id()
    stripped = {key: value for key, value in (version.payload_data or {}).items() if key not in sealed_ids}
    version.payload_fingerprint = version_fingerprint(stripped, row.pii_digest)
