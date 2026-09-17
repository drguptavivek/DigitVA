"""CLI for SmartVA run-directory archival.

Both commands are thin wrappers: option parsing and printing live here, and
every decision — what is a candidate, what content type an artifact gets, when
a verified archive lets the local copy go — belongs to
``app/services/smartva_run_archive_service.py``.

``archive-runs`` never deletes anything unless ``--delete-local`` is passed and
the archive of that run has been verified against the bucket. See
``docs/policy/smartva-generation-policy.md``.
"""

import click

from app.services import smartva_run_archive_service as svc


@click.group("smartva")
def smartva_group():
    """SmartVA run archive commands."""
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


def init_app(app):
    """Register SmartVA CLI commands with the Flask app."""
    app.cli.add_command(smartva_group)
