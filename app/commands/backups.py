"""CLI for database backups.

Every command here is a thin wrapper: option parsing and printing live in this
module, and every decision — how the dump is made, where it goes, what is
pruned, what a restore may trust — belongs to
``app/services/db_backup_service.py``.

Nothing here prints a credential or a connection string; the object key is the
only identifier a dump has outside the bucket. See
``docs/current-state/backup.md`` for the schedule, retention and the
restore-from-S3 runbook.
"""

import click

from app.models import VaDbBackup
from app.services import db_backup_service as svc


@click.group("backups")
def backups_group():
    """Database backup commands."""
    pass


@backups_group.command("db-dump")
@click.option(
    "--no-prune",
    is_flag=True,
    help="Keep every existing dump; do not apply DB_BACKUP_KEEP_DAILY afterwards.",
)
def db_dump(no_prune):
    """Dump the database to the object store and apply retention.

    Exits non-zero if the dump failed, so a cron or CI wrapper notices.
    """
    outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_CLI)
    click.echo(
        f"db-dump: status={outcome.status} store={outcome.store} "
        f"bytes={outcome.size_bytes}"
    )
    if outcome.object_key:
        click.echo(f"  key: {outcome.object_key}")
    if outcome.sha256:
        click.echo(f"  sha256: {outcome.sha256}")
    if not outcome.ok:
        raise click.ClickException(f"Backup failed: {outcome.error_code}")

    if no_prune:
        return
    prune = svc.prune_db_backups()
    click.echo(f"prune: kept={prune.kept} pruned={prune.pruned}")


@backups_group.command("db-prune")
@click.option("--dry-run", is_flag=True, help="Report what would go; delete nothing.")
def db_prune(dry_run):
    """Delete every dump beyond the newest DB_BACKUP_KEEP_DAILY."""
    if dry_run:
        report = svc.db_backup_overview()
        click.echo(
            f"db-prune (dry run): store={report['store']} "
            f"keep_daily={report['keep_daily']}"
        )
        click.echo("Nothing was deleted. Re-run without --dry-run to apply retention.")
        return

    prune = svc.prune_db_backups()
    click.echo(
        f"db-prune: store={prune.store} keep_daily={prune.keep_daily} "
        f"kept={prune.kept} pruned={prune.pruned}"
    )
    for key in prune.pruned_keys:
        click.echo(f"  pruned {key}")
    if prune.skipped_reason:
        raise click.ClickException(f"Prune skipped: {prune.skipped_reason}")


@backups_group.command("db-list")
@click.option("--limit", type=int, default=svc.OVERVIEW_LIMIT, help="Rows to show.")
def db_list(limit):
    """Print recent backups: time, status, store, size and object key."""
    report = svc.db_backup_overview()
    click.echo(
        f"Backup store: {report['store']} · prefix {report['key_prefix']} · "
        f"keep {report['keep_daily']} · daily at {report['daily_time']} UTC"
    )
    click.echo(
        f"Successful backups: {report['successful_backups']} "
        f"({report['total_bytes']} bytes recorded)"
    )
    rows = report["recent"][: max(int(limit or 0), 1)]
    if not rows:
        click.echo("No backups recorded yet.")
        return
    for row in rows:
        click.echo(
            f"  {row['started_at']}  {row['status']:<8} {row['store']:<5} "
            f"{row['size_bytes'] or 0:>12}  {row['object_key'] or ''}"
            + (f"  [{row['error_code']}]" if row["error_code"] else "")
        )


@backups_group.command("db-download")
@click.argument("object_key")
@click.argument("dest_path", type=click.Path())
def db_download(object_key, dest_path):
    """Fetch OBJECT_KEY out of the store to DEST_PATH, verifying its sha256.

    Refuses a key this app has no recorded checksum for, and removes the file
    on a mismatch, so what lands on disk is always a dump DigitVA made.
    """
    try:
        result = svc.download_db_backup(object_key, dest_path)
    except svc.DbBackupError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"db-download: {result['path']} ({result['size_bytes']} bytes, "
        f"sha256 verified)"
    )


def init_app(app):
    """Register database backup CLI commands with the Flask app."""
    app.cli.add_command(backups_group)
