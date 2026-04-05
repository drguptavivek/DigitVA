"""One-time migration: assign storage_name to all existing va_submission_attachments rows.

Usage:
  flask migrate-attachments run           # dry run by default — prints actions
  flask migrate-attachments run --apply   # actually rename files and update DB

IMPORTANT: run in a maintenance window with sync/backfill disabled.
Verify registration: flask --help | grep migrate-attachments

Crash safety: uses uuid5 over (va_sid, filename) so storage_name is deterministic.
On rerun after a crash, the same storage_name is computed and the already-renamed
file is detected on disk — DB update completes without re-renaming.
"""
import os
import uuid
import click
import sqlalchemy as sa
from flask.cli import with_appcontext

# Fixed namespace for deterministic storage_name generation in this migration.
# uuid5(NS, "{va_sid}:{filename}") is always the same for the same input.
_MIGRATION_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _migration_storage_name(va_sid: str, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".amr":
        ext = ".mp3"
    return uuid.uuid5(_MIGRATION_NS, f"{va_sid}:{filename}").hex + ext


@click.group("migrate-attachments")
def migrate_attachments_group():
    """One-time attachment storage_name migration commands."""
    pass


@migrate_attachments_group.command("run")
@click.option("--apply", is_flag=True, default=False, help="Apply changes (default: dry run)")
@with_appcontext
def run_migration(apply: bool):
    """Assign storage_name to all va_submission_attachments rows where storage_name IS NULL.

    Skips audit.csv rows. Safe to rerun — idempotent.
    """
    from app import db
    from app.models.va_submission_attachments import VaSubmissionAttachments
    from app.models.va_submissions import VaSubmissions
    from flask import current_app

    if not apply:
        click.echo("DRY RUN — pass --apply to make changes\n")

    batch_size = 500
    offset = 0
    total_done = 0
    total_missing = 0
    total_skipped_audit = 0

    while True:
        rows = db.session.scalars(
            sa.select(VaSubmissionAttachments)
            .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
            .where(VaSubmissionAttachments.storage_name.is_(None))
            .where(VaSubmissionAttachments.filename != "audit.csv")
            .order_by(VaSubmissionAttachments.va_sid, VaSubmissionAttachments.filename)
            .limit(batch_size)
            .offset(offset)
        ).all()

        if not rows:
            break

        for row in rows:
            new_storage_name = _migration_storage_name(row.va_sid, row.filename)

            if not row.local_path:
                click.echo(f"MISSING  {row.va_sid}/{row.filename} (no local_path, skipping)")
                total_missing += 1
                continue

            media_dir = os.path.dirname(row.local_path)
            new_local_path = os.path.join(media_dir, new_storage_name)

            if os.path.exists(new_local_path):
                # Recovery path: file already renamed by a previous interrupted run.
                click.echo(f"RECOVERY {row.va_sid}/{row.filename} → {new_storage_name}")
                if apply:
                    row.storage_name = new_storage_name
                    row.local_path = new_local_path
                    db.session.commit()
                total_done += 1
                continue

            if not os.path.exists(row.local_path):
                # File missing on disk — leave storage_name NULL so this row
                # remains retryable once the file is restored.
                click.echo(f"MISSING  {row.va_sid}/{row.filename} (file not on disk, skipping)")
                total_missing += 1
                continue

            click.echo(f"RENAME   {row.va_sid}/{row.filename} → {new_storage_name}")
            if apply:
                os.rename(row.local_path, new_local_path)
                row.storage_name = new_storage_name
                row.local_path = new_local_path
                db.session.commit()
            total_done += 1

        offset += batch_size

    click.echo(
        f"\n{'Applied' if apply else 'Dry run'}: "
        f"{total_done} migrated, {total_missing} missing (storage_name left NULL)"
    )


def init_app(app):
    app.cli.add_command(migrate_attachments_group)
