"""``flask web-intake`` commands: web-capture readiness.

Policy: docs/policy/web-intake.md, "Ready for web capture". The same
assessment the admin endpoint and the Projects panel serve, for an operator
on a shell who has no browser session.
"""
import sys

import click

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


def init_app(app) -> None:
    app.cli.add_command(web_intake_group)
