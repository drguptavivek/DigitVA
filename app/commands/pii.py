"""CLI for personal-data maintenance.

``flask pii rewrap`` moves every value's wrapped data key to the current KEM
public key (docs/policy/death-registration-identifiers.md, "Key rotation").
It needs the private keys of the old key ids (``PII_KEM_PRIVATE_KEY_FILE`` and
``PII_KEM_PREVIOUS_PRIVATE_KEY_FILES``), so run it in a process that holds
them. Key generation is ``scripts/generate_pii_keys.py``: it must work before
the app can start.

``flask pii sweep-national-id`` finds (dry run) and reduces (``--apply``)
national IDs stored before PII slice 1a; ``flask pii flush-cache`` drops the
rendered section cache after it. docs/kb/pii-slice-1a.md.

``flask pii split-payloads`` moves the sealed set of every payload version
into ``map_payload_version_pii`` (dry run, ``--apply``, ``--verify``,
``--restore``, ``--recompute-digests`` after a blind-key rotation);
``flask pii strip-upstream-copies`` strips the sealed set from upstream-change
copies written before the split; docs/kb/pii-slice-1b.md, "Release
procedure" and "Blind-key rotation".

Every ``--apply`` / ``--restore`` / ``--recompute-digests --apply`` takes the
backup gate (``confirm_db_backup``: a successful dump at most
``PII_BACKUP_MAX_AGE_HOURS`` old, or ``--allow-old-backup``).
"""

import logging

import click
import sqlalchemy as sa

from app import db
from app.models import MapDeathIdentifier, MapPayloadVersionPii
from app.services import national_id_sweep_service as sweep
from app.services import payload_pii_backfill_service as split_backfill
from app.utils import pii_crypto

log = logging.getLogger(__name__)


# The tables whose wrapped data keys a rotation moves: (model, primary key).
# A record table (map_payload_version_pii) wraps one DEK per record in the
# same format, so the same loop re-wraps it and its field ciphertexts stay
# byte-identical.
REWRAP_TABLES = (
    (MapDeathIdentifier, MapDeathIdentifier.death_identifier_id),
    (MapPayloadVersionPii, MapPayloadVersionPii.payload_version_id),
)


def rewrap_pending(batch_size: int = 200) -> dict[str, int]:
    """Re-wrap every row of ``REWRAP_TABLES`` not on the current key id, in
    keyset batches by primary key, one commit per batch. Only ``dek_wrapped``
    and ``key_id`` change; the data ciphertext is untouched. Idempotent and
    resumable (a rerun selects only rows still on an old key). A row that
    cannot be unwrapped is counted and skipped, named by id in the log; no
    value or key is logged. The update is conditional on ``dek_wrapped`` still
    being what was read, so a concurrent edit is never overwritten: that row
    counts as ``skipped`` and the next run sees it. Returns the totals over
    every table, ``{"rewrapped": n, "failed": n, "skipped": n}``."""
    totals = {"rewrapped": 0, "failed": 0, "skipped": 0}
    for model, pk in REWRAP_TABLES:
        counts = _rewrap_table(model, pk, batch_size)
        for key, value in counts.items():
            totals[key] += value
    return totals


def _rewrap_table(model, pk, batch_size: int) -> dict[str, int]:
    current = pii_crypto.current_key_id()
    table = model.__tablename__
    last_id = None
    counts = {"rewrapped": 0, "failed": 0, "skipped": 0}
    while True:
        query = sa.select(model).where(model.key_id != current).order_by(pk).limit(batch_size)
        if last_id is not None:
            query = query.where(pk > last_id)
        rows = db.session.scalars(query).all()
        if not rows:
            return counts
        for row in rows:
            row_id = getattr(row, pk.key)
            last_id = row_id
            read = row.dek_wrapped
            try:
                new_wrapped, new_key_id = pii_crypto.rewrap_dek(read, row_ref=str(row_id))
            except pii_crypto.PiiCryptoError as exc:
                counts["failed"] += 1
                log.error("pii rewrap | %s | %s", table, exc)
                continue
            updated = db.session.execute(
                sa.update(model)
                .where(pk == row_id, model.dek_wrapped == read)
                .values(dek_wrapped=new_wrapped, key_id=new_key_id)
                .execution_options(synchronize_session=False)
            )
            if updated.rowcount:
                counts["rewrapped"] += 1
            else:
                counts["skipped"] += 1
                log.warning("pii rewrap | %s | row %s changed during the run; skipped", table, row_id)
        db.session.commit()
        log.info(
            "pii rewrap | %s | batch done rewrapped=%d failed=%d skipped=%d",
            table, counts["rewrapped"], counts["failed"], counts["skipped"],
        )


@click.group("pii")
def pii_group():
    """Personal-data maintenance: key rotation, national-ID sweep, payload split, cache flush."""


@pii_group.command("rewrap")
@click.option("--batch-size", default=200, show_default=True, type=click.IntRange(1, 1000))
def rewrap(batch_size):
    """Re-wrap data keys onto the current KEM public key."""
    counts = rewrap_pending(batch_size)
    click.echo(f"rewrapped={counts['rewrapped']} failed={counts['failed']} skipped={counts['skipped']}")
    if counts["failed"]:
        raise click.ClickException("Some rows could not be unwrapped; see the log for their ids.")


def allow_old_backup_option(command):
    return click.option(
        "--allow-old-backup", is_flag=True,
        help="Accept a confirmed dump older than PII_BACKUP_MAX_AGE_HOURS (logged).",
    )(command)


def _confirm_backup(reference, allow_old):
    try:
        return sweep.confirm_db_backup(reference, allow_old=allow_old)
    except sweep.SweepRefused as exc:
        raise click.ClickException(str(exc)) from exc


@pii_group.command("sweep-national-id")
@click.option("--apply", "apply_", is_flag=True, help="Rewrite in place. Without it: a dry run, counts only.")
@click.option("--confirm-backup", default=None,
              help="Object key or sha256 of a successful `flask backups db-dump`; required with --apply.")
@allow_old_backup_option
@click.option("--table", "tables", multiple=True, type=click.Choice(sweep.TABLES),
              help="Limit to these tables (repeatable). Default: all.")
@click.option("--batch-size", default=sweep.DEFAULT_BATCH_SIZE, show_default=True,
              type=click.IntRange(1, sweep.MAX_BATCH_SIZE))
def sweep_national_id(apply_, confirm_backup, allow_old_backup, tables, batch_size):
    """Reduce stored national IDs: Id10073 to its last 3 digits, 12/16-digit
    runs in free text masked, Id10070 flagged only. Prints counts by table and
    field, never a value. Idempotent and resumable."""
    backup = _confirm_backup(confirm_backup, allow_old_backup) if apply_ else None
    report = sweep.sweep_national_ids(
        apply=apply_, tables=tuple(tables) or None, batch_size=batch_size, on_progress=click.echo,
    )
    mode = "apply" if apply_ else "dry-run"
    for table, counts in report["tables"].items():
        click.echo(
            f"{mode} {table}: scanned={counts['scanned']} changed={counts['changed']} "
            f"written={counts['written']} skipped={counts['skipped']}"
        )
    for field, count in report["redacted"].items():
        click.echo(f"  redact {field}={count}")
    for field, count in report["flagged"].items():
        click.echo(f"  flag {field}={count}")
    if apply_:
        # The audit line: counts and the backup's key only, never a value.
        log.warning(
            "pii sweep-national-id applied | backup_key=%s | %s",
            backup.object_key,
            " ".join(f"{t}:written={c['written']},skipped={c['skipped']}" for t, c in report["tables"].items()),
        )
        click.echo("Now run `flask pii flush-cache`.")


@pii_group.command("split-payloads")
@click.option("--apply", "apply_", is_flag=True, help="Split in place. Without it: a dry run, counts only.")
@click.option("--verify", "verify_", is_flag=True, help="Check the stored split (counts and an opened sample).")
@click.option("--restore", "restore_", is_flag=True,
              help="Undo the split: sealed fields back into payload_data as PLAINTEXT, side rows deleted.")
@click.option("--recompute-digests", "recompute_", is_flag=True,
              help="After a PII_BLIND_INDEX_KEY rotation: recompute digests, ABHA indexes and fingerprints "
                   "(dry run unless --apply).")
@click.option("--confirm-backup", default=None,
              help="Object key or sha256 of a successful `flask backups db-dump`; required to write.")
@allow_old_backup_option
@click.option("--sample", default=split_backfill.DEFAULT_SAMPLE, show_default=True,
              type=click.IntRange(0, split_backfill.MAX_SAMPLE), help="Side rows opened by --verify.")
@click.option("--batch-size", default=split_backfill.DEFAULT_BATCH_SIZE, show_default=True,
              type=click.IntRange(1, split_backfill.MAX_BATCH_SIZE))
def split_payloads(apply_, verify_, restore_, recompute_, confirm_backup, allow_old_backup, sample, batch_size):
    """Move the sealed set of every payload version (every status) into
    map_payload_version_pii and recompute every payload_fingerprint under
    the new rule. Run with ODK sync paused (docs/kb/pii-slice-1b.md,
    "Release procedure"). Prints counts, never a value."""
    if sum((apply_ and not recompute_, verify_, restore_, recompute_)) > 1:
        raise click.UsageError("Pass at most one of --apply, --verify, --restore, --recompute-digests.")
    if verify_:
        report = split_backfill.verify_split(sample=sample, batch_size=batch_size)
        click.echo(" ".join(f"{key}={value}" for key, value in report.items()))
        if not report["ok"]:
            raise click.ClickException("The split does not verify; see the counts above.")
        return
    backup = _confirm_backup(confirm_backup, allow_old_backup) if (apply_ or restore_) else None
    if recompute_:
        counts = split_backfill.recompute_digests(apply=apply_, batch_size=batch_size, on_progress=click.echo)
        mode = "apply" if apply_ else "dry-run"
        click.echo(f"recompute-digests {mode}: to_recompute={counts['to_recompute']} "
                   f"recomputed={counts['recomputed']} failed={counts['failed']}")
        if apply_:
            log.warning(
                "pii split-payloads recompute-digests applied | backup_key=%s | recomputed=%d failed=%d",
                backup.object_key, counts["recomputed"], counts["failed"],
            )
        if counts["failed"]:
            raise click.ClickException("Some side rows did not open; see the log for their ids.")
        return
    try:
        if restore_:
            counts = split_backfill.restore_split(batch_size=batch_size, on_progress=click.echo)
            log.warning(
                "pii split-payloads restored | backup_key=%s | restored=%d failed=%d",
                backup.object_key, counts["restored"], counts["failed"],
            )
            click.echo(f"restore: restored={counts['restored']} failed={counts['failed']}")
            if counts["failed"]:
                raise click.ClickException("Some side rows did not open; see the log for their ids.")
            click.echo("Keep every payload writer paused until this reports restored with failed=0.")
            return
        report = split_backfill.split_payloads(apply=apply_, batch_size=batch_size, on_progress=click.echo)
    except split_backfill.BackfillRefused as exc:
        raise click.ClickException(str(exc)) from exc
    mode = "apply" if apply_ else "dry-run"
    for status, counts in report["by_status"].items():
        click.echo(f"{mode} {status}: " + " ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    click.echo(
        f"{mode}: written={report['written']} stripped={report['stripped']} "
        f"recomputed_only={report['recomputed_only']} verified={report['verified']}"
    )
    if apply_:
        # The audit line: the backup's key and counts only, never a value.
        log.warning(
            "pii split-payloads applied | backup_key=%s | written=%d stripped=%d recomputed_only=%d "
            "verified=%d cache_keys_flushed=%d",
            backup.object_key, report["written"], report["stripped"], report["recomputed_only"],
            report["verified"], report["cache_keys_flushed"],
        )
        click.echo(
            "Now run `flask pii split-payloads --verify`. Do not set PAYLOAD_PII_SPLIT_ENABLED until the "
            "readers release (PII slice 1b part II-B) ships."
        )


@pii_group.command("strip-upstream-copies")
@click.option("--apply", "apply_", is_flag=True, help="Rewrite in place. Without it: a dry run, counts only.")
@click.option("--confirm-backup", default=None,
              help="Object key or sha256 of a successful `flask backups db-dump`; required with --apply.")
@allow_old_backup_option
@click.option("--batch-size", default=split_backfill.DEFAULT_BATCH_SIZE, show_default=True,
              type=click.IntRange(1, split_backfill.MAX_BATCH_SIZE))
def strip_upstream_copies(apply_, confirm_backup, allow_old_backup, batch_size):
    """Strip the sealed set and reduce national IDs in both payload copies of
    every upstream-change row (va_submission_upstream_changes). Lossless: the
    referenced versions hold the sealed fields. Counts only. Idempotent."""
    backup = _confirm_backup(confirm_backup, allow_old_backup) if apply_ else None
    counts = split_backfill.strip_upstream_copies(apply=apply_, batch_size=batch_size, on_progress=click.echo)
    mode = "apply" if apply_ else "dry-run"
    click.echo(f"strip-upstream-copies {mode}: " + " ".join(f"{key}={value}" for key, value in counts.items()))
    if apply_:
        log.warning(
            "pii strip-upstream-copies applied | backup_key=%s | written=%d skipped=%d",
            backup.object_key, counts["written"], counts["skipped"],
        )


@pii_group.command("flush-cache")
def flush_cache():
    """Delete every cached rendered section (run after a sweep or strip)."""
    from app.services.case_content_service import flush_section_data_cache

    deleted = flush_section_data_cache()
    log.info("pii flush-cache | deleted=%d", deleted)
    click.echo(f"flush-cache: deleted={deleted}")


def init_app(app):
    app.cli.add_command(pii_group)
