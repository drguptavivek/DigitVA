"""``flask web-intake`` commands: web-capture readiness, a dev consent notice.

Policy: docs/policy/web-intake.md, "Ready for web capture". The same
assessment the admin endpoint and the Projects panel serve, for an operator
on a shell who has no browser session.
"""
import sys

import click
import sqlalchemy as sa

from app import db
from app.models import VaUsers
from app.services import consent_service, identifier_type_service
from app.services.odk_case_service import backfill_odk_cases
from app.services.web_intake_readiness_service import (
    WebIntakeReadinessError,
    assess_web_intake_readiness,
)

#: Widest status word, so the table's columns line up without a formatter.
_STATUS_WIDTH = 4


@click.group("web-intake")
def web_intake_group():
    """Web intake (browser VA questionnaire) commands."""


@web_intake_group.command("readiness")
@click.argument("project_id")
def readiness(project_id: str) -> None:
    """Report whether PROJECT_ID can capture a VA through the browser form."""
    try:
        result = assess_web_intake_readiness(project_id)
    except WebIntakeReadinessError as exc:
        raise click.ClickException(str(exc))

    click.echo(
        f"{result['project_id']}: "
        + ("READY" if result["ready"] else "NOT READY")
    )
    for check in result["checks"]:
        click.echo(
            f"  {check['status'].upper():<{_STATUS_WIDTH}}  "
            f"{check['code']:<17}{check['message']}"
        )
        if check["fix_hint"]:
            click.echo(f"        {'':<17}Fix: {check['fix_hint']}")
    if not result["ready"]:
        sys.exit(1)


@web_intake_group.command("backfill-odk-cases")
@click.option("--project", "project_id", default=None, help="Only this project (default: every tree project).")
@click.option("--dry-run", is_flag=True, help="Count what would be created; write nothing.")
def backfill_odk_cases_command(project_id: str | None, dry_run: bool) -> None:
    """Give ODK-only VAs in tree projects a death-register case (digitva-l8y3)."""
    counts = backfill_odk_cases(project_id=project_id, dry_run=dry_run)
    verb = "would create" if dry_run else "created"
    click.echo(
        f"{verb}: {counts['created']}  skipped (identity missing): {counts['identity_missing']}  "
        f"skipped (already linked): {counts['linked']}  failed: {counts['failed']}"
    )


#: The dev notice's purposes, from docs/policy/respondent-consent-notice-draft.md.
_DEV_PURPOSES = (
    ("record_interview", "To record the death and complete the interview", True),
    ("contact", "To contact you about this interview", True),
    ("messages", "To send you messages about this interview", False),
    ("cause_of_death", "To decide the cause of death", True),
    ("reports", "For government and statistical reports", True),
    ("research", "For research on verbal autopsy, de-identified", False),
)
_DEV_TEXT = (
    "DEVELOPMENT NOTICE, not for field use. We ask about a death so that the cause can be "
    "understood. Your name, phone and address are used only for this interview. "
    "Please say yes or no to each item."
)


@web_intake_group.command("seed-consent-notice")
@click.argument("project_id")
@click.option("--actor", "actor_email", required=True, help="Email of the admin recorded as creating it.")
@click.option("--language", default="en", show_default=True)
@click.option("--require", "require", is_flag=True, help="Also set the project to require consent.")
def seed_consent_notice(project_id: str, actor_email: str, language: str, require: bool) -> None:
    """Add a development consent notice version to PROJECT_ID (digitva-gb8w.3).
    Field projects write their own notice through the consent-settings API."""
    actor = db.session.scalar(sa.select(VaUsers).where(sa.func.lower(VaUsers.email) == actor_email.lower()))
    if actor is None:
        raise click.ClickException("No user with that email.")
    project_id = project_id.strip().upper()
    try:
        row = consent_service.create_notice_version(actor, project_id, {
            "language": language, "text": _DEV_TEXT, "allowed_modes": ["spoken", "tap", "signed"],
            "purposes": [{"code": c, "label": label, "required": r} for c, label, r in _DEV_PURPOSES],
        })
        if require:
            consent_service.save_settings(actor, project_id, {"consent_required": True})
    except (consent_service.ConsentError, identifier_type_service.IdentifierTypeError) as exc:
        db.session.rollback()
        raise click.ClickException(str(exc))
    db.session.commit()
    click.echo(f"{project_id}: notice version {row.version} ({row.language}) {row.notice_version_id}"
               + (", consent required" if require else ""))


def init_app(app) -> None:
    app.cli.add_command(web_intake_group)
