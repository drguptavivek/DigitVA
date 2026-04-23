from .common import (
    _json_error,
    admin,
    current_app,
    export_icd10_2019_2_policy_json,
    get_icd10_2019_2_node_details,
    get_icd10_2019_2_policy_options,
    import_icd10_2019_2_policy_json,
    json,
    jsonify,
    list_icd10_2019_2_children,
    request,
    role_required,
    update_icd10_2019_2_policy,
)


@admin.get("/api/icd10/2019-2/children")
@role_required("admin")
def admin_icd10_2019_2_children():
    parent_code = (request.args.get("parent_code") or "").strip() or None
    filters = {
        "coding_filter": (request.args.get("coding_filter") or "any").strip()
        or "any",
        "sex_filter": (request.args.get("sex_filter") or "any").strip() or "any",
        "age_filter": (request.args.get("age_filter") or "any").strip() or "any",
    }
    return jsonify(
        {
            "parent_code": parent_code,
            "children": list_icd10_2019_2_children(parent_code, **filters),
        }
    )


@admin.get("/api/icd10/2019-2/node/<code>")
@role_required("admin")
def admin_icd10_2019_2_node(code):
    payload = get_icd10_2019_2_node_details(code.strip())
    if payload is None:
        return _json_error("ICD code not found.", 404)
    return jsonify(payload)


@admin.get("/api/icd10/2019-2/policy-options")
@role_required("admin")
def admin_icd10_2019_2_policy_options():
    return jsonify(get_icd10_2019_2_policy_options())


@admin.get("/api/icd10/2019-2/policy-export")
@role_required("admin")
def admin_icd10_2019_2_policy_export():
    payload = export_icd10_2019_2_policy_json()
    return current_app.response_class(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="icd10_2019_2_policy_export.json"'
        },
    )


@admin.post("/api/icd10/2019-2/policy-import")
@role_required("admin")
def admin_icd10_2019_2_policy_import():
    uploaded = request.files.get("file")
    if uploaded is None:
        return _json_error("file is required.", 400)
    try:
        payload = uploaded.read().decode("utf-8")
    except UnicodeDecodeError:
        return _json_error("Policy import file must be UTF-8 JSON.", 400)

    try:
        result = import_icd10_2019_2_policy_json(payload)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    return jsonify(
        {
            "message": "ICD policy import completed.",
            "total_items": result.total_items,
            "updated_items": result.updated_items,
            "reset_items": result.reset_items,
            "skipped_items": result.skipped_items,
            "failed_codes": result.skipped_items,
        }
    )


@admin.patch("/api/icd10/2019-2/node/<code>/policy")
@role_required("admin")
def admin_icd10_2019_2_update_policy(code):
    body = request.get_json(silent=True) or {}
    try:
        payload = update_icd10_2019_2_policy(
            code=code.strip(),
            is_coding_selectable=body.get("is_coding_selectable"),
            sex_selectable=body.get("sex_selectable"),
            age_group_selectable=body.get("age_group_selectable"),
            restriction_note=body.get("restriction_note"),
        )
    except LookupError:
        return _json_error("ICD code not found.", 404)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    return jsonify(payload)
