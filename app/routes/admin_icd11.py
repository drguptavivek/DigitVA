"""ICD-11 MMS admin browser and policy editor routes.

Mirrors the ICD-10 browser (``app/routes/admin.py``
``admin_panel_icd10_browser`` and ``/api/icd10/2019-2/*``): hierarchy,
node details, search, per-category policy PATCH, policy JSON import/export
and an xlsx export. The JSON import/export share their service functions
with the ``flask icd11 policy-import/export`` CLI, so both read and write
one format. Extends the ``admin`` blueprint the same way
``app/routes/admin_organization.py`` does.

ICD-11 entities are keyed by a linearization URI (it contains slashes), so
it travels as a ``linearization_uri`` query argument rather than a path
segment. Every endpoint takes an optional ``release`` argument.
"""

import json
import re

from flask import current_app, jsonify, render_template, request
from flask_login import current_user

from app.decorators import role_required
from app.routes.admin import _json_error, admin
from app.services.icd11_mms_service import (
    AGE_GROUP_SELECTABLE_OPTIONS,
    CODING_FILTER_OPTIONS,
    DEFAULT_ICD11_RELEASE,
    SEX_SELECTABLE_OPTIONS,
    export_icd11_mms_policy_json,
    export_icd11_mms_policy_xlsx,
    get_icd11_mms_node_details,
    get_icd11_mms_policy_options,
    get_icd11_mms_stats,
    import_icd11_mms_policy_json,
    list_icd11_mms_children,
    search_icd11_mms,
    update_icd11_mms_policy,
)

_RELEASE_RE = re.compile(r"^\d{4}-\d{2}$")
_FILTER_ALLOWED = {
    "coding_filter": CODING_FILTER_OPTIONS,
    "sex_filter": ("any", *SEX_SELECTABLE_OPTIONS),
    "age_filter": ("any", *AGE_GROUP_SELECTABLE_OPTIONS),
}
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _release_arg():
    """``(release, error_response)`` from the ``release`` query argument.

    The release also names export files, so it is held to WHO's ``YYYY-MM``.
    """
    release = (request.args.get("release") or DEFAULT_ICD11_RELEASE).strip()
    if not _RELEASE_RE.match(release):
        return None, _json_error("release must look like YYYY-MM.", 400)
    return release, None


def _admin_only():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
    return None


@admin.get("/panels/icd11-browser")
@role_required("admin")
def admin_panel_icd11_browser():
    return render_template(
        "admin/panels/icd11_browser.html",
        stats=get_icd11_mms_stats(DEFAULT_ICD11_RELEASE),
        release=DEFAULT_ICD11_RELEASE,
    )


@admin.get("/api/icd11/mms/children")
@role_required("admin")
def admin_icd11_mms_children():
    if (denied := _admin_only()) is not None:
        return denied
    release, error = _release_arg()
    if error is not None:
        return error
    filters = {}
    for name, allowed in _FILTER_ALLOWED.items():
        value = (request.args.get(name) or "any").strip() or "any"
        if value not in allowed:
            return _json_error(f"{name} must be one of {', '.join(allowed)}.", 400)
        filters[name] = value
    parent_uri = (request.args.get("parent_linearization_uri") or "").strip() or None
    return jsonify(
        {
            "parent_linearization_uri": parent_uri,
            "children": list_icd11_mms_children(parent_uri, release=release, **filters),
        }
    )


@admin.get("/api/icd11/mms/node")
@role_required("admin")
def admin_icd11_mms_node():
    if (denied := _admin_only()) is not None:
        return denied
    release, error = _release_arg()
    if error is not None:
        return error
    linearization_uri = (request.args.get("linearization_uri") or "").strip()
    if not linearization_uri:
        return _json_error("linearization_uri is required.", 400)
    payload = get_icd11_mms_node_details(linearization_uri, release=release)
    if payload is None:
        return _json_error("ICD-11 entity not found.", 404)
    return jsonify(payload)


@admin.get("/api/icd11/mms/search")
@role_required("admin")
def admin_icd11_mms_search():
    if (denied := _admin_only()) is not None:
        return denied
    release, error = _release_arg()
    if error is not None:
        return error
    query = request.args.get("q") or ""
    return jsonify({"results": search_icd11_mms(query, release=release)})


@admin.get("/api/icd11/mms/policy-options")
@role_required("admin")
def admin_icd11_mms_policy_options():
    if (denied := _admin_only()) is not None:
        return denied
    return jsonify(get_icd11_mms_policy_options())


@admin.get("/api/icd11/mms/policy-export")
@role_required("admin")
def admin_icd11_mms_policy_export():
    if (denied := _admin_only()) is not None:
        return denied
    release, error = _release_arg()
    if error is not None:
        return error
    payload = export_icd11_mms_policy_json(release=release)
    return current_app.response_class(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="icd11_mms_{release}_policy_export.json"'
            )
        },
    )


@admin.get("/api/icd11/mms/policy-export.xlsx")
@role_required("admin")
def admin_icd11_mms_policy_export_xlsx():
    if (denied := _admin_only()) is not None:
        return denied
    release, error = _release_arg()
    if error is not None:
        return error
    workbook_bytes = export_icd11_mms_policy_xlsx(release=release)
    return current_app.response_class(
        workbook_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="icd11_mms_{release}_policy_export.xlsx"'
            )
        },
    )


@admin.post("/api/icd11/mms/policy-import")
@role_required("admin")
def admin_icd11_mms_policy_import():
    """Import a policy JSON; form field ``dry_run=1`` previews without writing."""
    if (denied := _admin_only()) is not None:
        return denied
    release, error = _release_arg()
    if error is not None:
        return error
    uploaded = request.files.get("file")
    if uploaded is None:
        return _json_error("file is required.", 400)
    try:
        payload = uploaded.read().decode("utf-8")
    except UnicodeDecodeError:
        return _json_error("Policy import file must be UTF-8 JSON.", 400)
    dry_run = (request.form.get("dry_run") or "").strip().lower() in _TRUE_VALUES

    try:
        result = import_icd11_mms_policy_json(payload, release=release, dry_run=dry_run)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    if not dry_run:
        current_app.logger.info(
            "ICD-11 policy import applied by user %s: release=%s total=%s "
            "updated=%s reset=%s skipped=%s",
            current_user.user_id,
            release,
            result.total_items,
            result.updated_items,
            result.reset_items,
            len(result.skipped_items),
        )
    return jsonify(
        {
            "message": (
                "ICD-11 policy import preview (nothing saved)."
                if dry_run
                else "ICD-11 policy import completed."
            ),
            "dry_run": dry_run,
            "release": release,
            "total_items": result.total_items,
            "updated_items": result.updated_items,
            "reset_items": result.reset_items,
            "skipped_items": result.skipped_items,
            "failed_codes": result.skipped_items,
        }
    )


@admin.patch("/api/icd11/mms/node/policy")
@role_required("admin")
def admin_icd11_mms_update_policy():
    """Set one category's policy; ``linearization_uri`` is a query argument."""
    if (denied := _admin_only()) is not None:
        return denied
    release, error = _release_arg()
    if error is not None:
        return error
    linearization_uri = (request.args.get("linearization_uri") or "").strip()
    if not linearization_uri:
        return _json_error("linearization_uri is required.", 400)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _json_error("A JSON object body is required.", 400)
    try:
        payload = update_icd11_mms_policy(
            linearization_uri,
            release=release,
            is_coding_selectable=body.get("is_coding_selectable"),
            sex_selectable=body.get("sex_selectable"),
            age_group_selectable=body.get("age_group_selectable"),
            restriction_note=body.get("restriction_note"),
            policy_status=body.get("policy_status"),
        )
    except LookupError:
        return _json_error("ICD-11 entity not found.", 404)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    current_app.logger.info(
        "ICD-11 policy updated by user %s: release=%s uri=%s code=%s "
        "coding_selectable=%s sex=%s age=%s status=%s",
        current_user.user_id,
        release,
        linearization_uri,
        payload.get("code"),
        payload.get("is_coding_selectable"),
        payload.get("sex_selectable"),
        payload.get("age_group_selectable"),
        payload.get("policy_status"),
    )
    return jsonify(payload)
