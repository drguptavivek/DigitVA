"""Admin JSON API and panel for the health-system organization master data.

Thin HTTP layer over ``app.services.organization_service``; every rule lives
there. Routes hang off the ``admin`` blueprint (``/admin/api/organization/...``).
Plan: docs/planning/health-system-organization-model-plan.md
"""
import io
import logging
import re
import uuid

import sqlalchemy as sa
from flask import current_app, jsonify, render_template, request
from flask_login import current_user
from werkzeug.exceptions import RequestEntityTooLarge

from app import db, limiter
from app.decorators import role_required
from app.models import MapOrgLevelCadre, MasCadre, MasOrgUnit, VaUsers
from app.routes.admin import _current_user_can_manage_project, _json_error, admin
from app.services import org_grant_service
from app.services import organization_service as org
from app.services import project_user_import_service as user_import
from app.services import worker_enrolment_service as enrolment
from app.services.user_account_service import canonical_mobile

log = logging.getLogger(__name__)

_API = "/api/organization/<project_id>"


def _guard(project_id):
    """Return an error response when the user may not manage this project.

    Every route here calls this first, so it is also the one place that
    refuses writes (any non-GET: seed, levels, units, cadres, level-cadre grid,
    workers, coding gates, import including its dry run) to a project not in
    'organization' structure mode. Reads stay open so an existing tree can
    still be inspected and exported. Policy: docs/policy/organization-model.md
    ("Project structure mode").
    """
    if not _current_user_can_manage_project(project_id):
        return _json_error("You do not have access to that project.", 403)
    if request.method != "GET":
        try:
            org.require_organization_mode(project_id)
        except org.OrganizationError as exc:
            return _json_error(str(exc), 409)
    return None


def _payload():
    return request.get_json(silent=True) or {}


def _include_inactive():
    return request.args.get("include_inactive") == "1"


def _commit_and_log(action, project_id, detail):
    db.session.commit()
    log.info(
        "organization %s | project=%s | by=%s | %s",
        action, project_id, getattr(current_user, "user_id", None), detail,
    )


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


@admin.get("/panels/organization")
@role_required("admin", "project_pi")
def admin_panel_organization():
    return render_template(
        "admin/panels/organization.html", project_id=request.args.get("project_id")
    )


# ---------------------------------------------------------------------------
# Summary and template
# ---------------------------------------------------------------------------


@admin.get(_API)
@role_required("admin", "project_pi")
def admin_org_summary(project_id):
    if err := _guard(project_id):
        return err
    try:
        return jsonify(
            {
                "levels": [org.serialize_level(lv) for lv in org.list_levels(project_id, include_inactive=_include_inactive())],
                "cadres": [org.serialize_cadre(c) for c in org.list_cadres(project_id, include_inactive=_include_inactive())],
                "level_cadres": org.list_level_cadres(project_id),
                "units": org.get_unit_tree(project_id, include_inactive=_include_inactive()),
                "workers": org.list_workers(project_id, include_inactive=_include_inactive()),
            }
        )
    except org.OrganizationError as exc:
        return _json_error(str(exc), 400)


@admin.post(f"{_API}/seed-template")
@role_required("admin", "project_pi")
def admin_org_seed_template(project_id):
    if err := _guard(project_id):
        return err
    try:
        counts = org.seed_default_organization(project_id, include_cadres=bool(_payload().get("include_cadres", True)))
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("seed-template", project_id, counts)
    return jsonify({"seeded": counts})


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------


@admin.get(f"{_API}/levels")
@role_required("admin", "project_pi")
def admin_org_levels(project_id):
    if err := _guard(project_id):
        return err
    return jsonify({"levels": [org.serialize_level(lv) for lv in org.list_levels(project_id, include_inactive=_include_inactive())]})


@admin.post(f"{_API}/levels")
@role_required("admin", "project_pi")
def admin_org_create_level(project_id):
    if err := _guard(project_id):
        return err
    p = _payload()
    try:
        level = org.create_level(
            project_id,
            level_code=p.get("level_code"),
            level_name=p.get("level_name"),
            depth=p.get("depth"),
            is_optional=bool(p.get("is_optional", False)),
        )
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("level-create", project_id, level.level_code)
    return jsonify({"level": org.serialize_level(level)}), 201


@admin.patch(f"{_API}/levels/<org_level_id>")
@role_required("admin", "project_pi")
def admin_org_update_level(project_id, org_level_id):
    if err := _guard(project_id):
        return err
    p = _payload()
    allowed = {k: p[k] for k in ("level_code", "level_name", "depth", "is_optional", "is_active") if k in p}
    try:
        level = org.update_level(project_id, org_level_id, **allowed)
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("level-update", project_id, level.level_code)
    return jsonify({"level": org.serialize_level(level)})


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

_UNIT_FIELDS = (
    "org_level_id", "parent_org_unit_id", "unit_code", "unit_name", "address", "phone",
    "latitude", "longitude", "google_maps_url", "remarks",
)


@admin.get(f"{_API}/units")
@role_required("admin", "project_pi")
def admin_org_units(project_id):
    if err := _guard(project_id):
        return err
    if request.args.get("tree") == "1":
        return jsonify({"units": org.get_unit_tree(project_id, include_inactive=_include_inactive())})
    return jsonify({"units": org.list_units(project_id, include_inactive=_include_inactive())})


@admin.post(f"{_API}/units")
@role_required("admin", "project_pi")
def admin_org_create_unit(project_id):
    if err := _guard(project_id):
        return err
    p = _payload()
    try:
        unit = org.create_unit(project_id, **{k: p.get(k) for k in _UNIT_FIELDS})
        serialized = org.serialize_unit(unit, parent_code=unit.parent.unit_code if unit.parent else None)
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("unit-create", project_id, unit.unit_code)
    return jsonify({"unit": serialized}), 201


@admin.patch(f"{_API}/units/<org_unit_id>")
@role_required("admin", "project_pi")
def admin_org_update_unit(project_id, org_unit_id):
    if err := _guard(project_id):
        return err
    p = _payload()
    allowed = {k: p[k] for k in _UNIT_FIELDS + ("is_active",) if k in p}
    try:
        unit = org.update_unit(project_id, org_unit_id, **allowed)
        serialized = org.serialize_unit(unit, parent_code=unit.parent.unit_code if unit.parent else None)
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("unit-update", project_id, unit.unit_code)
    return jsonify({"unit": serialized})


@admin.post(f"{_API}/units/place")
@role_required("admin", "project_pi")
def admin_org_place_units(project_id):
    """Set parents for several units in one transaction (Map parents, drag-and-drop).

    Body: ``{"placements": [{"org_unit_id", "parent_org_unit_id"}, ...]}``.
    All or nothing; see ``organization_service.place_units``.
    """
    if err := _guard(project_id):
        return err
    try:
        units = org.place_units(project_id, _payload().get("placements"))
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    codes = [unit.unit_code for unit in units]
    _commit_and_log("unit-place", project_id, f"placed={len(codes)} units={','.join(codes)}")
    return jsonify({"placed": len(codes), "unit_codes": codes})


@admin.post(f"{_API}/units/<org_unit_id>/toggle")
@role_required("admin", "project_pi")
def admin_org_toggle_unit(project_id, org_unit_id):
    if err := _guard(project_id):
        return err
    raw_active = _payload().get("is_active")
    if not isinstance(raw_active, bool):
        return _json_error("is_active (true/false) is required.", 400)
    active = raw_active
    try:
        changed = org.set_unit_active(project_id, org_unit_id, active)
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("unit-toggle", project_id, f"unit={org_unit_id} active={active} changed={changed}")
    return jsonify({"changed": changed, "is_active": active})


# ---------------------------------------------------------------------------
# Per-unit coding gate
#
# A unit's own gate row narrows the site coding gate for its subtree; a unit
# with no row is not gated. See docs/policy/organization-model.md
# ("Coding scope") and .tasks/org-per-unit-coding-gates.md.
# ---------------------------------------------------------------------------


@admin.get(f"{_API}/units/<org_unit_id>/coding-gate")
@role_required("admin", "project_pi")
def admin_org_get_unit_coding_gate(project_id, org_unit_id):
    if err := _guard(project_id):
        return err
    try:
        gate = org.get_unit_coding_gate(project_id, org_unit_id)
    except org.OrganizationError as exc:
        return _json_error(str(exc), 400)
    return jsonify({"coding_gate": org.serialize_unit_coding_gate(gate)})


@admin.put(f"{_API}/units/<org_unit_id>/coding-gate")
@role_required("admin", "project_pi")
def admin_org_set_unit_coding_gate(project_id, org_unit_id):
    if err := _guard(project_id):
        return err
    p = _payload()
    try:
        gate = org.set_unit_coding_gate(
            project_id,
            org_unit_id,
            coding_enabled=p.get("coding_enabled"),
            coding_start_date=p.get("coding_start_date"),
            coding_end_date=p.get("coding_end_date"),
            daily_coder_limit=p.get("daily_coder_limit"),
        )
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("unit-coding-gate-set", project_id, f"unit={org_unit_id}")
    return jsonify({"coding_gate": org.serialize_unit_coding_gate(gate)})


@admin.delete(f"{_API}/units/<org_unit_id>/coding-gate")
@role_required("admin", "project_pi")
def admin_org_clear_unit_coding_gate(project_id, org_unit_id):
    if err := _guard(project_id):
        return err
    try:
        cleared = org.clear_unit_coding_gate(project_id, org_unit_id)
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("unit-coding-gate-clear", project_id, f"unit={org_unit_id} cleared={cleared}")
    return jsonify({"cleared": cleared})


# ---------------------------------------------------------------------------
# Per-unit VA question presets (Id10002/Id10003)
#
# A unit's own row sets the HIV/AIDS and malaria mortality area presets for
# its subtree; a unit with no row (or a null field) inherits its nearest
# ancestor's value. See docs/policy/web-intake.md ("Area VA presets") and
# app.services.org_grant_service.resolve_unit_va_presets.
# ---------------------------------------------------------------------------


@admin.get(f"{_API}/units/<org_unit_id>/va-presets")
@role_required("admin", "project_pi")
def admin_org_get_unit_va_presets(project_id, org_unit_id):
    if err := _guard(project_id):
        return err
    try:
        presets = org.get_unit_va_presets(project_id, org_unit_id)
        unit_id = uuid.UUID(str(org_unit_id))
        inherited = org_grant_service.resolve_unit_va_presets([unit_id]).get(unit_id, {})
    except org.OrganizationError as exc:
        return _json_error(str(exc), 400)
    return jsonify({
        "va_presets": org.serialize_unit_va_presets(presets),
        "inherited": {
            field: {"value": entry["value"], "source_unit_name": entry["source_unit_name"]}
            for field, entry in inherited.items()
        },
    })


@admin.put(f"{_API}/units/<org_unit_id>/va-presets")
@role_required("admin", "project_pi")
def admin_org_set_unit_va_presets(project_id, org_unit_id):
    if err := _guard(project_id):
        return err
    p = _payload()
    try:
        presets = org.set_unit_va_presets(
            project_id,
            org_unit_id,
            hiv_mortality=p.get("hiv_mortality"),
            malaria_mortality=p.get("malaria_mortality"),
            actor_id=getattr(current_user, "user_id", None),
        )
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("unit-va-presets-set", project_id, f"unit={org_unit_id}")
    return jsonify({"va_presets": org.serialize_unit_va_presets(presets)})


@admin.delete(f"{_API}/units/<org_unit_id>/va-presets")
@role_required("admin", "project_pi")
def admin_org_clear_unit_va_presets(project_id, org_unit_id):
    if err := _guard(project_id):
        return err
    try:
        cleared = org.clear_unit_va_presets(project_id, org_unit_id)
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("unit-va-presets-clear", project_id, f"unit={org_unit_id} cleared={cleared}")
    return jsonify({"cleared": cleared})


# ---------------------------------------------------------------------------
# Cadres and level permissions
# ---------------------------------------------------------------------------


@admin.get(f"{_API}/cadres")
@role_required("admin", "project_pi")
def admin_org_cadres(project_id):
    if err := _guard(project_id):
        return err
    return jsonify({"cadres": [org.serialize_cadre(c) for c in org.list_cadres(project_id, include_inactive=_include_inactive())]})


@admin.post(f"{_API}/cadres")
@role_required("admin", "project_pi")
def admin_org_create_cadre(project_id):
    if err := _guard(project_id):
        return err
    p = _payload()
    try:
        cadre = org.create_cadre(project_id, cadre_code=p.get("cadre_code"), cadre_name=p.get("cadre_name"))
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("cadre-create", project_id, cadre.cadre_code)
    return jsonify({"cadre": org.serialize_cadre(cadre)}), 201


@admin.patch(f"{_API}/cadres/<cadre_id>")
@role_required("admin", "project_pi")
def admin_org_update_cadre(project_id, cadre_id):
    if err := _guard(project_id):
        return err
    p = _payload()
    allowed = {k: p[k] for k in ("cadre_code", "cadre_name", "is_active") if k in p}
    try:
        cadre = org.update_cadre(project_id, cadre_id, **allowed)
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("cadre-update", project_id, cadre.cadre_code)
    return jsonify({"cadre": org.serialize_cadre(cadre)})


@admin.get(f"{_API}/level-cadres")
@role_required("admin", "project_pi")
def admin_org_level_cadres(project_id):
    if err := _guard(project_id):
        return err
    return jsonify({"level_cadres": org.list_level_cadres(project_id)})


@admin.put(f"{_API}/level-cadres")
@role_required("admin", "project_pi")
def admin_org_upsert_level_cadre(project_id):
    if err := _guard(project_id):
        return err
    p = _payload()
    if p.get("default_roles") is not None and not isinstance(p["default_roles"], list):
        return _json_error("default_roles must be a list of role names.", 400)
    try:
        row = org.upsert_level_cadre(
            project_id,
            org_level_id=p.get("org_level_id"),
            cadre_id=p.get("cadre_id"),
            can_fill_va_form=bool(p.get("can_fill_va_form", False)),
            can_code_va_form=bool(p.get("can_code_va_form", False)),
            # Absent keeps the current value (clients that predate the flag).
            can_supervise_interviews=(
                None if p.get("can_supervise_interviews") is None else bool(p["can_supervise_interviews"])
            ),
            can_report_deaths=(
                None if p.get("can_report_deaths") is None else bool(p["can_report_deaths"])
            ),
            default_roles=p.get("default_roles"),
            is_active=bool(p.get("is_active", True)),
        )
        serialized = org.serialize_level_cadre(row, level=row.level, cadre=row.cadre)
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("level-cadre-upsert", project_id, f"{serialized['level_code']}/{serialized['cadre_code']}")
    return jsonify({"level_cadre": serialized})


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

_WORKER_FIELDS = ("org_unit_id", "cadre_id", "worker_code", "worker_name", "phone", "user", "remarks")


def _worker_identity(payload):
    """Resolve identity fields without ever changing an existing profile."""
    raw_user = str(payload.get("user") or "").strip()
    linked = org.resolve_user(raw_user) if raw_user else None
    email = str(payload.get("email") or "").strip().lower()
    if email and (len(email) > 128 or not user_import.EMAIL_RE.fullmatch(email)):
        raise org.OrganizationError("invalid email")
    phone = str(payload.get("phone") or "").strip()
    mobile = canonical_mobile(phone)
    email_user = db.session.scalar(
        sa.select(VaUsers).where(sa.func.lower(VaUsers.email) == email)
    ) if email else None
    mobile_user = db.session.scalar(
        sa.select(VaUsers).where(VaUsers.mobile_login == mobile)
    ) if mobile else None
    # Email/mobile lookups include inactive rows so an existing account cannot
    # be silently treated as an unlinked roster-only worker.
    if email_user:
        org.resolve_user(email_user)
    if mobile_user:
        org.resolve_user(mobile_user)
    candidates = [user for user in (linked, email_user, mobile_user) if user is not None]
    if candidates and any(user.user_id != candidates[0].user_id for user in candidates[1:]):
        raise org.OrganizationError("Email, mobile and linked user identify different accounts.")
    if linked and email and (not linked.email or linked.email.lower() != email):
        raise org.OrganizationError("Email does not match the linked user.")
    if linked and mobile and linked.mobile_login and linked.mobile_login != mobile:
        raise org.OrganizationError("Mobile number does not match the linked user.")
    return linked or email_user or mobile_user, email, phone, mobile


def _validate_worker_account(payload, email):
    """Validate confirmed contact fields before creating a new account.

    Existing account links bypass this form-only confirmation contract.
    Raises OrganizationError without writing account, grant or worker rows.
    """
    no_email = payload.get("no_email", False)
    if not isinstance(no_email, bool):
        raise org.OrganizationError("No email must be true or false.")
    phone = payload.get("phone") or ""
    if no_email:
        if email or str(payload.get("email_confirm") or "").strip():
            raise org.OrganizationError("Remove the email and confirmation when choosing No email.")
        if not phone:
            raise org.OrganizationError("A 10-digit mobile number is required without email.")
        if payload.get("phone_confirm") != phone:
            raise org.OrganizationError("Mobile numbers must match.")
    elif not email or str(payload.get("email_confirm") or "").strip().lower() != email:
        raise org.OrganizationError("Enter and confirm the same email address, or choose No email.")
    year = payload.get("year_of_birth")
    if year not in (None, "") and not re.fullmatch(r"[0-9]{4}", str(year)):
        raise org.OrganizationError("Year of birth must be a whole number.")
    sex = payload.get("sex")
    if sex is not None and not isinstance(sex, str):
        raise org.OrganizationError("Sex must be a valid choice.")


def _worker_default_roles(project_id, payload):
    """Return configured defaults for a valid unit/cadre pair, if any."""
    try:
        unit_id = uuid.UUID(str(payload.get("org_unit_id")))
        cadre_id = uuid.UUID(str(payload.get("cadre_id")))
    except (TypeError, ValueError, AttributeError):
        return []
    unit = db.session.get(MasOrgUnit, unit_id)
    cadre = db.session.get(MasCadre, cadre_id)
    if unit is None or cadre is None or unit.project_id != project_id or cadre.project_id != project_id:
        return []
    permission = db.session.scalar(sa.select(MapOrgLevelCadre).where(
        MapOrgLevelCadre.org_level_id == unit.org_level_id,
        MapOrgLevelCadre.cadre_id == cadre.cadre_id,
    ))
    return list(permission.default_roles or []) if permission and permission.is_active else []


@admin.get(f"{_API}/workers")
@role_required("admin", "project_pi")
def admin_org_workers(project_id):
    if err := _guard(project_id):
        return err
    try:
        workers = org.list_workers(
            project_id, include_inactive=_include_inactive(), org_unit_id=request.args.get("org_unit_id")
        )
    except org.OrganizationError as exc:
        return _json_error(str(exc), 400)
    return jsonify({"workers": workers})


@admin.post(f"{_API}/workers")
@role_required("admin", "project_pi")
def admin_org_create_worker(project_id):
    if err := _guard(project_id):
        return err
    p = _payload()
    invitations = []
    changed_grants = []
    sign_in_codes = []
    onboarding = {
        "created_users": 0,
        "changed_grants": 0,
        "invitations_queued": 0,
        "invite_warnings": [],
        "sign_in_codes": [],
    }
    try:
        raw_phone = p.get("phone")
        if raw_phone not in (None, "") and (
            not isinstance(raw_phone, str) or not re.fullmatch(r"[0-9]{10}", raw_phone)
        ):
            raise org.OrganizationError("Phone must contain exactly 10 digits.")
        linked, email, phone, _mobile = _worker_identity(p)
        defaults = _worker_default_roles(project_id, p)
        # An existing email/mobile resolves to the account even when the
        # roster payload does not carry the internal user UUID.
        worker_user = str(linked.user_id) if linked else p.get("user")
        if defaults:
            if not linked:
                _validate_worker_account(p, email)
            if linked:
                email = email or (linked.email or "")
                phone = phone or (linked.mobile_login or "")
            row = {
                "_line_number": 1,
                "email": email,
                "name": str(p.get("worker_name") or ""),
                "role": "",
                "org_unit_code": "",
                "cadre_code": "",
                "language_codes": str(p.get("language_codes") or ""),
                "phone": phone,
            }
            # The importer validates the unit/cadre and expands the stored
            # defaults; codes are filled only after those records are found.
            unit = db.session.get(MasOrgUnit, uuid.UUID(str(p.get("org_unit_id"))))
            cadre = db.session.get(MasCadre, uuid.UUID(str(p.get("cadre_id"))))
            row["org_unit_code"] = unit.unit_code if unit else ""
            row["cadre_code"] = cadre.cadre_code if cadre else ""
            plan = user_import.prepare(project_id, [row], actor=current_user)
            invitations, changed_grants, sign_in_codes = user_import.apply(
                project_id, plan, actor_user_id=current_user.user_id
            )
            account = plan[0]["user"]
            if not linked:
                account.set_interviewer_profile(p.get("year_of_birth"), p.get("sex"))
            worker_user = str(account.user_id)
        worker = org.create_worker(
            project_id,
            **{k: p.get(k) for k in _WORKER_FIELDS if k != "user"},
            user=worker_user,
        )
        if "coding_unit_ids" in p or "supervision_unit_ids" in p:
            extra_grants = org.sync_worker_unit_scope_grants(
                project_id,
                worker,
                coding_unit_ids=p.get("coding_unit_ids"),
                supervision_unit_ids=p.get("supervision_unit_ids"),
                actor=current_user,
            )
            changed_grants.extend(extra_grants)
        serialized = org.list_workers(project_id, include_inactive=True, org_unit_id=worker.org_unit_id)
        serialized = next(w for w in serialized if w["worker_id"] == str(worker.worker_id))
        db.session.commit()
    except (org.OrganizationError, user_import.ProjectUserImportError, ValueError) as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    if changed_grants or invitations:
        queued, warnings = user_import.finalize_apply(
            project_id,
            actor_user_id=current_user.user_id,
            actor_role="admin" if current_user.is_admin() else "project_pi",
            changed_grants=changed_grants,
            invitations=invitations,
            request_ip=request.remote_addr,
        )
        onboarding.update(
            created_users=len(invitations) + len(sign_in_codes),
            changed_grants=len(changed_grants),
            invitations_queued=queued,
            invite_warnings=warnings,
            sign_in_codes=sign_in_codes,
        )
    onboarding["enrolment_email"] = None
    for user_id in enrolment.newly_collecting_user_ids(changed_grants):
        status = enrolment.send_enrolment_email(project_id, db.session.get(VaUsers, user_id), actor=current_user)
        onboarding["enrolment_email"] = status
        if status == "failed":
            onboarding["invite_warnings"].append(enrolment.SEND_FAILED_WARNING)
    response = jsonify({"worker": serialized, "onboarding": onboarding})
    response.headers["Cache-Control"] = "no-store"
    log.info("organization worker-create | project=%s | by=%s | worker=%s", project_id, current_user.user_id, worker.worker_code)
    return response, 201


@admin.patch(f"{_API}/workers/<worker_id>")
@role_required("admin", "project_pi")
def admin_org_update_worker(project_id, worker_id):
    if err := _guard(project_id):
        return err
    p = _payload()
    allowed = {k: p[k] for k in _WORKER_FIELDS + ("is_active",) if k in p}
    scope_changed = []
    try:
        worker = org.update_worker(project_id, worker_id, **allowed)
        if "coding_unit_ids" in p or "supervision_unit_ids" in p:
            scope_changed = org.sync_worker_unit_scope_grants(
                project_id,
                worker,
                coding_unit_ids=p.get("coding_unit_ids"),
                supervision_unit_ids=p.get("supervision_unit_ids"),
                actor=current_user,
            )
        serialized = org.list_workers(project_id, include_inactive=True, org_unit_id=worker.org_unit_id)
        serialized = next(w for w in serialized if w["worker_id"] == str(worker.worker_id))
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("worker-update", project_id, worker.worker_code)
    if scope_changed:
        user_import.finalize_apply(
            project_id,
            actor_user_id=current_user.user_id,
            actor_role="admin" if current_user.is_admin() else "project_pi",
            changed_grants=scope_changed,
            invitations=[],
            request_ip=request.remote_addr,
        )
    return jsonify({"worker": serialized})


@admin.post(f"{_API}/workers/<worker_id>/enrolment-email")
@role_required("admin", "project_pi")
@limiter.limit("10 per minute")
def admin_org_resend_enrolment_email(project_id, worker_id):
    """Email the worker a fresh app enrolment QR (mobile-sign-in.md section 6).
    400 unless the worker's account is active, has an email and holds an
    active interviewer or death_reporter grant in this project."""
    if err := _guard(project_id):
        return err
    try:
        user = org.worker_data_collector_user(project_id, worker_id)
    except org.OrganizationError as exc:
        return _json_error(str(exc), 400)
    status = enrolment.send_enrolment_email(project_id, user, actor=current_user)
    if status != "sent":
        return _json_error(enrolment.SEND_FAILED_WARNING, 502)
    log.info("organization enrolment-email | project=%s | by=%s | worker=%s", project_id, current_user.user_id, worker_id)
    return jsonify({"sent": True})


# ---------------------------------------------------------------------------
# Export and import
# ---------------------------------------------------------------------------


@admin.get(f"{_API}/export.xlsx")
@role_required("admin", "project_pi")
def admin_org_export_xlsx(project_id):
    if err := _guard(project_id):
        return err
    try:
        workbook_bytes = org.export_organization_xlsx(project_id)
    except org.OrganizationError as exc:
        return _json_error(str(exc), 400)
    log.info("organization export | project=%s | by=%s", project_id, current_user.user_id)
    return current_app.response_class(
        workbook_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="organization_{project_id}.xlsx"'},
    )


@admin.get(f"{_API}/export/<sheet>.csv")
@role_required("admin", "project_pi")
def admin_org_export_csv(project_id, sheet):
    if err := _guard(project_id):
        return err
    try:
        body = org.export_organization_csv(project_id, sheet)
    except org.OrganizationError as exc:
        return _json_error(str(exc), 400)
    log.info("organization export csv | project=%s | sheet=%s | by=%s", project_id, sheet, current_user.user_id)
    return current_app.response_class(
        body,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="organization_{project_id}_{sheet}.csv"'},
    )


@admin.get(f"{_API}/templates/units.csv")
@role_required("admin", "project_pi")
def admin_org_units_template(project_id):
    if err := _guard(project_id):
        return err
    # Keep the import column order, excluding the computed ltree path.
    from app.services.organization_service import _UNIT_HEADERS
    return current_app.response_class(
        ",".join(header for header in _UNIT_HEADERS if header != "path") + "\r\n", mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="organization_units_template.csv"'},
    )


@admin.get(f"{_API}/templates/units.xlsx")
@role_required("admin", "project_pi")
def admin_org_units_template_xlsx(project_id):
    if err := _guard(project_id):
        return err
    from app.services.organization_service import _UNIT_HEADERS
    from openpyxl import Workbook
    workbook = Workbook()
    workbook.active.title = "units"
    workbook.active.append([header for header in _UNIT_HEADERS if header != "path"])
    output = io.BytesIO()
    workbook.save(output)
    return current_app.response_class(
        output.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="organization_units_template.xlsx"'},
    )


@admin.get(f"{_API}/templates/project-users.csv")
@role_required("admin", "project_pi")
def admin_org_users_template(project_id):
    if err := _guard(project_id):
        return err
    return current_app.response_class(
        user_import.template_csv(), mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="project_users_template.csv"'},
    )


@admin.get(f"{_API}/templates/project-users.xlsx")
@role_required("admin", "project_pi")
def admin_org_users_template_xlsx(project_id):
    if err := _guard(project_id):
        return err
    return current_app.response_class(
        user_import.template_xlsx(project_id, actor=current_user),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="project_users_template.xlsx"'},
    )


@admin.post(f"{_API}/project-users/import")
@role_required("admin", "project_pi")
def admin_org_import_users(project_id):
    if err := _guard(project_id):
        return err
    actor_user_id = current_user.user_id
    actor_role = "admin" if current_user.is_admin() else "project_pi"
    request.max_content_length = 1024 * 1024 + 64 * 1024
    try:
        uploaded = request.files.get("file")
    except RequestEntityTooLarge:
        return _json_error("The upload exceeds the 1 MB limit.", 413)
    if uploaded is None or not uploaded.filename or not uploaded.filename.lower().endswith((".csv", ".xlsx")):
        return _json_error("Upload a project users CSV or XLSX as 'file'.", 400)
    dry_run = request.form.get("dry_run", "1") != "0"
    try:
        rows = user_import.parse_upload(uploaded.stream, uploaded.filename)
        plan = user_import.prepare(project_id, rows, actor=current_user)
        preview = [{"row": item["row"], "email": item["display"],
                    "role": item["role"].value,
                    "scope": item["unit"].unit_code if item["unit"] else "whole project",
                    "action": item["action"]} for item in plan]
        if dry_run:
            return jsonify({"dry_run": True, "rows": preview})
        new_users, changed_grants, sign_in_codes = user_import.apply(
            project_id, plan, actor_user_id=actor_user_id
        )
        db.session.commit()
    except user_import.ProjectUserImportError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    except Exception:
        db.session.rollback()
        log.exception("project users import failed | project=%s", project_id)
        return _json_error("The project users import failed.", 500)

    invitations_queued, invite_warnings = user_import.finalize_apply(
        project_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        changed_grants=changed_grants,
        invitations=new_users,
        request_ip=request.remote_addr,
    )
    log.info("project users import | project=%s by=%s rows=%s new_users=%s",
             project_id, actor_user_id, len(plan), len(new_users) + len(sign_in_codes))
    # New mobile-only accounts' first sign-in codes, shown once (section
    # 5.2): only in this no-store response, never logged.
    response = jsonify({"dry_run": False, "rows": preview,
                        "created_users": len(new_users) + len(sign_in_codes),
                        "changed_grants": len(changed_grants),
                        "invitations_queued": invitations_queued,
                        "invite_warnings": invite_warnings,
                        "sign_in_codes": sign_in_codes})
    response.headers["Cache-Control"] = "no-store"
    return response


@admin.get(f"{_API}/odk-choices.csv")
@role_required("admin", "project_pi")
def admin_org_odk_choices_csv(project_id):
    if err := _guard(project_id):
        return err
    body = org.export_odk_choices_csv(project_id)
    return current_app.response_class(
        body,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="odk_choices_{project_id}.csv"'},
    )


@admin.get(f"{_API}/odk-field-check")
@role_required("admin", "project_pi")
def admin_org_odk_field_check(project_id):
    """Check that a mapped ODK form carries this project's org_<level>_code fields.

    ``site_id`` names the project-site whose mapping to check. The ODK project
    and form come from that mapping, never from the request, so the form
    checked is always the one submissions will actually arrive from. Reads the
    field list from ODK Central live, through the shared connection guard.
    """
    if err := _guard(project_id):
        return err

    from app.models import MapProjectSiteOdk
    from app.services.org_unit_routing_service import check_odk_form_fields

    site_id = (request.args.get("site_id") or "").strip()
    if not site_id:
        return _json_error("site_id is required.", 400)

    mapping = db.session.scalar(
        sa.select(MapProjectSiteOdk).where(
            MapProjectSiteOdk.project_id == project_id,
            MapProjectSiteOdk.site_id == site_id,
        )
    )
    if mapping is None:
        return _json_error("This project-site has no ODK form mapping.", 404)

    try:
        result = check_odk_form_fields(
            project_id, mapping.odk_project_id, mapping.odk_form_id
        )
    except Exception as exc:  # noqa: BLE001 — surfaced verbatim to the operator
        log.warning(
            "organization odk-field-check failed | project=%s site=%s form=%s | %s",
            project_id, site_id, mapping.odk_form_id, exc,
        )
        return _json_error(f"Could not read the ODK form: {exc}", 502)

    result["site_id"] = site_id
    return jsonify(result)


@admin.post(f"{_API}/import")
@role_required("admin", "project_pi")
def admin_org_import(project_id):
    if err := _guard(project_id):
        return err
    request.max_content_length = 5 * 1024 * 1024 + 64 * 1024
    try:
        uploaded = request.files.get("file")
    except RequestEntityTooLarge:
        return _json_error("The upload exceeds the 5 MB limit.", 413)
    if uploaded is None or not uploaded.filename:
        return _json_error("Upload the organization workbook as 'file'.", 400)
    filename = uploaded.filename.lower()
    if not filename.endswith((".xlsx", ".csv")):
        return _json_error("Upload an .xlsx workbook or a .csv of one sheet.", 400)
    dry_run = request.form.get("dry_run", "1") != "0"
    deactivate_missing = request.form.get("deactivate_missing") == "1"
    try:
        if filename.endswith(".csv"):
            # One sheet per CSV, in the per-sheet export layout.
            sheets = org.parse_organization_csv(uploaded.stream, (request.form.get("sheet") or "").strip())
        elif (request.form.get("sheet") or "").strip() == "units":
            sheets = org.parse_units_upload(uploaded.stream, filename)
        else:
            sheets = org.parse_organization_workbook(uploaded.stream)
        plan = org.import_organization(
            project_id, sheets, dry_run=dry_run, deactivate_missing=deactivate_missing
        )
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    except Exception:  # malformed workbook
        db.session.rollback()
        log.exception("organization import failed | project=%s", project_id)
        return _json_error("The file could not be read.", 400)
    if plan.applied:
        _commit_and_log("import", project_id, {k: v for k, v in plan.as_dict()["counts"].items()})
    else:
        db.session.rollback()
    status = 400 if plan.errors else 200
    return jsonify({"plan": plan.as_dict(), "dry_run": dry_run}), status


# ---------------------------------------------------------------------------
# Existing user lookup, bulk VA mortality presets, and mentoring institutes
# ---------------------------------------------------------------------------


@admin.get(f"{_API}/users/lookup")
@role_required("admin", "project_pi")
@limiter.limit("60 per minute")
def admin_org_user_lookup(project_id):
    """Exact lookup; with ``suggest=1`` also ``suggestions`` (up to 8 partial
    matches) in the same response, so typing costs one request per pause."""
    if err := _guard(project_id):
        return err
    q, is_admin = request.args.get("q"), current_user.is_admin()
    result = org.lookup_existing_user(q, is_admin=is_admin)
    if request.args.get("suggest") == "1":
        result["suggestions"] = org.suggest_existing_users(q, is_admin=is_admin)
    return jsonify(result)


@admin.get(f"{_API}/va-presets")
@role_required("admin", "project_pi")
def admin_org_list_va_presets(project_id):
    if err := _guard(project_id):
        return err
    try:
        units = org.list_project_va_presets(project_id)
    except org.OrganizationError as exc:
        return _json_error(str(exc), 400)
    return jsonify({"units": units})


@admin.put(f"{_API}/va-presets")
@role_required("admin", "project_pi")
def admin_org_bulk_set_va_presets(project_id):
    if err := _guard(project_id):
        return err
    p = _payload()
    items = p.get("items") if "items" in p else (p.get("presets") or [])
    try:
        updated = org.bulk_set_unit_va_presets(
            project_id,
            items,
            actor_id=current_user.user_id,
        )
        units = org.list_project_va_presets(project_id)
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("va-presets-bulk", project_id, {"updated": updated})
    return jsonify({"updated": updated, "units": units})


@admin.get(f"{_API}/mentoring")
@role_required("admin", "project_pi")
def admin_org_mentoring_overview(project_id):
    if err := _guard(project_id):
        return err
    try:
        overview = org.project_mentoring_overview(project_id)
    except org.OrganizationError as exc:
        return _json_error(str(exc), 400)
    return jsonify(overview)


@admin.post(f"{_API}/mentoring/grants")
@role_required("admin", "project_pi")
def admin_org_mentoring_grants(project_id):
    if err := _guard(project_id):
        return err
    p = _payload()
    try:
        changed = org.sync_mentor_scientist_unit_grants(
            project_id,
            user_id=p.get("user_id"),
            role_name=str(p.get("role") or p.get("role_name") or ""),
            org_unit_ids=p.get("org_unit_ids") or [],
            actor=current_user,
        )
        db.session.commit()
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    if changed:
        user_import.finalize_apply(
            project_id,
            actor_user_id=current_user.user_id,
            actor_role="admin" if current_user.is_admin() else "project_pi",
            changed_grants=changed,
            invitations=[],
            request_ip=request.remote_addr,
        )
    overview = org.project_mentoring_overview(project_id)
    return jsonify({"changed": len(changed), "overview": overview, **overview})


@admin.post(f"{_API}/mentoring/districts")
@role_required("admin")
def admin_org_mentoring_districts(project_id):
    """Platform-admin actions for project mentoring institutes: sync district links or create/attach/detach/add_scientist."""
    if err := _guard(project_id):
        return err
    from app.models import MapMentorInstituteOrgUnit, MasMentorInstitute, MasOrgUnit
    from app.services import mentor_institute_service as mentor_svc

    p = _payload()
    action = str(p.get("action") or "").strip()
    try:
        if not action and p.get("mentor_institute_id") is not None:
            inst_uuid = org._uuid(p.get("mentor_institute_id"), what="Institute id")
            inst = db.session.get(MasMentorInstitute, inst_uuid)
            if inst is None or not inst.is_active:
                return _json_error("Active mentoring institute not found.", 404)
            desired_ids = {
                org._uuid(uid, what="Unit id")
                for uid in (p.get("district_unit_ids") or [])
            }
            project_districts = {
                u.org_unit_id: u
                for u in db.session.scalars(
                    sa.select(MasOrgUnit).where(
                        MasOrgUnit.project_id == project_id,
                        MasOrgUnit.is_active.is_(True),
                    )
                ).all()
            }
            for uid in desired_ids:
                if uid not in project_districts:
                    raise org.OrganizationError("Selected district unit does not belong to this project.")
            for uid in desired_ids:
                mentor_svc.attach_district(
                    inst.institute_code,
                    project_id,
                    project_districts[uid].unit_code,
                    actor_user_id=current_user.user_id,
                )
            existing_links = db.session.scalars(
                sa.select(MapMentorInstituteOrgUnit).where(
                    MapMentorInstituteOrgUnit.institute_id == inst.institute_id,
                    MapMentorInstituteOrgUnit.org_unit_id.in_(list(project_districts.keys())),
                    MapMentorInstituteOrgUnit.is_active.is_(True),
                )
            ).all()
            for link in existing_links:
                if link.org_unit_id not in desired_ids:
                    mentor_svc.detach_district(
                        inst.institute_code,
                        project_id,
                        project_districts[link.org_unit_id].unit_code,
                        actor_user_id=current_user.user_id,
                    )
        elif action == "create_and_attach":
            code = p.get("institute_code")
            name = p.get("institute_name")
            unit_code = p.get("unit_code")
            mentor_svc.create_institute(code, name, actor_user_id=current_user.user_id)
            if unit_code:
                mentor_svc.attach_district(code, project_id, unit_code, actor_user_id=current_user.user_id)
        elif action == "attach":
            mentor_svc.attach_district(
                p.get("institute_code"),
                project_id,
                p.get("unit_code"),
                actor_user_id=current_user.user_id,
            )
        elif action == "detach":
            mentor_svc.detach_district(
                p.get("institute_code"),
                project_id,
                p.get("unit_code"),
                actor_user_id=current_user.user_id,
            )
        elif action == "add_scientist":
            mentor_svc.add_member(
                p.get("institute_code"),
                email=str(p.get("email") or "").strip() or None,
                user_id=p.get("user_id") or None,
                actor_user_id=current_user.user_id,
            )
        else:
            return _json_error("Unknown action; use create_and_attach, attach, detach, or add_scientist.", 400)
        db.session.commit()
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    overview = org.project_mentoring_overview(project_id)
    return jsonify({"overview": overview, **overview})
