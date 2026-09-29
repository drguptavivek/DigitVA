"""``flask devices`` commands: collection-device enrolment codes from a shell.

Usage:
  flask devices create-enrolment-code --project HP2026 --actor admin@example.com [--minutes 60] [--uses 1]

Issues a code through the same service the admin API uses
(``device_auth_service.create_enrolment_code``), so the bounds, the
DEVICE_PUBLIC_URL check and the ``device_enrolment_code_created`` security
event are identical. The code row needs a creating user (``created_by`` is
not null), so the operator names an active global admin with ``--actor``;
that admin is the recorded actor. Prints only the QR payload JSON.
"""
import json

import click
import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import VaUsers
from app.services import device_auth_service as devices


@click.group("devices")
def devices_group():
    """Collection-device commands."""


@devices_group.command("create-enrolment-code")
@click.option("--project", "project_id", required=True, help="Project id the device enrols into.")
@click.option("--actor", "actor_email", required=True, help="Email of the active global admin issuing the code.")
@click.option("--minutes", type=int, default=None, help="Lifetime in minutes (default 60).")
@click.option("--uses", type=int, default=None, help="How many devices may use it (default 1).")
def create_enrolment_code(project_id: str, actor_email: str, minutes: int | None, uses: int | None) -> None:
    """Issue an enrolment code and print the QR payload JSON."""
    actor = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == actor_email.strip().lower()))
    if actor is None or not actor.is_admin():
        raise click.ClickException("--actor must be an active global admin.")
    try:
        row, code = devices.create_enrolment_code(
            project_id, actor=actor, expires_in_minutes=minutes, max_uses=uses
        )
    except devices.DeviceAuthError as exc:
        db.session.rollback()
        raise click.ClickException(str(exc))
    db.session.commit()
    click.echo(json.dumps(
        {"v": 1, "server": current_app.config["DEVICE_PUBLIC_URL"], "enroll": code, "project": row.project_id},
        separators=(",", ":"),
    ))


def init_app(app) -> None:
    app.cli.add_command(devices_group)
