"""Read-only ICD-11 MMS admin browser routes.

Cloned in spirit from the ICD-10 browser (``app/routes/admin.py``
``admin_panel_icd10_browser`` and ``/api/icd10/2019-2/*``), but read-only:
ICD-11 policy curation for phases 1-2 happens through the
``flask icd11 policy-import/export`` CLI, not this panel. Extends the
``admin`` blueprint the same way ``app/routes/admin_organization.py`` does.
"""

from flask import jsonify, render_template, request
from flask_login import current_user

from app.decorators import role_required
from app.routes.admin import _json_error, admin
from app.services.icd11_mms_service import (
    DEFAULT_ICD11_RELEASE,
    get_icd11_mms_node_details,
    get_icd11_mms_stats,
    list_icd11_mms_children,
    search_icd11_mms,
)


@admin.get("/panels/icd11-browser")
@role_required("admin")
def admin_panel_icd11_browser():
    return render_template(
        "admin/panels/icd11_browser.html",
        stats=get_icd11_mms_stats(DEFAULT_ICD11_RELEASE),
    )


@admin.get("/api/icd11/mms/children")
@role_required("admin")
def admin_icd11_mms_children():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
    parent_uri = (request.args.get("parent_linearization_uri") or "").strip() or None
    release = (request.args.get("release") or DEFAULT_ICD11_RELEASE).strip()
    return jsonify(
        {
            "parent_linearization_uri": parent_uri,
            "children": list_icd11_mms_children(parent_uri, release=release),
        }
    )


@admin.get("/api/icd11/mms/node")
@role_required("admin")
def admin_icd11_mms_node():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
    linearization_uri = (request.args.get("linearization_uri") or "").strip()
    if not linearization_uri:
        return _json_error("linearization_uri is required.", 400)
    release = (request.args.get("release") or DEFAULT_ICD11_RELEASE).strip()
    payload = get_icd11_mms_node_details(linearization_uri, release=release)
    if payload is None:
        return _json_error("ICD-11 entity not found.", 404)
    return jsonify(payload)


@admin.get("/api/icd11/mms/search")
@role_required("admin")
def admin_icd11_mms_search():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
    query = request.args.get("q") or ""
    release = (request.args.get("release") or DEFAULT_ICD11_RELEASE).strip()
    return jsonify({"results": search_icd11_mms(query, release=release)})
