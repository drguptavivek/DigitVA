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


@payload_backfill_group.command("transition-stuck")
@click.option("--batch-size", default=100, show_default=True, help="Transitions per commit.")
@click.option("--dry-run", is_flag=True, help="Report counts only; no transitions.")
def transition_stuck(batch_size, dry_run):
    """Transition attachment_sync_pending submissions whose metadata and attachments are complete.

    After payload-backfill enrich fills metadata fields, submissions remain in
    attachment_sync_pending because the backfill does not trigger workflow
    transitions.  This command checks each stuck submission and advances it:
      - attachment_sync_pending → smartva_pending   (if metadata + attachments complete)
      - smartva_pending → ready_for_coding          (if SmartVA result already exists)
    """
    from app.services.workflow.transitions import (
        mark_attachment_sync_completed,
        mark_smartva_completed,
        system_actor,
        WorkflowTransitionError,
    )
    from app.services.workflow.state_store import get_submission_workflow_state

    if dry_run:
        click.echo("[dry-run] no transitions will be applied")

    actor = system_actor()
    eligible = _find_stuck_attachment_sync_submissions()
    click.echo(f"Found {len(eligible)} submissions in attachment_sync_pending with complete metadata + attachments.")

    if dry_run:
        # Count how many also have SmartVA
        smartva_count = sum(1 for r in eligible if r["has_smartva"])
        click.echo(f"  {smartva_count} already have SmartVA results (would advance to ready_for_coding).")
        click.echo(f"  {len(eligible) - smartva_count} would advance to smartva_pending only.")
        return

    att_synced = 0
    smartva_done = 0
    errors = 0

    for i, row in enumerate(eligible, 1):
        va_sid = row["va_sid"]
        try:
            current = get_submission_workflow_state(va_sid)
            if current != "attachment_sync_pending":
                continue
            mark_attachment_sync_completed(va_sid, actor=actor)
            att_synced += 1

            if row["has_smartva"]:
                mark_smartva_completed(va_sid, actor=actor)
                smartva_done += 1
        except WorkflowTransitionError as exc:
            errors += 1
            click.echo(f"  error {va_sid}: {exc}")

        if i % batch_size == 0:
            db.session.commit()
            click.echo(f"  processed {i}/{len(eligible)}…")

    db.session.commit()
    click.echo(
        f"\nDone — attachment_sync→smartva_pending: {att_synced}"
        f"  smartva_pending→ready_for_coding: {smartva_done}"
        f"  errors: {errors}"
    )


def _find_stuck_attachment_sync_submissions():
    """Return va_sids in attachment_sync_pending with complete metadata + attachments."""
    rows = db.session.execute(sa.text("""
        SELECT s.va_sid,
               (sv.va_sid IS NOT NULL) AS has_smartva
        FROM va_submissions s
        JOIN va_submission_workflow w ON w.va_sid = s.va_sid
        JOIN va_submission_payload_versions pv
            ON pv.payload_version_id = s.active_payload_version_id
        JOIN (
            SELECT va_sid, COUNT(*) AS att_count
            FROM va_submission_attachments
            WHERE exists_on_odk = true
            GROUP BY va_sid
        ) att ON att.va_sid = s.va_sid
        LEFT JOIN va_smartva_results sv
            ON sv.va_sid = s.va_sid AND sv.va_smartva_status = 'active'
        WHERE w.workflow_state = 'attachment_sync_pending'
          AND pv.has_required_metadata = true
          AND pv.attachments_expected > 0
          AND att.att_count >= pv.attachments_expected
    """)).mappings().all()
    return rows


def init_app(app):
    app.cli.add_command(payload_backfill_group)
