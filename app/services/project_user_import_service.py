"""Validate and apply project user grants from a bounded CSV upload."""

import csv
import io
import re
import secrets

import sqlalchemy as sa

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
from app.services.org_grant_service import ROLES_ALLOWING_ORG_UNIT

HEADERS = ("email", "name", "role", "org_unit_code", "cadre_code", "language_codes", "phone")
MAX_BYTES = 1024 * 1024
MAX_ROWS = 1000
EMAIL_RE = re.compile(r"^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$")


class ProjectUserImportError(ValueError):
    """A CSV or one of its rows cannot be safely imported."""


def template_csv():
    """Return the blank, header-only CSV accepted by this importer."""
    output = io.StringIO()
    csv.writer(output).writerow(HEADERS)
    return output.getvalue()


def parse_csv(stream):
    """Read a UTF-8 CSV, enforcing the upload and row limits before validation."""
    raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ProjectUserImportError("CSV exceeds the 1 MB limit.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProjectUserImportError("CSV must be UTF-8 encoded.") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames != list(HEADERS):
        raise ProjectUserImportError("CSV headers must be: " + ",".join(HEADERS))
    rows = []
    try:
        for row in reader:
            if None in row:
                raise ProjectUserImportError("CSV row has more cells than headers.")
            if not any((value or "").strip() for value in row.values()):
                continue
            rows.append({**{key: (value or "").strip() for key, value in row.items()},
                         "_line_number": reader.line_num})
            if len(rows) > MAX_ROWS:
                raise ProjectUserImportError("CSV exceeds the 1000-row limit.")
    except csv.Error as exc:
        raise ProjectUserImportError("CSV could not be read.") from exc
    if not rows:
        raise ProjectUserImportError("CSV has no user rows.")
    return rows


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
            role = VaAccessRoles(row["role"])
            if role == VaAccessRoles.admin or (role == VaAccessRoles.project_pi and not is_admin):
                raise ProjectUserImportError("role is not grantable")
            unit_code = row["org_unit_code"].upper()
            unit = units.get(unit_code) if unit_code else None
            if unit_code and (unit is None or not unit.is_active):
                raise ProjectUserImportError("unit code is unknown or inactive")
            if not unit and role == VaAccessRoles.site_pi:
                raise ProjectUserImportError("site_pi requires an organization unit")
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
                if role == VaAccessRoles.coder and (permission is None or not permission.can_code_va_form):
                    raise ProjectUserImportError("coder needs a cadre permitted to code at this unit's level")
            key = (email, role, unit_code)
            if key in seen:
                raise ProjectUserImportError("duplicate email, role and scope")
            seen.add(key)
            user = users.get(email)
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
                         "action": "create_user" if not user else ("reactivate" if grant and grant.grant_status != VaStatuses.active else "update_cadre" if grant and unit and grant.cadre_id != (cadre.cadre_id if cadre else None) else "retain" if grant else "grant")})
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
            grant.cadre_id = item["cadre"].cadre_id if item["cadre"] else None
            changed_grants.append((grant, "grant_updated" if item["action"] == "update_cadre" else "grant_reactivated"))
    db.session.flush()
    return list(new_users.values()), changed_grants
