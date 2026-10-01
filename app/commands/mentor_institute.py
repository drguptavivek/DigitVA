"""``flask mentor-institute`` commands: platform-admin management of mentoring institutes.

Policy: docs/policy/organization-model.md, "Mentoring institutes". Operator-run
(shell access is the admin gate); every change is audited to grants.log.
"""
import click

from app import db
from app.services import mentor_institute_service as mentors
from app.services.organization_service import OrganizationError


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
def create(code: str, name: str) -> None:
    institute = _run(lambda: mentors.create_institute(code, name))
    click.echo(f"Created {institute.institute_code}: {institute.institute_name}")


@mentor_group.command("deactivate")
@click.argument("code")
def deactivate(code: str) -> None:
    _run(lambda: mentors.set_institute_active(code, False))
    click.echo(f"Deactivated {code}. Grants are untouched; the guard stops applying to its staff.")


@mentor_group.command("activate")
@click.argument("code")
def activate(code: str) -> None:
    _run(lambda: mentors.set_institute_active(code, True))
    click.echo(f"Activated {code}.")


@mentor_group.command("attach")
@click.argument("code")
@click.argument("project_id")
@click.argument("district_unit_code")
def attach(code: str, project_id: str, district_unit_code: str) -> None:
    _run(lambda: mentors.attach_district(code, project_id, district_unit_code))
    click.echo(f"{code} attached to {project_id}/{district_unit_code}.")


@mentor_group.command("detach")
@click.argument("code")
@click.argument("project_id")
@click.argument("district_unit_code")
def detach(code: str, project_id: str, district_unit_code: str) -> None:
    _run(lambda: mentors.detach_district(code, project_id, district_unit_code))
    click.echo(f"{code} detached from {project_id}/{district_unit_code}. Existing grants are untouched.")


@mentor_group.command("add-user")
@click.argument("code")
@click.argument("email")
def add_user(code: str, email: str) -> None:
    refused = _run(lambda: mentors.add_member(code, email))
    click.echo(f"{email} is now staff of {code}.")
    if refused:
        click.echo(
            f"WARNING: {refused} existing active grant(s) of this user would now be refused "
            "(project/site scope or non-mentor role). Revoke them in the grants panel.",
            err=True,
        )


@mentor_group.command("remove-user")
@click.argument("code")
@click.argument("email")
def remove_user(code: str, email: str) -> None:
    _run(lambda: mentors.remove_member(code, email))
    click.echo(f"{email} removed from {code}. Existing grants are untouched.")


def init_app(app) -> None:
    app.cli.add_command(mentor_group)
