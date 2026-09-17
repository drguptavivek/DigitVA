"""CLI for attachment delivery settings.

The per-project Central-fetch flag is the rollout switch for Phase 4a of
``docs/planning/s3-attachment-plan.md``. Delivery always reads DigitVA's own
store first; the flag decides only what happens on a store miss — with it off
a miss is a 404 exactly as before, with it on the original is fetched from the
project's own ODK Central connection, streamed to the browser, and written
into the store.
"""

import click

from app import db
from app.models import VaProjectMaster


@click.group("attachments")
def attachments_group():
    """Attachment delivery commands."""
    pass


@attachments_group.command("central-fetch")
@click.argument("project_id")
@click.option(
    "--enable",
    "action",
    flag_value="enable",
    help="Self-heal attachment store misses from ODK Central for this project.",
)
@click.option(
    "--disable",
    "action",
    flag_value="disable",
    help="Return this project to store-only delivery (a miss is a 404).",
)
@click.option(
    "--status",
    "action",
    flag_value="status",
    default=True,
    help="Report the current setting (default).",
)
def central_fetch(project_id, action):
    """Show or change Central self-heal on attachment store misses for PROJECT_ID."""
    project_id = (project_id or "").strip().upper()
    project = db.session.get(VaProjectMaster, project_id)
    if project is None:
        raise click.ClickException(f"Project '{project_id}' not found.")

    if action in ("enable", "disable"):
        project.attachment_central_fetch_enabled = action == "enable"
        db.session.commit()

    click.echo(
        f"{project.project_id}: attachment_central_fetch_enabled="
        f"{project.attachment_central_fetch_enabled}"
    )


def init_app(app):
    """Register attachment CLI commands with the Flask app."""
    app.cli.add_command(attachments_group)
