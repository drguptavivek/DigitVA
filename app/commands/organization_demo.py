"""Explicit synthetic demo setup and recoverable project-only reset."""

import json

import click

from app.services import synthetic_demo_service as service


@click.group("organization-demo")
def organization_demo_group():
    """Operate only the explicitly configured synthetic organization demo."""


@organization_demo_group.command("seed")
def seed():
    """Create fresh demo accounts/cases; refuses an ordinary existing project."""
    try:
        outcome = service.seed_organization_demo()
    except service.SyntheticDemoError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(outcome))


@organization_demo_group.command("reset")
@click.option("--dry-run", is_flag=True, help="Validate and count; do not back up or change cases.")
def reset(dry_run):
    """Reset once for the most recent scheduled Sunday, after verified backup."""
    outcome = service.reset_weekly_demo(dry_run=dry_run)
    click.echo(json.dumps(outcome, default=str))
    if outcome["status"] == "failed":
        raise click.ClickException("Synthetic demo reset failed; no operational changes committed.")


def init_app(app):
    app.cli.add_command(organization_demo_group)
