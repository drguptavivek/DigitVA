"""Split stored payload versions into payload_data plus the PII side row
(PII slice 1b part II-A; docs/kb/pii-slice-1b.md, "Backfill" and "Release
procedure").

``split_payloads`` walks EVERY payload version (every ``version_status``) in
keyset batches by ``payload_version_id``. For each one, in one transaction
per batch: the sealed set (``sealed_field_ids`` of its form type, OD9) is
sealed into ``map_payload_version_pii`` (``strip_version``), ``payload_data``
loses those keys and ``payload_fingerprint`` is recomputed under the new rule
(``version_fingerprint``), also for versions with no sealed field. Dry run by
default (counts only). Idempotent and resumable: a version already split
(side row present, no sealed key left, fingerprint current) is skipped
without a decrypt, so a rerun writes nothing and leaves every wrapped key as
it was. Each written batch is verified right after its commit: every
version's joined payload must hash to its reduced pre-strip payload, or the
run stops.

``verify_split`` checks the stored state (counts plus an opened sample);
``restore_split`` joins the side rows back into ``payload_data`` (plaintext
again) and drops them, the rollback while the KEM private key exists.

``recompute_digests`` is the blind-key rotation step: every side row whose
``blind_key_id`` is not the current key's gets its digest, ABHA indexes and
the version's fingerprint recomputed from the opened fields, without a
re-seal.

Run with ODK sync paused and the web intake closed (the release procedure):
the batch rows are locked (``FOR UPDATE``), but a concurrent writer could
still race a version between batches. Reports carry counts only, never a
value; a log line about a row that did not open names its
``payload_version_id`` (a UUID, no content) and nothing else.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter

import sqlalchemy as sa

from app import db
from app.models import MapPayloadVersionPii, VaSubmissionPayloadVersion, VaSubmissions
from app.services import payload_pii_accessor as accessor
from app.services.payload_pii_split import (
    fingerprint_of,
    join_payload,
    pii_digest,
    stored_fingerprint,
)
from app.services.pii_field_registry import sealed_field_ids
from app.services.submission_payload_version_service import canonical_payload_fingerprint
from app.utils import pii_crypto
from app.utils.national_id import redact_payload_national_ids
from app.utils.va_form.va_form_02_formtyperesolution import va_get_form_type_code_for_form

log = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 200
MAX_BATCH_SIZE = 1000
DEFAULT_SAMPLE = 200
MAX_SAMPLE = 10000


class BackfillRefused(RuntimeError):
    """A precondition refused the run. The message names no secret."""


def _content_hash(payload: dict) -> str:
    """Hash of a payload's content (sorted keys), for the in-batch check."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class _SealedSets:
    """The sealed set per form, resolved once per run (a form's type and
    flags do not change inside the release window)."""

    def __init__(self):
        self._by_form: dict[str | None, frozenset[str]] = {}

    def __call__(self, va_form_id: str | None) -> frozenset[str]:
        if va_form_id not in self._by_form:
            self._by_form[va_form_id] = sealed_field_ids(va_get_form_type_code_for_form(va_form_id))
        return self._by_form[va_form_id]


def _batches(batch_size: int, *, lock: bool):
    """Yield ``[(version, va_form_id, side_row or None)]`` in keyset order,
    side rows loaded in one query per batch (no per-row lookup)."""
    last = None
    while True:
        query = (
            sa.select(VaSubmissionPayloadVersion, VaSubmissions.va_form_id)
            .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionPayloadVersion.va_sid)
            .order_by(VaSubmissionPayloadVersion.payload_version_id)
            .limit(batch_size)
        )
        if last is not None:
            query = query.where(VaSubmissionPayloadVersion.payload_version_id > last)
        if lock:
            query = query.with_for_update(of=VaSubmissionPayloadVersion)
        rows = db.session.execute(query).all()
        if not rows:
            return
        ids = [version.payload_version_id for version, _ in rows]
        side = {
            row.payload_version_id: row
            for row in db.session.scalars(
                sa.select(MapPayloadVersionPii).where(MapPayloadVersionPii.payload_version_id.in_(ids))
            )
        }
        last = ids[-1]
        yield [(version, form_id, side.get(version.payload_version_id)) for version, form_id in rows]


def _is_split(version, side_row, sealed: frozenset[str]) -> bool:
    """Already in the split form: side row split on today's sealed set (a
    field flagged or unflagged since must move), its digest under the
    current blind key (a rotated row is rewritten), no sealed key in the
    payload, current fingerprint. Field ids only, no decrypt."""
    return (
        side_row is not None
        and frozenset(side_row.sealed_ids or ()) == sealed
        and side_row.blind_key_id == pii_crypto.blind_key_id()
        and not (sealed & set(version.payload_data or {}))
        and version.payload_fingerprint == stored_fingerprint(version.payload_data, side_row, sealed)
    )


def split_payloads(*, apply: bool = False, batch_size: int = DEFAULT_BATCH_SIZE, on_progress=None) -> dict:
    """Dry run (``apply=False``: counts, nothing written) or apply the split.

    Returns ``{"by_status": {status: {"versions", "with_sealed_fields",
    "side_rows", "to_strip", "to_recompute", "already_split"}}, "written",
    "stripped", "recomputed_only", "verified"}``. ``to_strip``: versions whose
    payload still holds a sealed key; ``to_recompute``: the rest that still
    need a side row or a new-rule fingerprint. Raises ``BackfillRefused``
    when a written batch fails its check (that batch is committed; run
    ``restore_split`` or the dump)."""
    batch_size = max(1, min(int(batch_size), MAX_BATCH_SIZE))
    sealed_for = _SealedSets()
    by_status: dict[str, Counter] = {}
    totals = Counter()
    for batch in _batches(batch_size, lock=apply):
        expected: dict = {}
        for version, form_id, side_row in batch:
            sealed = sealed_for(form_id)
            counts = by_status.setdefault(version.version_status, Counter())
            counts["versions"] += 1
            has_sealed = bool(sealed & set(version.payload_data or {}))
            counts["with_sealed_fields"] += has_sealed
            counts["side_rows"] += side_row is not None
            if _is_split(version, side_row, sealed):
                counts["already_split"] += 1
                continue
            counts["to_strip" if has_sealed else "to_recompute"] += 1
            if not apply:
                continue
            before = accessor.get_full_payload(version) if side_row is not None else (version.payload_data or {})
            expected[version.payload_version_id] = (
                version, sealed, _content_hash(redact_payload_national_ids(before)[0])
            )
            accessor.strip_version(version, sealed, invalidate_cache=False)
            totals["written"] += 1
            totals["stripped" if has_sealed else "recomputed_only"] += 1
        db.session.commit()
        if expected:
            totals["verified"] += _verify_written(expected)
        pii_crypto.clear_dek_cache()
        if on_progress:
            on_progress(f"... split-payloads: versions={sum(c['versions'] for c in by_status.values())} "
                        f"written={totals['written']}")
    if apply:
        from app.services.case_content_service import flush_section_data_cache

        totals["cache_keys_flushed"] = flush_section_data_cache()
    return {
        "by_status": {status: dict(counts) for status, counts in sorted(by_status.items())},
        **{key: totals[key] for key in ("written", "stripped", "recomputed_only", "verified")},
        "cache_keys_flushed": totals["cache_keys_flushed"],
    }


def _verify_written(expected: dict) -> int:
    """After the batch commit: each written version's joined payload must
    equal its reduced pre-strip payload, and its stored fingerprint the new
    rule's, both from the stored form and from the joined payload."""
    pii_crypto.clear_dek_cache()
    bad = 0
    for version, sealed, before_hash in expected.values():
        db.session.refresh(version)
        side_row = accessor.get_side_row(version)
        joined = accessor.get_full_payload(version)
        if (
            _content_hash(joined) != before_hash
            or version.payload_fingerprint != stored_fingerprint(version.payload_data, side_row, sealed)
            or version.payload_fingerprint != fingerprint_of(joined, sealed)
        ):
            bad += 1
    if bad:
        log.error("pii split-payloads | batch check failed for %d version(s); run stopped", bad)
        raise BackfillRefused(
            f"{bad} version(s) in the last batch do not join back to their pre-split payload; "
            "the run stopped. Investigate, then `flask pii split-payloads --restore` or restore the dump."
        )
    return len(expected)


def verify_split(*, sample: int = DEFAULT_SAMPLE, batch_size: int = DEFAULT_BATCH_SIZE) -> dict:
    """Check the stored state. Counts over every version (no decrypt):
    ``versions``, ``without_side_row``, ``sealed_key_in_payload``,
    ``fingerprint_mismatch``, ``sealed_set_changed`` (side row split on
    another set than today's: rerun ``--apply``), ``blind_key_stale`` (digest
    under a previous blind key: run ``--recompute-digests``); then an opened
    sample of side rows (``sampled``, ``sample_failed``): the opened fields
    digest to the row's ``pii_digest``, and the joined payload's fingerprint
    equals the stored one. ``ok`` is True only when every count of a problem
    is 0."""
    batch_size = max(1, min(int(batch_size), MAX_BATCH_SIZE))
    sample = max(0, min(int(sample), MAX_SAMPLE))
    sealed_for = _SealedSets()
    counts = Counter()
    current_blind = pii_crypto.blind_key_id()
    for batch in _batches(batch_size, lock=False):
        for version, form_id, side_row in batch:
            sealed = sealed_for(form_id)
            counts["versions"] += 1
            counts["without_side_row"] += side_row is None
            counts["sealed_key_in_payload"] += bool(sealed & set(version.payload_data or {}))
            if version.payload_fingerprint != stored_fingerprint(version.payload_data, side_row, sealed):
                counts["fingerprint_mismatch"] += 1
            if side_row is not None:
                counts["sealed_set_changed"] += frozenset(side_row.sealed_ids or ()) != sealed
                counts["blind_key_stale"] += side_row.blind_key_id != current_blind
    sampled = db.session.execute(
        sa.select(VaSubmissionPayloadVersion, VaSubmissions.va_form_id)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionPayloadVersion.va_sid)
        .join(MapPayloadVersionPii,
              MapPayloadVersionPii.payload_version_id == VaSubmissionPayloadVersion.payload_version_id)
        .order_by(sa.func.random())
        .limit(sample)
    ).all()
    for version, form_id in sampled:
        counts["sampled"] += 1
        row = accessor.get_side_row(version)
        try:
            opened = accessor.get_pii(version)
        except pii_crypto.PiiCryptoError as exc:
            counts["sample_failed"] += 1
            log.error("pii split-payloads verify | %s", exc)
            continue
        if pii_digest(opened) != row.pii_digest or version.payload_fingerprint != fingerprint_of(
            join_payload(version.payload_data, opened), frozenset(row.sealed_ids or ())
        ):
            counts["sample_failed"] += 1
    pii_crypto.clear_dek_cache()
    problems = (
        "without_side_row", "sealed_key_in_payload", "fingerprint_mismatch", "sealed_set_changed",
        "blind_key_stale", "sample_failed",
    )
    report = {key: counts[key] for key in ("versions", *problems[:-1], "sampled", "sample_failed")}
    report["ok"] = not any(report[key] for key in problems)
    return report


def restore_split(*, batch_size: int = DEFAULT_BATCH_SIZE, on_progress=None) -> dict:
    """Undo the split: for every version with a side row, the opened sealed
    fields go back into ``payload_data`` (PLAINTEXT again), the old-rule
    ``canonical_payload_fingerprint`` is written and the side row deleted;
    one commit per batch, resumable (a rerun finds only rows left). Refused
    with ``PAYLOAD_PII_SPLIT_ENABLED`` on (the next write would split again).
    A row that does not open is counted and kept. Returns ``{"restored",
    "failed"}``."""
    if accessor.split_enabled():
        raise BackfillRefused("Set PAYLOAD_PII_SPLIT_ENABLED=false (and restart) before --restore.")
    batch_size = max(1, min(int(batch_size), MAX_BATCH_SIZE))
    counts = Counter()
    failed_ids: set = set()
    while True:
        # Always the first batch of what is left: restored rows are deleted,
        # failed ones are skipped by id.
        query = (
            sa.select(VaSubmissionPayloadVersion)
            .join(MapPayloadVersionPii,
                  MapPayloadVersionPii.payload_version_id == VaSubmissionPayloadVersion.payload_version_id)
            .order_by(VaSubmissionPayloadVersion.payload_version_id)
            .limit(batch_size)
            .with_for_update(of=VaSubmissionPayloadVersion)
        )
        if failed_ids:
            query = query.where(VaSubmissionPayloadVersion.payload_version_id.not_in(failed_ids))
        versions = db.session.scalars(query).all()
        if not versions:
            break
        for version in versions:
            try:
                pii = accessor.get_pii(version)
            except pii_crypto.PiiCryptoError as exc:
                counts["failed"] += 1
                failed_ids.add(version.payload_version_id)
                log.error("pii split-payloads restore | %s", exc)
                continue
            joined = join_payload(version.payload_data, pii)
            version.payload_data = joined
            version.payload_fingerprint = canonical_payload_fingerprint(joined)
            db.session.delete(accessor.get_side_row(version))
            counts["restored"] += 1
        db.session.commit()
        pii_crypto.clear_dek_cache()
        if on_progress:
            on_progress(f"... split-payloads restore: restored={counts['restored']} failed={counts['failed']}")
    from app.services.case_content_service import flush_section_data_cache

    flush_section_data_cache()
    return {"restored": counts["restored"], "failed": counts["failed"]}


def recompute_digests(*, apply: bool = False, batch_size: int = DEFAULT_BATCH_SIZE, on_progress=None) -> dict:
    """After a ``PII_BLIND_INDEX_KEY`` rotation: dry run (counts) or, with
    *apply*, recompute ``pii_digest``, both ABHA indexes, ``blind_key_id``
    and the version's ``payload_fingerprint`` for every side row not on the
    current blind key (``accessor.recompute_digest``: opened, never
    re-sealed, so blobs and wrapped DEKs stay byte-identical). Keyset
    batches by ``payload_version_id``, rows locked, one commit per batch.
    Idempotent and resumable: recomputed rows leave the selection. A row
    that does not open is counted and skipped. Returns ``{"to_recompute",
    "recomputed", "failed"}``."""
    batch_size = max(1, min(int(batch_size), MAX_BATCH_SIZE))
    current = pii_crypto.blind_key_id()
    counts = Counter()
    last = None
    while True:
        query = (
            sa.select(VaSubmissionPayloadVersion, MapPayloadVersionPii)
            .join(MapPayloadVersionPii,
                  MapPayloadVersionPii.payload_version_id == VaSubmissionPayloadVersion.payload_version_id)
            .where(MapPayloadVersionPii.blind_key_id != current)
            .order_by(VaSubmissionPayloadVersion.payload_version_id)
            .limit(batch_size)
        )
        if last is not None:
            query = query.where(VaSubmissionPayloadVersion.payload_version_id > last)
        if apply:
            query = query.with_for_update(of=(VaSubmissionPayloadVersion, MapPayloadVersionPii))
        rows = db.session.execute(query).all()
        if not rows:
            break
        last = rows[-1][0].payload_version_id
        for version, row in rows:
            counts["to_recompute"] += 1
            if not apply:
                continue
            try:
                accessor.recompute_digest(version, row, frozenset(row.sealed_ids or ()))
            except pii_crypto.PiiCryptoError as exc:
                counts["failed"] += 1
                log.error("pii split-payloads recompute-digests | %s", exc)
                continue
            counts["recomputed"] += 1
        db.session.commit()
        pii_crypto.clear_dek_cache()
        if on_progress:
            on_progress(f"... recompute-digests: seen={counts['to_recompute']} recomputed={counts['recomputed']} "
                        f"failed={counts['failed']}")
    return {key: counts[key] for key in ("to_recompute", "recomputed", "failed")}


def _stripped_copy(copy, sealed: frozenset[str]):
    """An upstream-change copy reduced (national IDs) and without the sealed
    set; a non-dict (never written today) is returned as it is."""
    if not isinstance(copy, dict):
        return copy
    reduced = redact_payload_national_ids(copy)[0]
    return {key: value for key, value in reduced.items() if key not in sealed}


def strip_upstream_copies(*, apply: bool = False, batch_size: int = DEFAULT_BATCH_SIZE, on_progress=None) -> dict:
    """Strip the sealed set (and reduce national IDs) in
    ``va_submission_upstream_changes.previous_va_data`` and
    ``incoming_va_data`` written before the split: the rule ``payload_copy``
    applies from the flip on, here whatever the flag. Lossless: the versions
    a row references hold the sealed fields (in their side rows once split).
    Dry run by default (counts only). Keyset batches by
    ``upstream_change_id`` with the form joined (sealed set once per form),
    one commit per batch, compare-and-set on both columns, so a row a sync
    rewrote since it was read is ``skipped`` and the next run sees it.
    Idempotent: a stripped copy strips to itself. Returns ``{"scanned",
    "changed", "written", "skipped"}``."""
    from sqlalchemy.dialects.postgresql import JSONB

    from app.models import VaSubmissionUpstreamChange as Change

    batch_size = max(1, min(int(batch_size), MAX_BATCH_SIZE))
    sealed_for = _SealedSets()
    counts = Counter()
    last = None
    while True:
        query = (
            sa.select(Change.upstream_change_id, VaSubmissions.va_form_id,
                      Change.previous_va_data, Change.incoming_va_data)
            .join(VaSubmissions, VaSubmissions.va_sid == Change.va_sid)
            .order_by(Change.upstream_change_id)
            .limit(batch_size)
        )
        if last is not None:
            query = query.where(Change.upstream_change_id > last)
        rows = db.session.execute(query).all()
        if not rows:
            break
        last = rows[-1][0]
        for change_id, form_id, previous, incoming in rows:
            counts["scanned"] += 1
            sealed = sealed_for(form_id)
            new_previous, new_incoming = _stripped_copy(previous, sealed), _stripped_copy(incoming, sealed)
            if new_previous == previous and new_incoming == incoming:
                continue
            counts["changed"] += 1
            if not apply:
                continue
            result = db.session.execute(
                sa.update(Change)
                .where(
                    Change.upstream_change_id == change_id,
                    Change.previous_va_data == sa.type_coerce(previous, JSONB),
                    Change.incoming_va_data == sa.type_coerce(incoming, JSONB),
                )
                .values(previous_va_data=sa.type_coerce(new_previous, JSONB),
                        incoming_va_data=sa.type_coerce(new_incoming, JSONB))
                .execution_options(synchronize_session=False)
            )
            counts["written" if result.rowcount else "skipped"] += 1
        db.session.commit()
        if on_progress:
            on_progress(f"... strip-upstream-copies: scanned={counts['scanned']} changed={counts['changed']}")
    return {key: counts[key] for key in ("scanned", "changed", "written", "skipped")}
