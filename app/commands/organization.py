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


_REVOKE_NOTE = "Revoked {date}: unit grant without a cadre (digitva-4650, flask org cadreless-grants)."
_MENTOR_REVOKE_NOTE = (
    "Revoked {date}: mentoring-institute member's {role} grant outside the mentor roles, "
    "no worker record backs it (digitva-4650, flask org cadreless-grants)."
)
_CLEAR_NOTE = "Cadre {cadre_id} cleared {date}: borrowed by a mentoring-institute member (digitva-4650)."


def _cadreless_grants():
    """The active unit grants the cadre rule no longer accepts, three lists:

    - cadre-less: non-members' grants with no cadre;
    - outside: members' grants whose role is not a mentor unit role
      (MENTOR_UNIT_ROLES) and that no worker record of theirs backs;
    - borrowed: members' mentor-role grants carrying a cadre no worker
      record of theirs backs.

    Three queries, each ordered for a stable list."""
    from app.models import MasOrgUnit, VaAccessScopeTypes, VaStatuses, VaUserAccessGrants, VaUsers
    from app.services.mentor_institute_service import MENTOR_UNIT_ROLES, active_member_ids_select
    from app.services.org_grant_service import worker_backed_condition

    grant = VaUserAccessGrants
    base = (
        sa.select(grant, VaUsers.email, MasOrgUnit.unit_code, MasOrgUnit.project_id)
        .join(VaUsers, VaUsers.user_id == grant.user_id)
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == grant.org_unit_id)
        .where(grant.scope_type == VaAccessScopeTypes.org_unit, grant.grant_status == VaStatuses.active)
        .order_by(MasOrgUnit.project_id, VaUsers.email, grant.role, MasOrgUnit.unit_code)
    )
    members = active_member_ids_select()
    unbacked = sa.not_(worker_backed_condition(grant.user_id, grant.org_unit_id, grant.cadre_id))
    mentor_role = grant.role.in_(MENTOR_UNIT_ROLES)
    cadreless = db.session.execute(
        base.where(grant.cadre_id.is_(None), grant.user_id.not_in(members))
    ).all()
    outside = db.session.execute(
        base.where(grant.user_id.in_(members), sa.not_(mentor_role), unbacked)
    ).all()
    borrowed = db.session.execute(
        base.where(grant.cadre_id.is_not(None), grant.user_id.in_(members), mentor_role, unbacked)
    ).all()
    return cadreless, outside, borrowed


@org_group.command("cadreless-grants")
@click.option("--apply", is_flag=True, default=False,
              help="Revoke the listed grants and clear borrowed cadres (default: list only).")
@click.option("--actor", "actor_email", default=None,
              help="Email of the active global admin recorded in grants.log (required with --apply).")
def cadreless_grants(apply: bool, actor_email: str | None) -> None:
    """List, or with --apply fix, unit grants the cadre rule no longer accepts.

    Health-system (non-member) unit grants with no cadre are revoked: status
    deactive, a revoke note on the grant row and a grants.log line; re-enrol
    the person through Workers with a cadre. Mentoring-institute members'
    grants outside the mentor roles that no worker record of theirs backs
    are revoked the same way (left active, an interview_supervisor one would
    let a mentor correct interviews). Members' mentor-role grants carrying a
    cadre their worker record does not back have the cadre cleared (left in
    place it would make them PII), the old cadre id kept in a dated note on
    the grant. Run --apply only after a verified backup and the owner's
    approval of the dry-run list (docs/policy/organization-model.md,
    "Allowed and default roles per level x cadre").
    """
    from datetime import UTC, datetime

    from app.logging.va_logger import log_grant_action
    from app.models import VaStatuses, VaUsers

    cadreless, outside, borrowed = _cadreless_grants()
    click.echo(f"Unit grants without a cadre (revoke): {len(cadreless)}")
    for g, email, unit_code, project_id in cadreless:
        click.echo(f"  {g.grant_id}  {email}  {g.role.value}  {unit_code}  {project_id}")
    click.echo(f"Mentor grants outside the mentor roles, no worker record (revoke): {len(outside)}")
    for g, email, unit_code, project_id in outside:
        click.echo(f"  {g.grant_id}  {email}  {g.role.value}  {unit_code}  {project_id}  cadre={g.cadre_id}")
    click.echo(f"Mentor grants with a borrowed cadre (clear cadre): {len(borrowed)}")
    for g, email, unit_code, project_id in borrowed:
        click.echo(f"  {g.grant_id}  {email}  {g.role.value}  {unit_code}  {project_id}  cadre={g.cadre_id}")
    if not apply:
        click.echo("Dry run only; nothing written.")
        return

    actor = db.session.scalar(sa.select(VaUsers).where(
        VaUsers.email == (actor_email or "").strip().lower()
    )) if actor_email else None
    if actor is None or actor.user_status != VaStatuses.active or not actor.is_admin():
        raise click.ClickException("--apply needs --actor, the email of an active global admin.")

    today = datetime.now(UTC).date().isoformat()

    def add_note(g, note):
        g.notes = f"{g.notes}\n{note}" if g.notes else note

    audit = []
    for g, _email, _unit, project_id in cadreless:
        g.grant_status = VaStatuses.deactive
        add_note(g, _REVOKE_NOTE.format(date=today))
        audit.append(("grant_revoked_no_cadre", g, project_id, g.cadre_id))
    for g, _email, _unit, project_id in outside:
        g.grant_status = VaStatuses.deactive
        add_note(g, _MENTOR_REVOKE_NOTE.format(date=today, role=g.role.value))
        audit.append(("grant_revoked_mentor_role", g, project_id, g.cadre_id))
    for g, _email, _unit, project_id in borrowed:
        audit.append(("grant_cadre_cleared_mentor", g, project_id, g.cadre_id))
        add_note(g, _CLEAR_NOTE.format(cadre_id=g.cadre_id, date=today))
        g.cadre_id = None
    db.session.commit()
    for action, g, project_id, cadre_id in audit:
        log_grant_action(
            action=action, actor_user_id=actor.user_id, actor_role="admin",
            target_user_id=g.user_id, grant_id=g.grant_id, role=g.role.value,
            scope_type=g.scope_type.value, project_id=project_id,
            org_unit_id=g.org_unit_id, cadre_id=cadre_id,
        )
    click.echo(
        f"Revoked {len(cadreless)} cadre-less and {len(outside)} mentor grant(s); "
        f"cleared {len(borrowed)} borrowed cadre(s)."
    )


def init_app(app) -> None:
    app.cli.add_command(org_group)
