"""``flask org`` commands: seed template, export, import, ODK choices, ensure-site."""
import sys

import click
import sqlalchemy as sa

from app import db
from app.models import VaProjectMaster
from app.services import organization_service as org


@click.group("org")
def org_group():
    """Health-system organization master-data commands."""


@org_group.command("seed-template")
@click.argument("project_id")
@click.option("--no-cadres", is_flag=True, default=False, help="Seed levels only.")
def seed_template(project_id: str, no_cadres: bool) -> None:
    try:
        org.require_organization_mode(project_id)
        counts = org.seed_default_organization(project_id, include_cadres=not no_cadres)
    except org.OrganizationError as exc:
        raise click.ClickException(str(exc))
    db.session.commit()
    click.echo(f"Seeded {project_id}: {counts}")


@org_group.command("export")
@click.argument("project_id")
@click.option("--out", "out_path", required=True, help="Path of the .xlsx to write.")
def export_cmd(project_id: str, out_path: str) -> None:
    try:
        data = org.export_organization_xlsx(project_id)
    except org.OrganizationError as exc:
        raise click.ClickException(str(exc))
    with open(out_path, "wb") as handle:
        handle.write(data)
    click.echo(f"Wrote {out_path}")


@org_group.command("odk-choices")
@click.argument("project_id")
@click.option("--out", "out_path", default=None, help="Path of the CSV to write (stdout if omitted).")
def odk_choices(project_id: str, out_path: str | None) -> None:
    body = org.export_odk_choices_csv(project_id)
    if out_path:
        with open(out_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(body)
        click.echo(f"Wrote {out_path}")
    else:
        sys.stdout.write(body)


@org_group.command("import")
@click.argument("project_id")
@click.argument("xlsx_path")
@click.option("--apply", is_flag=True, default=False, help="Apply changes (default is a dry run).")
@click.option("--deactivate-missing", is_flag=True, default=False, help="Deactivate rows absent from supplied sheets.")
def import_cmd(project_id: str, xlsx_path: str, apply: bool, deactivate_missing: bool) -> None:
    try:
        org.require_organization_mode(project_id)
    except org.OrganizationError as exc:
        raise click.ClickException(str(exc))
    with open(xlsx_path, "rb") as handle:
        sheets = org.parse_organization_workbook(handle)
    plan = org.import_organization(
        project_id, sheets, dry_run=not apply, deactivate_missing=deactivate_missing
    )
    summary = plan.as_dict()
    for sheet, counts in summary["counts"].items():
        click.echo(f"{sheet:13s} rows={counts['rows']:5d} create={counts['create']:5d} update={counts['update']:5d} deactivate={counts['deactivate']:5d}")
    for error in summary["errors"]:
        click.echo(f"ERROR: {error}", err=True)
    if plan.applied:
        db.session.commit()
        click.echo("Applied.")
    else:
        db.session.rollback()
        click.echo("Dry run only; nothing written." if not summary["errors"] else "Not applied.")
        if summary["errors"]:
            sys.exit(1)


@org_group.command("ensure-site")
@click.option("--project", "project_id", default=None, help="One project (default: every organization project).")
def ensure_site(project_id: str | None) -> None:
    """Give organization projects their automatic site. Idempotent.

    For projects set to organization before the app created the site itself.
    Policy: docs/policy/organization-model.md ("Project structure mode").
    """
    if project_id:
        project_ids = [project_id]
    else:
        project_ids = db.session.scalars(
            sa.select(VaProjectMaster.project_id)
            .where(VaProjectMaster.project_structure_mode == "organization")
            .order_by(VaProjectMaster.project_id)
        ).all()
    for pid in project_ids:
        try:
            org.require_organization_mode(pid)
            site = org.ensure_organization_site(pid)
        except (org.OrganizationError, ValueError) as exc:
            db.session.rollback()
            raise click.ClickException(f"{pid}: {exc}")
        db.session.commit()
        click.echo(f"{pid}: site {site.site_id} ({site.site_name})")


def init_app(app) -> None:
    app.cli.add_command(org_group)
