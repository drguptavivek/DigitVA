"""CLI commands for payload enrichment backfill.

Usage:
  flask payload-backfill enrich                  # all unenriched
  flask payload-backfill enrich --form-id=FORM1  # single form
  flask payload-backfill enrich --dry-run        # preview only
  flask payload-backfill status                  # show counts
"""
from datetime import datetime, timezone
import logging
import os
import uuid
import click
import sqlalchemy as sa

from app import db


class _ClickEchoHandler(logging.Handler):
    """Forward log records to click.echo so CLI output is always visible."""
    def emit(self, record):
        click.echo(self.format(record))


@click.group("payload-backfill")
def payload_backfill_group():
    """Payload enrichment backfill commands."""
    pass


@payload_backfill_group.command("status")
def backfill_status():
    """Show how many active payload versions are missing ODK enrichment metadata."""
    from app.models.va_submission_payload_versions import VaSubmissionPayloadVersion
    from app.models import VaSubmissions, VaForms

    rows = db.session.execute(sa.text("""
        SELECT
            f.form_id,
            f.project_id,
            f.site_id,
            COUNT(*) FILTER (WHERE NOT pv.has_required_metadata) AS unenriched,
            COUNT(*) FILTER (WHERE pv.has_required_metadata)     AS enriched,
            COUNT(*)                                              AS total
        FROM va_submission_payload_versions pv
        JOIN va_submissions s ON s.va_sid = pv.va_sid
        JOIN va_forms f ON f.form_id = s.va_form_id
        WHERE pv.version_status = 'active'
        GROUP BY f.form_id, f.project_id, f.site_id
        HAVING COUNT(*) FILTER (WHERE NOT pv.has_required_metadata) > 0
        ORDER BY unenriched DESC
    """)).all()

    if not rows:
        click.echo("All active payload versions are enriched.")
        return

    total_unenriched = sum(r.unenriched for r in rows)
    click.echo(f"\n{'Form':<20} {'Project':<16} {'Site':<16} {'Unenriched':>10} {'Enriched':>10} {'Total':>8}")
    click.echo("-" * 82)
    for r in rows:
        click.echo(f"{r.form_id:<20} {r.project_id:<16} {r.site_id:<16} {r.unenriched:>10} {r.enriched:>10} {r.total:>8}")
    click.echo("-" * 82)
    click.echo(f"{'TOTAL':<54} {total_unenriched:>10}")


@payload_backfill_group.command("enrich")
@click.option("--form-id", default=None, help="Restrict to a single form ID.")
@click.option("--batch-size", default=10, show_default=True, help="Submissions per commit.")
@click.option("--max-forms", default=None, type=int, help="Stop after N forms (for test runs).")
@click.option("--max-per-form", default=None, type=int, help="Cap submissions per form (for smoke tests).")
@click.option("--dry-run", is_flag=True, help="Fetch enrichment data but write nothing.")
@click.option(
    "--force-attachments-redownload",
    is_flag=True,
    help="Bypass ETag check and re-download attachments for processed submissions.",
)
def enrich(form_id, batch_size, max_forms, max_per_form, dry_run, force_attachments_redownload):
    """Fetch missing ODK enrichment metadata for unenriched active payload versions.

    Contacts ODK Central per form, adds FormVersion / DeviceID / SubmitterID /
    instanceID / AttachmentsExpected / AttachmentsPresent to the stored
    payload_data, and updates has_required_metadata and attachments_expected.
    These fields are all in VOLATILE_PAYLOAD_KEYS so the canonical fingerprint
    is unchanged — no new payload version is created.

    Examples:

      # Test run: enrich 2 forms only\n
      flask payload-backfill enrich --max-forms=2

      # Single form\n
      flask payload-backfill enrich --form-id=UNSW01KA0101

      # Full backfill\n
      flask payload-backfill enrich
    """
    from app.services.payload_enrichment_backfill_service import enrich_unenriched_payloads

    # Wire up click.echo handler so log.info/warning lines appear in CLI output
    handler = _ClickEchoHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    # Show clean per-submission stage lines in console without logger-name noise.
    handler.setLevel(logging.INFO)
    svc_logger = logging.getLogger("app.services.payload_enrichment_backfill_service")
    svc_logger.addHandler(handler)
    svc_logger.setLevel(logging.INFO)
    run_id = uuid.uuid4().hex[:12]
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    run_log_path = os.path.join(log_dir, f"payload_backfill_enrich_{run_ts}_{run_id}.log")

    run_file_handler = logging.FileHandler(run_log_path, encoding="utf-8")
    run_file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    run_file_handler.setLevel(logging.DEBUG)
    root_logger = logging.getLogger()
    root_logger.addHandler(run_file_handler)

    if dry_run:
        click.echo("[dry-run] no changes will be written")
    if force_attachments_redownload:
        click.echo("[force] attachment re-download is enabled (ETag bypass)")
    click.echo(f"Run log: {run_log_path}")
    if form_id:
        click.echo(f"Enriching payloads for form: {form_id}")
    elif max_forms:
        click.echo(f"Enriching up to {max_forms} form(s), {batch_size} submissions per batch...")
    else:
        click.echo(f"Enriching all unenriched active payload versions ({batch_size} per batch)...")
    try:
        stats = enrich_unenriched_payloads(
            form_id=form_id,
            batch_size=batch_size,
            max_forms=max_forms,
            max_per_form=max_per_form,
            dry_run=dry_run,
            force_attachments_redownload=force_attachments_redownload,
        )

        click.echo(
            f"\nDone — processed={stats['processed']}  enriched={stats['enriched']}"
            f"  failed={stats['failed']}  skipped={stats['skipped']}"
        )
        if "smartva_checked" in stats:
            click.echo(
                "Attachments — "
                f"checked={stats.get('attachments_checked', 0)} "
                f"downloaded={stats.get('attachments_downloaded', 0)} "
                f"skipped={stats.get('attachments_skipped', 0)} "
                f"errors={stats.get('attachments_errors', 0)} "
                f"etag_not_modified={stats.get('attachments_etag_not_modified', 0)} "
                f"local_present_on_etag={stats.get('attachments_local_present_on_etag', 0)} "
                f"local_missing_on_etag={stats.get('attachments_local_missing_on_etag', 0)}"
            )
            click.echo(
                "SmartVA — "
                f"checked={stats['smartva_checked']} "
                f"missing_current_payload={stats.get('smartva_missing', 0)} "
                f"generated={stats.get('smartva_generated', 0)} "
                f"failed={stats.get('smartva_failed', 0)} "
                f"noop={stats.get('smartva_noop', 0)}"
            )
            click.echo(
                "Workflow — "
                f"attachment_sync→smartva_pending={stats.get('workflow_attachment_to_smartva', 0)} "
                f"smartva_pending→ready_for_coding={stats.get('workflow_smartva_to_ready', 0)} "
                f"errors={stats.get('workflow_errors', 0)}"
            )
            click.echo(
                "Submission Audit — "
                f"completed={stats.get('audit_completed', 0)} "
                f"partial={stats.get('audit_partial', 0)} "
                f"failed={stats.get('audit_failed', 0)}"
            )
        if stats["failed"]:
            click.echo(f"[warn] {stats['failed']} submissions failed enrichment — check logs")
    finally:
        svc_logger.removeHandler(handler)
        root_logger.removeHandler(run_file_handler)
        run_file_handler.close()
        click.echo(f"Run log saved: {run_log_path}")

def init_app(app):
    app.cli.add_command(payload_backfill_group)
