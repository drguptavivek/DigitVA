"""Seal the stored death-register rows (PII slice 2 T4; docs/kb/pii-slice-2.md,
"Backfill, verify, strip, restore").

``seal_register`` seals every ``va_death_register`` row's personal columns
into ``pii_sealed`` through the accessor and KEEPS the plaintext columns until
``strip_register`` (after ``verify_register`` and the hold). It also seals the
old/new values of sealed attributes inside ``map_case_transitions.changes``
(``seal_audit_changes``) and scrubs the legacy stage-0 ``mask`` member from
identifier entries there, but only in ``strip_register``: until the strip,
``--apply`` leaves the audit rows untouched, so everything stays recoverable
through the hold. Dry run by default (counts only). Idempotent and
resumable: a row sealed under the current blind key whose sealed set still
matches its plaintext is skipped without a decrypt, so a rerun leaves every
wrapped key as it was. Keyset batches by primary key, rows locked
(``FOR UPDATE``), one commit per batch; each written batch is reopened after
its commit and compared with the plaintext, or the run stops.

Writes are Core updates that set ``updated_at = updated_at``: the column has
``onupdate`` and drives keyset cursors and the worklist sort, so a backfill
must not reorder the cases.

``verify_register`` checks the stored state (counts without decrypting, then
an opened random sample); ``strip_register`` NULLs the sealed plaintext columns
of rows that verify, are past the hold and open to exactly their plaintext;
``restore_register`` writes the opened values back (rollback, flag off);
``recompute_digests`` is the blind-key rotation step.

Run with the web intake closed and ODK sync paused: the batch rows are locked,
but a writer could still race a row between batches. Reports carry counts
only, never a value or a row id; a log line never names a row.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import aliased

from app import db
from app.models import MapCaseTransition, VaDeathRegister
from app.services import register_pii_accessor as accessor
from app.utils import pii_crypto

log = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 200
MAX_BATCH_SIZE = 1000
DEFAULT_SAMPLE = 200
MAX_SAMPLE = 10000
DEFAULT_HOLD_DAYS = 30

#: Columns the accessor sets besides the plaintext ones.
_SEAL_COLUMNS = (
    "pii_sealed", "pii_dek_wrapped", "pii_key_id", "pii_blind_key_id", "pii_sealed_at",
    "informant_phone_bidx", "informant_phone_2_bidx", "abha_number_bidx", "abha_address_bidx",
    "has_deceased_name", "has_informant_phone", "has_informant_phone_2", "has_location",
)
_BIDX_COLUMNS = ("informant_phone_bidx", "informant_phone_2_bidx", "abha_number_bidx", "abha_address_bidx")
#: presence flag -> the blob key whose presence it records
_FLAG_FIELDS = {
    "has_deceased_name": "deceased_name",
    "has_informant_phone": "informant_phone",
    "has_informant_phone_2": "informant_phone_2",
    "has_location": accessor.LOCATION_FIELD,
}


class BackfillRefused(RuntimeError):
    """A precondition refused the run. The message names no secret or row."""


def _clamp(batch_size) -> int:
    return max(1, min(int(batch_size), MAX_BATCH_SIZE))


def _plain(row) -> dict:
    return {attr: getattr(row, attr) for attr in accessor.SEALED_ATTRS}


def _has_plain(plain: dict) -> bool:
    return any(value is not None for value in plain.values())


def _expected_fields(plain: dict) -> set[str]:
    """Blob keys the plaintext columns call for."""
    fields = {c for c in accessor.SEALED_COLUMNS if plain[c] is not None}
    if plain["latitude"] is not None and plain["longitude"] is not None:
        fields.add(accessor.LOCATION_FIELD)
    return fields


def _bidx(values: dict) -> dict:
    return {
        "informant_phone_bidx": accessor.phone_bidx(values.get("informant_phone")),
        "informant_phone_2_bidx": accessor.phone_bidx(values.get("informant_phone_2")),
        "abha_number_bidx": accessor.abha_number_bidx(values.get("abha_number")),
        "abha_address_bidx": accessor.abha_address_bidx(values.get("abha_address")),
    }


def _update(death_id, values: dict):
    """Core update of one register row with ``updated_at`` pinned."""
    return db.session.execute(
        sa.update(VaDeathRegister)
        .where(VaDeathRegister.death_id == death_id)
        .values(**values, updated_at=VaDeathRegister.updated_at)
        .execution_options(synchronize_session=False)
    )


def _batches(model, pk, batch_size: int, *, lock: bool, where=()):
    """Yield lists of *model* rows in keyset order of *pk*; *where*
    conditions are ANDed; rows locked when *lock*."""
    last = None
    while True:
        query = sa.select(model).where(*where).order_by(pk).limit(batch_size)
        if last is not None:
            query = query.where(pk > last)
        if lock:
            query = query.with_for_update(of=model)
        rows = db.session.scalars(query).all()
        if not rows:
            return
        last = getattr(rows[-1], pk.key)
        yield rows


def _register_batches(batch_size: int, *, lock: bool, where=()):
    return _batches(VaDeathRegister, VaDeathRegister.death_id, batch_size, lock=lock, where=where)


def _audit_batches(batch_size: int, *, lock: bool, where=()):
    return _batches(
        MapCaseTransition, MapCaseTransition.transition_id, batch_size, lock=lock,
        where=(MapCaseTransition.changes.is_not(None), *where),
    )


def _case_stripped():
    """SQL condition on ``map_case_transitions``: the case's register row is
    stripped, i.e. sealed and with every sealed plaintext column NULL. A row
    still inside the hold keeps its plaintext, so its audit rows stay out."""
    register = aliased(VaDeathRegister)
    return sa.exists().where(
        register.death_id == MapCaseTransition.death_id,
        register.pii_sealed.is_not(None),
        *[getattr(register, attr).is_(None) for attr in accessor.SEALED_ATTRS],
    )


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def _is_done(row, plain: dict, current_blind: str) -> bool:
    """Sealed under the current blind key, with the sealed set the plaintext
    (if still there) calls for. Key names only, no decrypt."""
    if row.pii_sealed is None or row.pii_blind_key_id != current_blind:
        return False
    return not _has_plain(plain) or set(row.pii_sealed) == _expected_fields(plain)


def _sealed_values(death_id, plain: dict) -> dict:
    """Seal *plain* through the accessor on a transient object (the session
    row stays clean, so no ORM flush can run ``onupdate``)."""
    transient = VaDeathRegister(death_id=death_id, **plain)
    accessor.seal_register_pii(transient, keep_plaintext=True)
    return {column: getattr(transient, column) for column in _SEAL_COLUMNS}


def _scrub_mask(changes: dict) -> dict:
    """*changes* without the legacy ``mask`` member of identifier entries
    (``identifier:<code>`` -> ``{"old": {...}, "new": {...}}``)."""
    out = changes
    for name, change in changes.items():
        if not (name.startswith("identifier:") and isinstance(change, dict)):
            continue
        for side, trace in change.items():
            if isinstance(trace, dict) and "mask" in trace:
                if out is changes:
                    out = {k: dict(v) if isinstance(v, dict) else v for k, v in changes.items()}
                out[name][side] = {k: v for k, v in trace.items() if k != "mask"}
    return out


def _sealable_names(changes: dict) -> list[str]:
    return [name for name in changes if name in accessor.SEALED_ATTRS]


def seal_register(*, apply: bool = False, batch_size: int = DEFAULT_BATCH_SIZE, on_progress=None) -> dict:
    """Dry run (``apply=False``: counts, nothing written) or seal.

    Register counts: ``rows``, ``already_sealed``, ``to_seal`` (unsealed, or
    sealed under an old blind key / other sealed set with the plaintext still
    there), ``stale_blind_key`` (sealed, plaintext gone, old blind key: run
    ``--recompute-digests``), ``written``, ``verified``. Register rows only;
    the audit rows are ``seal_audit``'s (run by the strip). Raises
    ``BackfillRefused`` when a written batch fails its check (that batch is
    committed; run ``restore_register`` or the dump)."""
    batch_size = _clamp(batch_size)
    current = pii_crypto.blind_key_id()
    counts = Counter()
    for batch in _register_batches(batch_size, lock=apply):
        written = {}
        for row in batch:
            counts["rows"] += 1
            plain = _plain(row)
            if _is_done(row, plain, current):
                counts["already_sealed"] += 1
                continue
            if row.pii_sealed is not None and not _has_plain(plain):
                counts["stale_blind_key"] += 1
                continue
            counts["to_seal"] += 1
            if not apply:
                continue
            _update(row.death_id, _sealed_values(row.death_id, plain))
            written[row.death_id] = plain
            counts["written"] += 1
        db.session.commit()
        if written:
            counts["verified"] += _verify_written(written)
        pii_crypto.clear_dek_cache()
        if on_progress:
            on_progress(f"... seal-register: rows={counts['rows']} written={counts['written']}")
    keys = ("rows", "already_sealed", "to_seal", "stale_blind_key", "written", "verified")
    return {key: counts[key] for key in keys}


def _verify_written(expected: dict) -> int:
    """After the batch commit: each written row opens to exactly its plaintext
    (still in the columns), with the bidx and presence flags the plaintext
    gives."""
    pii_crypto.clear_dek_cache()
    db.session.expire_all()
    rows = db.session.scalars(
        sa.select(VaDeathRegister).where(VaDeathRegister.death_id.in_(list(expected)))
    ).all()
    bad = 0 if len(rows) == len(expected) else len(expected) - len(rows)
    for row in rows:
        plain = expected[row.death_id]
        try:
            opened = accessor.current_values(row)
        except pii_crypto.PiiCryptoError:
            bad += 1
            continue
        if (
            opened != plain
            or _plain(row) != plain
            or any(getattr(row, c) != v for c, v in _bidx(plain).items())
            or any(getattr(row, f) != (k in _expected_fields(plain)) for f, k in _FLAG_FIELDS.items())
        ):
            bad += 1
    if bad:
        log.error("pii seal-register | batch check failed for %d row(s); run stopped", bad)
        raise BackfillRefused(
            f"{bad} row(s) in the last batch do not open to their plaintext; the run stopped. "
            "Investigate, then `flask pii seal-register --restore` or restore the dump."
        )
    return len(expected)


_AUDIT_KEYS = ("audit_rows", "audit_to_seal", "audit_mask_to_scrub", "audit_skipped",
               "audit_written", "audit_verified")


def seal_audit(
    *, apply: bool = False, batch_size: int = DEFAULT_BATCH_SIZE, on_progress=None, stripped_only: bool = False
) -> dict:
    """Seal the sealed-attribute values of ``map_case_transitions.changes``
    and scrub ``mask``; dry run unless *apply*. Run by ``strip_register`` (the
    audit plaintext stays recoverable until then). Counts: ``audit_rows``
    (with ``changes``, not yet sealed), ``audit_to_seal``,
    ``audit_mask_to_scrub``, ``audit_skipped`` (a sealed attribute whose entry
    is not ``{old, new}``), ``audit_written``, ``audit_verified``. One commit
    per batch, each written row reopened. With *stripped_only* (the strip's
    call) only rows of cases whose register row is stripped are seen; the
    rows of held cases stay plaintext, ``mask`` included, until a later run.
    The dry run without it counts every case (what the strip will do in the end)."""
    batch_size = _clamp(batch_size)
    counts = Counter()
    where = (MapCaseTransition.changes_dek_wrapped.is_(None), *((_case_stripped(),) if stripped_only else ()))
    for batch in _audit_batches(batch_size, lock=apply, where=where):
        written = {}
        for row in batch:
            counts["audit_rows"] += 1
            changes = row.changes
            scrubbed = _scrub_mask(changes)
            names = _sealable_names(scrubbed)
            if names and not all(isinstance(scrubbed[n], dict) for n in names):
                counts["audit_skipped"] += 1
                continue
            if scrubbed is not changes:
                counts["audit_mask_to_scrub"] += 1
            if names:
                counts["audit_to_seal"] += 1
            if scrubbed is changes and not names:
                continue
            if not apply:
                continue
            new, dek_wrapped, key_id = accessor.seal_audit_changes(scrubbed, row.transition_id)
            db.session.execute(
                sa.update(MapCaseTransition)
                .where(MapCaseTransition.transition_id == row.transition_id)
                .values(changes=sa.type_coerce(new, JSONB), changes_dek_wrapped=dek_wrapped, changes_key_id=key_id)
                .execution_options(synchronize_session=False)
            )
            written[row.transition_id] = scrubbed
            counts["audit_written"] += 1
        db.session.commit()
        if written:
            counts["audit_verified"] += _verify_audit_written(written)
        pii_crypto.clear_dek_cache()
        if on_progress:
            on_progress(f"... seal-register audit: rows={counts['audit_rows']} written={counts['audit_written']}")
    return {key: counts[key] for key in _AUDIT_KEYS}


def _verify_audit_written(expected: dict) -> int:
    pii_crypto.clear_dek_cache()
    db.session.expire_all()
    rows = db.session.scalars(
        sa.select(MapCaseTransition).where(MapCaseTransition.transition_id.in_(list(expected)))
    ).all()
    bad = len(expected) - len(rows)
    for row in rows:
        try:
            ok = accessor.open_audit_changes(row) == expected[row.transition_id]
        except pii_crypto.PiiCryptoError:
            ok = False
        bad += not ok
    if bad:
        log.error("pii seal-register | audit batch check failed for %d row(s); run stopped", bad)
        raise BackfillRefused(
            f"{bad} audit row(s) in the last batch do not open to their original changes; the run "
            "stopped. Investigate, then `flask pii seal-register --restore` or restore the dump."
        )
    return len(expected)


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

#: Counts that make ``verify_register`` fail.
_PROBLEMS = (
    "unsealed", "blind_key_stale", "flag_mismatch", "sealed_set_changed", "audit_unsealed", "audit_mask",
    "sample_failed",
)


def verify_register(
    *, sample: int = DEFAULT_SAMPLE, batch_size: int = DEFAULT_BATCH_SIZE, after_strip: bool = False
) -> dict:
    """Check the stored state. Without decrypting, over every row: ``rows``,
    ``unsealed`` (no ``pii_sealed``), ``blind_key_stale`` (index under a
    previous blind key: ``--recompute-digests``), ``flag_mismatch`` (a
    presence flag that disagrees with the blob's keys), ``sealed_set_changed``
    (plaintext still there and the blob's keys differ: rerun ``--apply``);
    with *after_strip*, over the audit rows: ``audit_unsealed`` (sealed
    attribute in plain ``changes``), ``audit_mask`` (legacy member left), only
    of cases whose register row is stripped (held cases stay plaintext); both
    0 before (the audit rows are sealed by the strip, so before it they are
    expected, not a problem). Then an opened random
    sample (``sampled``, ``sample_failed``): a register row opens, equals its
    plaintext when that is still there, and its recomputed indexes equal the
    stored ones; an audit row opens. ``ok`` only when every problem count is
    0."""
    batch_size = _clamp(batch_size)
    sample = max(0, min(int(sample), MAX_SAMPLE))
    current = pii_crypto.blind_key_id()
    counts = Counter()
    for batch in _register_batches(batch_size, lock=False):
        for row in batch:
            counts["rows"] += 1
            if row.pii_sealed is None:
                counts["unsealed"] += 1
                continue
            keys = set(row.pii_sealed)
            counts["blind_key_stale"] += row.pii_blind_key_id != current
            counts["flag_mismatch"] += any(getattr(row, f) != (k in keys) for f, k in _FLAG_FIELDS.items())
            plain = _plain(row)
            counts["sealed_set_changed"] += _has_plain(plain) and keys != _expected_fields(plain)
    for batch in _audit_batches(batch_size, lock=False, where=(_case_stripped(),)) if after_strip else ():
        for row in batch:
            counts["audit_mask"] += _scrub_mask(row.changes) is not row.changes
            counts["audit_unsealed"] += row.changes_dek_wrapped is None and bool(_sealable_names(row.changes))

    sampled = db.session.scalars(
        sa.select(VaDeathRegister).where(VaDeathRegister.pii_sealed.is_not(None))
        .order_by(sa.func.random()).limit(sample)
    ).all()
    for row in sampled:
        counts["sampled"] += 1
        try:
            opened = accessor.current_values(row)
        except pii_crypto.PiiCryptoError:
            counts["sample_failed"] += 1
            continue
        plain = _plain(row)
        if (_has_plain(plain) and opened != plain) or any(
            getattr(row, c) != v for c, v in _bidx(opened).items()
        ):
            counts["sample_failed"] += 1
    audit_sample = db.session.scalars(
        sa.select(MapCaseTransition).where(MapCaseTransition.changes_dek_wrapped.is_not(None))
        .order_by(sa.func.random()).limit(sample)
    ).all()
    for row in audit_sample:
        counts["sampled"] += 1
        try:
            accessor.open_audit_changes(row)
        except pii_crypto.PiiCryptoError:
            counts["sample_failed"] += 1
    pii_crypto.clear_dek_cache()
    report = {key: counts[key] for key in ("rows", *_PROBLEMS[:-1], "sampled", "sample_failed")}
    report["ok"] = not any(report[key] for key in _PROBLEMS)
    return report


# ---------------------------------------------------------------------------
# Strip
# ---------------------------------------------------------------------------

def strip_register(
    *, hold_days: int = DEFAULT_HOLD_DAYS, sample: int = DEFAULT_SAMPLE,
    batch_size: int = DEFAULT_BATCH_SIZE, on_progress=None,
) -> dict:
    """NULL the sealed plaintext columns. Refuses (``BackfillRefused``) unless
    ``verify_register`` passes. A row is stripped only when its
    ``pii_sealed_at`` is at least *hold_days* old (else ``held``) and it opens
    to exactly the plaintext about to go (else ``failed``, kept). Presence
    flags stay true. Then ``seal_audit(apply=True, stripped_only=True)`` seals
    the audit rows of cases whose register row is stripped (in this or an
    earlier run), the step that makes their plaintext unrecoverable except by
    ``restore_register``; held cases' audit rows wait for a later run. Idempotent and resumable (a
    stripped row has no plaintext left to select). Returns ``{"stripped",
    "held", "failed", "audit_written", "audit_skipped"}``."""
    batch_size = _clamp(batch_size)
    report = verify_register(sample=sample, batch_size=batch_size)
    if not report["ok"]:
        raise BackfillRefused("The register does not verify; run `flask pii seal-register --verify`.")
    cutoff = datetime.now(UTC) - timedelta(days=max(0, int(hold_days)))
    has_plain = sa.or_(*[getattr(VaDeathRegister, attr).is_not(None) for attr in accessor.SEALED_ATTRS])
    counts = Counter()
    nulls = {attr: None for attr in accessor.SEALED_ATTRS}
    for batch in _register_batches(batch_size, lock=True, where=(VaDeathRegister.pii_sealed.is_not(None), has_plain)):
        for row in batch:
            if row.pii_sealed_at is None or row.pii_sealed_at > cutoff:
                counts["held"] += 1
                continue
            plain = _plain(row)
            try:
                same = accessor.current_values(row) == plain
            except pii_crypto.PiiCryptoError:
                same = False
            if not same:
                counts["failed"] += 1
                continue
            _update(row.death_id, nulls)
            counts["stripped"] += 1
        db.session.commit()
        pii_crypto.clear_dek_cache()
        if on_progress:
            on_progress(f"... seal-register strip: stripped={counts['stripped']} held={counts['held']} "
                        f"failed={counts['failed']}")
    audit = seal_audit(apply=True, batch_size=batch_size, on_progress=on_progress, stripped_only=True)
    counts.update(audit_written=audit["audit_written"], audit_skipped=audit["audit_skipped"])
    return {key: counts[key] for key in ("stripped", "held", "failed", "audit_written", "audit_skipped")}


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def restore_register(*, batch_size: int = DEFAULT_BATCH_SIZE, on_progress=None) -> dict:
    """Undo the seal: opened values go back into the plaintext columns, the
    ``pii_*`` columns and indexes are cleared, audit ``changes`` are opened
    again. One commit per batch, resumable (a restored row leaves the
    selection). Refused with ``REGISTER_PII_SPLIT_ENABLED`` on (the next write
    would seal again). A row that does not open is counted and kept. Returns
    ``{"restored", "failed", "audit_restored", "audit_failed"}``."""
    if accessor.split_enabled():
        raise BackfillRefused("Set REGISTER_PII_SPLIT_ENABLED=false (and restart) before --restore.")
    batch_size = _clamp(batch_size)
    counts = Counter()
    cleared = {column: None for column in _SEAL_COLUMNS if not column.startswith("has_")}
    cleared["pii_sealed"] = sa.null()  # a Python None would be stored as JSON null, not SQL NULL
    for batch in _register_batches(batch_size, lock=True, where=(VaDeathRegister.pii_sealed.is_not(None),)):
        for row in batch:
            try:
                opened = accessor.current_values(row)
            except pii_crypto.PiiCryptoError:
                counts["failed"] += 1
                continue
            _update(row.death_id, {
                **opened, **cleared,
                "has_deceased_name": opened["deceased_name"] is not None,
                "has_informant_phone": opened["informant_phone"] is not None,
                "has_informant_phone_2": opened["informant_phone_2"] is not None,
                "has_location": opened["latitude"] is not None,
            })
            counts["restored"] += 1
        db.session.commit()
        pii_crypto.clear_dek_cache()
        if on_progress:
            on_progress(f"... seal-register restore: restored={counts['restored']} failed={counts['failed']}")
    for batch in _audit_batches(batch_size, lock=True, where=(MapCaseTransition.changes_dek_wrapped.is_not(None),)):
        for row in batch:
            try:
                opened = accessor.open_audit_changes(row)
            except pii_crypto.PiiCryptoError:
                counts["audit_failed"] += 1
                continue
            db.session.execute(
                sa.update(MapCaseTransition)
                .where(MapCaseTransition.transition_id == row.transition_id)
                .values(changes=sa.type_coerce(opened, JSONB), changes_dek_wrapped=None, changes_key_id=None)
                .execution_options(synchronize_session=False)
            )
            counts["audit_restored"] += 1
        db.session.commit()
        pii_crypto.clear_dek_cache()
    return {key: counts[key] for key in ("restored", "failed", "audit_restored", "audit_failed")}


# ---------------------------------------------------------------------------
# Blind-key rotation
# ---------------------------------------------------------------------------

def recompute_digests(*, apply: bool = False, batch_size: int = DEFAULT_BATCH_SIZE, on_progress=None) -> dict:
    """After a ``PII_BLIND_INDEX_KEY`` rotation: dry run (counts) or, with
    *apply*, recompute the four indexes and ``pii_blind_key_id`` of every
    sealed row not on the current blind key, from the opened values and
    without re-sealing (blob and wrapped DEK stay byte-identical). Locked
    keyset batches, one commit per batch, idempotent and resumable. A row
    that does not open is counted and skipped. Returns ``{"to_recompute",
    "recomputed", "failed"}``."""
    batch_size = _clamp(batch_size)
    current = pii_crypto.blind_key_id()
    counts = Counter()
    where = (VaDeathRegister.pii_sealed.is_not(None), VaDeathRegister.pii_blind_key_id.is_distinct_from(current))
    for batch in _register_batches(batch_size, lock=apply, where=where):
        for row in batch:
            counts["to_recompute"] += 1
            if not apply:
                continue
            try:
                opened = accessor.current_values(row)
            except pii_crypto.PiiCryptoError:
                counts["failed"] += 1
                continue
            _update(row.death_id, {**_bidx(opened), "pii_blind_key_id": current})
            counts["recomputed"] += 1
        db.session.commit()
        pii_crypto.clear_dek_cache()
        if on_progress:
            on_progress(f"... recompute-digests: seen={counts['to_recompute']} "
                        f"recomputed={counts['recomputed']} failed={counts['failed']}")
    return {key: counts[key] for key in ("to_recompute", "recomputed", "failed")}
