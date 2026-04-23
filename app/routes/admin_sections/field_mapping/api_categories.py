from .common import (
    _json_error,
    _load_form_type,
    admin,
    db,
    jsonify,
    request,
    role_required,
    sa,
)


@admin.post("/api/form-types/<form_type_code>/categories")
@role_required("admin")
def admin_category_create(form_type_code):
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasCategoryOrder

    form_type = _load_form_type(form_type_code)
    if not form_type:
        return _json_error("Form type not found.", 404)

    data = request.get_json(silent=True) or {}
    code = (data.get("category_code") or "").strip()
    name = (data.get("category_name") or "").strip() or None
    order = data.get("display_order")
    render_mode = (data.get("render_mode") or "default").strip() or "default"

    if not code:
        return _json_error("category_code is required.", 400)

    existing = db.session.scalar(
        sa.select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == code,
        )
    )
    if existing:
        return _json_error("Category code already exists for this form type.", 409)

    if order is None:
        max_row = db.session.scalar(
            sa.select(sa.func.max(MasCategoryDisplayConfig.display_order)).where(
                MasCategoryDisplayConfig.form_type_id == form_type.form_type_id
            )
        )
        order = (max_row or 0) + 10

    cat = MasCategoryOrder(
        form_type_id=form_type.form_type_id,
        category_code=code,
        category_name=name,
        display_order=int(order),
    )
    db.session.add(cat)
    db.session.add(
        MasCategoryDisplayConfig(
            form_type_id=form_type.form_type_id,
            category_code=code,
            display_label=name or code,
            nav_label=name or code,
            display_order=int(order),
            render_mode=render_mode if render_mode != "default" else "table_sections",
        )
    )
    db.session.commit()
    return jsonify(
        {
            "category": {
                "category_code": cat.category_code,
                "category_name": cat.category_name,
                "display_order": cat.display_order,
            }
        }
    ), 201


@admin.put("/api/form-types/<form_type_code>/categories/<category_code>")
@role_required("admin")
def admin_category_update(form_type_code, category_code):
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasCategoryOrder

    form_type = _load_form_type(form_type_code)
    if not form_type:
        return _json_error("Form type not found.", 404)

    display_cfg = db.session.scalar(
        sa.select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == category_code,
        )
    )
    if not display_cfg:
        return _json_error("Category not found.", 404)

    cat = db.session.scalar(
        sa.select(MasCategoryOrder).where(
            MasCategoryOrder.form_type_id == form_type.form_type_id,
            MasCategoryOrder.category_code == category_code,
        )
    )

    data = request.get_json(silent=True) or {}
    old_name = display_cfg.display_label
    if "category_name" in data:
        new_name = (data["category_name"] or "").strip() or None
        if cat:
            cat.category_name = new_name
        new_label = new_name or category_code
        if not display_cfg.display_label or display_cfg.display_label in {
            old_name,
            category_code,
        }:
            display_cfg.display_label = new_label
        if not display_cfg.nav_label or display_cfg.nav_label in {
            old_name,
            category_code,
        }:
            display_cfg.nav_label = new_label
    if "display_order" in data:
        try:
            new_order = int(data["display_order"])
        except (TypeError, ValueError):
            return _json_error("display_order must be an integer.", 400)
        display_cfg.display_order = new_order
        if cat:
            cat.display_order = new_order

    db.session.commit()
    return jsonify(
        {
            "category": {
                "category_code": display_cfg.category_code,
                "category_name": display_cfg.display_label,
                "display_order": display_cfg.display_order,
            }
        }
    )


@admin.delete("/api/form-types/<form_type_code>/categories/<category_code>")
@role_required("admin")
def admin_category_delete(form_type_code, category_code):
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasCategoryOrder

    form_type = _load_form_type(form_type_code)
    if not form_type:
        return _json_error("Form type not found.", 404)

    display_cfg = db.session.scalar(
        sa.select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == category_code,
        )
    )
    if not display_cfg:
        return _json_error("Category not found.", 404)

    cat = db.session.scalar(
        sa.select(MasCategoryOrder).where(
            MasCategoryOrder.form_type_id == form_type.form_type_id,
            MasCategoryOrder.category_code == category_code,
        )
    )

    db.session.delete(display_cfg)
    if cat:
        db.session.delete(cat)
    db.session.commit()
    return jsonify({"deleted": True})


@admin.post("/api/form-types/<form_type_code>/categories/<category_code>/subcategories")
@role_required("admin")
def admin_subcategory_create(form_type_code, category_code):
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasSubcategoryOrder

    form_type = _load_form_type(form_type_code)
    if not form_type:
        return _json_error("Form type not found.", 404)

    cat = db.session.scalar(
        sa.select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == category_code,
            MasCategoryDisplayConfig.is_active == True,
        )
    )
    if not cat:
        return _json_error("Category not found.", 404)

    data = request.get_json(silent=True) or {}
    code = (data.get("subcategory_code") or "").strip()
    name = (data.get("subcategory_name") or "").strip() or None
    order = data.get("display_order")
    render_mode = (data.get("render_mode") or "default").strip() or "default"

    if not code:
        return _json_error("subcategory_code is required.", 400)

    existing = db.session.scalar(
        sa.select(MasSubcategoryOrder).where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.category_code == category_code,
            MasSubcategoryOrder.subcategory_code == code,
        )
    )
    if existing:
        return _json_error("Subcategory code already exists.", 409)

    if order is None:
        max_row = db.session.scalar(
            sa.select(sa.func.max(MasSubcategoryOrder.display_order)).where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_code,
            )
        )
        order = (max_row or 0) + 10

    sub = MasSubcategoryOrder(
        form_type_id=form_type.form_type_id,
        category_code=category_code,
        subcategory_code=code,
        subcategory_name=name,
        display_order=int(order),
        render_mode=render_mode,
    )
    db.session.add(sub)
    db.session.commit()
    return jsonify(
        {
            "subcategory": {
                "subcategory_code": sub.subcategory_code,
                "subcategory_name": sub.subcategory_name,
                "display_order": sub.display_order,
                "render_mode": sub.render_mode,
            }
        }
    ), 201


@admin.put(
    "/api/form-types/<form_type_code>/categories/"
    "<category_code>/subcategories/<subcategory_code>"
)
@role_required("admin")
def admin_subcategory_update(form_type_code, category_code, subcategory_code):
    from app.models.va_field_mapping import MasSubcategoryOrder

    form_type = _load_form_type(form_type_code)
    if not form_type:
        return _json_error("Form type not found.", 404)

    sub = db.session.scalar(
        sa.select(MasSubcategoryOrder).where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.category_code == category_code,
            MasSubcategoryOrder.subcategory_code == subcategory_code,
        )
    )
    if not sub:
        return _json_error("Subcategory not found.", 404)

    data = request.get_json(silent=True) or {}
    if "subcategory_name" in data:
        sub.subcategory_name = (data["subcategory_name"] or "").strip() or None
    if "display_order" in data:
        try:
            sub.display_order = int(data["display_order"])
        except (TypeError, ValueError):
            return _json_error("display_order must be an integer.", 400)
    if "render_mode" in data:
        sub.render_mode = (data["render_mode"] or "default").strip() or "default"

    db.session.commit()
    return jsonify(
        {
            "subcategory": {
                "subcategory_code": sub.subcategory_code,
                "subcategory_name": sub.subcategory_name,
                "display_order": sub.display_order,
                "render_mode": sub.render_mode,
            }
        }
    )


@admin.delete(
    "/api/form-types/<form_type_code>/categories/"
    "<category_code>/subcategories/<subcategory_code>"
)
@role_required("admin")
def admin_subcategory_delete(form_type_code, category_code, subcategory_code):
    from app.models.va_field_mapping import MasSubcategoryOrder

    form_type = _load_form_type(form_type_code)
    if not form_type:
        return _json_error("Form type not found.", 404)

    sub = db.session.scalar(
        sa.select(MasSubcategoryOrder).where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.category_code == category_code,
            MasSubcategoryOrder.subcategory_code == subcategory_code,
        )
    )
    if not sub:
        return _json_error("Subcategory not found.", 404)

    db.session.delete(sub)
    db.session.commit()
    return jsonify({"deleted": True})
