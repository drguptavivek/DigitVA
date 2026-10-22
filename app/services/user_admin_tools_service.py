"""The Users page admin tools (digitva-cgmc): account upload and grant grid.

Admin only; everyone else is refused 403 (the Users list keeps its own
scoping). Policy: docs/policy/account-onboarding-and-passwords.md ("Admin
account upload and invite on first grant") and
docs/policy/access-control-model.md ("Users page admin tools").

Upload: a ``name, email, phone`` table parsed by the project user import's
bounded parser; preview classifies every row, apply re-classifies the same
file and creates only the ``new`` rows. Grid: one chosen project, one row per
account (grantless ones included), and a per-row save that applies a grant
diff at one unit through the admin access-grant panel's validation
(``_resolve_scope_from_payload``) and the importer's ``finalize_apply``.
"""

from __future__ import annotations

import base64
import binascii
import io
import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from types import SimpleNamespace

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (
    MasCadre,
    MasOrgLevel,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import user_account_service as accounts
from app.services import worker_enrolment_service as enrolment
from app.services.project_user_import_service import EMAIL_RE, MAX_BYTES, MAX_ROWS, finalize_apply
from app.services.security_event_service import record_security_event
from app.services.tabular_import_service import TabularImportError, parse_table
from app.services.user_directory_service import (
    _NOT_ENROLLED,
    MAX_LIMIT,
    MAX_OFFSET,
    STATUSES,
    UserDirectoryError,
    _choice,
    _enrolment_by_user,
    _grants_by_user,
    _int,
    _iso,
    _like,
    _options,
    _Scope,
    _text,
    _visible_exists,
)

log = logging.getLogger(__name__)

UPLOAD_HEADERS = ("name", "email", "phone")
#: Base64 of MAX_BYTES, plus padding: refused before decoding.
_MAX_ENCODED = (MAX_BYTES + 2) // 3 * 4 + 4
_MAX_NAME = 128
_MAX_PHONE = 15  # VaUsers.phone
MAX_SITES = 500
MAX_CADRES = 200

#: The grid's six checkboxes, in column order.
GRID_ROLES = (
    VaAccessRoles.death_reporter,
    VaAccessRoles.interviewer,
    VaAccessRoles.interview_supervisor,
    VaAccessRoles.coder,
    VaAccessRoles.reviewer,
    VaAccessRoles.data_manager,
)
_GRID_ROLE_VALUES = frozenset(r.value for r in GRID_ROLES)
_ROLE_VALUES = frozenset(r.value for r in VaAccessRoles)
INVITE_MARKER = "first_grant_invited_at"
#: Roles whose case lists filter on ``vacode_language`` (coder_workflow_service,
#: reviewer_dashboard_service): useless to an account without languages.
_LANGUAGE_ROLES = frozenset({VaAccessRoles.coder, VaAccessRoles.reviewer})


def _require_admin(viewer) -> _Scope:
    scope = _Scope(viewer)  # consults authz for the request
    if not scope.is_admin:
        raise UserDirectoryError("Admin access required.", 403, "forbidden")
    return scope


# ---------------------------------------------------------------------------
# Account upload
# ---------------------------------------------------------------------------

def _upload_rows(body: Mapping) -> list[dict]:
    """The table in ``body`` (``filename``, base64 ``content``), bounded."""
    filename = body.get("filename")
    content = body.get("content")
    if not isinstance(filename, str) or not filename.strip() or len(filename) > 128:
        raise UserDirectoryError("filename is required.")
    if not isinstance(content, str) or not content:
        raise UserDirectoryError("content is required.")
    if len(content) > _MAX_ENCODED:
        raise UserDirectoryError(f"The file exceeds the {MAX_BYTES // (1024 * 1024)} MB limit.", 413,
                                 "payload_too_large")
    try:
        raw = base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError):
        raise UserDirectoryError("content is not valid base64.") from None
    try:
        rows = parse_table(io.BytesIO(raw), filename.strip(), UPLOAD_HEADERS, max_bytes=MAX_BYTES,
                           max_rows=MAX_ROWS, require_all=True)
    except TabularImportError as exc:
        raise UserDirectoryError(str(exc)) from None
    if not rows:
        raise UserDirectoryError("The file has no account rows.")
    return rows


def _classify(rows: list[dict]) -> list[dict]:
    """Each row as ``new``, ``exists`` or ``invalid`` (with ``reason``).
    Two queries: accounts by email, and holders of the file's mobiles."""
    def cell(row, name):
        value = row.get(name)
        return "" if value is None else str(value).strip()

    parsed = []
    for row in rows:
        email = cell(row, "email").lower()
        phone = cell(row, "phone")
        parsed.append({"row": row["_line_number"], "name": cell(row, "name"), "email": email,
                       "phone": phone, "mobile": accounts.canonical_mobile(phone)})
    emails = {p["email"] for p in parsed if p["email"]}
    by_email = dict(db.session.execute(
        sa.select(sa.func.lower(VaUsers.email), VaUsers.user_id).where(sa.func.lower(VaUsers.email).in_(emails))
    ).all()) if emails else {}
    mobiles = {p["mobile"] for p in parsed if p["mobile"]}
    holders: dict[str, set] = {}
    if mobiles:
        for user_id, login, canonical in db.session.execute(
            sa.select(VaUsers.user_id, VaUsers.mobile_login, accounts.PHONE_CANONICAL).where(sa.or_(
                VaUsers.mobile_login.in_(mobiles), accounts.PHONE_CANONICAL.in_(mobiles),
            ))
        ):
            for number in {login, canonical} & mobiles:
                holders.setdefault(number, set()).add(user_id)

    seen_emails, seen_mobiles, out = set(), set(), []
    for p in parsed:
        reason = None
        if not p["name"] or len(p["name"]) > _MAX_NAME:
            reason = "name is required (at most 128 characters)"
        elif not p["email"] or len(p["email"]) > 128 or not EMAIL_RE.fullmatch(p["email"]):
            reason = "invalid email"
        elif p["phone"] and (p["mobile"] is None or len(p["phone"]) > _MAX_PHONE):
            reason = "phone must be a 10-digit mobile number"
        elif p["email"] in seen_emails:
            reason = "email repeats an earlier row"
        elif p["mobile"] and p["mobile"] in seen_mobiles:
            reason = "phone repeats an earlier row"
        seen_emails.add(p["email"])
        if p["mobile"]:
            seen_mobiles.add(p["mobile"])
        existing = by_email.get(p["email"])
        others = holders.get(p["mobile"], set()) - {existing} if p["mobile"] else set()
        if reason:
            status = "invalid"
        elif existing:
            status = "exists"
        elif others:
            status, reason = "invalid", "phone is already used by another account"
        else:
            status = "new"
        out.append({
            "row": p["row"], "name": p["name"], "email": p["email"],
            # Never a whole number back (mobile-sign-in.md section 4).
            "phone": accounts.mask_mobile(p["mobile"]),
            "status": status, "reason": reason,
            "phone_clash": bool(existing and others),
            "_phone": p["phone"], "_mobile": p["mobile"],
        })
    return out


def _public(rows: list[dict]) -> dict:
    counts = {"new": 0, "exists": 0, "invalid": 0}
    for r in rows:
        counts[r["status"]] += 1
    return {"rows": [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows], "counts": counts}


def preview_upload(viewer, body: Mapping) -> dict:
    """Classify an uploaded ``name, email, phone`` table; writes nothing."""
    _require_admin(viewer)
    return _public(_classify(_upload_rows(body)))


def apply_upload(viewer, body: Mapping) -> dict:
    """Re-classify the same file and create its ``new`` rows: active, a
    random unknown password, no languages, ``created_via`` import. Sends no
    email. One ``account_upload_applied`` audit event. Commits. Raises
    UserDirectoryError (409 when another writer took an email or number)."""
    _require_admin(viewer)
    rows = _classify(_upload_rows(body))
    created = 0
    try:
        for r in rows:
            if r["status"] != "new":
                continue
            accounts.create_invited_user(
                {"email": r["email"], "name": r["name"], "phone": r["_phone"], "mobile": r["_mobile"],
                 "languages": []},
                via="import", actor_user_id=viewer.user_id,
            )
            created += 1
    except accounts.UserAccountError as exc:
        db.session.rollback()
        raise UserDirectoryError(f"{exc} Preview the file again.", 409, "conflict") from None
    record_security_event(user_id=None, actor_user_id=viewer.user_id, event_type="account_upload_applied",
                          detail={"created": created, "rows": len(rows)})
    db.session.commit()
    log.info("users account-upload | by=%s | created=%s | rows=%s", viewer.user_id, created, len(rows))
    return {**_public(rows), "created": created}


# ---------------------------------------------------------------------------
# Grant grid: list
# ---------------------------------------------------------------------------

def _active_project(project_id) -> VaProjectMaster:
    if not isinstance(project_id, str) or not project_id.strip() or len(project_id) > 64:
        raise UserDirectoryError("project is required.")
    project = db.session.get(VaProjectMaster, project_id.strip().upper())
    if project is None or project.project_status != VaStatuses.active:
        raise UserDirectoryError("Active project not found.", 404, "not_found")
    return project


def _has_tree(project_id: str) -> bool:
    return bool(db.session.scalar(sa.select(sa.exists().where(
        MasOrgLevel.project_id == project_id, MasOrgLevel.is_active.is_(True),
    ))))


def _date(args, name):
    raw = _text(args, name)
    if not raw:
        return ""
    try:
        date.fromisoformat(raw)
    except ValueError:
        raise UserDirectoryError(f"{name} must be a date (YYYY-MM-DD).") from None
    return raw


def unit_key(grant: dict) -> str:
    """The grid's unit key of a directory grant: ``project``,
    ``site:<site_id>`` or ``unit:<org_unit_id>``."""
    if grant["scope"] == VaAccessScopeTypes.org_unit.value:
        return f"unit:{grant['org_unit_id']}"
    if grant["scope"] == VaAccessScopeTypes.project_site.value:
        return f"site:{grant['site_id']}"
    return "project"


def _grid_rows(scope: _Scope, users, project_id: str, now) -> list[dict]:
    """Rows for *users*: two batched queries (grants, device sessions)."""
    ids = [u.user_id for u in users]
    grants = _grants_by_user(scope, ids)
    enrolled = _enrolment_by_user(ids, now)
    rows = []
    for u in users:
        mine = [{**g, "unit": unit_key(g)} for g in grants.get(u.user_id, []) if g["project_id"] == project_id]
        rows.append({
            "user_id": str(u.user_id),
            "name": u.name,
            "email": u.email,
            "phone": u.phone or u.mobile_login,
            "active": u.user_status == VaStatuses.active,
            # Stored naive UTC.
            "created_at": _iso(u.user_created_at.replace(tzinfo=UTC)) if u.user_created_at else None,
            "grants": mine,
            "enrolment": enrolled.get(u.user_id, _NOT_ENROLLED),
        })
    return rows


def _grid_options(scope: _Scope, project: VaProjectMaster) -> dict:
    tree = _has_tree(project.project_id)
    units = []
    if tree:
        units = [{"key": f"unit:{u['org_unit_id']}", "label": f"{u['unit_name']} ({u['level_name']})",
                  "depth": u["depth"]} for u in _options(scope, project.project_id)["units"]]
    else:
        units = [
            {"key": f"site:{r.site_id}", "label": r.site_name or r.site_id, "depth": 0}
            for r in db.session.execute(
                sa.select(VaProjectSites.site_id, VaSiteMaster.site_name)
                .outerjoin(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
                .where(VaProjectSites.project_id == project.project_id,
                       VaProjectSites.project_site_status == VaStatuses.active)
                .order_by(VaProjectSites.site_id).limit(MAX_SITES)
            ).all()
        ]
    cadres = [
        {"cadre_id": str(r.cadre_id), "cadre_code": r.cadre_code, "cadre_name": r.cadre_name}
        for r in db.session.execute(
            sa.select(MasCadre.cadre_id, MasCadre.cadre_code, MasCadre.cadre_name)
            .where(MasCadre.project_id == project.project_id, MasCadre.is_active.is_(True))
            .order_by(MasCadre.cadre_code).limit(MAX_CADRES)
        ).all()
    ] if tree else []
    return {"mode": "organization" if tree else "sites", "units": units, "cadres": cadres}


def list_grid(viewer, args: Mapping[str, str]) -> dict:
    """One page of the grant grid. Query: ``project`` (required), ``from``
    and ``to`` (created date, the admin's local days), ``q`` (name or email,
    contains), ``role`` (holds that role in the project), ``status``,
    ``limit`` (1..100, default 50), ``offset``. Newest created first."""
    from app.services.data_management_service import _local_date_conditions

    scope = _require_admin(viewer)
    project = _active_project(args.get("project"))
    q = _text(args, "q")
    role = _choice(args, "role", _ROLE_VALUES)
    status = _choice(args, "status", STATUSES, "all")
    date_from, date_to = _date(args, "from"), _date(args, "to")
    limit = _int(args, "limit", 50, 1, MAX_LIMIT)
    offset = _int(args, "offset", 0, 0, MAX_OFFSET)

    where = _local_date_conditions(viewer, date_from, date_to, column=VaUsers.user_created_at)
    if role:
        where.append(_visible_exists(scope, VaUsers.user_id, project_id=project.project_id, role=role))
    if status == "active":
        where.append(VaUsers.user_status == VaStatuses.active)
    elif status == "inactive":
        where.append(VaUsers.user_status != VaStatuses.active)
    if q:
        pattern = _like(q)
        where.append(sa.or_(VaUsers.name.ilike(pattern, escape="\\"), VaUsers.email.ilike(pattern, escape="\\")))

    total = db.session.scalar(sa.select(sa.func.count()).select_from(VaUsers).where(*where))
    users = db.session.execute(
        sa.select(VaUsers.user_id, VaUsers.name, VaUsers.email, VaUsers.phone, VaUsers.mobile_login,
                  VaUsers.user_status, VaUsers.user_created_at)
        .where(*where)
        .order_by(VaUsers.user_created_at.desc(), VaUsers.user_id)
        .limit(limit).offset(offset)
    ).all()
    body = {
        "users": _grid_rows(scope, users, project.project_id, datetime.now(UTC)),
        "total": int(total or 0), "limit": limit, "offset": offset,
    }
    if offset == 0:
        body["options"] = _grid_options(scope, project)
    return body


# ---------------------------------------------------------------------------
# Grant grid: save one row
# ---------------------------------------------------------------------------

def _target(project: VaProjectMaster, key) -> dict:
    """The access-grant panel's scope payload for a grid unit key."""
    if key == "project":
        return {"scope_type": VaAccessScopeTypes.project.value, "project_id": project.project_id}
    if not isinstance(key, str) or len(key) > 80 or ":" not in key:
        raise UserDirectoryError("unit is not valid.")
    kind, _, value = key.partition(":")
    if kind == "site":
        pair = db.session.scalar(sa.select(VaProjectSites.project_site_id).where(
            VaProjectSites.project_id == project.project_id, VaProjectSites.site_id == value,
            VaProjectSites.project_site_status == VaStatuses.active,
        ))
        if pair is None:
            raise UserDirectoryError("Site not found in this project.")
        return {"scope_type": VaAccessScopeTypes.project_site.value, "project_site_id": str(pair)}
    if kind == "unit":
        from app.models import MasOrgUnit

        try:
            unit = db.session.get(MasOrgUnit, uuid.UUID(value))
        except ValueError:
            unit = None
        if unit is None or unit.project_id != project.project_id:
            raise UserDirectoryError("Unit not found in this project.")
        return {"scope_type": VaAccessScopeTypes.org_unit.value, "org_unit_id": str(unit.org_unit_id)}
    raise UserDirectoryError("unit is not valid.")


def _at_target(target: dict):
    g = VaUserAccessGrants
    scope = VaAccessScopeTypes(target["scope_type"])
    if scope == VaAccessScopeTypes.project:
        return [g.scope_type == scope, g.project_id == target["project_id"]]
    if scope == VaAccessScopeTypes.project_site:
        return [g.scope_type == scope, g.project_site_id == uuid.UUID(target["project_site_id"])]
    return [g.scope_type == scope, g.org_unit_id == uuid.UUID(target["org_unit_id"])]


def _audit(grant: VaUserAccessGrants, action: str):
    return (dict(user_id=grant.user_id, grant_id=grant.grant_id, role=grant.role.value,
                 scope_type=grant.scope_type.value, org_unit_id=grant.org_unit_id,
                 cadre_id=grant.cadre_id), action)


def _apply_profile(viewer, user: VaUsers, body: Mapping) -> None:
    # Another admin's account is managed on the admin Users panel, not here: the
    # grid must not let one admin deactivate, rename or re-number the others.
    before = (user.name, user.phone, user.user_status)
    if "name" in body:
        name = body.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > _MAX_NAME:
            raise UserDirectoryError("name is required (at most 128 characters).")
        if name.strip()[0] in "=+-@":
            raise UserDirectoryError("name must not start with =, +, - or @.")
        user.name = name.strip()
    if "phone" in body:
        phone = body.get("phone")
        if phone is not None and not isinstance(phone, str):
            raise UserDirectoryError("phone must be text.")
        if phone and phone.strip() and accounts.canonical_mobile(phone) is None:
            raise UserDirectoryError("phone must be a 10-digit mobile number.")
        try:
            accounts.assign_phone(user, phone)
        except accounts.UserAccountError as exc:
            raise UserDirectoryError(str(exc)) from None
    if "active" in body:
        active = body.get("active")
        if not isinstance(active, bool):
            raise UserDirectoryError("active must be true or false.")
        if not active and user.user_id == viewer.user_id:
            raise UserDirectoryError("You cannot deactivate yourself.")
        user.user_status = VaStatuses.active if active else VaStatuses.deactive
    if user.user_id != viewer.user_id and (user.name, user.phone, user.user_status) != before and user.is_admin():
        raise UserDirectoryError("Edit another admin's account on the admin Users panel.", 403, "admin_account")


def save_grid_row(viewer, user_id: str, body: Mapping, *, request_ip=None) -> dict:
    """Apply one grid row's save: the six grid roles at ``unit`` of
    ``project_id`` set to exactly ``roles`` (added: created or reactivated
    through the admin panel's validation; removed: soft revoked), plus
    optional ``name``, ``phone``, ``active`` and ``cadre_id`` (unit grants
    needing a cadre; default the cadre of the account's grant there). All
    or nothing. On the account's first active grant, sends the invitation
    and, for a data-collector role, the enrolment email, once. Returns the
    refreshed row and mail ``warnings``. Raises UserDirectoryError."""
    from app.routes.admin import _resolve_scope_from_payload

    scope = _require_admin(viewer)
    try:
        user = db.session.get(VaUsers, uuid.UUID(str(user_id)))
    except ValueError:
        user = None
    if user is None:
        raise UserDirectoryError("User not found.", 404, "not_found")
    project = _active_project(body.get("project_id"))
    target = _target(project, body.get("unit"))
    roles = body.get("roles")
    if not isinstance(roles, list) or any(not isinstance(r, str) or r not in _GRID_ROLE_VALUES for r in roles):
        raise UserDirectoryError("roles must be a list of: " + ", ".join(r.value for r in GRID_ROLES) + ".")
    wanted = {VaAccessRoles(r) for r in roles}
    cadre_id = body.get("cadre_id")
    if cadre_id is not None and not isinstance(cadre_id, str):
        raise UserDirectoryError("cadre_id is not valid.")

    had_grant = bool(db.session.scalar(sa.select(sa.exists().where(
        VaUserAccessGrants.user_id == user.user_id, VaUserAccessGrants.grant_status == VaStatuses.active,
    ))))
    existing = {g.role: g for g in db.session.scalars(sa.select(VaUserAccessGrants).where(
        VaUserAccessGrants.user_id == user.user_id, VaUserAccessGrants.role.in_(GRID_ROLES),
        *_at_target(target),
    ))}
    if target["scope_type"] == VaAccessScopeTypes.org_unit.value and not cadre_id:
        held = next((g.cadre_id for g in existing.values() if g.cadre_id), None)
        cadre_id = str(held) if held else None

    changed, added, errors = [], [], []
    for role in GRID_ROLES:
        grant = existing.get(role)
        live = grant is not None and grant.grant_status == VaStatuses.active
        if role in wanted and not live:
            if role in _LANGUAGE_ROLES and not user.vacode_language:
                errors.append(f"{role.value}: set the account's coding languages on the admin Users panel first.")
                continue
            try:
                resolved = _resolve_scope_from_payload(
                    {"role": role.value, **target, "cadre_id": cadre_id}, user_id=user.user_id,
                )
            except ValueError as exc:
                errors.append(f"{role.value}: {exc}")
                continue
            if grant is None:
                grant = VaUserAccessGrants(
                    user_id=user.user_id, role=role, scope_type=resolved.scope_type,
                    project_id=resolved.project_id if resolved.scope_type == VaAccessScopeTypes.project else None,
                    project_site_id=resolved.project_site_id, org_unit_id=resolved.org_unit_id,
                    cadre_id=resolved.cadre_id, grant_status=VaStatuses.active,
                    created_by_user_id=viewer.user_id,
                )
                db.session.add(grant)
                action = "grant_created"
            else:
                grant.grant_status = VaStatuses.active
                if resolved.scope_type == VaAccessScopeTypes.org_unit:
                    grant.cadre_id = resolved.cadre_id
                action = "grant_reactivated"
            changed.append((grant, action))
            added.append(role)
        elif role not in wanted and live:
            grant.grant_status = VaStatuses.deactive
            changed.append((grant, "grant_toggled_inactive"))
    if errors:
        db.session.rollback()
        raise UserDirectoryError("; ".join(errors), 400, "grant_refused")
    try:
        _apply_profile(viewer, user, body)
        db.session.flush()
    except UserDirectoryError:
        db.session.rollback()
        raise
    except IntegrityError as exc:
        db.session.rollback()
        translated = accounts.translate_integrity_error(exc)
        if translated is None:
            raise
        raise UserDirectoryError(str(translated), 409, "conflict") from None
    audit = [_audit(grant, action) for grant, action in changed]
    first_invite = (
        added and not had_grant and user.user_status == VaStatuses.active
        and user.last_signed_in_at is None and not accounts.has_usable_password(user)
        and not (user.other or {}).get(INVITE_MARKER)
    )
    invitations = [SimpleNamespace(user_id=user.user_id, email=user.email, name=user.name)] \
        if first_invite and user.email else []
    db.session.commit()

    warnings, queued, enrolment_status = [], 0, None
    if audit or invitations:
        queued, warnings = finalize_apply(
            project.project_id, actor_user_id=viewer.user_id, actor_role="admin",
            changed_grants=audit, invitations=invitations, request_ip=request_ip,
        )
    if first_invite and any(r.value in enrolment.DATA_COLLECTOR_ROLES for r in added):
        enrolment_status = enrolment.send_enrolment_email(project.project_id, user, actor=viewer)
        if enrolment_status == "failed":
            warnings.append(enrolment.SEND_FAILED_WARNING)
    if first_invite and (queued or enrolment_status == "sent"):
        # Reassigned, not mutated: JSONB change tracking sees a new dict.
        user.other = {**(user.other or {}), INVITE_MARKER: datetime.now(UTC).isoformat()}
        db.session.commit()
    log.info("users grid-save | by=%s | user=%s | project=%s | changes=%s | invited=%s",
             viewer.user_id, user.user_id, project.project_id, len(audit), bool(queued))

    row = db.session.execute(
        sa.select(VaUsers.user_id, VaUsers.name, VaUsers.email, VaUsers.phone, VaUsers.mobile_login,
                  VaUsers.user_status, VaUsers.user_created_at).where(VaUsers.user_id == user.user_id)
    ).one()
    return {
        "user": _grid_rows(scope, [row], project.project_id, datetime.now(UTC))[0],
        "changes": len(audit),
        "invited": bool(queued),
        "enrolment_email": enrolment_status,
        "warnings": warnings,
    }
