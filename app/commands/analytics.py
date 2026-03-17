"""CLI commands for analytics materialized views."""

import click

from app.services.submission_analytics_mv import refresh_submission_analytics_mv


@click.group("analytics")
def analytics_group():
    """Analytics and reporting commands."""
    pass


@analytics_group.command("refresh-submission-mv")
@click.option(
    "--concurrently",
    is_flag=True,
    help="Use REFRESH MATERIALIZED VIEW CONCURRENTLY.",
)
def refresh_submission_mv(concurrently):
    """Refresh the submission analytics materialized view."""
    refresh_submission_analytics_mv(concurrently=concurrently)
    click.echo("Submission analytics materialized view refreshed.")


def init_app(app):
    """Register analytics CLI commands with the Flask app."""
    app.cli.add_command(analytics_group)
