from .common import (
    Decimal,
    InvalidOperation,
    _build_field_row_context,
    _clear_mapping_cache,
    _get_odk_client_for_connection,
    _get_ordered_category_configs_for_form_type,
    _json_error,
    _load_form_type,
    _ordered_field_lists_for_form_type,
    MasOdkConnections,
    admin,
    current_user,
    db,
    jsonify,
    render_template,
    request,
    role_required,
    sa,
    uuid,
)


@admin.get("/panels/field-mapping")
@role_required("admin")
def admin_panel_field_mapping():
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from app.services.form_type_service import get_form_type_service

    service = get_form_type_service()
    form_types = service.list_form_types()
    stats = [
        service.get_form_type_stats(form_type.form_type_code) for form_type in form_types
    ]
    return render_template(
        "admin/panels/field_mapping.html",
        form_types=form_types,
        stats=stats,
    )


@admin.get("/panels/field-mapping/fields")
@role_required("admin")
def admin_panel_field_mapping_fields():
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from sqlalchemy.orm import aliased

    from app.models import MasFieldDisplayConfig
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasSubcategoryOrder

    form_type_code = request.args.get("form_type", "WHO_2022_VA")
    category_filter = request.args.get("category", "")
    subcategory_filter = request.args.get("subcategory", "")
    search = request.args.get("search", "").strip()
    flag_filters = set(request.args.getlist("flag")) & {
        "flip",
        "info",
        "summary",
        "pii",
    }
    no_category = request.args.get("no_category", "") == "1"

    form_type = _load_form_type(form_type_code)
    if not form_type:
        return "Form type not found", 404

    categories = _get_ordered_category_configs_for_form_type(form_type.form_type_id)

    subcategories_for_filter = []
    if category_filter:
        subcategories_for_filter = db.session.scalars(
            sa.select(MasSubcategoryOrder)
            .where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_filter,
                MasSubcategoryOrder.is_active == True,
            )
            .order_by(MasSubcategoryOrder.display_order)
        ).all()

    cat_name_map = {
        category.category_code: category.display_label or category.category_code
        for category in categories
    }
    all_subcategories = db.session.scalars(
        sa.select(MasSubcategoryOrder)
        .where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.is_active == True,
        )
    ).all()
    subcat_name_map = {
        (subcategory.category_code, subcategory.subcategory_code): (
            subcategory.subcategory_name or subcategory.subcategory_code
        )
        for subcategory in all_subcategories
    }

    category_order = aliased(MasCategoryDisplayConfig)
    subcategory_order = aliased(MasSubcategoryOrder)
    query = (
        sa.select(MasFieldDisplayConfig)
        .outerjoin(
            category_order,
            sa.and_(
                category_order.form_type_id == MasFieldDisplayConfig.form_type_id,
                category_order.category_code == MasFieldDisplayConfig.category_code,
                category_order.is_active == True,
            ),
        )
        .outerjoin(
            subcategory_order,
            sa.and_(
                subcategory_order.form_type_id == MasFieldDisplayConfig.form_type_id,
                subcategory_order.category_code == MasFieldDisplayConfig.category_code,
                subcategory_order.subcategory_code
                == MasFieldDisplayConfig.subcategory_code,
                subcategory_order.is_active == True,
            ),
        )
        .where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.is_active == True,
        )
        .order_by(
            category_order.display_order.is_(None),
            category_order.display_order,
            MasFieldDisplayConfig.category_code,
            subcategory_order.display_order.is_(None),
            subcategory_order.display_order,
            MasFieldDisplayConfig.subcategory_code,
            MasFieldDisplayConfig.display_order,
            MasFieldDisplayConfig.field_id,
        )
    )
    if no_category:
        query = query.where(MasFieldDisplayConfig.category_code == None)
    elif category_filter:
        query = query.where(MasFieldDisplayConfig.category_code == category_filter)
    if subcategory_filter:
        query = query.where(MasFieldDisplayConfig.subcategory_code == subcategory_filter)

    flag_predicates = {
        "flip": MasFieldDisplayConfig.flip_color == True,
        "info": MasFieldDisplayConfig.is_info == True,
        "summary": MasFieldDisplayConfig.summary_include == True,
        "pii": MasFieldDisplayConfig.is_pii == True,
    }
    for flag_filter in flag_filters:
        query = query.where(flag_predicates[flag_filter])
    if search:
        query = query.where(
            sa.or_(
                MasFieldDisplayConfig.field_id.ilike(f"%{search}%"),
                MasFieldDisplayConfig.short_label.ilike(f"%{search}%"),
            )
        )

    fields = db.session.scalars(query).all()
    subcategories_by_category = {}
    for subcategory in all_subcategories:
        subcategories_by_category.setdefault(subcategory.category_code, []).append(
            subcategory
        )

    return render_template(
        "admin/panels/field_mapping_fields.html",
        form_type_code=form_type_code,
        fields=fields,
        category_filter=category_filter,
        subcategory_filter=subcategory_filter,
        search=search,
        flag_filters=flag_filters,
        no_category=no_category,
        categories=categories,
        subcategories_for_filter=subcategories_for_filter,
        cat_name_map=cat_name_map,
        subcat_name_map=subcat_name_map,
        subcats_by_cat=subcategories_by_category,
    )


@admin.route("/panels/field-mapping/field/<form_type_code>/<field_id>", methods=["GET", "POST"])
@role_required("admin")
def admin_panel_field_mapping_field_edit(form_type_code, field_id):
    from app.models import MasFieldDisplayConfig
    from app.models.va_field_mapping import MasChoiceMappings, MasSubcategoryOrder

    form_type = _load_form_type(form_type_code)
    if not form_type:
        return "Form type not found", 404

    field = db.session.scalar(
        sa.select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id == field_id,
        )
    )
    if not field:
        return "Field not found", 404

    origin = (request.args.get("origin") or request.form.get("origin") or "").strip()
    categories = _get_ordered_category_configs_for_form_type(form_type.form_type_id)

    subcategories = []
    if field.category_code:
        subcategories = db.session.scalars(
            sa.select(MasSubcategoryOrder)
            .where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == field.category_code,
            )
            .order_by(MasSubcategoryOrder.display_order)
        ).all()

    choices = db.session.scalars(
        sa.select(MasChoiceMappings)
        .where(
            MasChoiceMappings.form_type_id == form_type.form_type_id,
            MasChoiceMappings.field_id == field.field_id,
            MasChoiceMappings.is_active == True,
        )
        .order_by(MasChoiceMappings.display_order, MasChoiceMappings.choice_label)
    ).all()

    if request.method == "POST":
        field.short_label = request.form.get("short_label") or field.short_label
        field.full_label = request.form.get("full_label") or None
        field.category_code = request.form.get("category_code") or None
        field.subcategory_code = request.form.get("subcategory_code") or None
        raw_order = (request.form.get("display_order") or "").strip()
        if raw_order:
            try:
                field.display_order = Decimal(raw_order)
            except InvalidOperation:
                return "display_order must be a number.", 400
        field.flip_color = request.form.get("flip_color") == "on"
        field.is_info = request.form.get("is_info") == "on"
        field.summary_include = request.form.get("summary_include") == "on"
        field.is_pii = request.form.get("is_pii") == "on"
        field.pii_type = request.form.get("pii_type") or None
        for choice in choices:
            label_key = f"choice_label__{choice.choice_id}"
            raw_label = request.form.get(label_key)
            if raw_label is not None:
                choice.choice_label = raw_label.strip()
        db.session.commit()
        _clear_mapping_cache()

        return render_template(
            "admin/panels/field_mapping_field_row.html",
            **_build_field_row_context(
                form_type_code,
                form_type.form_type_id,
                field,
            ),
        )

    return render_template(
        "admin/panels/field_mapping_field_edit.html",
        form_type_code=form_type_code,
        field=field,
        categories=categories,
        subcategories=subcategories,
        choices=choices,
        origin=origin,
    )


@admin.patch("/panels/field-mapping/field/<form_type_code>/<field_id>/category")
@role_required("admin")
def admin_panel_field_mapping_field_quick_category(form_type_code, field_id):
    """Quick inline update of category/subcategory only. Returns updated table row HTML."""
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from app.models import MasFieldDisplayConfig

    form_type = _load_form_type(form_type_code)
    if not form_type:
        return "Form type not found", 404

    field = db.session.scalar(
        sa.select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id == field_id,
        )
    )
    if not field:
        return "Field not found", 404

    new_category = request.form.get("category_code") or None
    new_subcategory = request.form.get("subcategory_code") or None
    if new_category != field.category_code:
        new_subcategory = None

    field.category_code = new_category
    field.subcategory_code = new_subcategory
    db.session.commit()
    _clear_mapping_cache()

    return render_template(
        "admin/panels/field_mapping_field_row.html",
        **_build_field_row_context(
            form_type_code,
            form_type.form_type_id,
            field,
        ),
    )


@admin.patch("/panels/field-mapping/field/<form_type_code>/<field_id>/order")
@role_required("admin")
def admin_panel_field_mapping_field_quick_order(form_type_code, field_id):
    """Quick inline update of field display_order. Returns updated table row HTML."""
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from app.models import MasFieldDisplayConfig

    form_type = _load_form_type(form_type_code)
    if not form_type:
        return "Form type not found", 404

    field = db.session.scalar(
        sa.select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id == field_id,
        )
    )
    if not field:
        return "Field not found", 404

    raw_order = (request.form.get("display_order") or "").strip()
    try:
        field.display_order = Decimal(raw_order)
    except InvalidOperation:
        return "display_order must be a number.", 400

    db.session.commit()
    _clear_mapping_cache()

    return render_template(
        "admin/panels/field_mapping_field_row.html",
        **_build_field_row_context(
            form_type_code,
            form_type.form_type_id,
            field,
        ),
    )


@admin.get("/panels/field-mapping/categories")
@role_required("admin")
def admin_panel_field_mapping_categories():
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    form_type_code = request.args.get("form_type", "").strip()
    form_type = _load_form_type(form_type_code)
    if not form_type:
        return "Form type not found", 404

    fields_by_category, _ = _ordered_field_lists_for_form_type(form_type.form_type_id)
    categories = _get_ordered_category_configs_for_form_type(form_type.form_type_id)
    categories_json = [
        {
            "category_code": category.category_code,
            "category_name": category.display_label,
            "display_order": category.display_order,
            "ordered_fields": fields_by_category.get(category.category_code, []),
        }
        for category in categories
    ]

    return render_template(
        "admin/panels/field_mapping_categories.html",
        form_type_code=form_type_code,
        form_type_name=form_type.form_type_name,
        categories_json=categories_json,
    )


@admin.get("/panels/field-mapping/choices")
@role_required("admin")
def admin_panel_field_mapping_choices():
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from app.models import MasFieldDisplayConfig
    from app.models.va_field_mapping import MasChoiceMappings

    form_type_code = request.args.get("form_type", "WHO_2022_VA")
    form_type = _load_form_type(form_type_code)
    if not form_type:
        return "Form type not found", 404

    rows = db.session.execute(
        sa.select(
            MasChoiceMappings.field_id,
            MasChoiceMappings.choice_value,
            MasChoiceMappings.choice_label,
            MasChoiceMappings.display_order,
            MasFieldDisplayConfig.short_label,
            MasFieldDisplayConfig.field_type,
        )
        .outerjoin(
            MasFieldDisplayConfig,
            sa.and_(
                MasFieldDisplayConfig.form_type_id == MasChoiceMappings.form_type_id,
                MasFieldDisplayConfig.field_id == MasChoiceMappings.field_id,
            ),
        )
        .where(
            MasChoiceMappings.form_type_id == form_type.form_type_id,
            MasChoiceMappings.is_active == True,
        )
        .order_by(
            MasChoiceMappings.field_id,
            MasChoiceMappings.display_order,
            MasChoiceMappings.choice_value,
        )
    ).all()

    return render_template(
        "admin/panels/field_mapping_choices.html",
        form_type_code=form_type_code,
        form_type_name=form_type.form_type_name,
        rows=rows,
    )


@admin.get("/panels/field-mapping/sync")
@role_required("admin")
def admin_panel_field_mapping_sync():
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    form_type_code = request.args.get("form_type", "WHO_2022_VA")
    return render_template(
        "admin/panels/field_mapping_sync.html",
        form_type_code=form_type_code,
    )


@admin.post("/panels/field-mapping/sync/preview")
@role_required("admin")
def admin_panel_field_mapping_sync_preview():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.odk_schema_sync_service import get_sync_service

    data = request.get_json(force=True)
    form_type_code = data.get("form_type_code")
    odk_project_id = data.get("odk_project_id")
    odk_form_id = data.get("odk_form_id")
    connection_id_str = data.get("connection_id")

    if not all([form_type_code, odk_project_id, odk_form_id, connection_id_str]):
        return _json_error("Missing required fields.", 400)

    try:
        conn_uuid = uuid.UUID(connection_id_str)
    except (ValueError, AttributeError):
        return _json_error("Invalid connection_id.", 400)

    connection = db.session.get(MasOdkConnections, conn_uuid)
    if not connection:
        return _json_error("ODK connection not found.", 404)
    if connection.status.value != "active":
        return _json_error(
            f"ODK connection '{connection.connection_name}' is not active.", 400
        )

    client = _get_odk_client_for_connection(connection)
    result = get_sync_service().preview_sync(
        form_type_code,
        int(odk_project_id),
        odk_form_id,
        client=client,
    )
    return jsonify(result)


@admin.post("/panels/field-mapping/sync/apply")
@role_required("admin")
def admin_panel_field_mapping_sync_apply():
    """Apply a user-selected subset of previewed sync changes."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.odk_schema_sync_service import get_sync_service

    data = request.get_json(force=True)
    form_type_code = data.get("form_type_code")
    selected = data.get("selected") or {}

    if not form_type_code:
        return _json_error("form_type_code is required.", 400)

    stats = get_sync_service().sync_selected(form_type_code, selected)
    return jsonify(stats)


@admin.post("/panels/field-mapping/sync")
@role_required("admin")
def admin_panel_field_mapping_sync_run():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.odk_schema_sync_service import get_sync_service

    data = request.get_json(force=True)
    form_type_code = data.get("form_type_code")
    odk_project_id = data.get("odk_project_id")
    odk_form_id = data.get("odk_form_id")
    connection_id_str = data.get("connection_id")

    if not all([form_type_code, odk_project_id, odk_form_id, connection_id_str]):
        return _json_error(
            "Missing form_type_code, connection_id, odk_project_id, or odk_form_id.",
            400,
        )

    try:
        conn_uuid = uuid.UUID(connection_id_str)
    except (ValueError, AttributeError):
        return _json_error("Invalid connection_id.", 400)

    connection = db.session.get(MasOdkConnections, conn_uuid)
    if not connection:
        return _json_error("ODK connection not found.", 404)
    if connection.status.value != "active":
        return _json_error(
            f"ODK connection '{connection.connection_name}' is not active.", 400
        )

    client = _get_odk_client_for_connection(connection)
    stats = get_sync_service().sync_form_choices(
        form_type_code,
        int(odk_project_id),
        odk_form_id,
        client=client,
    )
    return jsonify(stats)
