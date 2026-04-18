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


def repair_attachment_storage_names(
    *,
    apply: bool,
    batch_size: int = 500,
    progress_callback=None,
    verbose: bool = False,
) -> dict[str, int]:
    """Assign deterministic storage_name values to legacy attachment rows.

    Skips `audit.csv` rows and leaves rows with missing local files untouched so
    they remain retryable later.
    """
    from app import db
    from app.models.va_submission_attachments import VaSubmissionAttachments
    from app.models.va_submissions import VaSubmissions

    def report(message: str, *, is_verbose: bool = False) -> None:
        if progress_callback is None:
            return
        if is_verbose and not verbose:
            return
        progress_callback(message)

    total_done = 0
    total_missing = 0
    total_scanned = 0

    while True:
        rows = db.session.scalars(
            sa.select(VaSubmissionAttachments)
            .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
            .where(VaSubmissionAttachments.storage_name.is_(None))
            .where(VaSubmissionAttachments.filename != "audit.csv")
            .order_by(VaSubmissionAttachments.va_sid, VaSubmissionAttachments.filename)
            .limit(batch_size)
        ).all()

        if not rows:
            break

        report(
            f"legacy-attachment repair: processing batch of {len(rows)} row(s)"
        )

        for row in rows:
            total_scanned += 1
            new_storage_name = _migration_storage_name(row.va_sid, row.filename)

            if not row.local_path:
                report(
                    f"MISSING  {row.va_sid}/{row.filename} (no local_path, skipping)",
                    is_verbose=True,
                )
                total_missing += 1
                continue

            media_dir = os.path.dirname(row.local_path)
            new_local_path = os.path.join(media_dir, new_storage_name)

            if os.path.exists(new_local_path):
                report(
                    f"RECOVERY {row.va_sid}/{row.filename} → {new_storage_name}",
                    is_verbose=True,
                )
                if apply:
                    row.storage_name = new_storage_name
                    row.local_path = new_local_path
                    db.session.commit()
                total_done += 1
                continue

            if not os.path.exists(row.local_path):
                report(
                    f"MISSING  {row.va_sid}/{row.filename} (file not on disk, skipping)",
                    is_verbose=True,
                )
                total_missing += 1
                continue

            report(
                f"RENAME   {row.va_sid}/{row.filename} → {new_storage_name}",
                is_verbose=True,
            )
            if apply:
                os.rename(row.local_path, new_local_path)
                row.storage_name = new_storage_name
                row.local_path = new_local_path
                db.session.commit()
            total_done += 1

    return {
        "migrated": total_done,
        "missing": total_missing,
        "scanned": total_scanned,
    }


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
    if not apply:
        click.echo("DRY RUN — pass --apply to make changes\n")

    result = repair_attachment_storage_names(
        apply=apply,
        batch_size=500,
        progress_callback=click.echo,
        verbose=True,
    )
    click.echo(
        f"\n{'Applied' if apply else 'Dry run'}: "
        f"{result['migrated']} migrated, {result['missing']} missing "
        f"(storage_name left NULL)"
    )


def init_app(app):
    app.cli.add_command(migrate_attachments_group)
