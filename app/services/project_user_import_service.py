"""Validate and apply project user grants from a bounded table upload."""

import csv
import io
import re
import secrets
from types import SimpleNamespace

import sqlalchemy as sa
from openpyxl import Workbook

from app import db
from app.models import (
    MapOrgLevelCadre,
    MasCadre,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.mas_languages import MasLanguages
from app.services.mentor_institute_service import check_mentor_grant, member_user_ids
from app.services.org_grant_service import CADRE_FLAG_BY_ROLE, ROLES_ALLOWING_ORG_UNIT
from app.services.tabular_import_service import TabularImportError, parse_table

HEADERS = ("email", "name", "role", "org_unit_code", "cadre_code", "language_codes", "phone")
MAX_BYTES = 1024 * 1024
MAX_ROWS = 1000
EMAIL_RE = re.compile(r"^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$")


class ProjectUserImportError(ValueError):
    """A table or one of its rows cannot be safely imported."""


def template_csv():
    """Return the blank, header-only CSV accepted by this importer."""
    output = io.StringIO()
    csv.writer(output).writerow(HEADERS)
    return output.getvalue()


def template_xlsx():
    """Return the blank first-sheet workbook accepted by this importer."""
    workbook = Workbook()
    workbook.active.title = "project_users"
    workbook.active.append(HEADERS)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def parse_upload(stream, filename):
    """Read a bounded CSV or first-sheet XLSX into user rows."""
    try:
        rows = parse_table(stream, filename, HEADERS, max_bytes=MAX_BYTES,
                           max_rows=MAX_ROWS, require_all=True)
    except TabularImportError as exc:
        raise ProjectUserImportError(str(exc)) from exc
    if not rows:
        raise ProjectUserImportError("The file has no user rows.")
    for row in rows:
        for header in HEADERS:
            row[header] = str(row[header]) if row[header] is not None else ""
    return rows


def parse_csv(stream):
    """Retain the existing CSV API for callers outside the upload route."""
    return parse_upload(stream, "users.csv")


def prepare(project_id, rows, *, is_admin):
    """Resolve all users, roles and scopes without writing; return an apply plan.

    Raises ProjectUserImportError with row numbers. Existing user profiles are
    ignored; profile fields are used only when an admin creates a new account.
    """
    project = db.session.get(VaProjectMaster, project_id)
    if not project or project.project_status != VaStatuses.active:
        raise ProjectUserImportError("Active project not found.")
    if project.project_structure_mode != "organization":
        raise ProjectUserImportError("This project is not in organization mode.")

    emails = {(row["email"] or "").lower() for row in rows}
    users = {user.email.lower(): user for user in db.session.scalars(
        sa.select(VaUsers).where(sa.func.lower(VaUsers.email).in_(emails))
    )}
    requested_units = {row["org_unit_code"].upper() for row in rows if row["org_unit_code"]}
    units = {unit.unit_code.upper(): unit for unit in db.session.scalars(
        sa.select(MasOrgUnit).where(MasOrgUnit.project_id == project_id,
                                    MasOrgUnit.unit_code.in_(requested_units))
    )}
    requested_cadres = {row["cadre_code"].upper() for row in rows if row["cadre_code"]}
    cadres = {cadre.cadre_code.upper(): cadre for cadre in db.session.scalars(
        sa.select(MasCadre).where(MasCadre.project_id == project_id,
                                  MasCadre.cadre_code.in_(requested_cadres))
    )}
    permissions = {(permission.org_level_id, permission.cadre_id): permission
                   for permission in db.session.scalars(
                       sa.select(MapOrgLevelCadre).where(
                           MapOrgLevelCadre.org_level_id.in_(
                               [unit.org_level_id for unit in units.values()]
                           ),
                           MapOrgLevelCadre.cadre_id.in_(
                               [cadre.cadre_id for cadre in cadres.values()]
                           ),
                       )
                   )}
    active_languages = set(db.session.scalars(
        sa.select(MasLanguages.language_code).where(MasLanguages.is_active.is_(True))
    ))
    existing_grants = {(grant.user_id, grant.role, grant.scope_type,
                        grant.org_unit_id if grant.scope_type == VaAccessScopeTypes.org_unit else grant.project_id): grant
                       for grant in db.session.scalars(sa.select(VaUserAccessGrants).where(
                           VaUserAccessGrants.user_id.in_([user.user_id for user in users.values()]),
                           sa.or_(VaUserAccessGrants.project_id == project_id,
                                  VaUserAccessGrants.org_unit_id.in_([unit.org_unit_id for unit in units.values()])),
                       ))}
    mentor_members = member_user_ids(user.user_id for user in users.values())
    plan = []
    seen = set()
    new_profiles = {}
    errors = []
    for row in rows:
        number = row["_line_number"]
        try:
            email = row["email"].lower()
            if len(email) > 128 or not EMAIL_RE.fullmatch(email):
                raise ProjectUserImportError("invalid email")
            allowed_roles = [role for role in VaAccessRoles
                             if role != VaAccessRoles.admin and
                             (is_admin or role != VaAccessRoles.project_pi)]
            if row["role"] not in {role.value for role in allowed_roles}:
                raise ProjectUserImportError("role must be one of: " + ", ".join(role.value for role in allowed_roles))
            role = VaAccessRoles(row["role"])
            if role == VaAccessRoles.admin or (role == VaAccessRoles.project_pi and not is_admin):
                raise ProjectUserImportError("role is not grantable")
            unit_code = row["org_unit_code"].upper()
            unit = units.get(unit_code) if unit_code else None
            if unit_code and (unit is None or not unit.is_active):
                raise ProjectUserImportError("unit code is unknown or inactive")
            if role == VaAccessRoles.site_pi:
                raise ProjectUserImportError("site_pi cannot be held at a unit; the project PI covers every district")
            if not unit and role == VaAccessRoles.interview_supervisor:
                raise ProjectUserImportError(f"{role.value} requires an organization unit")
            cadre_code = row["cadre_code"].upper()
            if cadre_code and not unit:
                raise ProjectUserImportError("cadre requires an organization unit")
            cadre = cadres.get(cadre_code) if cadre_code else None
            if cadre_code and cadre is None:
                raise ProjectUserImportError("cadre code is unknown")
            if unit:
                if role not in ROLES_ALLOWING_ORG_UNIT:
                    raise ProjectUserImportError("role cannot use organization unit scope")
                if cadre and not cadre.is_active:
                    raise ProjectUserImportError("cadre is inactive")
                permission = permissions.get((unit.org_level_id, cadre.cadre_id)) if cadre else None
                if cadre and (permission is None or not permission.is_active):
                    raise ProjectUserImportError("cadre is not active at this unit's level")
                if role in CADRE_FLAG_BY_ROLE:
                    flag, permits = CADRE_FLAG_BY_ROLE[role]
                    if permission is None or not getattr(permission, flag):
                        raise ProjectUserImportError(
                            f"{role.value} needs a cadre permitted to {permits} at this unit's level"
                        )
            key = (email, role, unit_code)
            if key in seen:
                raise ProjectUserImportError("duplicate email, role and scope")
            seen.add(key)
            user = users.get(email)
            if user and user.user_id in mentor_members:
                check_mentor_grant(user.user_id, role, unit)
            if not is_admin and (not user or user.user_status != VaStatuses.active):
                raise ProjectUserImportError("account is unavailable for this project import")
            if user and user.user_status != VaStatuses.active:
                raise ProjectUserImportError("existing user is inactive")
            languages = [code.strip() for code in row["language_codes"].split(";") if code.strip()]
            if not user:
                if not is_admin:
                    raise ProjectUserImportError("project PI cannot create accounts")
                if not row["name"] or len(row["name"]) > 128:
                    raise ProjectUserImportError("new user needs a name of at most 128 characters")
                if not languages or any(code not in active_languages for code in languages):
                    raise ProjectUserImportError("new user needs active language codes")
                if len(row["phone"]) > 15:
                    raise ProjectUserImportError("phone is too long")
                profile = (row["name"], tuple(languages), row["phone"])
                if email in new_profiles and new_profiles[email] != profile:
                    raise ProjectUserImportError("new user profile differs from an earlier row")
                new_profiles[email] = profile
            scope = VaAccessScopeTypes.org_unit if unit else VaAccessScopeTypes.project
            grant_key = (user.user_id, role, scope, unit.org_unit_id if unit else project_id) if user else None
            grant = existing_grants.get(grant_key)
            plan.append({"row": number, "email": email, "name": row["name"], "phone": row["phone"],
                         "languages": languages, "role": role, "unit": unit, "cadre": cadre,
                         "user": user, "grant": grant,
                         "action": "create_user" if not user else ("reactivate" if grant and grant.grant_status != VaStatuses.active else "update_cadre" if grant and unit and cadre and grant.cadre_id != cadre.cadre_id else "retain" if grant else "grant")})
        except (ValueError, KeyError) as exc:
            errors.append(f"Row {number}: {exc}")
    if errors:
        raise ProjectUserImportError("; ".join(errors))
    return plan


def apply(project_id, plan, *, actor_user_id):
    """Write a validated plan in the caller's transaction; return new users and grants."""
    new_users = {}
    changed_grants = []
    for item in plan:
        user = item["user"] or new_users.get(item["email"])
        if user is None:
            user = VaUsers(email=item["email"], name=item["name"], phone=item["phone"] or None,
                           user_status=VaStatuses.active, vacode_language=item["languages"],
                           permission={}, landing_page="coder", pw_reset_t_and_c=False,
                           email_verified=False, other={"created_by_user_id": str(actor_user_id)})
            user.set_password(secrets.token_urlsafe(32))
            db.session.add(user)
            db.session.flush()
            new_users[item["email"]] = user
        grant = item["grant"]
        if grant is None:
            unit = item["unit"]
            grant = VaUserAccessGrants(
                user_id=user.user_id, role=item["role"],
                scope_type=VaAccessScopeTypes.org_unit if unit else VaAccessScopeTypes.project,
                project_id=None if unit else project_id,
                org_unit_id=unit.org_unit_id if unit else None,
                cadre_id=item["cadre"].cadre_id if item["cadre"] else None,
                grant_status=VaStatuses.active, created_by_user_id=actor_user_id,
            )
            db.session.add(grant)
            changed_grants.append((grant, "grant_created"))
        elif grant.grant_status != VaStatuses.active or item["action"] == "update_cadre":
            grant.grant_status = VaStatuses.active
            if item["cadre"] is not None or item["action"] == "reactivate":
                grant.cadre_id = item["cadre"].cadre_id if item["cadre"] else None
            changed_grants.append((grant, "grant_updated" if item["action"] == "update_cadre" else "grant_reactivated"))
    db.session.flush()
    # Snapshot values before commit expires ORM state; invitation helpers need
    # only name, email and ID, and audit logging needs grant scalar fields.
    invitations = [SimpleNamespace(user_id=user.user_id, email=user.email, name=user.name)
                   for user in new_users.values()]
    audit = [(dict(user_id=grant.user_id, grant_id=grant.grant_id, role=grant.role.value,
                   scope_type=grant.scope_type.value, org_unit_id=grant.org_unit_id,
                   cadre_id=grant.cadre_id), action) for grant, action in changed_grants]
    return invitations, audit
