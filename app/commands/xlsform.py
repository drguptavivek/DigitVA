"""``flask xlsform`` commands: compare a deployed ODK workbook with the project's
generated form (digitva-aek). Policy: docs/policy/va-form-project-configuration.md,
"The ODK form is a project output".
"""
from pathlib import Path

import click

from app import db
from app.models import VaProjectMaster
from app.services import xlsform_service

#: Rows listed per section before the rest are counted, so a workbook that
#: shares nothing with the form does not print thousands of lines.
_LIST_LIMIT = 200


def _section(title: str, items: list) -> None:
    click.echo(f"\n{title}: {len(items)}")
    for item in items[:_LIST_LIMIT]:
        click.echo(f"  {item}")
    if len(items) > _LIST_LIMIT:
        click.echo(f"  ... and {len(items) - _LIST_LIMIT} more")


@click.group("xlsform")
def xlsform_group():
    """ODK XLSForm commands."""


@xlsform_group.command("diff")
@click.option("--workbook", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="The deployed workbook (.xlsx) to compare.")
@click.option("--project", "project_id", required=True, help="The project whose generated form to compare against.")
@click.option("--form-id", default=None, help="Which ODK form, when the project maps several.")
def diff_cmd(workbook: Path, project_id: str, form_id: str | None) -> None:
    """List rows only the deployed workbook has, only the generated form has,
    and rows both have that differ. Nothing is merged or written."""
    project = db.session.get(VaProjectMaster, project_id)
    if project is None:
        raise click.ClickException(f"Project {project_id!r} not found.")
    try:
        form = xlsform_service.compose_project_form(project, form_id=form_id)
        report = xlsform_service.diff_against_workbook(form, workbook)
    except xlsform_service.XlsFormError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"{report['workbook']} against the generated form {report['form_id']} ({project_id})")
    _section("Survey rows only in the workbook", report["survey_only_in_workbook"])
    _section("Survey rows only in the generated form", report["survey_only_in_generated"])
    _section(
        "Survey rows in both that differ",
        [f"{c['name']}: {', '.join(c['columns'])}" for c in report["survey_changed"]],
    )
    _section("Choices only in the workbook (list/name)", [f"{a}/{b}" for a, b in report["choices_only_in_workbook"]])
    _section("Choices only in the generated form (list/name)", [f"{a}/{b}" for a, b in report["choices_only_in_generated"]])


def init_app(app) -> None:
    app.cli.add_command(xlsform_group)
