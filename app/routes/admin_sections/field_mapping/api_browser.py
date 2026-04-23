from .common import (
    Decimal,
    _clear_mapping_cache,
    _json_error,
    _load_form_type,
    _serialize_category_browser_state,
    admin,
    db,
    jsonify,
    request,
    role_required,
    sa,
)


@admin.get("/api/form-types/<form_type_code>/categories/<category_code>/subcategories")
@role_required("admin")
def admin_form_type_subcategories(form_type_code, category_code):
    """Return subcategories for a given form type + category."""
    form_type = _load_form_type(form_type_code)
    if not form_type:
        return _json_error("Form type not found.", 404)

    state = _serialize_category_browser_state(form_type, category_code)
    if not state:
        return _json_error("Category not found.", 404)
    return jsonify({"subcategories": state["subcategories"]})


@admin.get("/api/form-types/<form_type_code>/categories/<category_code>/browser-state")
@role_required("admin")
def admin_form_type_category_browser_state(form_type_code, category_code):
    """Return full browser state for one category in the 3-panel UI."""
    form_type = _load_form_type(form_type_code)
    if not form_type:
        return _json_error("Form type not found.", 404)

    state = _serialize_category_browser_state(form_type, category_code)
    if not state:
        return _json_error("Category not found.", 404)
    return jsonify(state)


@admin.post("/api/form-types/<form_type_code>/categories/<category_code>/fields/reorder")
@role_required("admin")
def admin_category_fields_reorder(form_type_code, category_code):
    """Persist ordered field_ids for a category browser selection."""
    from app.models import MasFieldDisplayConfig

    form_type = _load_form_type(form_type_code)
    if not form_type:
        return _json_error("Form type not found.", 404)

    data = request.get_json(silent=True) or {}
    field_ids = data.get("field_ids") or []
    if not isinstance(field_ids, list) or not field_ids:
        return _json_error("field_ids must be a non-empty list.", 400)

    fields = db.session.scalars(
        sa.select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id.in_(field_ids),
        )
    ).all()
    field_by_id = {field.field_id: field for field in fields}
    if len(field_by_id) != len(set(field_ids)):
        return _json_error("One or more field_ids were not found.", 404)

    for index, field_id in enumerate(field_ids, start=1):
        field = field_by_id[field_id]
        if field.category_code != category_code:
            return _json_error(
                "All field_ids must belong to the selected category.", 400
            )
        field.display_order = Decimal(index * 10)

    db.session.commit()
    _clear_mapping_cache()

    state = _serialize_category_browser_state(form_type, category_code)
    return jsonify(state)


@admin.post("/api/form-types/<form_type_code>/fields/<field_id>/move")
@role_required("admin")
def admin_field_move_to_subcategory(form_type_code, field_id):
    """Move a field to a category/subcategory and append it to that target bucket."""
    from app.models import MasFieldDisplayConfig
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasSubcategoryOrder

    form_type = _load_form_type(form_type_code)
    if not form_type:
        return _json_error("Form type not found.", 404)

    field = db.session.scalar(
        sa.select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id == field_id,
        )
    )
    if not field:
        return _json_error("Field not found.", 404)

    data = request.get_json(silent=True) or {}
    category_code = (data.get("category_code") or "").strip()
    subcategory_code = data.get("subcategory_code")
    if isinstance(subcategory_code, str):
        subcategory_code = subcategory_code.strip() or None

    if not category_code:
        return _json_error("category_code is required.", 400)

    category = db.session.scalar(
        sa.select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == category_code,
            MasCategoryDisplayConfig.is_active == True,
        )
    )
    if not category:
        return _json_error("Category not found.", 404)

    if subcategory_code:
        subcategory = db.session.scalar(
            sa.select(MasSubcategoryOrder).where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_code,
                MasSubcategoryOrder.subcategory_code == subcategory_code,
            )
        )
        if not subcategory:
            return _json_error("Subcategory not found.", 404)

    max_order = db.session.scalar(
        sa.select(sa.func.max(MasFieldDisplayConfig.display_order)).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.category_code == category_code,
            MasFieldDisplayConfig.subcategory_code == subcategory_code,
        )
    )

    field.category_code = category_code
    field.subcategory_code = subcategory_code
    field.display_order = Decimal(max_order or 0) + Decimal("10")
    db.session.commit()
    _clear_mapping_cache()

    state = _serialize_category_browser_state(form_type, category_code)
    return jsonify(state)


@admin.get("/api/form-types/<form_type_code>/fields/search")
@role_required("admin")
def admin_form_type_fields_search(form_type_code):
    """Search available fields for assignment into the category browser."""
    from app.models import MasFieldDisplayConfig

    form_type = _load_form_type(form_type_code)
    if not form_type:
        return _json_error("Form type not found.", 404)

    search = request.args.get("q", "").strip()
    if len(search) < 2:
        return jsonify({"fields": []})

    fields = db.session.scalars(
        sa.select(MasFieldDisplayConfig)
        .where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.is_active == True,
            sa.or_(
                MasFieldDisplayConfig.field_id.ilike(f"%{search}%"),
                MasFieldDisplayConfig.short_label.ilike(f"%{search}%"),
            ),
        )
        .order_by(MasFieldDisplayConfig.field_id)
        .limit(25)
    ).all()

    return jsonify(
        {
            "fields": [
                {
                    "field_id": field.field_id,
                    "label": field.short_label or field.field_id,
                    "category_code": field.category_code,
                    "subcategory_code": field.subcategory_code,
                }
                for field in fields
            ]
        }
    )
