"""Sweep stored data for national IDs (PII slice 1a; docs/kb/pii-slice-1a.md).

Ingest reduces ``Id10073`` and masks national-ID digit runs in free text from
slice 1a on (``app/utils/national_id.py``). This sweep finds and, with
``apply``, rewrites what was stored before: every payload version (every
``version_status``), the upstream-change copies, web-intake draft sections,
draft prefill and meta, and the register's free text.

Dry run by default; it reports counts by table, column and field id only,
never a value or a row id. ``apply`` is the caller's after a verified backup
(``confirm_db_backup``); it rewrites in keyset batches by primary key, one
commit per batch, and only where the stored value is still the one read
(compare-and-set), so a concurrent sync or save is never overwritten: that
row counts as ``skipped`` and the next run sees it. Idempotent: a rerun finds
nothing to change. Resumable: an interrupted run keeps every committed batch.

Rewriting ``payload_data`` is safe for change detection:
``normalize_payload_for_fingerprint`` reduces national IDs on both sides, so
a reduced stored version and full incoming ODK data compare equal
(tests/services/test_national_id_sync_rerun.py). The stored
``payload_fingerprint`` column, written but never compared, is recomputed
with the row (``stored_payload_fingerprint``: the new rule once
``PAYLOAD_PII_SPLIT_ENABLED`` is on).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from flask import current_app
from sqlalchemy.dialects.postgresql import JSONB

from app import db
from app.models import (
    VaDbBackup,
    VaDeathRegister,
    VaSubmissionPayloadVersion,
    VaSubmissionUpstreamChange,
    VaWebIntakeDraft,
    VaWebIntakeDraftSection,
)
from app.services.submission_payload_version_service import stored_payload_fingerprint
from app.utils.national_id import redact_national_id_digits, redact_payload_national_ids

log = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 200
MAX_BATCH_SIZE = 1000

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SweepTarget:
    table: str
    model: type
    pk: str
    json_columns: tuple[str, ...] = ()
    text_columns: tuple[str, ...] = ()


TARGETS: tuple[SweepTarget, ...] = (
    SweepTarget("va_submission_payload_versions", VaSubmissionPayloadVersion, "payload_version_id",
                json_columns=("payload_data",)),
    SweepTarget("va_submission_upstream_changes", VaSubmissionUpstreamChange, "upstream_change_id",
                json_columns=("previous_va_data", "incoming_va_data")),
    SweepTarget("va_web_intake_draft_sections", VaWebIntakeDraftSection, "section_row_id",
                json_columns=("data",)),
    SweepTarget("va_web_intake_drafts", VaWebIntakeDraft, "draft_id", json_columns=("prefill", "meta")),
    SweepTarget("va_death_register", VaDeathRegister, "death_id", text_columns=("remarks", "place_of_death")),
)
TABLES = tuple(target.table for target in TARGETS)


class SweepRefused(RuntimeError):
    """The backup gate refused an apply. The message names no secret."""


def confirm_db_backup(reference: str | None, *, allow_old: bool = False) -> VaDbBackup:
    """The recorded, successful dump *reference* names (its object key or its
    sha256), or ``SweepRefused``. AGENTS.md "Protect data": no bulk rewrite
    without a verified backup. A pruned dump does not count: it is gone. A
    dump started more than ``PII_BACKUP_MAX_AGE_HOURS`` (default 24) ago is
    refused unless *allow_old* (the caller's explicit ``--allow-old-backup``;
    logged as a warning with the dump's age): an old dump misses every write
    since, so restoring it would lose them."""
    reference = (reference or "").strip()
    if not reference:
        raise SweepRefused("--apply needs --confirm-backup <object key or sha256 of a verified dump>.")
    column = VaDbBackup.sha256 if _SHA256_RE.match(reference.lower()) else VaDbBackup.object_key
    value = reference.lower() if column is VaDbBackup.sha256 else reference
    backup = db.session.scalars(
        sa.select(VaDbBackup)
        .where(column == value, VaDbBackup.status == VaDbBackup.STATUS_SUCCESS, VaDbBackup.sha256.is_not(None))
        .order_by(VaDbBackup.started_at.desc())
        .limit(1)
    ).first()
    if backup is None:
        raise SweepRefused(
            "No successful backup with a recorded sha256 matches --confirm-backup; "
            "run `flask backups db-dump --no-prune` and pass its key or sha256."
        )
    max_age = timedelta(hours=int(current_app.config.get("PII_BACKUP_MAX_AGE_HOURS", 24)))
    started = backup.started_at if backup.started_at.tzinfo else backup.started_at.replace(tzinfo=UTC)
    age = datetime.now(UTC) - started
    if age > max_age:
        if not allow_old:
            raise SweepRefused(
                f"The confirmed backup is {age.total_seconds() / 3600:.0f} hours old (limit "
                f"PII_BACKUP_MAX_AGE_HOURS={max_age.total_seconds() / 3600:.0f}); take a fresh "
                "`flask backups db-dump --no-prune`, or pass --allow-old-backup to use it anyway."
            )
        log.warning("pii backup gate | an old backup was accepted with --allow-old-backup | age_hours=%.0f",
                    age.total_seconds() / 3600)
    return backup


def sweep_national_ids(*, apply: bool = False, tables: tuple[str, ...] | None = None,
                       batch_size: int = DEFAULT_BATCH_SIZE, on_progress=None) -> dict:
    """Scan (and with *apply* rewrite) every target table.

    Returns ``{"tables": {table: {"scanned", "changed", "written",
    "skipped"}}, "redacted": {"table.column.field": n}, "flagged": {...}}``:
    ``redacted`` counts values that are (or would be) rewritten, ``flagged``
    the field ids a reviewer should look at (``Id10070`` matches, malformed
    ``Id10073`` values). Counts only.
    """
    batch_size = max(1, min(int(batch_size), MAX_BATCH_SIZE))
    selected = [t for t in TARGETS if tables is None or t.table in tables]
    if any(t.model is VaDeathRegister for t in selected):
        # Sealed rows hold NULL plaintext, so the scan would call them clean.
        # Their free text is reduced at write and by the register backfill.
        sealed = db.session.scalar(
            sa.select(sa.func.count()).select_from(VaDeathRegister).where(VaDeathRegister.pii_sealed.is_not(None))
        )
        if sealed:
            raise SweepRefused(
                f"{sealed} sealed register row(s) cannot be swept (their free text is sealed; it is reduced "
                "when written and by the register backfill). Sweep the other tables with --table."
            )
    report = {"tables": {}, "redacted": Counter(), "flagged": Counter()}
    for target in selected:
        report["tables"][target.table] = _sweep_table(
            target, apply=apply, batch_size=batch_size,
            redacted=report["redacted"], flagged=report["flagged"], on_progress=on_progress,
        )
    report["redacted"] = dict(sorted(report["redacted"].items()))
    report["flagged"] = dict(sorted(report["flagged"].items()))
    return report


def _sweep_table(target: SweepTarget, *, apply: bool, batch_size: int, redacted: Counter,
                 flagged: Counter, on_progress) -> dict:
    model = target.model
    pk = getattr(model, target.pk)
    columns = target.json_columns + target.text_columns
    counts = {"scanned": 0, "changed": 0, "written": 0, "skipped": 0}
    last = None
    while True:
        query = sa.select(pk, *(getattr(model, c) for c in columns)).order_by(pk).limit(batch_size)
        if last is not None:
            query = query.where(pk > last)
        rows = db.session.execute(query).all()
        if not rows:
            break
        for row in rows:
            last = row[0]
            counts["scanned"] += 1
            changes = {}
            for index, column in enumerate(columns, start=1):
                old = row[index]
                if column in target.json_columns:
                    new, row_flags = redact_payload_national_ids(old)
                    for field in row_flags:
                        flagged[f"{target.table}.{column}.{field}"] += 1
                    if isinstance(old, dict) and new is not old:
                        for field in old:
                            if new.get(field) is not old.get(field):
                                redacted[f"{target.table}.{column}.{field}"] += 1
                        changes[column] = (old, new)
                else:
                    new, found = redact_national_id_digits(old)
                    if found:
                        redacted[f"{target.table}.{column}"] += 1
                        changes[column] = (old, new)
            if not changes:
                continue
            counts["changed"] += 1
            if apply:
                counts["written" if _write_row(target, row[0], changes) else "skipped"] += 1
        # One short transaction per batch; a dry run has written nothing.
        db.session.commit()
        if on_progress:
            on_progress(f"... {target.table}: scanned={counts['scanned']} changed={counts['changed']}")
    return counts


def _write_row(target: SweepTarget, row_id, changes: dict) -> bool:
    """Compare-and-set one row; False when it changed since it was read."""
    model = target.model
    conditions = [getattr(model, target.pk) == row_id]
    values = {}
    for column, (old, new) in changes.items():
        attr = getattr(model, column)
        if column in target.json_columns:
            conditions.append(attr == sa.type_coerce(old, JSONB))
            values[column] = sa.type_coerce(new, JSONB)
        else:
            conditions.append(attr == old)
            values[column] = new
        if column == "payload_data":
            # Flag on: the version_fingerprint of the rewritten stripped
            # payload and the side row's digest (the sealed set is not here).
            values["payload_fingerprint"] = stored_payload_fingerprint(db.session.get(model, row_id), new)
    result = db.session.execute(
        sa.update(model).where(*conditions).values(**values).execution_options(synchronize_session=False)
    )
    return bool(result.rowcount)
