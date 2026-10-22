"""Public demo project operations (docs/policy/public-demo.md).

  flask public-demo setup --by admin@example.org
  flask public-demo purge --dry-run | --apply

Refuses unless PUBLIC_DEMO_ENABLED. ``--by`` is an existing admin account: the
actor of the consent audit trail (the seeded notice is approved for demo use
in its name). ``purge`` deletes accounts idle 30 days and everything they
created (policy section 9): ``--dry-run`` does the deletes inside a transaction
it rolls back and prints the counts; ``--apply`` also needs
PUBLIC_DEMO_PURGE_ENABLED. Output is JSON counts; no personal data.
"""

import json

import click
import sqlalchemy as sa

from app import db
from app.models import VaUsers
from app.services import public_demo_service as service


@click.group("public-demo")
def public_demo_group():
    """Operate the public demo project."""


@public_demo_group.command("setup")
@click.option("--by", "by", required=True, help="Email of the administrator acting.")
def setup(by):
    """Create the public demo project and its structure, or confirm it (idempotent)."""
    from app.services.consent_service import ConsentError
    from app.services.organization_service import OrganizationError

    actor = db.session.scalar(
        sa.select(VaUsers).where(sa.func.lower(VaUsers.email) == by.strip().lower())
    )
    try:
        outcome = service.setup_public_demo_project(actor)
    except service.PublicDemoError as exc:
        raise click.ClickException(f"{exc.code}: {exc.message}") from exc
    except (ConsentError, OrganizationError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(outcome, default=str, indent=2))


@public_demo_group.command("purge")
@click.option("--dry-run/--apply", "dry_run", required=True,
              help="--dry-run counts what would go and changes nothing; --apply deletes.")
def purge(dry_run):
    """Delete public-demo accounts idle for 30 days and everything they created."""
    from app.services import public_demo_purge_service

    result = public_demo_purge_service.purge_run(apply=not dry_run)
    click.echo(json.dumps(result, default=str, indent=2))
    if result["status"] != "ok":
        raise click.ClickException(f"refused: {result['status']}")


def init_app(app):
    app.cli.add_command(public_demo_group)
