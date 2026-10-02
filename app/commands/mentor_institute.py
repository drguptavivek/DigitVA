"""``flask mentor-institute`` commands: platform-admin management of mentoring institutes.

Policy: docs/policy/organization-model.md, "Mentoring institutes". Operator-run
(shell access is the admin gate); every command takes ``--actor``, the email of
an active global admin, which fills ``created_by_user_id`` and the audit line in
grants.log (mirrors ``flask devices create-enrolment-code``).
"""
import functools

import click
import sqlalchemy as sa

from app import db
from app.models import VaStatuses, VaUsers
from app.services import mentor_institute_service as mentors
from app.services.organization_service import OrganizationError


def _actor_option(command):
    """Add the required --actor option; the command receives ``actor_user_id``."""

    @click.option(
        "--actor", "actor_email", required=True,
        help="Email of the active global admin making the change.",
    )
    @functools.wraps(command)
    def wrapper(*args, actor_email, **kwargs):
        actor = db.session.scalar(
            sa.select(VaUsers).where(VaUsers.email == actor_email.strip().lower())
        )
        if actor is None or actor.user_status != VaStatuses.active or not actor.is_admin():
            raise click.ClickException("--actor must be an active global admin.")
        return command(*args, actor_user_id=actor.user_id, **kwargs)

    return wrapper


def _run(action):
    """Run one service call, commit on success, report a refusal as a CLI error."""
    try:
        result = action()
    except OrganizationError as exc:
        db.session.rollback()
        raise click.ClickException(str(exc))
    db.session.commit()
    return result


@click.group("mentor-institute")
def mentor_group():
    """Mentoring institutes: create, attach to districts, manage staff."""


@mentor_group.command("create")
@click.argument("code")
@click.argument("name")
@_actor_option
def create(code: str, name: str, actor_user_id) -> None:
    institute = _run(lambda: mentors.create_institute(code, name, actor_user_id=actor_user_id))
    click.echo(f"Created {institute.institute_code}: {institute.institute_name}")


@mentor_group.command("deactivate")
@click.argument("code")
@_actor_option
def deactivate(code: str, actor_user_id) -> None:
    _run(lambda: mentors.set_institute_active(code, False, actor_user_id=actor_user_id))
    click.echo(f"Deactivated {code}. Grants are untouched; the guard stops applying to its staff.")


@mentor_group.command("activate")
@click.argument("code")
@_actor_option
def activate(code: str, actor_user_id) -> None:
    _run(lambda: mentors.set_institute_active(code, True, actor_user_id=actor_user_id))
    click.echo(f"Activated {code}.")


@mentor_group.command("attach")
@click.argument("code")
@click.argument("project_id")
@click.argument("district_unit_code")
@_actor_option
def attach(code: str, project_id: str, district_unit_code: str, actor_user_id) -> None:
    _run(lambda: mentors.attach_district(
        code, project_id, district_unit_code, actor_user_id=actor_user_id))
    click.echo(f"{code} attached to {project_id}/{district_unit_code}.")


@mentor_group.command("detach")
@click.argument("code")
@click.argument("project_id")
@click.argument("district_unit_code")
@_actor_option
def detach(code: str, project_id: str, district_unit_code: str, actor_user_id) -> None:
    _run(lambda: mentors.detach_district(
        code, project_id, district_unit_code, actor_user_id=actor_user_id))
    click.echo(f"{code} detached from {project_id}/{district_unit_code}. Existing grants are untouched.")


@mentor_group.command("add-user")
@click.argument("code")
@click.argument("email")
@_actor_option
def add_user(code: str, email: str, actor_user_id) -> None:
    refused = _run(lambda: mentors.add_member(code, email, actor_user_id=actor_user_id))
    click.echo(f"{email} is now staff of {code}.")
    if refused:
        click.echo(
            f"WARNING: {refused} existing active grant(s) of this user would now be refused "
            "(not unit scope, not a mentor role, or a unit outside every district the "
            "institute is attached to). Revoke them in the grants panel.",
            err=True,
        )


@mentor_group.command("remove-user")
@click.argument("code")
@click.argument("email")
@_actor_option
def remove_user(code: str, email: str, actor_user_id) -> None:
    _run(lambda: mentors.remove_member(code, email, actor_user_id=actor_user_id))
    click.echo(f"{email} removed from {code}. Existing grants are untouched.")


@mentor_group.command("set-admin")
@click.argument("code")
@click.argument("email")
@click.option("--revoke", is_flag=True, help="Clear the institute-admin flag instead of setting it.")
@_actor_option
def set_admin(code: str, email: str, revoke: bool, actor_user_id) -> None:
    """Make an active member the institute admin (creates and removes their institute's staff)."""
    _run(lambda: mentors.set_member_admin(code, email, not revoke, actor_user_id=actor_user_id))
    click.echo(f"{email} is {'no longer' if revoke else 'now'} an admin of {code}.")


def init_app(app) -> None:
    app.cli.add_command(mentor_group)
