"""Admin JSON API and panel for the health-system organization master data.

Thin HTTP layer over ``app.services.organization_service``; every rule lives
there. Routes hang off the ``admin`` blueprint (``/admin/api/organization/...``).
Plan: docs/planning/health-system-organization-model-plan.md
"""
import io
import logging
import uuid

import sqlalchemy as sa
from flask import current_app, jsonify, render_template, request
from flask_login import current_user
from openpyxl import Workbook
from werkzeug.exceptions import RequestEntityTooLarge

from app import db
from app.decorators import role_required
from app.routes.admin import _current_user_can_manage_project, _json_error, admin
from app.services import authz, org_grant_service
from app.services import organization_service as org
from app.services import project_user_import_service as user_import

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
    try:
        worker = org.create_worker(project_id, **{k: p.get(k) for k in _WORKER_FIELDS})
        serialized = org.list_workers(project_id, include_inactive=True, org_unit_id=worker.org_unit_id)
        serialized = next(w for w in serialized if w["worker_id"] == str(worker.worker_id))
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("worker-create", project_id, worker.worker_code)
    return jsonify({"worker": serialized}), 201


@admin.patch(f"{_API}/workers/<worker_id>")
@role_required("admin", "project_pi")
def admin_org_update_worker(project_id, worker_id):
    if err := _guard(project_id):
        return err
    p = _payload()
    allowed = {k: p[k] for k in _WORKER_FIELDS + ("is_active",) if k in p}
    try:
        worker = org.update_worker(project_id, worker_id, **allowed)
        serialized = org.list_workers(project_id, include_inactive=True, org_unit_id=worker.org_unit_id)
        serialized = next(w for w in serialized if w["worker_id"] == str(worker.worker_id))
    except org.OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    _commit_and_log("worker-update", project_id, worker.worker_code)
    return jsonify({"worker": serialized})


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
        user_import.template_xlsx(),
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

    from app.logging.va_logger import log_grant_action
    for grant, action in changed_grants:
        authz.invalidate(grant["user_id"])
        log_grant_action(
            action=action, actor_user_id=actor_user_id, actor_role=actor_role,
            target_user_id=grant["user_id"], grant_id=grant["grant_id"], role=grant["role"],
            scope_type=grant["scope_type"], project_id=project_id,
            org_unit_id=grant["org_unit_id"], cadre_id=grant["cadre_id"],
            request_ip=request.remote_addr,
        )
    invite_warnings = []
    invitations_queued = 0
    if new_users:
        from app.services.email_service import is_mail_configured, send_verification_email
        from app.services.token_service import generate_token
        if not is_mail_configured():
            invite_warnings.append(
                "Email delivery is not configured; invitations were not queued. "
                "Resend from Users after configuring email."
            )
        else:
            for user in new_users:
                try:
                    # Opening the verification link emails the password
                    # (account-onboarding-and-passwords.md section 5.1).
                    if send_verification_email(
                        user, generate_token(user.user_id, "email_verify"),
                        actor_user_id=actor_user_id, commit=False,
                    ):
                        invitations_queued += 1
                    else:
                        invite_warnings.append(f"Invitation for {user.email} was skipped; resend from Users.")
                except Exception:
                    log.exception("project users invitation failed | project=%s user_id=%s", project_id, user.user_id)
                    invite_warnings.append(f"Invitation for {user.email} could not be queued; resend from Users.")
            # One commit for the loop's verification_email_sent events.
            db.session.commit()
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
