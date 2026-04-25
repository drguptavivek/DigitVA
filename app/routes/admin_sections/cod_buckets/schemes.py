"""Scheme-oriented COD bucket routes."""

import json
import uuid

from flask import current_app, jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import MasCodBucketSchemeAgeBand
from app.http.responses import json_error as _json_error
from app.routes.admin import admin
from app.services.analytics.cod_buckets import (
    create_cod_bucket_scheme,
    export_cod_bucket_scheme_json,
    get_cod_bucket_scheme,
    get_cod_bucket_scheme_editor_payload,
    list_cod_bucket_scheme_cards,
    list_cod_bucket_unmapped_icd_rows,
    reset_cod_bucket_scheme_age_band_to_source,
    search_cod_bucket_icd_candidates,
    update_cod_bucket_scheme,
)


@admin.get("/api/cod-bucket-schemes")
@role_required("admin")
def admin_cod_bucket_schemes():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
    return jsonify({"schemes": list_cod_bucket_scheme_cards()})


@admin.post("/api/cod-bucket-schemes")
@role_required("admin")
def admin_cod_bucket_scheme_create():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    data = request.get_json(silent=True) or {}
    try:
        scheme, warnings = create_cod_bucket_scheme(
            scheme_name=(data.get("scheme_name") or "").strip(),
            scheme_code=(data.get("scheme_code") or "").strip(),
            age_bands=data.get("age_bands") or [],
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)

    card = next(
        (item for item in list_cod_bucket_scheme_cards() if item["scheme_code"] == scheme.scheme_code),
        None,
    )
    return jsonify({"scheme": card, "warnings": warnings}), 201


@admin.patch("/api/cod-bucket-schemes/<scheme_code>")
@role_required("admin")
def admin_cod_bucket_scheme_update(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    data = request.get_json(silent=True) or {}
    try:
        scheme, warnings = update_cod_bucket_scheme(
            scheme_code=scheme_code,
            scheme_name=(data.get("scheme_name") or "").strip(),
            age_bands=data.get("age_bands") or [],
        )
    except LookupError:
        return _json_error("COD bucket scheme not found.", 404)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    card = next(
        (item for item in list_cod_bucket_scheme_cards() if item["scheme_code"] == scheme.scheme_code),
        None,
    )
    return jsonify({"scheme": card, "warnings": warnings})


@admin.post("/api/cod-bucket-schemes/<scheme_code>/reset-default")
@role_required("admin")
def admin_cod_bucket_scheme_reset_default(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    data = request.get_json(silent=True) or {}
    raw_age_scope = (data.get("age_scope") or "").strip()
    reset_scope = (data.get("reset_scope") or "").strip().lower() or "age_band"
    try:
        scheme = reset_cod_bucket_scheme_age_band_to_source(
            scheme_code=scheme_code,
            age_scope=raw_age_scope or None,
            reset_entire_scheme=reset_scope == "scheme",
        )
    except LookupError:
        return _json_error("COD bucket scheme not found.", 404)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    return jsonify(
        {
            "message": (
                "Scheme reset from source."
                if reset_scope == "scheme"
                else "Scheme age band reset from source."
            ),
            "scheme_code": scheme.scheme_code,
            "age_scope": None if reset_scope == "scheme" else (raw_age_scope or None),
            "reset_scope": reset_scope,
        }
    )


@admin.get("/api/cod-bucket-schemes/<scheme_code>")
@role_required("admin")
def admin_cod_bucket_scheme_detail(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    try:
        payload = get_cod_bucket_scheme_editor_payload(
            scheme_code=scheme_code,
            age_scope=(request.args.get("age_scope") or "").strip() or None,
        )
    except LookupError:
        return _json_error("COD bucket scheme not found.", 404)
    return jsonify(payload)


@admin.get("/api/cod-bucket-schemes/<scheme_code>/export")
@role_required("admin")
def admin_cod_bucket_scheme_export(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    try:
        payload = export_cod_bucket_scheme_json(scheme_code=scheme_code)
    except LookupError:
        return _json_error("COD bucket scheme not found.", 404)

    filename = f"cod_bucket_scheme_{scheme_code.lower()}.json"
    return current_app.response_class(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@admin.get("/api/cod-bucket-schemes/<scheme_code>/unmapped-icd")
@role_required("admin")
def admin_cod_bucket_scheme_unmapped_icd(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    try:
        payload = list_cod_bucket_unmapped_icd_rows(scheme_code=scheme_code)
    except LookupError:
        return _json_error("COD bucket scheme not found.", 404)
    return jsonify(payload)


@admin.get("/api/cod-bucket-schemes/<scheme_code>/icd-search")
@role_required("admin")
def admin_cod_bucket_scheme_icd_search(scheme_code):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    age_scope = (request.args.get("age_scope") or "").strip() or None
    query = (request.args.get("q") or "").strip()
    selected_node_id = None
    selected_node_id_raw = (request.args.get("selected_node_id") or "").strip()
    if selected_node_id_raw:
        try:
            selected_node_id = uuid.UUID(selected_node_id_raw)
        except ValueError:
            return _json_error("selected_node_id must be a valid UUID.", 400)
    unmapped_only = (request.args.get("unmapped_only") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    try:
        results = search_cod_bucket_icd_candidates(
            scheme_code=scheme_code,
            age_scope=age_scope,
            query=query,
            selected_node_id=selected_node_id,
            unmapped_only=unmapped_only,
        )
    except LookupError:
        return _json_error("COD bucket scheme not found.", 404)

    return jsonify(
        {"results": results, "query": query, "unmapped_only": unmapped_only}
    )
