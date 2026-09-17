"""CLI for attachment lifecycle operations.

Every command here is a thin wrapper: option parsing and printing live in this
module, and every decision — the Central-fetch flag, the store overview, the
local → S3 cutover — belongs to ``app/services/attachment_service.py``, which
is the only module that knows how an attachment is ingested, stored, derived,
repaired, retired or migrated.

``s3-upload`` and ``local-quarantine`` are the cutover pair. Neither ever
deletes an attachment: the upload copies local blobs into the bucket and
verifies them, and the quarantine only *moves* verified local files aside so
an operator can remove them by hand after a retention window. See
``docs/policy/attachment-storage.md``.
"""

import click

from app.services import attachment_service as svc
from app.services.attachment_store import AttachmentStoreError

# Re-exported for operators and tests that name the quarantine directory.
QUARANTINE_DIRNAME = svc.QUARANTINE_DIRNAME


@click.group("attachments")
def attachments_group():
    """Attachment delivery and lifecycle commands."""
    pass


@attachments_group.command("central-fetch")
@click.argument("project_id")
@click.option(
    "--enable",
    "action",
    flag_value="enable",
    help="Self-heal attachment store misses from ODK Central for this project.",
)
@click.option(
    "--disable",
    "action",
    flag_value="disable",
    help="Return this project to store-only delivery (a miss is a 404).",
)
@click.option(
    "--status",
    "action",
    flag_value="status",
    default=True,
    help="Report the current setting (default).",
)
def central_fetch(project_id, action):
    """Show or change Central self-heal on attachment store misses for PROJECT_ID."""
    enabled = None
    if action in ("enable", "disable"):
        enabled = action == "enable"
    try:
        value = svc.set_project_central_fetch(project_id, enabled)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"{(project_id or '').strip().upper()}: "
        f"attachment_central_fetch_enabled={value}"
    )


@attachments_group.command("overview")
@click.option("--project-id", default=None, help="Limit to one project_id.")
def overview(project_id):
    """Print the same counts the admin Attachment Management panel shows."""
    scope = [project_id.strip().upper()] if project_id else None
    report = svc.attachment_management_overview(scope)

    click.echo(f"Attachment store: {report['store']}")
    click.echo(f"Scope: {', '.join(report['project_ids']) or 'ALL'}")
    for form in report["forms"]:
        click.echo("")
        click.echo(f"[{form['project_id']}] {form['form_id']}")
        for label in (
            "source_state", "derivative_state", "store_state", "local_fallback_state",
        ):
            counts = ", ".join(
                f"{state}={count}" for state, count in sorted(form[label].items())
            )
            click.echo(f"  {label}: {counts or 'none'}")
        click.echo(
            f"  retired_rows={form['retired_rows']} awaiting_s3={form['awaiting_s3']}"
        )

    click.echo("")
    counters = ", ".join(
        f"{outcome}={count}" for outcome, count in sorted(report["delivery_counters"].items())
    )
    click.echo(f"Delivery counters (this process): {counters}")
    if report["source_error_categories"]:
        click.echo("Source error categories:")
        for entry in report["source_error_categories"]:
            click.echo(f"  {entry['category']}: {entry['rows']}")


@attachments_group.command("s3-upload")
@click.option("--form-id", default=None, help="Limit to one form_id.")
@click.option("--dry-run", is_flag=True, help="Report what would be uploaded; write nothing.")
@click.option("--limit", type=int, default=0, help="Stop after N rows (0 = no limit).")
@click.option("--workers", type=int, default=4, help="Parallel uploads (default 4).")
def s3_upload(form_id, dry_run, limit, workers):
    """Copy local attachment blobs into the S3 store and point the rows at them.

    Idempotent and resumable; local files are never deleted. Use
    ``local-quarantine`` and then a manual removal after the retention window.
    """
    if workers < 1:
        raise click.ClickException("--workers must be at least 1.")
    try:
        counts = svc.s3_upload_backlog(
            form_id=form_id,
            dry_run=dry_run,
            limit=limit,
            workers=workers,
            on_progress=click.echo,
        )
    except AttachmentStoreError as exc:
        raise click.ClickException(str(exc)) from exc

    for line in counts["planned"]:
        click.echo(f"would upload {line}")
    click.echo(
        f"s3-upload: scanned={counts['scanned']} uploaded={counts['uploaded']} "
        f"would_upload={counts['would_upload']} failed={counts['failed']}"
    )
    for failure in counts["failures"][:50]:
        click.echo(f"- {failure}")
    if counts["failed"]:
        raise SystemExit(1)


@attachments_group.command("local-quarantine")
@click.option("--form-id", default=None, help="Limit to one form_id.")
@click.option("--dry-run", is_flag=True, help="Report what would move; move nothing.")
@click.option(
    "--include-retained",
    is_flag=True,
    help=(
        "Also move the archival copies of submissions retired from ODK. Off by "
        "default because the policy keeps those local files."
    ),
)
def local_quarantine(form_id, dry_run, include_retained):
    """Move the local files of verified S3-stored rows into media/.s3-uploaded/.

    Nothing is deleted. Each file moves only after its object is confirmed
    present in the bucket, so the copy count never drops below one.
    """
    try:
        counts = svc.quarantine_local_copies(
            form_id=form_id,
            dry_run=dry_run,
            include_retained=include_retained,
            on_message=click.echo,
        )
    except AttachmentStoreError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        f"local-quarantine: moved={counts['moved']} would_move={counts['would_move']} "
        f"skipped_no_object={counts['skipped_no_object']} "
        f"no_local_file={counts['no_local_file']}"
    )


def init_app(app):
    """Register attachment CLI commands with the Flask app."""
    app.cli.add_command(attachments_group)
