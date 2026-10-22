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

``flask pii seal-register`` seals the death register's personal columns
(``--apply``, plaintext kept) and, at ``--strip`` after the hold, the audit
rows' sealed values (dry run, ``--apply``, ``--verify``, ``--strip``, ``--restore``, ``--recompute-digests``); docs/kb/pii-slice-2.md,
"Backfill, verify, strip, restore". ``rewrap`` also moves the register's and
the audit rows' wrapped keys.

Every ``--apply`` / ``--restore`` / ``--strip`` / ``--recompute-digests --apply`` takes the
backup gate (``confirm_db_backup``: a successful dump at most
``PII_BACKUP_MAX_AGE_HOURS`` old, or ``--allow-old-backup``).
"""

import logging

import click
import sqlalchemy as sa

from app import db
from app.models import MapCaseTransition, MapDeathIdentifier, MapPayloadVersionPii, VaDeathRegister
from app.services import national_id_sweep_service as sweep
from app.services import payload_pii_backfill_service as split_backfill
from app.services import register_pii_backfill_service as register_backfill
from app.utils import pii_crypto

log = logging.getLogger(__name__)


# The tables whose wrapped data keys a rotation moves: (model, primary key,
# wrapped-DEK attribute, key-id attribute, pin updated_at). A record table
# (map_payload_version_pii, the register's pii_sealed, the audit rows'
# sealed changes) wraps one DEK per record in the same format, so the same
# loop re-wraps it and its field ciphertexts stay byte-identical. The register
# pins updated_at: it has onupdate and drives keyset cursors and the worklist.
REWRAP_TABLES = (
    (MapDeathIdentifier, MapDeathIdentifier.death_identifier_id, "dek_wrapped", "key_id", False),
    (MapPayloadVersionPii, MapPayloadVersionPii.payload_version_id, "dek_wrapped", "key_id", False),
    (VaDeathRegister, VaDeathRegister.death_id, "pii_dek_wrapped", "pii_key_id", True),
    (MapCaseTransition, MapCaseTransition.transition_id, "changes_dek_wrapped", "changes_key_id", False),
)


def rewrap_pending(batch_size: int = 200) -> dict[str, int]:
    """Re-wrap every row of ``REWRAP_TABLES`` not on the current key id, in
    keyset batches by primary key, one commit per batch. Only the wrapped DEK
    and key id columns change (``updated_at`` is pinned on the register); the data ciphertext is untouched. Idempotent and
    resumable (a rerun selects only rows still on an old key). A row that
    cannot be unwrapped is counted and skipped, named by id in the log; no
    value or key is logged. The update is conditional on ``dek_wrapped`` still
    being what was read, so a concurrent edit is never overwritten: that row
    counts as ``skipped`` and the next run sees it. Returns the totals over
    every table, ``{"rewrapped": n, "failed": n, "skipped": n}``."""
    totals = {"rewrapped": 0, "failed": 0, "skipped": 0}
    for table in REWRAP_TABLES:
        counts = _rewrap_table(*table, batch_size)
        for key, value in counts.items():
            totals[key] += value
    return totals


def _rewrap_table(model, pk, dek_attr: str, key_attr: str, pin_updated_at: bool, batch_size: int) -> dict[str, int]:
    current = pii_crypto.current_key_id()
    table = model.__tablename__
    dek_col, key_col = getattr(model, dek_attr), getattr(model, key_attr)
    last_id = None
    counts = {"rewrapped": 0, "failed": 0, "skipped": 0}
    while True:
        # Only the three columns: a register row would otherwise load its sealed blob.
        query = sa.select(pk, dek_col).where(key_col != current).order_by(pk).limit(batch_size)
        if last_id is not None:
            query = query.where(pk > last_id)
        rows = db.session.execute(query).all()
        if not rows:
            return counts
        for row_id, read in rows:
            last_id = row_id
            try:
                new_wrapped, new_key_id = pii_crypto.rewrap_dek(read, row_ref=str(row_id))
            except pii_crypto.PiiCryptoError as exc:
                counts["failed"] += 1
                log.error("pii rewrap | %s | %s", table, exc)
                continue
            updated = db.session.execute(
                sa.update(model)
                .where(pk == row_id, dek_col == read)
                .values(**{dek_attr: new_wrapped, key_attr: new_key_id},
                        **({"updated_at": model.updated_at} if pin_updated_at else {}))
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
    try:
        report = sweep.sweep_national_ids(
            apply=apply_, tables=tuple(tables) or None, batch_size=batch_size, on_progress=click.echo,
        )
    except sweep.SweepRefused as exc:
        raise click.ClickException(str(exc)) from exc
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


@pii_group.command("seal-register")
@click.option("--apply", "apply_", is_flag=True,
              help="Seal in place, plaintext columns kept. Without it: a dry run, counts only.")
@click.option("--verify", "verify_", is_flag=True, help="Check the stored state (counts and an opened sample).")
@click.option("--after-strip", is_flag=True,
              help="With --verify: also require the audit rows sealed (they are sealed by --strip).")
@click.option("--strip", "strip_", is_flag=True,
              help="NULL the sealed plaintext columns of verified rows past --hold-days, then seal the audit "
                   "rows' sealed values and scrub the legacy `mask` (the point of no easy return).")
@click.option("--restore", "restore_", is_flag=True,
              help="Undo the seal: values back into the plaintext columns (REGISTER_PII_SPLIT_ENABLED off).")
@click.option("--recompute-digests", "recompute_", is_flag=True,
              help="After a PII_BLIND_INDEX_KEY rotation: recompute the four indexes (dry run unless --apply).")
@click.option("--confirm-backup", default=None,
              help="Object key or sha256 of a successful `flask backups db-dump`; required to write.")
@allow_old_backup_option
@click.option("--sample", default=register_backfill.DEFAULT_SAMPLE, show_default=True,
              type=click.IntRange(0, register_backfill.MAX_SAMPLE), help="Rows opened by --verify and --strip.")
@click.option("--hold-days", default=register_backfill.DEFAULT_HOLD_DAYS, show_default=True,
              type=click.IntRange(0, 3650), help="--strip leaves rows sealed more recently than this.")
@click.option("--batch-size", default=register_backfill.DEFAULT_BATCH_SIZE, show_default=True,
              type=click.IntRange(1, register_backfill.MAX_BATCH_SIZE))
def seal_register(apply_, verify_, after_strip, strip_, restore_, recompute_, confirm_backup, allow_old_backup,
                  sample, hold_days, batch_size):
    """Seal every death-register row (plaintext kept until --strip). --strip
    also seals the sealed values in the audit rows of the cases it has
    stripped and scrubs the legacy `mask` member there. Run with ODK sync paused (docs/kb/pii-slice-2.md). Prints
    counts, never a value or a row id."""
    if sum((apply_ and not recompute_, verify_, strip_, restore_, recompute_)) > 1:
        raise click.UsageError(
            "Pass at most one of --apply, --verify, --strip, --restore, --recompute-digests."
        )
    if after_strip and not verify_:
        raise click.UsageError("--after-strip goes with --verify.")
    if verify_:
        report = register_backfill.verify_register(sample=sample, batch_size=batch_size, after_strip=after_strip)
        click.echo(" ".join(f"{key}={value}" for key, value in report.items()))
        if not report["ok"]:
            raise click.ClickException("The register does not verify; see the counts above.")
        return
    backup = _confirm_backup(confirm_backup, allow_old_backup) if (apply_ or strip_ or restore_) else None
    try:
        if strip_:
            counts = register_backfill.strip_register(
                hold_days=hold_days, sample=sample, batch_size=batch_size, on_progress=click.echo)
            log.warning(
                "pii seal-register stripped | backup_key=%s | %s",
                backup.object_key, " ".join(f"{key}={value}" for key, value in counts.items()),
            )
            click.echo("strip: " + " ".join(f"{key}={value}" for key, value in counts.items()))
            click.echo("Now run `flask pii seal-register --verify --after-strip` and `flask pii flush-cache`.")
            if counts["failed"]:
                raise click.ClickException("Some rows did not open to their plaintext and were kept.")
            if counts["audit_skipped"]:
                raise click.ClickException("Some audit rows could not be sealed (unexpected shape); see the counts.")
            return
        if restore_:
            counts = register_backfill.restore_register(batch_size=batch_size, on_progress=click.echo)
            log.warning(
                "pii seal-register restored | backup_key=%s | restored=%d failed=%d audit_restored=%d "
                "audit_failed=%d", backup.object_key, counts["restored"], counts["failed"],
                counts["audit_restored"], counts["audit_failed"],
            )
            click.echo("restore: " + " ".join(f"{key}={value}" for key, value in counts.items()))
            if counts["failed"] or counts["audit_failed"]:
                raise click.ClickException("Some rows did not open and were kept sealed.")
            click.echo("Keep every register writer paused until this reports failed=0, then run `flask pii flush-cache`.")
            return
        if recompute_:
            counts = register_backfill.recompute_digests(apply=apply_, batch_size=batch_size, on_progress=click.echo)
            mode = "apply" if apply_ else "dry-run"
            click.echo(f"recompute-digests {mode}: " + " ".join(f"{key}={value}" for key, value in counts.items()))
            if apply_:
                log.warning(
                    "pii seal-register recompute-digests applied | backup_key=%s | recomputed=%d failed=%d",
                    backup.object_key, counts["recomputed"], counts["failed"],
                )
            if counts["failed"]:
                raise click.ClickException("Some rows did not open and were skipped.")
            return
        report = register_backfill.seal_register(apply=apply_, batch_size=batch_size, on_progress=click.echo)
        if not apply_:  # what --strip will seal in the audit rows
            report.update(register_backfill.seal_audit(apply=False, batch_size=batch_size))
    except register_backfill.BackfillRefused as exc:
        raise click.ClickException(str(exc)) from exc
    mode = "apply" if apply_ else "dry-run"
    click.echo(f"{mode}: " + " ".join(f"{key}={value}" for key, value in report.items()))
    if apply_:
        log.warning(
            "pii seal-register applied | backup_key=%s | %s",
            backup.object_key, " ".join(f"{key}={value}" for key, value in report.items()),
        )
        click.echo(
            "Now run `flask pii seal-register --verify` and `flask pii flush-cache`. Do not set "
            "REGISTER_PII_SPLIT_ENABLED until the readers release ships."
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
