"""The web app's Users page (digitva-75wn): accounts in the viewer's scope,
their in-scope grants, mobile enrolment, activity, and issuing an app
enrolment code.

Policy: docs/policy/access-control-model.md ("Users page"), organization-model.md
("Users page: contacts shown"), mobile-sign-in.md section 6. Who is listed is
``authz.user_list_filter`` (admin: every account). A page is three queries:
the users (with a count), their in-scope grants, their device sessions
grouped per user. Responses name only whitelisted fields: never a password
hash, TOTP or recovery material, token, code hash, year of birth or sex.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from app import db
from app.models import (
    AuthDevice,
    AuthDeviceEnrolmentCode,
    AuthDeviceSession,
    AuthSecurityEvent,
    AuthWebauthnCredential,
    MapTrainingParticipant,
    MasTrainingSession,
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import device_auth_service as devices
from app.services import worker_enrolment_service as enrolment
from app.services.authz import (
    NATIVE_DEVICE_ROLES,
    resolve_grants,
    subtree_select,
    user_list_filter,
    writer_grants,
)
from app.services.org_grant_service import active_project_condition
from app.services.totp_service import provisioning_qr_png
from app.services.user_home_service import get_user_activity_summary

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
MAX_OFFSET = 100_000
MAX_PROJECTS = 200
MAX_UNITS = 500
_MAX_TEXT = 64
STATUSES = ("all", "active", "inactive")
ENROLMENT_STATES = ("enrolled", "revoked", "none")
YES_NO = ("yes", "no")
CREATED_QUICK = ("today", "yesterday")
DELIVERIES = ("show", "email")
_ROLE_VALUES = frozenset(r.value for r in VaAccessRoles)

_G = VaUserAccessGrants
_PS = VaAccessScopeTypes.project_site
_U = VaAccessScopeTypes.org_unit


class UserDirectoryError(Exception):
    """A refused request: *status* is the HTTP status, *code* the machine code."""

    def __init__(self, message: str, status: int = 400, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


def _not_found() -> UserDirectoryError:
    # Alike whether the account exists or is outside the viewer's scope.
    return UserDirectoryError("User not found.", 404, "not_found")


class _Scope:
    """The viewer's Users-page reach, resolved once per request."""

    def __init__(self, viewer):
        resolved = resolve_grants(viewer)
        self.is_admin = resolved.is_admin
        self.clause = user_list_filter(viewer, _grants=resolved)  # marks the request consulted
        self.writers = writer_grants(resolved)
        self.project_ids = frozenset(g.project_id for g in self.writers)


# ---------------------------------------------------------------------------
# Grants, joined to the project they resolve to
# ---------------------------------------------------------------------------

def _grant_rows():
    """FROM va_user_access_grants with its pair and unit, and the project
    every scope resolves to. Fresh aliases per call: each EXISTS gets its own."""
    pair = sa.orm.aliased(VaProjectSites, name="ud_pair")
    unit = sa.orm.aliased(MasOrgUnit, name="ud_unit")
    project = sa.func.coalesce(_G.project_id, pair.project_id, unit.project_id)
    joined = (
        sa.select(_G)
        .outerjoin(pair, pair.project_site_id == _G.project_site_id)
        .outerjoin(unit, unit.org_unit_id == _G.org_unit_id)
    )
    return joined, pair, unit, project


def _live(scope: _Scope, project) -> list:
    return [_G.grant_status == VaStatuses.active, scope.clause, active_project_condition(project)]


def _visible_exists(scope: _Scope, user_id_expr, *, project_id=None, unit_id=None, role=None,
                    roles=None):
    """EXISTS an active, in-scope grant of *user_id_expr* on an active project,
    narrowed by the optional filters (unit: that unit's subtree)."""
    joined, _pair, _unit, project = _grant_rows()
    where = [_G.user_id == user_id_expr, *_live(scope, project)]
    if project_id:
        where.append(project == project_id)
    if unit_id:
        where += [_G.scope_type == _U, _G.org_unit_id.in_(subtree_select([unit_id]))]
    if role:
        where.append(_G.role == VaAccessRoles(role))
    if roles:
        where.append(_G.role.in_(sorted(roles, key=lambda r: r.value)))
    return sa.exists(joined.with_only_columns(sa.literal(1)).where(*where))


# ---------------------------------------------------------------------------
# Enrolment (device sessions; a device is shared, the session names the user)
# ---------------------------------------------------------------------------

def _live_session(now):
    return sa.and_(
        AuthDeviceSession.revoked_at.is_(None),
        AuthDevice.revoked_at.is_(None),
        AuthDeviceSession.refresh_expires_at > now,
    )


def _enrolment_filter(state: str, now):
    def sessions(*extra):
        return sa.exists(
            sa.select(1)
            .select_from(AuthDeviceSession)
            .join(AuthDevice, AuthDevice.device_id == AuthDeviceSession.device_id)
            .where(AuthDeviceSession.user_id == VaUsers.user_id, *extra)
        )

    if state == "enrolled":
        return sessions(_live_session(now))
    if state == "none":
        return sa.not_(sessions())
    return sa.and_(sessions(), sa.not_(sessions(_live_session(now))))


def _enrolment_by_user(user_ids, now) -> dict:
    """One grouped query: live device count, revoked device count and the
    last time any of the user's device sessions was seen."""
    if not user_ids:
        return {}
    live = _live_session(now)
    rows = db.session.execute(
        sa.select(
            AuthDeviceSession.user_id,
            sa.func.count(sa.distinct(AuthDevice.device_id)).filter(live),
            sa.func.count(sa.distinct(AuthDevice.device_id)).filter(AuthDevice.revoked_at.is_not(None)),
            sa.func.max(AuthDeviceSession.last_seen_at),
        )
        .join(AuthDevice, AuthDevice.device_id == AuthDeviceSession.device_id)
        .where(AuthDeviceSession.user_id.in_(user_ids))
        .group_by(AuthDeviceSession.user_id)
    ).all()
    return {
        user_id: {
            "status": "enrolled" if active else "revoked",
            "devices": int(active),
            "revoked_devices": int(revoked),
            "last_seen_at": _iso(last_seen),
        }
        for user_id, active, revoked, last_seen in rows
    }


_NOT_ENROLLED = {"status": "none", "devices": 0, "revoked_devices": 0, "last_seen_at": None}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _text(args: Mapping[str, str], name: str) -> str:
    value = (args.get(name) or "").strip()
    if len(value) > _MAX_TEXT:
        raise UserDirectoryError(f"{name} is too long.")
    return value


def _choice(args, name, allowed, default=""):
    value = _text(args, name) or default
    if value and value not in allowed:
        raise UserDirectoryError(f"{name} must be one of: {', '.join(sorted(allowed))}.")
    return value


def _int(args, name, default, low, high) -> int:
    raw = args.get(name)
    if raw in (None, ""):
        return default
    if not str(raw).isdigit() or not low <= int(raw) <= high:
        raise UserDirectoryError(f"{name} must be a whole number from {low} to {high}.")
    return int(raw)


def _uuid(value: str, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise UserDirectoryError(f"{name} is not a valid id.") from None


def _day(args, name) -> date | None:
    value = _text(args, name)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise UserDirectoryError(f"{name} must be a date as YYYY-MM-DD.") from None


def _viewer_zone(viewer) -> ZoneInfo:
    try:
        return ZoneInfo(getattr(viewer, "timezone", None) or "UTC")
    except Exception:  # unknown zone name: fall back to UTC
        return ZoneInfo("UTC")


def _created_bounds(args, zone: ZoneInfo, now: datetime):
    """``(start, end)`` naive-UTC bounds (user_created_at is naive UTC) for
    ``created`` (today | yesterday) or ``created_from`` / ``created_to``
    (inclusive days in the viewer's timezone); either bound may be None."""
    quick = _choice(args, "created", CREATED_QUICK)
    first, last = _day(args, "created_from"), _day(args, "created_to")
    if quick:
        today = now.astimezone(zone).date()
        first = last = today if quick == "today" else today - timedelta(days=1)
    if first and last and first > last:
        raise UserDirectoryError("created_from must not be after created_to.")

    def utc(day):
        return datetime.combine(day, datetime.min.time(), tzinfo=zone).astimezone(UTC).replace(tzinfo=None)

    return (utc(first) if first else None), (utc(last + timedelta(days=1)) if last else None)


def _parse(args: Mapping[str, str]) -> dict:
    unit = _text(args, "unit")
    return {
        "q": _text(args, "q"),
        "project": _text(args, "project").upper(),
        "unit": _uuid(unit, "unit") if unit else None,
        "role": _choice(args, "role", _ROLE_VALUES),
        "status": _choice(args, "status", STATUSES, "all"),
        "enrolment": _choice(args, "enrolment", ENROLMENT_STATES),
        "email_verified": _choice(args, "email_verified", YES_NO),
        "password_set": _choice(args, "password_set", YES_NO),
        "passkey": _choice(args, "passkey", YES_NO),
        "limit": _int(args, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT),
        "offset": _int(args, "offset", 0, 0, MAX_OFFSET),
    }


def _like(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------

# A usable password: the person has accepted the terms or redeemed a sign-in
# code (user_account_service.has_usable_password, as SQL).
_PASSWORD_SET = sa.or_(VaUsers.pw_reset_t_and_c.is_(True), VaUsers.mobile_verified_at.is_not(None))
_HAS_PASSKEY = sa.exists(
    sa.select(1).where(AuthWebauthnCredential.user_id == VaUsers.user_id)
)


def _yes_no(condition, value: str):
    return condition if value == "yes" else sa.not_(condition)


def _grants_by_user(scope: _Scope, user_ids) -> dict:
    """The in-scope active grants of *user_ids*, one query, named for display."""
    if not user_ids:
        return {}
    joined, pair, unit, project = _grant_rows()
    # Aliased: active_project_condition's EXISTS names VaProjectMaster itself.
    named = sa.orm.aliased(VaProjectMaster, name="ud_project")
    rows = db.session.execute(
        joined.with_only_columns(
            _G.user_id, _G.role, _G.scope_type, project.label("project_id"),
            named.project_name, pair.site_id, VaSiteMaster.site_name,
            unit.org_unit_id, unit.unit_name, MasOrgLevel.level_name,
        )
        .outerjoin(named, named.project_id == project)
        .outerjoin(VaSiteMaster, VaSiteMaster.site_id == pair.site_id)
        .outerjoin(MasOrgLevel, MasOrgLevel.org_level_id == unit.org_level_id)
        .where(_G.user_id.in_(user_ids), *_live(scope, project))
        .order_by(_G.user_id, project, _G.role)
    ).all()
    out: dict = {}
    for r in rows:
        out.setdefault(r.user_id, []).append({
            "role": r.role.value,
            "scope": r.scope_type.value,
            "project_id": r.project_id,
            "project_name": r.project_name,
            "site_id": r.site_id,
            "site_name": r.site_name,
            "org_unit_id": str(r.org_unit_id) if r.org_unit_id else None,
            "unit_name": r.unit_name,
            "level_name": r.level_name,
        })
    return out


def _options(scope: _Scope, project_id: str) -> dict:
    """Filter choices: the viewer's projects, and the units of the chosen
    project they reach (whole tree for an admin, PI or project-scope data
    manager; else their unit grants' subtrees), capped."""
    projects_q = sa.select(VaProjectMaster.project_id, VaProjectMaster.project_name).where(
        VaProjectMaster.project_status == VaStatuses.active
    )
    if not scope.is_admin:
        projects_q = projects_q.where(VaProjectMaster.project_id.in_(sorted(scope.project_ids)))
    projects = db.session.execute(projects_q.order_by(VaProjectMaster.project_id).limit(MAX_PROJECTS)).all()
    units = []
    if project_id and (scope.is_admin or project_id in scope.project_ids):
        whole = scope.is_admin or any(
            g.project_id == project_id and g.scope_type == VaAccessScopeTypes.project for g in scope.writers
        )
        unit_ids = [g.org_unit_id for g in scope.writers if g.project_id == project_id and g.scope_type == _U]
        if whole or unit_ids:
            units_q = (
                sa.select(MasOrgUnit.org_unit_id, MasOrgUnit.unit_name, MasOrgLevel.level_name, MasOrgLevel.depth)
                .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
                .where(MasOrgUnit.project_id == project_id, MasOrgUnit.is_active.is_(True))
            )
            if not whole:
                units_q = units_q.where(MasOrgUnit.org_unit_id.in_(subtree_select(unit_ids)))
            units = [
                {"org_unit_id": str(r.org_unit_id), "unit_name": r.unit_name,
                 "level_name": r.level_name, "depth": r.depth}
                for r in db.session.execute(units_q.order_by(MasOrgUnit.path).limit(MAX_UNITS)).all()
            ]
    return {
        "projects": [{"project_id": p.project_id, "project_name": p.project_name} for p in projects],
        "units": units,
    }


def list_users(viewer, args: Mapping[str, str]) -> dict:
    """One page of the Users list. Query: ``q`` (name, email or phone,
    contains), ``project``, ``unit`` (its subtree), ``role``, ``status``
    (all | active | inactive), ``enrolment`` (enrolled | revoked | none),
    ``created`` (today | yesterday), ``created_from`` / ``created_to``
    (YYYY-MM-DD, account-created day in the viewer's timezone),
    ``email_verified`` / ``password_set`` / ``passkey`` (yes | no),
    ``limit`` (1..100, default 50), ``offset``. Raises UserDirectoryError
    (400) on a malformed parameter."""
    scope = _Scope(viewer)
    f = _parse(args)
    now = datetime.now(UTC)
    start, end = _created_bounds(args, _viewer_zone(viewer), now)
    where = []
    if start:
        where.append(VaUsers.user_created_at >= start)
    if end:
        where.append(VaUsers.user_created_at < end)
    if f["email_verified"]:
        where.append(_yes_no(VaUsers.email_verified.is_(True), f["email_verified"]))
    if f["password_set"]:
        where.append(_yes_no(_PASSWORD_SET, f["password_set"]))
    if f["passkey"]:
        where.append(_yes_no(_HAS_PASSKEY, f["passkey"]))
    if not scope.is_admin or f["project"] or f["unit"] or f["role"]:
        where.append(_visible_exists(
            scope, VaUsers.user_id, project_id=f["project"] or None, unit_id=f["unit"], role=f["role"] or None,
        ))
    if f["status"] == "active":
        where.append(VaUsers.user_status == VaStatuses.active)
    elif f["status"] == "inactive":
        where.append(VaUsers.user_status != VaStatuses.active)
    if f["enrolment"]:
        where.append(_enrolment_filter(f["enrolment"], now))
    if f["q"]:
        pattern = _like(f["q"])
        where.append(sa.or_(*(
            column.ilike(pattern, escape="\\")
            for column in (VaUsers.name, VaUsers.email, VaUsers.phone, VaUsers.mobile_login)
        )))

    total = db.session.scalar(sa.select(sa.func.count()).select_from(VaUsers).where(*where))
    users = db.session.execute(
        sa.select(
            VaUsers.user_id, VaUsers.name, VaUsers.email, VaUsers.phone, VaUsers.mobile_login,
            VaUsers.user_status, VaUsers.last_signed_in_at,
        )
        .where(*where)
        .order_by(VaUsers.name, VaUsers.user_id)
        .limit(f["limit"])
        .offset(f["offset"])
    ).all()
    ids = [u.user_id for u in users]
    grants = _grants_by_user(scope, ids)
    enrolled = _enrolment_by_user(ids, now)
    body = {
        "users": [
            {
                "user_id": str(u.user_id),
                "name": u.name,
                "email": u.email,
                "phone": u.phone or u.mobile_login,
                "active": u.user_status == VaStatuses.active,
                "last_signed_in_at": _iso(u.last_signed_in_at),
                "grants": grants.get(u.user_id, []),
                "enrolment": enrolled.get(u.user_id, _NOT_ENROLLED),
            }
            for u in users
        ],
        "total": int(total or 0),
        "limit": f["limit"],
        "offset": f["offset"],
    }
    if f["offset"] == 0:
        body["options"] = _options(scope, f["project"])
    return body


# ---------------------------------------------------------------------------
# One user
# ---------------------------------------------------------------------------

def _visible_user(scope: _Scope, user_id: str) -> VaUsers:
    """The account, when the viewer may see it; else 404 alike."""
    try:
        parsed = uuid.UUID(str(user_id))
    except ValueError:
        raise _not_found() from None
    user = db.session.get(VaUsers, parsed)
    if user is None:
        raise _not_found()
    if not scope.is_admin and not db.session.scalar(sa.select(_visible_exists(scope, user.user_id))):
        raise _not_found()
    return user


def user_activity(viewer, user_id: str) -> dict:
    """The user's activity counts (``/me/activity``'s shape) within the
    viewer's projects (all for an admin), plus when they were last active:
    the later of the last web sign-in and the last device session seen."""
    scope = _Scope(viewer)
    user = _visible_user(scope, user_id)
    summary = get_user_activity_summary(user, project_ids=None if scope.is_admin else scope.project_ids)
    device_seen = db.session.scalar(
        sa.select(sa.func.max(AuthDeviceSession.last_seen_at)).where(AuthDeviceSession.user_id == user.user_id)
    )
    seen = [v for v in (user.last_signed_in_at, device_seen) if v is not None]
    return {
        "user_id": str(user.user_id),
        "name": user.name,
        **summary,
        "last_signed_in_at": _iso(user.last_signed_in_at),
        "last_device_seen_at": _iso(device_seen),
        "last_active_at": _iso(max(seen)) if seen else None,
    }


def user_placement(viewer, user_id: str) -> dict:
    """Where the user sits in each project's organization: ``{projects: [...]}``
    in the shape of "My organization" (``organization_service.my_organization``
    run for the target). Same visibility as ``user_status`` (404 otherwise), and
    limited to the projects the viewer holds a managing grant in (an admin: all)."""
    from app.services import organization_service as org

    scope = _Scope(viewer)
    user = _visible_user(scope, user_id)
    return org.my_organization(user, project_ids=None if scope.is_admin else scope.project_ids)


_STATUS_EVENTS = ("email_verified", "verification_email_sent", "password_generated", "terms_accepted")
_CODE_HISTORY = 5


def _code_state(row: AuthDeviceEnrolmentCode, now: datetime) -> str:
    if row.revoked_at is not None:
        return "revoked"
    if row.use_count >= row.max_uses:
        return "used"
    return "expired" if row.expires_at <= now else "valid"


def user_status(viewer, user_id: str) -> dict:
    """The Status popup: what the account has done, from stored facts only
    (digitva-9npt). Same visibility as ``user_activity`` (404 otherwise).
    Never a password, hash, token or code. Fixed query count, whatever the
    history: events, passkeys, devices, code events and rows, training, QRs.
    Times are ISO strings or null where the system keeps none."""
    from app.services import sign_in_qr_service as sign_in_qr

    scope = _Scope(viewer)
    user = _visible_user(scope, user_id)
    uid, now = user.user_id, datetime.now(UTC)
    last = dict(db.session.execute(
        sa.select(AuthSecurityEvent.event_type, sa.func.max(AuthSecurityEvent.occurred_at))
        .where(AuthSecurityEvent.user_id == uid, AuthSecurityEvent.event_type.in_(_STATUS_EVENTS))
        .group_by(AuthSecurityEvent.event_type)
    ).all())
    passkeys, passkey_used = db.session.execute(
        sa.select(sa.func.count(), sa.func.max(AuthWebauthnCredential.last_used_at))
        .where(AuthWebauthnCredential.user_id == uid)
    ).one()

    events = db.session.execute(
        sa.select(AuthSecurityEvent.occurred_at, AuthSecurityEvent.detail)
        .where(AuthSecurityEvent.user_id == uid, AuthSecurityEvent.event_type == "device_enrolment_code_created")
        .order_by(AuthSecurityEvent.occurred_at.desc()).limit(_CODE_HISTORY)
    ).all()
    code_ids = []
    for _at, detail in events:
        try:
            code_ids.append(uuid.UUID((detail or {}).get("code_id", "")))
        except ValueError:
            code_ids.append(None)  # issued before the event named its code
    rows = {
        r.id: r for r in db.session.scalars(
            sa.select(AuthDeviceEnrolmentCode).where(AuthDeviceEnrolmentCode.id.in_([c for c in code_ids if c]))
        )
    } if any(code_ids) else {}
    codes = [
        {
            "generated_at": _iso(at),
            "project_id": (detail or {}).get("project_id"),
            "status": _code_state(rows[cid], now) if cid in rows else "unknown",
            "expires_at": _iso(rows[cid].expires_at) if cid in rows else None,
        }
        for (at, detail), cid in zip(events, code_ids)
    ]

    training = [
        {
            "session_code": s.session_code, "session_name": s.name, "session_status": s.status,
            "role": p.role, "coder_slot": p.coder_slot, "onboarded": p.onboarded_at is not None,
            "onboarded_at": _iso(p.onboarded_at),
        }
        for p, s in db.session.execute(
            sa.select(MapTrainingParticipant, MasTrainingSession)
            .join(MasTrainingSession,
                  MasTrainingSession.training_session_id == MapTrainingParticipant.training_session_id)
            .where(MapTrainingParticipant.user_id == uid, MapTrainingParticipant.status == "active")
            .order_by(MasTrainingSession.session_code, MapTrainingParticipant.role)
        ).all()
    ]
    try:
        qrs = sign_in_qr.list_for_user(viewer, str(uid))
    except sign_in_qr.SignInQrError:  # QRs are for device-role users only
        qrs = []
    return {
        "user_id": str(uid),
        "name": user.name,
        "active": user.user_status == VaStatuses.active,
        "created_at": _iso(user.user_created_at.replace(tzinfo=UTC)),
        "email_verified": bool(user.email_verified),
        "email_verified_at": _iso(last.get("email_verified")),
        "password_set": bool(user.pw_reset_t_and_c or user.mobile_verified_at is not None),
        "verification_email_sent_at": _iso(last.get("verification_email_sent")),
        "password_emailed_at": _iso(last.get("password_generated")),
        "terms_accepted": bool(user.pw_reset_t_and_c),
        "terms_accepted_at": _iso(last.get("terms_accepted")),
        "passkeys": {"count": int(passkeys), "last_used_at": _iso(passkey_used)},
        "enrolment_codes": codes,
        "mobile": _enrolment_by_user([uid], now).get(uid, _NOT_ENROLLED),
        "sign_in_qrs": qrs,
        "training": training,
    }


def issue_enrolment_code(viewer, user_id: str, body: Mapping) -> dict:
    """Issue an app enrolment code for a listed user in ``body["project_id"]``
    (mobile-sign-in.md section 6). The user must be active and hold an
    active device-role grant there that the viewer's scope covers.
    ``delivery`` ``show`` (default): a Devices-page code (``expires_in_minutes``,
    ``max_uses`` as there) returned once with its QR; ``email``: the
    enrolment email. Commits. Raises UserDirectoryError."""
    scope = _Scope(viewer)
    user = _visible_user(scope, user_id)
    project_id = body.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip() or len(project_id) > _MAX_TEXT:
        raise UserDirectoryError("project_id is required.")
    project_id = project_id.strip().upper()
    delivery = body.get("delivery", "show")
    if delivery not in DELIVERIES:
        raise UserDirectoryError("delivery must be show or email.")
    if user.user_status != VaStatuses.active:
        raise UserDirectoryError("This account is not active.", 400, "user_inactive")
    if not db.session.scalar(sa.select(_visible_exists(scope, user.user_id, project_id=project_id,
                                                       roles=NATIVE_DEVICE_ROLES))):
        raise UserDirectoryError(
            "This user holds no app role in that project within your scope.", 400, "no_device_role"
        )

    if delivery == "email":
        if not user.email:
            raise UserDirectoryError("This user has no email; show the code instead.", 400, "no_email")
        if enrolment.send_enrolment_email(project_id, user, actor=viewer) != "sent":
            raise UserDirectoryError(enrolment.SEND_FAILED_WARNING, 502, "email_failed")
        return {"emailed": True}

    # The code enrols any phone into the whole project, so a non-admin (often
    # unit-scoped) issuer gets one use within the default hour, no wider.
    minutes = body.get("expires_in_minutes")
    if not scope.is_admin and (
        body.get("max_uses") not in (None, 1)
        or (minutes is not None and not (isinstance(minutes, int) and minutes <= 60))
    ):
        raise UserDirectoryError(
            "Only an admin may issue a code for more than one use or longer than 60 minutes.", 400, "code_too_wide"
        )
    try:
        row, code = devices.create_enrolment_code(
            project_id, actor=viewer, expires_in_minutes=body.get("expires_in_minutes"),
            max_uses=body.get("max_uses"), subject_user_id=user.user_id,
        )
    except devices.DeviceAuthError as exc:
        db.session.rollback()
        raise UserDirectoryError(str(exc), exc.status_code, exc.code) from None
    db.session.commit()
    payload = devices.enrolment_qr_payload(row, code)
    return {
        "code": code,
        "qr_payload": payload,
        "qr_png": base64.b64encode(provisioning_qr_png(payload)).decode("ascii"),
        "project_id": row.project_id,
        "expires_at": _iso(row.expires_at),
        "max_uses": row.max_uses,
    }
