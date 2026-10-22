"""Read and write the sealed personal data of a death-register row (PII slice 2).

Policy: docs/policy/pii-encryption-at-rest.md, "Register design"; interface for
the reader, duplicate-matching and backfill tasks: docs/kb/pii-slice-2.md.
The only code that touches ``va_death_register.pii_sealed`` and its siblings.

With ``REGISTER_PII_SPLIT_ENABLED`` on, a write seals the personal columns into
one record (one DEK, one ciphertext per field, AAD = table, field, ``death_id``)
and NULLs the plaintext columns; presence flags and blind indexes are set in
the same write. With it off nothing here changes a row, and ``write_fields``
refuses a write of a sealed attribute on a row that is already sealed
(``RegisterSplitStateError``), because writing plaintext beside a blob would be
silently undone by the next open; other attributes write normally.

Reading never needs the flag: ``open_register_pii`` opens the blob when
``pii_sealed`` is set and otherwise returns the plaintext columns, so the same
code serves flag-off, pre-backfill and sealed rows. The caller owns the
transaction and the authorization check; nothing here logs a value.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from flask import current_app

from app.models.va_web_intake import VaDeathRegister
from app.services.payload_pii_accessor import _abha_address_bidx, _abha_number_bidx
from app.utils import pii_crypto
from app.utils.phone import normalise_phone

TABLE_NAME = "va_death_register"
AUDIT_TABLE_NAME = "map_case_transitions"

#: Columns sealed one field each, in the blob under their own name.
SEALED_COLUMNS = (
    "deceased_name", "father_name", "mother_name", "informant_name", "informant_phone", "informant_phone_2",
    "abha_number", "abha_address", "address", "address_house_street", "address_village_ward",
    "address_landmark", "place_of_death", "remarks",
)
#: The GPS fix: three columns, sealed as ONE blob field ``location`` (JSON).
LOCATION_COLUMNS = ("latitude", "longitude", "accuracy_m")
LOCATION_FIELD = "location"
#: Keys of the blob.
SEALED_FIELDS = (*SEALED_COLUMNS, LOCATION_FIELD)
#: Attribute names of ``open_register_pii`` results (the shape the serialisers
#: use): every sealed column plus the three coordinates, flattened.
SEALED_ATTRS = (*SEALED_COLUMNS, *LOCATION_COLUMNS)

class RegisterSplitStateError(RuntimeError):
    """A register row is sealed but this process runs with
    ``REGISTER_PII_SPLIT_ENABLED`` off: writing plaintext would diverge from
    the blob. Turn the flag on (the normal state after the release), or
    restore the row to plaintext first."""


def split_enabled() -> bool:
    """``REGISTER_PII_SPLIT_ENABLED``: register writes seal their personal
    columns."""
    return bool(current_app.config.get("REGISTER_PII_SPLIT_ENABLED"))


def is_sealed(death: VaDeathRegister) -> bool:
    return death.pii_sealed is not None


def _death_id(death: VaDeathRegister) -> uuid.UUID:
    # Ids are generated on flush, but the AAD binds the ciphertext to the id:
    # fix it before sealing.
    if death.death_id is None:
        death.death_id = uuid.uuid4()
    return death.death_id


# ---------------------------------------------------------------------------
# Blind indexes
# ---------------------------------------------------------------------------

def phone_bidx(value) -> str | None:
    """``phone`` class index of an informant phone: separators dropped, a
    leading ``+91``, ``91`` or ``0`` stripped to the 10 digits; anything else
    (older free text) is sealed with no index. The same normalisation serves
    both columns, so a number matches in either."""
    digits = normalise_phone(value) if isinstance(value, str) else None
    return pii_crypto.class_index("phone", digits) if digits else None


def abha_number_bidx(value) -> str | None:
    return _abha_number_bidx(value)


def abha_address_bidx(value) -> str | None:
    return _abha_address_bidx(value)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _opened(death: VaDeathRegister, only=None) -> dict:
    """Blob of *death* as ``{field: value}`` (location left whole)."""
    names = None if only is None else [n for n in SEALED_FIELDS if n in only]
    text = pii_crypto.open_record(
        death.pii_sealed, death.pii_dek_wrapped, table=TABLE_NAME, row_id=_death_id(death).bytes,
        row_ref=str(death.death_id), only=names,
    )
    return {field: json.loads(value) for field, value in text.items()}


def open_register_pii(rows, *, only=None) -> dict:
    """``{death_id: {attr: value}}`` for each row in *rows* (loaded
    ``VaDeathRegister`` objects), holding the sealed attributes
    (``SEALED_ATTRS``, coordinates flattened; *only* limits them, and a row's
    DEK is unwrapped only when a requested field lives in its blob). A sealed
    row is opened from its blob; any other row returns its plaintext columns,
    so flag-off and pre-backfill rows read exactly as before. No query: the
    blob is a column of the row. One DEK unwrap per sealed row (``pii_crypto``
    DEK cache). Callers authorize first; a row that does not open raises
    ``PiiCryptoError`` naming the row id only."""
    wanted = SEALED_ATTRS if only is None else tuple(a for a in SEALED_ATTRS if a in only)
    fields = {LOCATION_FIELD if a in LOCATION_COLUMNS else a for a in wanted}
    result = {}
    for death in rows:
        if death.pii_sealed is None:
            result[death.death_id] = {attr: getattr(death, attr) for attr in wanted}
            continue
        blob = _opened(death, only=fields)
        location = blob.get(LOCATION_FIELD) or {}
        values = {}
        for attr in wanted:
            values[attr] = location.get(attr) if attr in LOCATION_COLUMNS else blob.get(attr)
        result[death.death_id] = values
    return result


def current_values(death: VaDeathRegister, names=None) -> dict:
    """The sealed attributes of one row (``open_register_pii``), for a writer
    that needs the stored value before changing it."""
    return open_register_pii([death], only=names)[death.death_id]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def seal_register_pii(
    death: VaDeathRegister, fields: dict | None = None, *, keep_plaintext: bool = False
) -> None:
    """Seal *death*'s personal data under one fresh DEK and NULL the plaintext
    columns (*keep_plaintext*: leave them, for the backfill's hold before
    strip, ``register_pii_backfill_service``). The record is the blob already stored (if any), overlaid by any
    plaintext still on the object (a new row built with plaintext, or an
    unsealed row), overlaid by *fields* (``{attr: value}`` over
    ``SEALED_ATTRS``; ``None`` clears a value). Sets ``pii_sealed``,
    ``pii_dek_wrapped``, ``pii_key_id``, ``pii_blind_key_id``,
    ``pii_sealed_at``, the four presence flags and the four blind indexes.
    ``captured_at`` is the caller's: ``has_location`` must match it (CHECK).
    Does not check the flag: callers go through ``write_fields``. The object
    needs no database access; ``death_id`` is assigned here when missing."""
    row_id = _death_id(death)
    merged = {} if death.pii_sealed is None else current_values(death)
    for attr in SEALED_ATTRS:
        if getattr(death, attr) is not None:
            merged[attr] = getattr(death, attr)
    for attr, value in (fields or {}).items():
        if attr not in SEALED_ATTRS:
            raise ValueError("Not a sealed register attribute.")
        merged[attr] = value

    blob = {a: json.dumps(merged[a]) for a in SEALED_COLUMNS if merged.get(a) is not None}
    # A fix needs both coordinates (CHECK); accuracy has no meaning alone.
    has_location = merged.get("latitude") is not None and merged.get("longitude") is not None
    if has_location:
        blob[LOCATION_FIELD] = json.dumps({a: merged.get(a) for a in LOCATION_COLUMNS})
    sealed, dek_wrapped, key_id = pii_crypto.seal_record(blob, table=TABLE_NAME, row_id=row_id.bytes)

    if not keep_plaintext:
        for attr in SEALED_ATTRS:
            setattr(death, attr, None)
    death.pii_sealed = sealed
    death.pii_dek_wrapped = dek_wrapped
    death.pii_key_id = key_id
    death.pii_blind_key_id = pii_crypto.blind_key_id()
    death.pii_sealed_at = datetime.now(UTC)
    death.has_deceased_name = merged.get("deceased_name") is not None
    death.has_informant_phone = merged.get("informant_phone") is not None
    death.has_informant_phone_2 = merged.get("informant_phone_2") is not None
    death.has_location = has_location
    death.informant_phone_bidx = phone_bidx(merged.get("informant_phone"))
    death.informant_phone_2_bidx = phone_bidx(merged.get("informant_phone_2"))
    death.abha_number_bidx = abha_number_bidx(merged.get("abha_number"))
    death.abha_address_bidx = abha_address_bidx(merged.get("abha_address"))


def write_fields(death: VaDeathRegister, values: dict) -> None:
    """Set register attributes *values* (``{attr: value}``) on *death*: the
    one door for a writer that changes existing rows. Flag off: plain
    ``setattr``, and ``RegisterSplitStateError`` (before anything is set) when a
    sealed row would get a sealed attribute written. Flag on: non-sealed attributes are set, sealed ones are
    re-sealed together with the rest of the record (one DEK per call).
    Nothing to write is not a write: no refusal."""
    if not values:
        return
    if not split_enabled():
        # Only a write that touches a sealed attribute would diverge from the
        # blob; the rest (age, dates, status) writes normally on a sealed row.
        if is_sealed(death) and any(attr in SEALED_ATTRS for attr in values):
            raise RegisterSplitStateError(
                "A register row has sealed fields in pii_sealed but REGISTER_PII_SPLIT_ENABLED is off; "
                "the write was refused."
            )
        for attr, value in values.items():
            setattr(death, attr, value)
        return
    sealed_values = {}
    for attr, value in values.items():
        if attr in SEALED_ATTRS:
            sealed_values[attr] = value
        else:
            setattr(death, attr, value)
    if sealed_values:
        seal_register_pii(death, sealed_values)


def seal_new_row(death: VaDeathRegister) -> None:
    """A new row built with plaintext: with the flag on, seal it before it is
    added (so the plaintext never reaches the table); with it off, no-op."""
    if split_enabled():
        seal_register_pii(death)


# ---------------------------------------------------------------------------
# Audit rows (map_case_transitions.changes)
# ---------------------------------------------------------------------------

def seal_audit_changes(changes: dict | None, transition_id: uuid.UUID):
    """``(changes, changes_dek_wrapped, changes_key_id)`` for an audit row.
    *changes* is ``{attr: {"old": ..., "new": ...}}``; the old and new values
    of sealed attributes become ciphertexts (one DEK for the row, AAD =
    ``map_case_transitions``, ``<attr>.old|new``, *transition_id*); other
    fields stay as they are. Without a sealed attribute: ``(changes, None,
    None)``. Does not check the flag: the caller (``case_transition_service``)
    does."""
    names = [name for name in (changes or {}) if name in SEALED_ATTRS]
    if not names:
        return changes, None, None
    plain = {
        f"{name}.{side}": json.dumps(changes[name][side])
        for name in names for side in ("old", "new") if side in changes[name]
    }
    sealed, dek_wrapped, key_id = pii_crypto.seal_record(
        plain, table=AUDIT_TABLE_NAME, row_id=transition_id.bytes
    )
    out = {
        name: ({side: sealed[f"{name}.{side}"] for side in ("old", "new") if side in change}
               if name in names else change)
        for name, change in changes.items()
    }
    return out, dek_wrapped, key_id


def open_audit_changes(transition) -> dict | None:
    """``transition.changes`` with sealed old/new values opened (rows without
    ``changes_dek_wrapped`` return ``changes`` as stored). For the admin audit
    tool only; never an API."""
    if transition.changes is None or transition.changes_dek_wrapped is None:
        return transition.changes
    names = [name for name in transition.changes if name in SEALED_ATTRS]
    sealed = {
        f"{name}.{side}": value
        for name in names for side, value in transition.changes[name].items()
    }
    opened = pii_crypto.open_record(
        sealed, transition.changes_dek_wrapped, table=AUDIT_TABLE_NAME,
        row_id=transition.transition_id.bytes, row_ref=str(transition.transition_id),
    )
    return {
        name: ({side: json.loads(opened[f"{name}.{side}"]) for side in change} if name in names else change)
        for name, change in transition.changes.items()
    }

