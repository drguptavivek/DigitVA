"""CLI commands for payload enrichment backfill.

Usage:
  flask payload-backfill enrich                  # all unenriched
  flask payload-backfill enrich --form-id=FORM1  # single form
  flask payload-backfill enrich --dry-run        # preview only
  flask payload-backfill status                  # show counts
"""
import click
import sqlalchemy as sa

from app import db


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
@click.option("--batch-size", default=50, show_default=True, help="Submissions per commit.")
@click.option("--dry-run", is_flag=True, help="Preview without writing.")
def enrich(form_id, batch_size, dry_run):
    """Fetch missing ODK enrichment metadata for unenriched active payload versions.

    Contacts ODK Central per form, adds FormVersion / DeviceID / SubmitterID /
    instanceID / AttachmentsExpected / AttachmentsPresent to the stored
    payload_data, and updates has_required_metadata and attachments_expected.
    These fields are all in VOLATILE_PAYLOAD_KEYS so the canonical fingerprint
    is unchanged — no new payload version is created.
    """
    from app.services.payload_enrichment_backfill_service import enrich_unenriched_payloads

    if dry_run:
        click.echo("[dry-run] no changes will be written")
    if form_id:
        click.echo(f"Enriching payloads for form: {form_id}")
    else:
        click.echo("Enriching all unenriched active payload versions...")

    stats = enrich_unenriched_payloads(
        form_id=form_id,
        batch_size=batch_size,
        dry_run=dry_run,
    )

    click.echo(
        f"\nDone — processed={stats['processed']}  enriched={stats['enriched']}"
        f"  failed={stats['failed']}  skipped={stats['skipped']}"
    )
    if stats["failed"]:
        click.echo(f"[warn] {stats['failed']} submissions failed enrichment — check logs")


def init_app(app):
    app.cli.add_command(payload_backfill_group)
