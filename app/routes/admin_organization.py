"""Admin JSON API and panel for the health-system organization master data.

Thin HTTP layer over ``app.services.organization_service``; every rule lives
there. Routes hang off the ``admin`` blueprint (``/admin/api/organization/...``).
Plan: docs/planning/health-system-organization-model-plan.md
"""
import logging

import sqlalchemy as sa
from flask import current_app, jsonify, render_template, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.routes.admin import _current_user_can_manage_project, _json_error, admin
from app.services import organization_service as org

log = logging.getLogger(__name__)

_API = "/api/organization/<project_id>"


def _guard(project_id):
    """Return an error response when the user may not manage this project."""
    if not _current_user_can_manage_project(project_id):
        return _json_error("You do not have access to that project.", 403)
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
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return _json_error("Upload the organization workbook as 'file'.", 400)
    if not uploaded.filename.lower().endswith(".xlsx"):
        return _json_error("Only .xlsx workbooks are accepted.", 400)
    dry_run = request.form.get("dry_run", "1") != "0"
    deactivate_missing = request.form.get("deactivate_missing") == "1"
    try:
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
        return _json_error("The workbook could not be read.", 400)
    if plan.applied:
        _commit_and_log("import", project_id, {k: v for k, v in plan.as_dict()["counts"].items()})
    else:
        db.session.rollback()
    status = 400 if plan.errors else 200
    return jsonify({"plan": plan.as_dict(), "dry_run": dry_run}), status
