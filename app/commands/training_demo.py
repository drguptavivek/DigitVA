"""Training & demo project (TRN01) operations.

  flask training-demo setup
  flask training-demo create-session --name "..." --by admin@example.org
  flask training-demo list-sessions
  flask training-demo add-participant S001 user@example.org coder,reviewer_data_manager --by admin@example.org
  flask training-demo remove-participant S001 user@example.org coder --by admin@example.org
  flask training-demo check-source [--form-id UNSW01NC0101] [--limit 200]
  flask training-demo report S001 --by admin@example.org [--csv coders.csv --cases-csv cases.csv]
  flask training-demo close-session S001 --by admin@example.org
  flask training-demo reopen-session S001 --by admin@example.org

Needs DIGITVA_TRAINING_PROJECT_ID=TRN01. ``--by`` is an existing admin account:
the actor of the grant audit trail. Output is JSON; no case content.
Policy: docs/policy/training-demo-project.md.
"""

import json

import click
import sqlalchemy as sa

from app import db
from app.models import VaUsers
from app.models.mas_training import PARTICIPANT_ROLES
from app.services import training_demo_service as service


@click.group("training-demo")
def training_demo_group():
    """Operate the Training & demo project (TRN01) and its training sessions."""


def _admin(email: str) -> VaUsers:
    user = db.session.scalar(sa.select(VaUsers).where(sa.func.lower(VaUsers.email) == email.strip().lower()))
    if user is None:
        raise click.ClickException("No user has that --by email address.")
    return user


def _run(call, *args, **kwargs):
    try:
        outcome = call(*args, **kwargs)
    except service.TrainingDemoError as exc:
        raise click.ClickException(f"{exc.code}: {exc.message}") from exc
    click.echo(json.dumps(outcome, default=str, indent=2))


by_option = click.option("--by", "by", required=True, help="Email of the administrator acting.")


@training_demo_group.command("setup")
def setup():
    """Create TRN01 and its fixed structure, or confirm it (idempotent)."""
    _run(service.setup_training_project)


@training_demo_group.command("check-source")
@click.option("--form-id", default=service.DEFAULT_SOURCE_FORM_ID, show_default=True, help="Source ODK form.")
@click.option("--limit", default=200, show_default=True, type=click.IntRange(1, 1000), help="Cases to check.")
def check_source(form_id, limit):
    """Read-only: pseudonymise the source cases in memory and print counts only."""
    _run(service.check_source, form_id, limit)


@training_demo_group.command("create-session")
@click.option("--name", required=True, help="Session name, e.g. the training's place and date.")
@by_option
def create_session(name, by):
    """Create a session: 20 coder slots and 200 pseudonymised cases."""
    _run(lambda: service.create_training_session(name, _admin(by)))


@training_demo_group.command("list-sessions")
def list_sessions():
    """List sessions with participants, coder slots used and cases coded."""
    _run(service.list_training_sessions)


@training_demo_group.command("add-participant")
@click.argument("code")
@click.argument("email")
@click.option("--role", "roles", multiple=True, type=click.Choice(PARTICIPANT_ROLES), help="Repeat for more roles.")
@click.argument("role_list", required=False)
@by_option
def add_participant(code, email, roles, role_list, by):
    """Add an existing user to a session in one or more roles, all or nothing.

    Roles: a comma-separated ROLE_LIST (coder,reviewer_data_manager) or a
    repeated --role. Never creates a user.
    """
    chosen = [*roles, *(r.strip() for r in (role_list or "").split(","))]
    _run(lambda: service.add_participant(code, email, [r for r in chosen if r], _admin(by)))


@training_demo_group.command("remove-participant")
@click.argument("code")
@click.argument("email")
@click.argument("role", type=click.Choice(PARTICIPANT_ROLES))
@by_option
def remove_participant(code, email, role, by):
    """Deactivate a participant's training grants (reversible by adding again)."""
    def run():
        user = db.session.scalar(sa.select(VaUsers).where(sa.func.lower(VaUsers.email) == email.strip().lower()))
        if user is None:
            raise service.TrainingDemoError("unknown_user")
        return service.remove_participant(code, user.user_id, role, _admin(by))

    _run(run)


@training_demo_group.command("close-session")
@click.argument("code")
@by_option
def close_session(code, by):
    """Close a session: deactivate its participants' training grants."""
    _run(lambda: service.close_training_session(code, _admin(by)))


@training_demo_group.command("reopen-session")
@click.argument("code")
@by_option
def reopen_session(code, by):
    """Reopen a closed session: reactivate the grants of active participants."""
    _run(lambda: service.reopen_training_session(code, _admin(by)))


@training_demo_group.command("report")
@click.argument("code")
@by_option
@click.option("--csv", "coders_path", type=click.Path(dir_okay=False), help="Write the coder table here.")
@click.option("--cases-csv", "cases_path", type=click.Path(dir_okay=False), help="Write the per-case table here.")
def report(code, by, coders_path, cases_path):
    """Print the trainer report (counts, no case content); optionally write its CSVs."""
    from app.services import training_report_service as reports

    def run():
        data = reports.training_session_report(code, _admin(by))
        for path, build in ((coders_path, reports.coders_csv), (cases_path, reports.cases_csv)):
            if path:
                with open(path, "w", encoding="utf-8", newline="") as handle:
                    handle.write(build(data))
        return {"session": data["session"]["session_code"], "totals": data["totals"]}

    _run(run)


def init_app(app):
    app.cli.add_command(training_demo_group)
