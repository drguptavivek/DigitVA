"""Flask CLI commands for KPI management."""
import click
from datetime import datetime, date, timedelta
from flask import current_app

@click.group()
def kpi():
    """KPI management commands."""
    pass


@kpi.command()
@click.option(
    "--from",
    "from_date",
    required=True,
    help="Start date in YYYY-MM-DD format",
)
@click.option(
    "--to",
    "to_date",
    required=True,
    help="End date in YYYY-MM-DD format (inclusive)",
)
@click.option(
    "--site",
    "site_ids",
    multiple=True,
    help="Specific site IDs to backfill (defaults to all active sites)",
)
def backfill(from_date, to_date, site_ids):
    """Backfill KPI aggregates for a date range.

    Example:
        flask kpi backfill --from 2026-01-01 --to 2026-04-07
        flask kpi backfill --from 2026-03-01 --to 2026-04-07 --site NC02 --site KA01
    """
    try:
        start = datetime.fromisoformat(from_date).date()
        end = datetime.fromisoformat(to_date).date()
    except ValueError:
        click.secho("Error: Invalid date format. Use YYYY-MM-DD", fg="red")
        return

    if start > end:
        click.secho("Error: --from date must be <= --to date", fg="red")
        return

    # Resolve site_ids if not provided
    if not site_ids:
        from app import db
        import sqlalchemy as sa
        from app.models import VaSites

        site_ids = db.session.execute(
            sa.select(VaSites.site_id).where(VaSites.site_status == "active")
        ).scalars().all()
        site_ids = list(site_ids)
    else:
        site_ids = list(site_ids)

    if not site_ids:
        click.secho("No active sites found", fg="yellow")
        return

    click.echo(f"Backfilling KPI snapshots from {start} to {end}")
    click.echo(f"Sites: {', '.join(site_ids)}")
    click.echo()

    # Use the Celery task directly
    from app.tasks.kpi_tasks import compute_daily_kpi_snapshot

    total_days = (end - start).days + 1
    processed = 0
    failed = 0

    with click.progressbar(
        length=total_days,
        label="Processing",
    ) as bar:
        current_date = start
        while current_date <= end:
            result = compute_daily_kpi_snapshot(
                snapshot_date=current_date.isoformat(),
                site_ids=site_ids,
            )
            if result and result.get("status") in ("ok", "partial"):
                processed += 1
                if result.get("sites_failed", 0) > 0:
                    failed += result.get("sites_failed", 0)
            else:
                click.secho(f"Error on {current_date}: {result}", fg="red")

            bar.update(1)
            current_date += timedelta(days=1)

    click.echo()
    click.secho(f"✓ Backfill complete: {processed} days processed, {failed} failures", fg="green")


@kpi.command()
@click.option(
    "--date",
    "snapshot_date",
    default=None,
    help="Snapshot date in YYYY-MM-DD format (defaults to yesterday)",
)
@click.option(
    "--site",
    "site_ids",
    multiple=True,
    help="Specific site IDs to snapshot (defaults to all active sites)",
)
def snapshot(snapshot_date, site_ids):
    """Compute KPI snapshot for a specific date.

    Example:
        flask kpi snapshot  # Yesterday
        flask kpi snapshot --date 2026-04-07
        flask kpi snapshot --date 2026-04-07 --site NC02
    """
    if snapshot_date is None:
        snapshot_date = (date.today() - timedelta(days=1)).isoformat()
    else:
        try:
            snapshot_date = datetime.fromisoformat(snapshot_date).date().isoformat()
        except ValueError:
            click.secho("Error: Invalid date format. Use YYYY-MM-DD", fg="red")
            return

    site_ids = list(site_ids) if site_ids else None

    click.echo(f"Computing KPI snapshot for {snapshot_date}")
    if site_ids:
        click.echo(f"Sites: {', '.join(site_ids)}")

    from app.tasks.kpi_tasks import compute_daily_kpi_snapshot

    result = compute_daily_kpi_snapshot(
        snapshot_date=snapshot_date,
        site_ids=site_ids,
    )

    click.echo()
    if result and result.get("status") == "ok":
        click.secho(
            f"✓ Snapshot complete: {result.get('sites_processed', 0)} sites processed",
            fg="green",
        )
    elif result and result.get("status") == "partial":
        click.secho(
            f"⚠ Snapshot partial: {result.get('sites_processed', 0)} sites processed, "
            f"{result.get('sites_failed', 0)} failed",
            fg="yellow",
        )
    else:
        click.secho(f"✗ Snapshot failed: {result}", fg="red")


@kpi.command("recount-day-events")
@click.option("--from", "from_date", default=None, help="First stored day, YYYY-MM-DD (default: earliest)")
@click.option("--to", "to_date", default=None, help="Last stored day, YYYY-MM-DD, inclusive (default: latest)")
@click.option("--dry-run", is_flag=True, help="Report how many rows would change; write nothing")
def recount_day_events(from_date, to_date, dry_run):
    """Recount consent_refused_count and not_codeable_count from workflow events.

    Rows written before digitva-9uqn hold a running stock of the submissions
    in those states; the columns are per-day event counts (docs/policy/kpis.md,
    C-01). Touches only those two columns of rows that already exist and only
    where the value differs; every other column, pending and upstream-changed
    backlog included, is left alone (unlike ``backfill``).

    Example:
        flask kpi recount-day-events --dry-run
        flask kpi recount-day-events
        flask kpi recount-day-events --from 2026-03-01 --to 2026-04-07
    """
    try:
        start = datetime.fromisoformat(from_date).date() if from_date else date.min
        end = datetime.fromisoformat(to_date).date() if to_date else date.max
    except ValueError:
        click.secho("Error: Invalid date format. Use YYYY-MM-DD", fg="red")
        return

    if start > end:
        click.secho("Error: --from date must be <= --to date", fg="red")
        return

    import sqlalchemy as sa

    from app import db
    from app.services.odk_retirement_service import IN_ODK_BIND
    from app.services.workflow.definition import EVENT_CONSENT_REFUSED_SQL, EVENT_NOT_CODEABLE_SQL
    from app.tasks.kpi_tasks import _IN_ODK_SQL, _NOT_DUPLICATE_SQL

    # One grouped event scan; the LEFT JOIN gives stored days with no events
    # a 0, and IS DISTINCT FROM keeps the row count to rows that change.
    result = db.session.execute(
        sa.text(f"""
            WITH ev AS (
                SELECT f.site_id, DATE(e.event_created_at) AS d,
                       COUNT(*) FILTER (WHERE {EVENT_CONSENT_REFUSED_SQL}) AS consent_refused,
                       COUNT(*) FILTER (WHERE {EVENT_NOT_CODEABLE_SQL}) AS not_codeable
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND ({EVENT_CONSENT_REFUSED_SQL} OR {EVENT_NOT_CODEABLE_SQL})
                  AND DATE(e.event_created_at) BETWEEN :start AND :end
                GROUP BY f.site_id, DATE(e.event_created_at)
            ), want AS (
                SELECT a.snapshot_date, a.site_id,
                       COALESCE(ev.consent_refused, 0) AS consent_refused,
                       COALESCE(ev.not_codeable, 0) AS not_codeable
                FROM va_daily_kpi_aggregates a
                LEFT JOIN ev ON ev.site_id = a.site_id AND ev.d = a.snapshot_date
                WHERE a.snapshot_date BETWEEN :start AND :end
            )
            UPDATE va_daily_kpi_aggregates a
            SET consent_refused_count = want.consent_refused,
                not_codeable_count = want.not_codeable
            FROM want
            WHERE a.snapshot_date = want.snapshot_date
              AND a.site_id = want.site_id
              AND (a.consent_refused_count IS DISTINCT FROM want.consent_refused
                   OR a.not_codeable_count IS DISTINCT FROM want.not_codeable)
        """),
        {**IN_ODK_BIND, "start": start, "end": end},
    )
    changed = result.rowcount
    if dry_run:
        db.session.rollback()
        click.echo(f"Dry run: {changed} row(s) would be updated; nothing written")
        return
    db.session.commit()
    click.secho(f"✓ Updated {changed} row(s)", fg="green")


def init_app(app):
    """Register KPI CLI commands with the Flask app."""
    app.cli.add_command(kpi)
