"""CLI for SmartVA run-directory archival.

Both commands are thin wrappers: option parsing and printing live here, and
every decision — what is a candidate, what content type an artifact gets, when
a verified archive lets the local copy go — belongs to
``app/services/smartva_run_archive_service.py``.

``scrub-runs`` is the same kind of wrapper over
``app/services/smartva_run_scrub_service.py``.

``archive-runs`` never deletes anything unless ``--delete-local`` is passed and
the archive of that run has been verified against the bucket. See
``docs/policy/smartva-generation-policy.md``.
"""

import logging

import click

from app.services import smartva_run_archive_service as svc

log = logging.getLogger(__name__)


@click.group("smartva")
def smartva_group():
    """SmartVA run archive and scrub commands."""
    pass


@smartva_group.command("archive-runs")
@click.option("--form-id", default=None, help="Limit to one form_id.")
@click.option("--dry-run", is_flag=True, help="Report what would be archived; write nothing.")
@click.option("--limit", type=int, default=0, help="Stop after N run directories (0 = no limit).")
@click.option(
    "--delete-local",
    is_flag=True,
    help=(
        "Remove a run directory once its archive is verified and "
        "SMARTVA_RUNS_KEEP_LOCAL_DAYS has elapsed. Off by default."
    ),
)
def archive_runs(form_id, dry_run, limit, delete_local):
    """Archive SmartVA run directories to the DigitVA object store.

    Idempotent and resumable: an object already present at the right size is
    verified rather than re-uploaded, and an interrupted sweep keeps everything
    it finished. Does nothing at all on the local attachment store.
    """
    if limit < 0:
        raise click.ClickException("--limit cannot be negative.")

    counts = svc.archive_run_backlog(
        form_id=form_id,
        dry_run=dry_run,
        limit=limit,
        delete_local=delete_local,
        on_progress=click.echo,
    )

    if counts["skipped_local_store"]:
        click.echo(
            f"archive-runs: ATTACHMENT_STORE is '{counts['store']}' — run "
            "directories stay on disk and nothing was archived."
        )
        return

    click.echo(
        f"archive-runs: scanned={counts['scanned']} archived={counts['archived']} "
        f"would_archive={counts['would_archive']} absent={counts['absent']} "
        f"deleted_local={counts['deleted_local']} failed={counts['failed']}"
    )
    for failure in counts["failures"][:50]:
        click.echo(f"- {failure}")
    if counts["failed"]:
        raise SystemExit(1)


@smartva_group.command("archive-status")
@click.option("--form-id", default=None, help="Limit to one form_id.")
def archive_status(form_id):
    """Print the same counts the admin SmartVA run archive block shows."""
    report = svc.smartva_archive_overview(form_id=form_id)

    click.echo(f"Attachment store: {report['store']}")
    click.echo(f"Scope: {report['form_id'] or 'ALL'}")
    click.echo(f"Key prefix: {report['key_prefix']}")
    click.echo(f"Keep local days: {report['keep_local_days']}")
    counts = ", ".join(
        f"{state}={count}" for state, count in sorted(report["counts"].items())
    )
    click.echo(f"Runs by archive_state: {counts} (total {report['total_runs']})")
    click.echo(
        f"Local run directories remaining: {report['local_run_dirs']} "
        f"({report['local_bytes']} bytes)"
    )
    failure = report["last_failure"]
    if failure:
        click.echo(
            f"Last failure: {failure['error_code']} "
            f"(run completed {failure['run_completed_at']})"
        )


@smartva_group.command("scrub-runs")
@click.option("--apply", "apply_", is_flag=True, help="Blank the cells in place. Without it: a dry run, counts only.")
@click.option("--confirm-backup", default=None,
              help="Object key or sha256 of a successful `flask backups db-dump` (the recorded backup "
                   "gate); required with --apply. Archive the run files themselves before too.")
@click.option("--allow-old-backup", is_flag=True,
              help="Accept a confirmed dump older than PII_BACKUP_MAX_AGE_HOURS (logged).")
@click.option("--s3", "use_s3", is_flag=True, help="Scrub the smartva_runs/ archive in the object store instead.")
@click.option("--versioning-noted", is_flag=True,
              help="With --s3 --apply: you have noted that earlier object versions stay in a versioned "
                   "bucket and must be expired by the bucket's lifecycle; this command never deletes them.")
def scrub_runs(apply_, confirm_backup, allow_old_backup, use_s3, versioning_noted):
    """Blank personal-data columns in existing SmartVA run CSVs.

    The sealed WHO fields in smartva_input.csv, their SmartVA names in the
    intermediates and national_id/name/surname/geography in the per-death
    outputs. Counts per file kind, never a path or a value. Idempotent.
    Local first: --s3 --apply refuses while a local run file is unscrubbed.
    """
    from app.services import national_id_sweep_service as sweep
    from app.services import smartva_run_scrub_service as scrub

    backup = None
    if apply_:
        if use_s3 and not versioning_noted:
            raise click.ClickException(
                "--s3 --apply needs --versioning-noted: earlier object versions are not deleted here."
            )
        try:
            backup = sweep.confirm_db_backup(confirm_backup, allow_old=allow_old_backup)
        except sweep.SweepRefused as exc:
            raise click.ClickException(str(exc)) from exc
    try:
        counts = scrub.scrub_archived_runs(apply=apply_) if use_s3 else scrub.scrub_local_runs(apply=apply_)
    except scrub.ScrubRefused as exc:
        raise click.ClickException(str(exc)) from exc
    if counts.get("skipped_local_store"):
        click.echo("scrub-runs: ATTACHMENT_STORE is not s3; there is no archive to scrub.")
        return
    mode = "apply" if apply_ else "dry-run"
    where = "s3" if use_s3 else "local"
    for kind in sorted(counts["files"]):
        click.echo(
            f"{mode} {where} {kind}: files={counts['files'][kind]} "
            f"files_with_cells={counts['files_with_cells'][kind]} cells={counts['cells'][kind]}"
        )
    click.echo(f"{mode} {where}: errors={counts['errors']}")
    if apply_:
        log.warning(
            "smartva scrub-runs applied | where=%s backup_key=%s files_rewritten=%d cells=%d errors=%d",
            where, backup.object_key, sum(counts["files_with_cells"].values()),
            sum(counts["cells"].values()), counts["errors"],
        )
    if counts["errors"]:
        raise SystemExit(1)


def init_app(app):
    """Register SmartVA CLI commands with the Flask app."""
    app.cli.add_command(smartva_group)
