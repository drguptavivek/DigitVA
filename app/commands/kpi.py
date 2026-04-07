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
        from app.models import VaSite

        site_ids = db.session.execute(
            sa.select(VaSite.site_id).where(VaSite.site_status == "active")
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


def init_app(app):
    """Register KPI CLI commands with the Flask app."""
    app.cli.add_command(kpi)
