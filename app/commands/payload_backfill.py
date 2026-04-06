"""CLI commands for payload enrichment backfill.

Usage:
  flask payload-backfill enrich                  # all unenriched
  flask payload-backfill enrich --form-id=FORM1  # single form
  flask payload-backfill enrich --dry-run        # preview only
  flask payload-backfill status                  # show counts
"""
import logging
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
def enrich(form_id, batch_size, max_forms, max_per_form, dry_run):
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
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    svc_logger = logging.getLogger("app.services.payload_enrichment_backfill_service")
    svc_logger.addHandler(handler)
    svc_logger.setLevel(logging.DEBUG)

    if dry_run:
        click.echo("[dry-run] no changes will be written")
    if form_id:
        click.echo(f"Enriching payloads for form: {form_id}")
    elif max_forms:
        click.echo(f"Enriching up to {max_forms} form(s), {batch_size} submissions per batch...")
    else:
        click.echo(f"Enriching all unenriched active payload versions ({batch_size} per batch)...")

    stats = enrich_unenriched_payloads(
        form_id=form_id,
        batch_size=batch_size,
        max_forms=max_forms,
        max_per_form=max_per_form,
        dry_run=dry_run,
    )

    click.echo(
        f"\nDone — processed={stats['processed']}  enriched={stats['enriched']}"
        f"  failed={stats['failed']}  skipped={stats['skipped']}"
    )
    if stats["failed"]:
        click.echo(f"[warn] {stats['failed']} submissions failed enrichment — check logs")

    svc_logger.removeHandler(handler)


def init_app(app):
    app.cli.add_command(payload_backfill_group)
