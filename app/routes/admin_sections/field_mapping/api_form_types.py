from .common import (
    Decimal,
    Response,
    _json_error,
    _load_form_type,
    admin,
    current_user,
    db,
    jsonify,
    json,
    request,
    role_required,
)


@admin.get("/api/form-types")
@role_required("admin")
def admin_form_types_list():
    """Return all active form types (code + name)."""
    from app.services.forms.form_type import get_form_type_service

    service = get_form_type_service()
    return jsonify(
        {
            "form_types": [
                {
                    "form_type_id": str(form_type.form_type_id),
                    "form_type_code": form_type.form_type_code,
                    "form_type_name": form_type.form_type_name,
                }
                for form_type in service.list_form_types()
            ]
        }
    )


@admin.post("/api/form-types")
@role_required("admin")
def admin_form_types_create():
    """Create a new blank form type."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.forms.form_type import get_form_type_service

    data = request.get_json(silent=True) or {}
    code = (data.get("form_type_code") or "").strip().upper()
    name = (data.get("form_type_name") or "").strip()
    description = (data.get("description") or "").strip() or None

    if not code or not name:
        return _json_error("form_type_code and form_type_name are required.", 400)

    try:
        form_type = get_form_type_service().register_form_type(code, name, description)
    except ValueError as exc:
        return _json_error(str(exc), 409)

    return jsonify(
        {
            "form_type_code": form_type.form_type_code,
            "form_type_name": form_type.form_type_name,
        }
    ), 201


@admin.patch("/api/form-types/<form_type_code>")
@role_required("admin")
def admin_form_types_update(form_type_code):
    """Update a form type's name and description."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    form_type = _load_form_type(form_type_code)
    if not form_type:
        return _json_error("Form type not found.", 404)

    data = request.get_json(silent=True) or {}
    name = (data.get("form_type_name") or "").strip()
    description = (data.get("description") or "").strip() or None

    if not name:
        return _json_error("form_type_name is required.", 400)

    form_type.form_type_name = name
    form_type.form_type_description = description
    db.session.commit()
    return jsonify(
        {
            "form_type_code": form_type.form_type_code,
            "form_type_name": form_type.form_type_name,
        }
    )


@admin.post("/api/form-types/<source_code>/duplicate")
@role_required("admin")
def admin_form_types_duplicate(source_code):
    """Duplicate a form type, copying fields, categories, and choices."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.forms.form_type import get_form_type_service

    data = request.get_json(silent=True) or {}
    new_code = (data.get("new_code") or "").strip().upper()
    new_name = (data.get("new_name") or "").strip()
    description = (data.get("description") or "").strip() or None

    if not new_code or not new_name:
        return _json_error("new_code and new_name are required.", 400)

    try:
        form_type = get_form_type_service().duplicate_form_type(
            source_code.upper(), new_code, new_name, description
        )
    except ValueError as exc:
        return _json_error(str(exc), 409)

    return jsonify(
        {
            "form_type_code": form_type.form_type_code,
            "form_type_name": form_type.form_type_name,
        }
    ), 201


@admin.get("/api/form-types/<form_type_code>/export")
@role_required("admin")
def admin_form_types_export(form_type_code):
    """Download a form type configuration as a JSON file."""
    from app.services.forms.form_type import get_form_type_service

    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    try:
        data = get_form_type_service().export_form_type(form_type_code.upper())
    except ValueError as exc:
        return _json_error(str(exc), 404)

    class _Encoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Decimal):
                if obj == obj.to_integral_value():
                    return int(obj)
                return float(obj)
            return super().default(obj)

    filename = f"form_type_{form_type_code.lower()}.json"
    return Response(
        json.dumps(data, indent=2, ensure_ascii=False, cls=_Encoder),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@admin.post("/api/form-types/import")
@role_required("admin")
def admin_form_types_import():
    """Import a form type from an uploaded JSON file."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    uploaded = request.files.get("file")
    if not uploaded:
        return _json_error("No file uploaded.", 400)

    try:
        raw = uploaded.read()
        if len(raw) > 10 * 1024 * 1024:
            return _json_error("File too large (max 10 MB).", 400)
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return _json_error("Invalid JSON file.", 400)

    override_code = (request.form.get("override_code") or "").strip().upper() or None
    override_name = (request.form.get("override_name") or "").strip() or None
    override_description = request.form.get("override_description")
    if override_description is not None:
        override_description = override_description.strip() or None

    from app.services.forms.form_type import get_form_type_service

    try:
        form_type, stats = get_form_type_service().import_form_type(
            data,
            override_code=override_code,
            override_name=override_name,
            override_description=override_description,
        )
    except ValueError as exc:
        return _json_error(str(exc), 409)

    return jsonify(
        {
            "form_type_code": form_type.form_type_code,
            "form_type_name": form_type.form_type_name,
            **stats,
        }
    ), 201
