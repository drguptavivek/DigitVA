"""Data management blueprint — /data-management/

Page routes and JSON API routes for data-manager user/grant management.
Submission-related JSON API routes live in app/routes/api/data_management.py.
Shared helpers live in app/services/data_management_service.py.
"""

import logging
import re
import uuid

import sqlalchemy as sa
from flask import Blueprint, g, jsonify, redirect, render_template, request
from flask_login import current_user
from flask_wtf.csrf import generate_csrf
from functools import wraps

from app import db, limiter
from app.decorators import role_required
from app.models import (
    MasCadre,
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
    VaUsers,
)
from app.routes.admin import (
    _grant_org_unit_columns,
    _grant_project_id_expression,
    _grant_site_id_expression,
    _json_error,
    _payload_grant_target,
    _resolve_scope_from_payload,
    _serialize_grant,
    _serialize_project_site,
    _serialize_projects,
    _serialize_user,
)
from app.services import authz
from app.services import mentor_institute_service as mentors
from app.services import organization_service as org
from app.services.org_grant_service import validate_org_unit_grant
from app.services.organization_service import OrganizationError
from app.services.submission_analytics_mv import get_dm_kpi_from_mv
from app.services.data_management_service import (
    dm_odk_edit_url,
    audit_dm_submission_action,
    dm_grant_scope,
    dm_scoped_forms,
)
from app.services.authz import Action, AuthzError, GrantTarget, require
from app.services.authz.actions import DM_SITE_ASSIGNABLE, DM_TREE_ASSIGNABLE
from app.services.cod_bucket_mapping_service import (
    default_reporting_scheme_code,
    list_cod_bucket_schemes,
)
from app.utils.va_permission.va_permission_01_abortwithflash import (
    va_permission_abortwithflash,
)

data_management = Blueprint("data_management", __name__)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_R = VaAccessRoles
_P = VaAccessScopeTypes.project
_PS = VaAccessScopeTypes.project_site
_U = VaAccessScopeTypes.org_unit

#: The roles this interface writes and lists, for every caller (admin
#: included): what a data manager assigns in either project kind. Who may
#: write which role where is ``authz.can_grant``'s; site_pi,
#: interview_supervisor, project_pi and admin stay on the admin panel.
_DM_INTERFACE_ROLES = DM_SITE_ASSIGNABLE | DM_TREE_ASSIGNABLE
_DM_INTERFACE_ROLE_LIST = sorted(_DM_INTERFACE_ROLES, key=lambda r: r.value)

#: One message for every refusal, so it never says whether the grantee is a
#: mentoring institute member (the guard runs only after this passes).
_GRANT_REFUSAL = "You may not manage this grant."


def _grant_target(role, scope_type, project_id, project_site_id, org_unit_id):
    return GrantTarget(
        role=role,
        scope_type=scope_type,
        project_id=project_id if scope_type == _P else None,
        project_site_id=project_site_id if scope_type == _PS else None,
        org_unit_id=org_unit_id if scope_type == _U else None,
    )


def _may_write(target, grantee_id) -> bool:
    """Whether the current user may create, reactivate or revoke *target* here."""
    return target.role in _DM_INTERFACE_ROLES and bool(
        authz.can_grant(current_user, target, grantee_id=grantee_id)
    )


def _writer_role() -> str:
    """The role recorded as the actor of a grant write in the audit log."""
    g = authz.resolve_grants(current_user)
    if g.is_admin:
        return "admin"
    held = {x.role for x in authz.writer_grants(g)}
    return next(
        (r.value for r in (_R.project_pi, _R.site_pi, _R.data_manager) if r in held),
        "data_manager",
    )


def _assignable_roles(g, writers):
    """The interface roles some writer grant of the actor may assign somewhere."""
    if g.is_admin:
        return _DM_INTERFACE_ROLES
    roles = set()
    for x in writers:
        if x.role == _R.project_pi:
            roles |= _DM_INTERFACE_ROLES
        elif not g.has_tree(x.project_id):
            roles |= DM_SITE_ASSIGNABLE
        else:
            roles |= DM_TREE_ASSIGNABLE
            if x.scope_type != _PS:  # nothing lies below a pair
                roles.add(_R.data_manager)
    return roles


def _mentor_guard_error(user_id, role, org_unit_id=None, cadre_id=None):
    """The mentoring-institute guard for a grant write, as a message or None.

    Run only after the caller's own permission check passed, so the message
    never discloses membership to someone who may not manage the grant.
    """
    if user_id is None:
        return None
    try:
        if org_unit_id is not None:
            validate_org_unit_grant(
                role=role, org_unit_id=org_unit_id, cadre_id=cadre_id, user_id=user_id
            )
        else:
            mentors.check_mentor_grant(user_id, role, None)
    except OrganizationError as exc:
        return str(exc)
    return None


def _listed_grants_condition():
    """The grants these pages list: interface roles the actor may manage."""
    return sa.and_(
        VaUserAccessGrants.role.in_(_DM_INTERFACE_ROLE_LIST),
        authz.grant_list_filter(current_user),
    )


def _is_wide_writer() -> bool:
    """Admin, or a project/pair data manager or project PI: the full user
    search and any account. A unit writer (unit data manager, In-charge)
    reaches only the people it manages."""
    g = authz.resolve_grants(current_user)
    return g.is_admin or any(x.scope_type in (_P, _PS) for x in authz.writer_grants(g))


def _managed_user_condition():
    """Accounts holding an active grant the current user may manage."""
    return VaUsers.user_id.in_(
        sa.select(VaUserAccessGrants.user_id).where(
            VaUserAccessGrants.grant_status == VaStatuses.active,
            _listed_grants_condition(),
        )
    )


def _dm_may_see_user(target_user_id) -> bool:
    """Whose account the current user may open or edit on these pages.

    A wide writer (``_is_wide_writer``) keeps the reach project and site data
    managers always had. A unit writer sees the holders of grants it may
    manage, plus the mentoring institute staff of districts it covers (the
    same people its user search returns).
    """
    if _is_wide_writer():
        return True
    if db.session.scalar(sa.select(sa.exists().where(
        VaUsers.user_id == target_user_id, _managed_user_condition()
    ))):
        return True
    staff, _ = mentors.dm_visible_mentor_staff(
        current_user.user_id, "", True, user_id=target_user_id
    )
    return bool(staff)


def require_dm_scope(f):
    """Structural authz gate for grant mutation endpoints.

    Asks ``authz.can_grant`` (behind the interface role list) before the
    handler so the check is structurally unskippable, then the
    mentoring-institute guard. Two paths:

    - Toggle (grant_id in URL kwargs): the stored grant's role and scope; a
      non-admin never revokes their own data_manager grant here.
    - Create (no grant_id): resolves scope from JSON payload and stores the
      parsed values in g.dm_scope so the handler avoids re-parsing.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        grant_id = kwargs.get("grant_id")

        guard_error = None
        if grant_id is not None:
            # Toggle path — scope comes from the existing grant record.
            grant = db.session.get(VaUserAccessGrants, grant_id)
            if not grant:
                return _json_error("Grant not found.", 404)
            if (
                not current_user.is_admin()
                and grant.role == _R.data_manager
                and grant.user_id == current_user.user_id
            ):
                return _json_error(
                    "You cannot revoke your own data_manager grant from this interface.", 400
                )
            ok = _may_write(
                _grant_target(grant.role, grant.scope_type, grant.project_id,
                              grant.project_site_id, grant.org_unit_id),
                grant.user_id,
            )
            if ok and grant.grant_status != VaStatuses.active:
                # Reactivating is a write: the mentor guard (and, for a unit
                # grant, the cadre rule) run after the permission check.
                guard_error = _mentor_guard_error(
                    grant.user_id, grant.role,
                    grant.org_unit_id if grant.scope_type == _U else None,
                    grant.cadre_id,
                )
        else:
            # Create path — scope comes from the request payload. Resolve
            # without the mentor guard; it runs after the permission check.
            payload = request.get_json(silent=True) or {}
            try:
                target_id = uuid.UUID(str(payload.get("user_id")))
            except ValueError:
                target_id = None  # the handler rejects a bad user_id itself
            # Permission first: the cadre and unit checks below would tell a
            # caller about a unit outside their scope (digitva-xd1q).
            early = _payload_grant_target(payload)
            if early is not None and not _may_write(early, target_id):
                log.warning(
                    "Grant scope denied: user=%s path=%s", current_user.get_id(), request.path
                )
                return _json_error(_GRANT_REFUSAL, 403)
            try:
                scope = _resolve_scope_from_payload(payload)
            except ValueError as exc:
                return _json_error(str(exc), 400)
            ok = _may_write(
                _grant_target(scope.role, scope.scope_type, scope.project_id,
                              scope.project_site_id, scope.org_unit_id),
                target_id,
            )
            if ok:
                guard_error = _mentor_guard_error(
                    target_id, scope.role,
                    scope.org_unit_id if scope.scope_type == _U else None,
                    scope.cadre_id,
                )
            # Store parsed scope on g so the handler doesn't need to re-parse.
            g.dm_scope = scope

        if not ok:
            log.warning(
                "Grant scope denied: user=%s path=%s", current_user.get_id(), request.path
            )
            return _json_error(_GRANT_REFUSAL, 403)
        if guard_error:
            return _json_error(guard_error, 400)

        return f(*args, **kwargs)
    return wrapper


@data_management.get("/")
@role_required("data_manager", "admin", "collaborator", "collaborator_pii")
def dashboard():
    scope = dm_grant_scope(current_user, viewers=True)
    if not scope and not current_user.is_admin():
        va_permission_abortwithflash("No data-manager scope has been assigned.", 403)

    kpi = get_dm_kpi_from_mv(
        project_ids=sorted(scope.project_ids),
        project_site_pairs=scope.pairs,
        unit_ids=scope.unit_subtree(),
    )
    return render_template(
        "va_frontpages/va_data_manager.html",
        total_submissions=kpi["total_submissions"],
        flagged_submissions=kpi["flagged_submissions"],
        odk_has_issues_submissions=kpi["odk_has_issues_submissions"],
        smartva_missing_submissions=kpi["smartva_missing_submissions"],
        # Whole-form sync (authz SYNC_FORM): a data-manager project or site
        # grant, or project_pi on a tree project; the sync routes are
        # data-manager only, so an admin without such a grant is not offered it.
        can_sync_forms=(
            current_user.is_data_manager() and dm_grant_scope(current_user).has_direct
        ),
        # A viewer's row link opens the read-only area view; the data-manager
        # view, ODK edit and upstream-change actions are not theirs.
        view_only=not (current_user.is_admin() or current_user.is_data_manager()),
    )


@data_management.get("/dashboard")
@role_required("data_manager", "admin")
def kpi_dashboard():
    """Data manager KPI analytics dashboard.

    Shell template only — all data fetched client-side from /api/v1/analytics/dm-kpi/* endpoints.

    Admits exactly what those endpoints admit (digitva-4in): data managers
    as ``effective_roles`` counts them (any scope, the In-charge, project_pi
    on a tree project) and admin. Viewers are not: several panels name
    coders, with no redaction path.
    """
    if not current_user.is_admin() and not dm_grant_scope(current_user):
        va_permission_abortwithflash("No data-manager scope has been assigned.", 403)

    return render_template("va_frontpages/va_dm_kpi_dashboard.html")


@data_management.get("/cod-buckets")
# NOT viewer-reachable. The page itself is only a shell: every value on it
# comes from app/routes/api/cod_buckets.py (/schemes, /aggregates,
# /export.csv), all three of which are data_manager/admin only. Granting the
# page alone would hand a collaborator a screen that 403s on every fetch.
# Opening the API to viewers is a separate widening -- export.csv carries
# staff identity and has no redaction path yet -- so it needs its own review
# rather than being pulled in as a side effect of granting the page.
@role_required("data_manager", "admin")
def cod_bucket_reporting():
    if not current_user.is_admin() and not dm_grant_scope(current_user, viewers=True):
        va_permission_abortwithflash("No data-manager scope has been assigned.", 403)

    forms = dm_scoped_forms(current_user)
    schemes = [
        {
            "scheme_code": scheme.scheme_code,
            "scheme_name": scheme.scheme_name,
        }
        for scheme in list_cod_bucket_schemes()
        if scheme.is_active
    ]
    default_scheme_code = default_reporting_scheme_code()
    return render_template(
        "va_frontpages/va_cod_bucket_reporting.html",
        cod_bucket_forms=forms,
        cod_bucket_schemes=schemes,
        cod_bucket_default_scheme_code=default_scheme_code,
    )


@data_management.get("/view/<va_sid>")
@role_required("data_manager", "admin")
def view_submission(va_sid):
    """Data manager read-only view of a submission.

    The data-manager rendering carries the triage panel, so it needs authz
    TRIAGE (the data-manager lens; admin bypasses, F11).
    """
    from app.models import VaSubmissionsAuditlog
    from app.services.coding_service import render_va_coding_page
    try:
        require(current_user, Action.TRIAGE, va_sid)
    except AuthzError as e:
        message = (
            e.message if e.status_code == 404
            else "You do not have data-manager access to this submission."
        )
        va_permission_abortwithflash(message, e.status_code)
    form = db.session.get(VaSubmissions, va_sid)
    # Audit read
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid,
        va_audit_byrole="data_manager",
        va_audit_by=current_user.user_id,
        va_audit_operation="r",
        va_audit_action="data_manager_viewed_submission_read_only",
        va_audit_entityid=uuid.uuid4(),
    ))
    db.session.commit()
    return render_va_coding_page(form, "vadata", "vaview", "data_manager")


@data_management.get("/submissions/<path:va_sid>/odk-edit")
@role_required("data_manager", "admin")
def submission_odk_edit(va_sid):
    odk_edit_url = dm_odk_edit_url(current_user, va_sid)
    if not odk_edit_url:
        va_permission_abortwithflash(
            "ODK edit link is not available for this submission.", 404
        )
    audit_dm_submission_action(va_sid, "data_manager_opened_odk_edit_link")
    return redirect(odk_edit_url)


# ---------------------------------------------------------------------------
# User & Grant Management
# ---------------------------------------------------------------------------


@data_management.get("/users")
@role_required("data_manager", "admin")
def user_management():
    """User + grant management page for data-managers."""
    from app.models.mas_languages import MasLanguages

    languages = db.session.scalars(
        sa.select(MasLanguages)
        .where(MasLanguages.is_active == True)
        .order_by(MasLanguages.language_name)
    ).all()
    return render_template(
        "va_frontpages/data_manager_partials/_user_management.html",
        available_languages=[
            {"code": lang.language_code, "name": lang.language_name}
            for lang in languages
        ],
    )


@data_management.get("/api/bootstrap")
@role_required("data_manager", "admin")
def manage_bootstrap():
    """Return CSRF token and scope context for the management JS."""
    grants = authz.resolve_grants(current_user)
    writers = authz.writer_grants(grants)
    is_admin = grants.is_admin
    # Admins are treated as project-scoped (can assign at project or site level)
    is_project_scoped = is_admin or any(x.scope_type == _P for x in writers)

    return jsonify({
        "csrf_header_name": "X-CSRFToken",
        "csrf_token": generate_csrf(),
        "user": {
            "user_id": str(current_user.user_id),
            "email": current_user.email,
            "name": current_user.name,
            "is_admin": is_admin,
            "is_project_scoped": is_project_scoped,
            "managed_project_ids": sorted({x.project_id for x in writers if x.scope_type == _P}),
            "managed_site_pairs": [
                {"project_id": pid, "site_id": sid}
                for pid, sid in sorted({(x.project_id, x.site_id) for x in writers
                                        if x.scope_type == _PS})
            ],
        },
        "allowed_roles": sorted(r.value for r in _assignable_roles(grants, writers)),
    })


@data_management.get("/api/projects")
@role_required("data_manager", "admin")
def manage_projects():
    """Projects the current user may write grants in, each with ``has_tree``
    (an active organization level: the unit scope applies)."""
    stmt = (
        sa.select(VaProjectMaster)
        .where(VaProjectMaster.project_status == VaStatuses.active)
        .order_by(VaProjectMaster.project_id)
    )
    grants = authz.resolve_grants(current_user)
    if not grants.is_admin:
        project_ids = sorted({x.project_id for x in authz.writer_grants(grants)})
        if not project_ids:
            return jsonify({"projects": []})
        stmt = stmt.where(VaProjectMaster.project_id.in_(project_ids))
    projects = db.session.scalars(stmt).all()
    tree_ids = set(db.session.scalars(
        sa.select(MasOrgLevel.project_id).distinct().where(
            MasOrgLevel.project_id.in_([p.project_id for p in projects]),
            MasOrgLevel.is_active.is_(True),
        )
    ))
    serialized = _serialize_projects(projects)
    for item in serialized:
        item["has_tree"] = item["project_id"] in tree_ids
    return jsonify({"projects": serialized})


@data_management.get("/api/project-sites")
@role_required("data_manager", "admin")
def manage_project_sites():
    """Project-sites the current user may write grants on: every site of a
    project they hold a project-scope writer grant in, and their own pairs."""
    project_id = request.args.get("project_id")
    grants = authz.resolve_grants(current_user)
    writers = authz.writer_grants(grants)

    stmt = (
        sa.select(
            VaProjectSites.project_site_id,
            VaProjectSites.project_id,
            VaProjectSites.site_id,
            VaProjectSites.project_site_status,
            VaProjectSites.coding_enabled,
            VaProjectSites.coding_start_date,
            VaProjectSites.coding_end_date,
            VaProjectSites.daily_coder_limit,
            VaProjectMaster.project_name,
            VaSiteMaster.site_name,
        )
        .join(VaProjectMaster, VaProjectMaster.project_id == VaProjectSites.project_id)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
        .where(
            VaProjectSites.project_site_status == VaStatuses.active,
            VaProjectMaster.project_status == VaStatuses.active,
            VaSiteMaster.site_status == VaStatuses.active,
        )
    )

    if project_id:
        stmt = stmt.where(VaProjectSites.project_id == project_id)

    # Admins see all project-sites.
    if not grants.is_admin:
        projects = sorted({x.project_id for x in writers if x.scope_type == _P})
        pairs = sorted({(x.project_id, x.site_id) for x in writers if x.scope_type == _PS})
        conditions = []
        if projects:
            conditions.append(VaProjectSites.project_id.in_(projects))
        if pairs:
            conditions.append(
                sa.tuple_(VaProjectSites.project_id, VaProjectSites.site_id).in_(pairs)
            )
        if not conditions:
            return jsonify({"project_sites": []})
        stmt = stmt.where(sa.or_(*conditions))

    rows = db.session.execute(
        stmt.order_by(VaProjectSites.project_id, VaProjectSites.site_id)
    ).all()
    return jsonify({"project_sites": [_serialize_project_site(r) for r in rows]})


@data_management.get("/api/organization")
@role_required("data_manager", "admin")
def manage_organization():
    """Unit and cadre pickers for one district project.

    ``units``: the active units the current user may write grants on (all of
    them for an admin or a project-scope writer, the subtree of each unit
    writer grant, none for a pair writer); ``cadres`` and ``level_cadres``
    let the page offer only cadres defined at a unit's level, as the
    validator requires. 403 when the user writes no grant in the project.
    """
    project_id = (request.args.get("project_id") or "").strip()
    grants = authz.resolve_grants(current_user)
    writers = [x for x in authz.writer_grants(grants) if x.project_id == project_id]
    if not (grants.is_admin or writers):
        return _json_error("You do not have access to that project.", 403)

    stmt = (
        sa.select(
            MasOrgUnit.org_unit_id, MasOrgUnit.unit_code, MasOrgUnit.unit_name,
            MasOrgUnit.org_level_id, MasOrgLevel.level_code, MasOrgLevel.depth,
        )
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .where(MasOrgUnit.project_id == project_id, MasOrgUnit.is_active.is_(True))
        .order_by(MasOrgUnit.path)
    )
    if not (grants.is_admin or any(x.scope_type == _P for x in writers)):
        unit_ids = [x.org_unit_id for x in writers if x.scope_type == _U]
        if not unit_ids:
            return jsonify({"units": [], "cadres": [], "level_cadres": []})
        stmt = stmt.where(MasOrgUnit.org_unit_id.in_(authz.subtree_select(unit_ids)))
    units = [
        {
            "org_unit_id": str(row.org_unit_id),
            "unit_code": row.unit_code,
            "unit_name": row.unit_name,
            "org_level_id": str(row.org_level_id),
            "level_code": row.level_code,
            "depth": row.depth,
        }
        for row in db.session.execute(stmt)
    ]
    return jsonify({
        "units": units,
        "cadres": [org.serialize_cadre(c) for c in org.list_cadres(project_id)],
        "level_cadres": org.list_level_cadres(project_id),
    })


#: Rows a data-manager user search returns; more matches set ``truncated``.
_USER_SEARCH_LIMIT = 25


def _search_users(stmt, query, include_inactive):
    """Run a user search: *query* is a literal substring of email or name
    (%, _ and \\ match themselves; autoescape sets its own ESCAPE character).
    Returns up to ``_USER_SEARCH_LIMIT + 1`` rows so the caller can flag more."""
    if not include_inactive:
        stmt = stmt.where(VaUsers.user_status == VaStatuses.active)
    if query:
        stmt = stmt.where(
            sa.or_(
                VaUsers.email.icontains(query, autoescape=True),
                VaUsers.name.icontains(query, autoescape=True),
            )
        )
    return db.session.scalars(
        stmt.order_by(VaUsers.email).limit(_USER_SEARCH_LIMIT + 1)
    ).all()


@data_management.get("/api/users")
@role_required("data_manager", "admin")
def manage_users():
    """User search for data-manager grant assignment.

    Returns ``{"users": [...], "truncated": bool}``; *truncated* says more
    than ``_USER_SEARCH_LIMIT`` people matched, so the caller can ask the
    user to refine the search instead of silently missing someone.
    """
    query = (request.args.get("query") or "").strip()
    include_inactive = request.args.get("include_inactive", "1") == "1"
    if not _is_wide_writer():
        # A unit writer (unit data manager, In-charge) finds the holders of
        # grants it may manage and the staff of mentoring institutes attached
        # to districts it covers; no one else, and no contact details.
        staff, truncated = mentors.dm_visible_mentor_staff(
            current_user.user_id, query, include_inactive, limit=_USER_SEARCH_LIMIT
        )
        found = {u.user_id: (u, codes) for u, codes in staff}
        managed = _search_users(
            sa.select(VaUsers).where(_managed_user_condition()), query, include_inactive
        )
        truncated = truncated or len(managed) > _USER_SEARCH_LIMIT
        for user in managed[:_USER_SEARCH_LIMIT]:
            found.setdefault(user.user_id, (user, []))
        rows = sorted(found.values(), key=lambda row: row[0].email)
        return jsonify({"users": [
            {
                "user_id": str(u.user_id),
                "name": u.name,
                "email": u.email,
                "status": u.user_status.value,
                "institutes": codes,
            }
            for u, codes in rows[:_USER_SEARCH_LIMIT]
        ], "truncated": truncated or len(rows) > _USER_SEARCH_LIMIT})
    users = _search_users(sa.select(VaUsers), query, include_inactive)
    return jsonify({
        "users": [_serialize_user(u) for u in users[:_USER_SEARCH_LIMIT]],
        "truncated": len(users) > _USER_SEARCH_LIMIT,
    })


#: At most this many accounts for one mobile number (numbers are not unique).
_LOOKUP_MOBILE_LIMIT = 5

#: The stored phone, normalised in SQL exactly as ``_canonical_mobile`` does
#: in Python: digits only, then a leading ``0`` or ``91`` in front of ten
#: digits dropped.
_PHONE_CANONICAL = sa.func.regexp_replace(
    sa.func.regexp_replace(VaUsers.phone, "[^0-9]", "", "g"),
    "^(0|91)([0-9]{10})$",
    r"\2",
)


def _canonical_mobile(value):
    """The ten-digit form of a typed mobile number, or None.

    Keeps the digits only (spaces, dashes, brackets and ``+`` go), then drops
    a trunk ``0`` (eleven digits) or the country code ``91`` (twelve digits).
    Anything that is not then exactly ten digits is not a full number, so a
    partial or padded number never matches. ``_PHONE_CANONICAL`` applies the
    same rule to the stored phone.
    """
    digits = re.sub(r"[^0-9]", "", value)
    if (len(digits) == 11 and digits.startswith("0")) or (
        len(digits) == 12 and digits.startswith("91")
    ):
        digits = digits[-10:]
    return digits if len(digits) == 10 else None


def _lookup_posts(user_ids):
    """Active unit grants of *user_ids* as posts: unit and cadre, no role.

    Returns ``{user_id: [post, ...]}``; two roles at one unit with one cadre
    are one post.
    """
    rows = db.session.execute(
        sa.select(
            VaUserAccessGrants.user_id,
            VaUserAccessGrants.org_unit_id,
            VaUserAccessGrants.cadre_id,
            MasOrgUnit.unit_code,
            MasOrgUnit.unit_name,
            MasOrgLevel.level_name,
            MasCadre.cadre_code,
            MasCadre.cadre_name,
        )
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .outerjoin(MasCadre, MasCadre.cadre_id == VaUserAccessGrants.cadre_id)
        .where(
            VaUserAccessGrants.user_id.in_(user_ids),
            VaUserAccessGrants.scope_type == _U,
            VaUserAccessGrants.grant_status == VaStatuses.active,
        )
        .order_by(MasOrgUnit.unit_code, MasCadre.cadre_code)
    ).all()
    posts, seen = {}, set()
    for row in rows:
        key = (row.user_id, row.org_unit_id, row.cadre_id)
        if key in seen:
            continue
        seen.add(key)
        posts.setdefault(row.user_id, []).append({
            "unit_code": row.unit_code,
            "unit_name": row.unit_name,
            "level_name": row.level_name,
            "cadre_code": row.cadre_code,
            "cadre_name": row.cadre_name,
        })
    return posts


@data_management.get("/api/users/lookup")
@role_required("data_manager", "admin")
@limiter.limit("10 per minute")
def manage_lookup_user():
    """Find an existing account by its full email or full mobile number.

    For a writer about to grant someone outside its area (policy:
    dm-user-grant-management.md, digitva-i0zb). ``value`` containing ``@``
    is an email, matched whole and case-insensitively (at most one); anything
    else is a mobile number matched on ``_canonical_mobile`` (at most
    ``_LOOKUP_MOBILE_LIMIT``). Active accounts only; no partial match.

    Returns ``{"users": [{user_id, name, email, status, posts}]}``, empty on
    a miss; 400 for an empty value. No phone, roles or grants, and finding
    someone does not widen ``_dm_may_see_user``. Rate-limited because it
    says whether an address has an account.
    """
    value = (request.args.get("value") or "").strip()
    if not value:
        return _json_error("Enter a full email address or mobile number.", 400)
    stmt = sa.select(VaUsers).where(VaUsers.user_status == VaStatuses.active)
    if "@" in value:
        stmt = stmt.where(sa.func.lower(VaUsers.email) == value.lower()).limit(1)
    else:
        mobile = _canonical_mobile(value)
        if mobile is None:
            return jsonify({"users": []})
        stmt = stmt.where(_PHONE_CANONICAL == mobile).limit(_LOOKUP_MOBILE_LIMIT)
    users = db.session.scalars(stmt.order_by(VaUsers.email)).all()
    posts = _lookup_posts([u.user_id for u in users]) if users else {}
    # Job title joins these rows once the user model has one (digitva-04u4).
    return jsonify({"users": [
        {
            "user_id": str(u.user_id),
            "name": u.name,
            "email": u.email,
            "status": u.user_status.value,
            "posts": posts.get(u.user_id, []),
        }
        for u in users
    ]})


#: create-user payload key -> the grant payload key it stands for.
_INITIAL_SCOPE_KEYS = {
    "initial_project_id": "project_id",
    "initial_project_site_id": "project_site_id",
    "initial_org_unit_id": "org_unit_id",
    "initial_cadre_id": "cadre_id",
}


@data_management.post("/api/users")
@role_required("data_manager", "admin")
def manage_create_user():
    """Create a new user with one initial grant the current user may write."""
    from app.services import user_account_service as accounts

    payload = request.get_json(silent=True) or {}
    initial_project_id = (payload.get("initial_project_id") or "").strip() or None

    try:
        fields = accounts.validate_new_user_payload(payload)
    except accounts.UserAccountError as exc:
        return _json_error(str(exc), 400)

    if not payload.get("initial_role") or not payload.get("initial_scope_type"):
        return _json_error("initial_role and initial_scope_type are required.", 400)
    if not initial_project_id:
        return _json_error("initial_project_id is required.", 400)
    scope_type = payload.get("initial_scope_type")
    if scope_type not in {_P.value, _PS.value, _U.value}:
        return _json_error("Invalid initial_scope_type.", 400)
    # The initial grant is parsed exactly as a grant payload: project scope
    # names the project, the others their own pair or unit.
    grant_payload = {"role": payload.get("initial_role"), "scope_type": scope_type}
    for initial_key, key in _INITIAL_SCOPE_KEYS.items():
        if key == "project_id" and scope_type != _P.value:
            continue
        if payload.get(initial_key):
            grant_payload[key] = payload[initial_key]
    # Permission first, as on the grant create path (digitva-xd1q).
    early = _payload_grant_target(grant_payload)
    if early is not None and not _may_write(early, None):
        return _json_error(_GRANT_REFUSAL, 403)
    try:
        scope = _resolve_scope_from_payload(grant_payload)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    if scope.project_id != initial_project_id:
        return _json_error("The initial grant scope does not belong to initial_project_id.", 400)
    if not _may_write(
        _grant_target(scope.role, scope.scope_type, scope.project_id,
                      scope.project_site_id, scope.org_unit_id),
        None,
    ):
        return _json_error(_GRANT_REFUSAL, 403)

    new_user = accounts.create_invited_user(
        fields, other={"created_by_user_id": str(current_user.user_id)}
    )
    new_grant = VaUserAccessGrants(
        user_id=new_user.user_id,
        role=scope.role,
        scope_type=scope.scope_type,
        project_id=scope.project_id if scope.scope_type == _P else None,
        project_site_id=scope.project_site_id,
        org_unit_id=scope.org_unit_id,
        cadre_id=scope.cadre_id,
        notes="auto-created with user",
        grant_status=VaStatuses.active,
    )
    db.session.add(new_grant)
    db.session.commit()
    authz.invalidate(new_user.user_id)

    accounts.send_invitation(new_user)

    return jsonify({"user": _serialize_user(new_user)}), 201


@data_management.get("/api/users/<uuid:target_user_id>")
@role_required("data_manager", "admin")
def manage_user_detail(target_user_id):
    """Return user details for DM/admin view."""
    user = db.session.get(VaUsers, target_user_id)
    if not user or not _dm_may_see_user(target_user_id):
        return _json_error("User not found.", 404)

    project_id_expression = _grant_project_id_expression()
    site_id_expression = _grant_site_id_expression()
    rows = db.session.execute(
        sa.select(
            VaUserAccessGrants.grant_id,
            VaUserAccessGrants.user_id,
            VaUserAccessGrants.role,
            VaUserAccessGrants.scope_type,
            VaUserAccessGrants.project_site_id,
            VaUserAccessGrants.org_unit_id,
            VaUserAccessGrants.grant_status,
            VaUserAccessGrants.notes,
            VaUsers.email,
            VaUsers.name,
            project_id_expression.label("resolved_project_id"),
            site_id_expression.label("resolved_site_id"),
            *_grant_org_unit_columns(),
        )
        .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .where(
            VaUserAccessGrants.user_id == target_user_id,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            _listed_grants_condition(),
        )
        .order_by(
            project_id_expression.asc(),
            site_id_expression.asc().nullsfirst(),
            VaUserAccessGrants.role.asc(),
        )
    ).all()

    serialized_grants = [_serialize_grant(row) for row in rows]
    project_grants = [g for g in serialized_grants if g["scope_type"] == VaAccessScopeTypes.project.value]
    project_site_grants = [
        g for g in serialized_grants if g["scope_type"] == VaAccessScopeTypes.project_site.value
    ]

    user_json = _serialize_user(user)
    if not _is_wide_writer():
        # Unit writers open managed people without contact details (policy).
        for key in ("phone", "landing_page", "is_admin"):
            user_json.pop(key, None)
    return jsonify(
        {
            "user": user_json,
            "grants": serialized_grants,
            "project_grants": project_grants,
            "project_site_grants": project_site_grants,
        }
    )


@data_management.post("/api/users/<uuid:target_user_id>/resend-verification")
@role_required("data_manager", "admin")
def manage_resend_verification(target_user_id):
    """Resend email verification link for a user."""
    user = db.session.get(VaUsers, target_user_id)
    if not user or not _dm_may_see_user(target_user_id):
        return _json_error("User not found.", 404)
    if user.email_verified:
        return _json_error("User email is already verified.", 400)
    try:
        from app.services.token_service import generate_token
        from app.services.email_service import send_verification_email

        verify_token = generate_token(user.user_id, "email_verify")
        send_verification_email(user, verify_token)
    except Exception as exc:
        log.exception("Resend verification failed for %s: %s", user.email, exc)
        return _json_error("Failed to send verification email.", 500)
    return jsonify({"message": "Verification email sent."})


def _dm_can_edit_user_email(target_user: VaUsers) -> bool:
    """DM can edit email only for users created by them; admins bypass."""
    if current_user.is_admin():
        return True
    other = target_user.other or {}
    created_by = other.get("created_by_user_id")
    return created_by == str(current_user.user_id)


@data_management.put("/api/users/<uuid:target_user_id>")
@role_required("data_manager", "admin")
def manage_update_user(target_user_id):
    """Update user email and/or languages (email is creator-scoped for DMs)."""
    target_user = db.session.get(VaUsers, target_user_id)
    if not target_user or not _dm_may_see_user(target_user_id):
        return _json_error("User not found.", 404)
    payload = request.get_json(silent=True) or {}
    email_raw = payload.get("email")
    email_confirm_raw = payload.get("email_confirm")
    email_requested = email_raw is not None or email_confirm_raw is not None
    languages_requested = "languages" in payload

    if not email_requested and not languages_requested:
        return _json_error("Provide email/email_confirm and/or languages.", 400)

    changed_email = False
    changed_languages = False

    if email_requested:
        if not _dm_can_edit_user_email(target_user):
            return _json_error("You may update email only for users created by you.", 403)
        email = (email_raw or "").strip().lower()
        email_confirm = (email_confirm_raw or "").strip().lower()
        if not email or not email_confirm:
            return _json_error("email and email_confirm are required.", 400)
        if email != email_confirm:
            return _json_error("Email confirmation does not match.", 400)
        if email != target_user.email:
            existing = db.session.scalar(
                sa.select(VaUsers).where(
                    VaUsers.email == email,
                    VaUsers.user_id != target_user.user_id,
                )
            )
            if existing:
                return _json_error("Email already in use.", 400)
            target_user.email = email
            target_user.email_verified = False
            changed_email = True

    if languages_requested:
        from app.models.mas_languages import MasLanguages

        languages = payload.get("languages")
        if not isinstance(languages, list) or not languages:
            return _json_error("At least one language must be selected.", 400)
        valid_codes = set(
            db.session.scalars(
                sa.select(MasLanguages.language_code).where(MasLanguages.is_active == True)
            ).all()
        )
        invalid = [code for code in languages if code not in valid_codes]
        if invalid:
            return _json_error(f"Invalid language codes: {invalid}", 400)
        if list(target_user.vacode_language or []) != list(languages):
            target_user.vacode_language = languages
            changed_languages = True

    if changed_email or changed_languages:
        db.session.commit()

    if changed_email:
        try:
            from app.services.token_service import generate_token
            from app.services.email_service import send_verification_email

            verify_token = generate_token(target_user.user_id, "email_verify")
            send_verification_email(target_user, verify_token)
        except Exception:
            pass

    return jsonify({"user": _serialize_user(target_user)})


@data_management.get("/api/access-grants")
@role_required("data_manager", "admin")
def manage_access_grants():
    """List the active grants the current user may manage (``can_grant``),
    of the roles this interface writes."""
    project_id_expression = _grant_project_id_expression()
    site_id_expression = _grant_site_id_expression()

    stmt = (
        sa.select(
            VaUserAccessGrants.grant_id,
            VaUserAccessGrants.user_id,
            VaUserAccessGrants.role,
            VaUserAccessGrants.scope_type,
            VaUserAccessGrants.project_site_id,
            VaUserAccessGrants.org_unit_id,
            VaUserAccessGrants.grant_status,
            VaUserAccessGrants.notes,
            VaUsers.email,
            VaUsers.name,
            project_id_expression.label("resolved_project_id"),
            site_id_expression.label("resolved_site_id"),
            *_grant_org_unit_columns(),
        )
        .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .where(
            VaUserAccessGrants.grant_status == VaStatuses.active,
            _listed_grants_condition(),
        )
    )

    project_id = request.args.get("project_id")
    if project_id:
        stmt = stmt.where(project_id_expression == project_id)
    role = request.args.get("role")
    if role:
        if role not in {member.value for member in VaAccessRoles}:
            return _json_error("Invalid role.", 400)
        stmt = stmt.where(VaUserAccessGrants.role == VaAccessRoles(role))

    rows = db.session.execute(
        stmt.order_by(project_id_expression, site_id_expression, VaUsers.email)
    ).all()
    return jsonify({"grants": [_serialize_grant(r) for r in rows]})


@data_management.post("/api/access-grants")
@role_required("data_manager", "admin")
@require_dm_scope
def manage_create_access_grant():
    """Create or reactivate a grant the current user may write (``can_grant``)."""
    # Scope already validated by @require_dm_scope; retrieve parsed values from g.
    scope = g.dm_scope
    role, scope_type = scope.role, scope.scope_type
    resolved_project_id, project_site_id = scope.project_id, scope.project_site_id

    payload = request.get_json(silent=True) or {}
    user_id_value = payload.get("user_id")
    if not user_id_value:
        return _json_error("user_id is required.", 400)
    try:
        user_id = uuid.UUID(user_id_value)
    except (ValueError, TypeError):
        return _json_error("Invalid user_id.", 400)

    target_user = db.session.get(VaUsers, user_id)
    if not target_user or target_user.user_status != VaStatuses.active:
        return _json_error("Active user not found.", 404)

    if scope_type == VaAccessScopeTypes.project:
        project = db.session.get(VaProjectMaster, resolved_project_id)
        if not project or project.project_status != VaStatuses.active:
            return _json_error("Active project not found.", 404)

    # Check for existing grant (reactivate if found)
    existing = None
    if scope_type == VaAccessScopeTypes.project:
        existing = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.role == role,
                VaUserAccessGrants.scope_type == scope_type,
                VaUserAccessGrants.project_id == resolved_project_id,
            )
        )
    elif scope_type == VaAccessScopeTypes.org_unit:
        existing = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.role == role,
                VaUserAccessGrants.scope_type == scope_type,
                VaUserAccessGrants.org_unit_id == scope.org_unit_id,
            )
        )
    else:
        existing = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.role == role,
                VaUserAccessGrants.scope_type == scope_type,
                VaUserAccessGrants.project_site_id == project_site_id,
            )
        )

    status_code = 201
    if existing:
        existing.grant_status = VaStatuses.active
        existing.notes = payload.get("notes") or existing.notes
        if scope_type == VaAccessScopeTypes.org_unit:
            # As the admin route: reactivation re-states the cadre.
            existing.cadre_id = scope.cadre_id
        grant = existing
        status_code = 200
    else:
        grant = VaUserAccessGrants(
            user_id=user_id,
            role=role,
            scope_type=scope_type,
            project_id=resolved_project_id if scope_type == VaAccessScopeTypes.project else None,
            project_site_id=project_site_id,
            org_unit_id=scope.org_unit_id,
            cadre_id=scope.cadre_id,
            notes=payload.get("notes"),
            grant_status=VaStatuses.active,
        )
        db.session.add(grant)

    db.session.commit()
    authz.invalidate(user_id)

    from app.logging.va_logger import log_grant_action
    log_grant_action(
        action="grant_reactivated" if (status_code == 200) else "grant_created",
        actor_user_id=current_user.user_id,
        actor_role=_writer_role(),
        target_user_id=user_id,
        grant_id=grant.grant_id,
        role=role.value,
        scope_type=scope_type.value,
        project_id=resolved_project_id,
        project_site_id=project_site_id,
        org_unit_id=scope.org_unit_id,
        cadre_id=scope.cadre_id,
        request_ip=request.remote_addr,
    )

    row = db.session.execute(
        sa.select(
            VaUserAccessGrants.grant_id,
            VaUserAccessGrants.user_id,
            VaUserAccessGrants.role,
            VaUserAccessGrants.scope_type,
            VaUserAccessGrants.project_site_id,
            VaUserAccessGrants.org_unit_id,
            VaUserAccessGrants.grant_status,
            VaUserAccessGrants.notes,
            VaUsers.email,
            VaUsers.name,
            _grant_project_id_expression().label("resolved_project_id"),
            _grant_site_id_expression().label("resolved_site_id"),
            *_grant_org_unit_columns(),
        )
        .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .where(VaUserAccessGrants.grant_id == grant.grant_id)
    ).one()
    return jsonify({"grant": _serialize_grant(row)}), status_code


@data_management.post("/api/access-grants/<uuid:grant_id>/toggle")
@role_required("data_manager", "admin")
@require_dm_scope
def manage_toggle_access_grant(grant_id):
    """Toggle (activate/deactivate) a grant the current user may manage."""
    # Scope (and the own-data_manager-grant refusal) already checked by
    # @require_dm_scope; load grant for the update.
    grant = db.session.get(VaUserAccessGrants, grant_id)
    if not grant:
        return _json_error("Grant not found.", 404)

    new_status = (
        VaStatuses.deactive if grant.grant_status == VaStatuses.active else VaStatuses.active
    )
    grant.grant_status = new_status
    db.session.commit()
    authz.invalidate(grant.user_id)

    from app.logging.va_logger import log_grant_action
    log_grant_action(
        action="grant_toggled_inactive" if new_status == VaStatuses.deactive else "grant_toggled_active",
        actor_user_id=current_user.user_id,
        actor_role=_writer_role(),
        target_user_id=grant.user_id,
        grant_id=grant.grant_id,
        role=grant.role.value,
        scope_type=grant.scope_type.value,
        org_unit_id=grant.org_unit_id,
        request_ip=request.remote_addr,
    )

    return jsonify({"grant_id": str(grant.grant_id), "status": grant.grant_status.value})
