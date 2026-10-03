"""The site PI report: one (project, site) pair or one unit's subtree.

Offered to a site_pi for each pair they hold, to an In-charge (site_pi at a
unit) for each unit they hold, and to a project_pi for their projects' sites
and, on a tree project, its top-level units (access-control-model.md,
"site_pi", "In-charge"; digitva-0wc F8). Every selection is authorized by
``authz.can(user, SITE_PI_REPORT, target)``, never by the option list.
"""

import uuid

import sqlalchemy as sa
from flask import Blueprint, render_template, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import (
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectSites,
    VaStatuses,
)
from app.services.authz import Action, Reason, can, resolve_grants
from app.services.sitepi_reporting_service import (
    get_sitepi_dashboard_data,
    get_sitepi_unit_dashboard_data,
)
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash

sitepi = Blueprint("sitepi", __name__)

_UNIT_PREFIX = "unit:"


def _site_key(project_id: str, site_id: str) -> str:
    """The dropdown value for one (project, site) pair: a site_id alone is
    shared across projects (digitva-d5s)."""
    return f"{project_id}:{site_id}"


def _site_label(project_id: str, site_id: str) -> str:
    return f"{project_id} / {site_id}"


def _unit_label(project_id: str, level_name: str, unit_name: str, unit_code: str) -> str:
    return f"{project_id} / {level_name} {unit_name} ({unit_code})"


def _report_options(user):
    """([(key, label)] of pairs, [(key, label)] of units) the user is offered.

    Two queries at most, whatever the number of grants.
    """
    g = resolve_grants(user)
    pairs = {
        (x.project_id, x.site_id)
        for x in g.of((VaAccessRoles.site_pi,), scope_types=(VaAccessScopeTypes.project_site,))
    }
    pi_projects = sorted({x.project_id for x in g.of((VaAccessRoles.project_pi,))})
    if pi_projects:
        pairs |= set(db.session.execute(
            sa.select(VaProjectSites.project_id, VaProjectSites.site_id).where(
                VaProjectSites.project_id.in_(pi_projects),
                VaProjectSites.project_site_status == VaStatuses.active,
            )
        ).tuples())
    held_units = sorted(
        str(x.org_unit_id)
        for x in g.of((VaAccessRoles.site_pi,), scope_types=(VaAccessScopeTypes.org_unit,))
    )
    pi_trees = [p for p in pi_projects if g.has_tree(p)]
    units = []
    if held_units or pi_trees:
        units = db.session.execute(
            sa.select(
                MasOrgUnit.org_unit_id, MasOrgUnit.project_id, MasOrgUnit.unit_code,
                MasOrgUnit.unit_name, MasOrgLevel.level_name,
            )
            .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
            .where(
                MasOrgUnit.is_active.is_(True),
                sa.or_(
                    MasOrgUnit.org_unit_id.in_(held_units),
                    sa.and_(
                        MasOrgUnit.project_id.in_(pi_trees),
                        MasOrgUnit.parent_org_unit_id.is_(None),
                    ),
                ),
            )
            .order_by(MasOrgUnit.project_id, MasOrgUnit.path)
        ).all()
    return (
        [(_site_key(p, s), _site_label(p, s)) for p, s in sorted(pairs)],
        [
            (f"{_UNIT_PREFIX}{u.org_unit_id}",
             _unit_label(u.project_id, u.level_name, u.unit_name, u.unit_code))
            for u in units
        ],
    )


def _report(selected: str):
    """(kind, label, data) for one validated selection; refuses with 403/404."""
    if selected.startswith(_UNIT_PREFIX):
        try:
            org_unit_id = uuid.UUID(selected[len(_UNIT_PREFIX):])
        except ValueError:
            va_permission_abortwithflash("Unit not found.", 404)
        decision = can(current_user, Action.SITE_PI_REPORT, ("unit", org_unit_id))
        if not decision:
            status = 404 if decision.reason is Reason.NOT_FOUND else 403
            va_permission_abortwithflash("Access denied for this unit.", status)
        unit = db.session.execute(
            sa.select(
                MasOrgUnit.project_id, MasOrgUnit.unit_code, MasOrgUnit.unit_name,
                MasOrgLevel.level_name,
            )
            .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
            .where(MasOrgUnit.org_unit_id == org_unit_id)
        ).one()
        return (
            "Unit",
            _unit_label(unit.project_id, unit.level_name, unit.unit_name, unit.unit_code),
            get_sitepi_unit_dashboard_data(org_unit_id),
        )
    project_id, _, site_id = selected.partition(":")
    if not project_id or not site_id or not can(
        current_user, Action.SITE_PI_REPORT, ("pair", project_id, site_id)
    ):
        va_permission_abortwithflash("Access denied for this site.", 403)
    return "Site", _site_label(project_id, site_id), get_sitepi_dashboard_data(project_id, site_id)


@sitepi.get("/")
@role_required("site_pi", "project_pi")
def dashboard():
    sitepi_sites, sitepi_units = _report_options(current_user)
    options = sitepi_sites + sitepi_units
    if not options:
        va_permission_abortwithflash("No sites or units assigned for supervision.", 403)

    kind, label, data = _report(options[0][0])
    return render_template(
        "va_frontpages/va_sitepi.html",
        sitepi_sites=sitepi_sites,
        sitepi_units=sitepi_units,
        default_kind=kind,
        default_site=label,
        default_site_data=data,
    )


@sitepi.get("/data")
@role_required("site_pi", "project_pi")
def sitepi_data():
    selected = request.args.get("siteSelect")
    if not selected:
        return "<div class='text-center py-5'><p class='text-muted'>No site selected.</p></div>"

    kind, label, data = _report(selected)
    return render_template(
        "va_intermediate_partials/sitepi_dashboard_content.html",
        site_data=data,
        site_label=label,
        report_kind=kind,
    )
