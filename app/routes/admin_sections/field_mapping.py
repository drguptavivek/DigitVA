import json
import uuid
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from flask import Response, jsonify, render_template, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import MasOdkConnections
from app.routes.admin import admin
from app.routes.admin_support.field_mapping import (
    get_ordered_category_configs_for_form_type as _get_ordered_category_configs_for_form_type,
    ordered_field_lists_for_form_type as _ordered_field_lists_for_form_type,
    serialize_category_browser_state as _serialize_category_browser_state,
)
from app.routes.admin_support.http import json_error as _json_error
from app.routes.admin_support.odk import (
    get_odk_client_for_connection as _get_odk_client_for_connection,
)


@admin.get("/api/form-types/<form_type_code>/categories/<category_code>/subcategories")
@role_required("admin")
def admin_form_type_subcategories(form_type_code, category_code):
    """Return subcategories for a given form type + category."""
    from sqlalchemy import select as sa_select

    from app.models import MasFormTypes

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
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
    from sqlalchemy import select as sa_select

    from app.models import MasFormTypes

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
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
    from sqlalchemy import select as sa_select

    from app.models import MasFieldDisplayConfig, MasFormTypes

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    data = request.get_json(silent=True) or {}
    field_ids = data.get("field_ids") or []
    if not isinstance(field_ids, list) or not field_ids:
        return _json_error("field_ids must be a non-empty list.", 400)

    fields = db.session.scalars(
        sa_select(MasFieldDisplayConfig).where(
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

    from app.services.field_mapping_service import get_mapping_service

    get_mapping_service().clear_cache()

    state = _serialize_category_browser_state(form_type, category_code)
    return jsonify(state)


@admin.post("/api/form-types/<form_type_code>/fields/<field_id>/move")
@role_required("admin")
def admin_field_move_to_subcategory(form_type_code, field_id):
    """Move a field to a category/subcategory and append it to that target bucket."""
    from sqlalchemy import select as sa_select

    from app.models import MasFieldDisplayConfig, MasFormTypes
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    field = db.session.scalar(
        sa_select(MasFieldDisplayConfig).where(
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
        sa_select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == category_code,
            MasCategoryDisplayConfig.is_active == True,
        )
    )
    if not category:
        return _json_error("Category not found.", 404)

    if subcategory_code:
        subcategory = db.session.scalar(
            sa_select(MasSubcategoryOrder).where(
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

    from app.services.field_mapping_service import get_mapping_service

    get_mapping_service().clear_cache()

    state = _serialize_category_browser_state(form_type, category_code)
    return jsonify(state)


@admin.get("/api/form-types/<form_type_code>/fields/search")
@role_required("admin")
def admin_form_type_fields_search(form_type_code):
    """Search available fields for assignment into the category browser."""
    from sqlalchemy import select as sa_select

    from app.models import MasFieldDisplayConfig, MasFormTypes

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    search = request.args.get("q", "").strip()
    if len(search) < 2:
        return jsonify({"fields": []})

    fields = db.session.scalars(
        sa_select(MasFieldDisplayConfig)
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


@admin.post("/api/form-types/<form_type_code>/categories")
@role_required("admin")
def admin_category_create(form_type_code):
    from sqlalchemy import select as sa_select

    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasCategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
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
        sa_select(MasCategoryDisplayConfig).where(
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
    from sqlalchemy import select as sa_select

    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasCategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    display_cfg = db.session.scalar(
        sa_select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == category_code,
        )
    )
    if not display_cfg:
        return _json_error("Category not found.", 404)

    cat = db.session.scalar(
        sa_select(MasCategoryOrder).where(
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
    from sqlalchemy import select as sa_select

    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasCategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    display_cfg = db.session.scalar(
        sa_select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == category_code,
        )
    )
    if not display_cfg:
        return _json_error("Category not found.", 404)

    cat = db.session.scalar(
        sa_select(MasCategoryOrder).where(
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
    from sqlalchemy import select as sa_select

    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    cat = db.session.scalar(
        sa_select(MasCategoryDisplayConfig).where(
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
        sa_select(MasSubcategoryOrder).where(
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
    from sqlalchemy import select as sa_select

    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    sub = db.session.scalar(
        sa_select(MasSubcategoryOrder).where(
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
    from sqlalchemy import select as sa_select

    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    sub = db.session.scalar(
        sa_select(MasSubcategoryOrder).where(
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


@admin.get("/api/form-types")
@role_required("admin")
def admin_form_types_list():
    """Return all active form types (code + name)."""
    from app.services.form_type_service import get_form_type_service

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

    from app.services.form_type_service import get_form_type_service

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

    from app.models import MasFormTypes

    form_type = db.session.scalar(
        sa.select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
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

    from app.services.form_type_service import get_form_type_service

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
    from app.services.form_type_service import get_form_type_service

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

    from app.services.form_type_service import get_form_type_service

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


@admin.get("/panels/field-mapping")
@role_required("admin")
def admin_panel_field_mapping():
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from app.services.form_type_service import get_form_type_service

    service = get_form_type_service()
    form_types = service.list_form_types()
    stats = [service.get_form_type_stats(form_type.form_type_code) for form_type in form_types]
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

    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import aliased

    from app.models import MasFieldDisplayConfig, MasFormTypes
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

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    categories = _get_ordered_category_configs_for_form_type(form_type.form_type_id)

    subcategories_for_filter = []
    if category_filter:
        subcategories_for_filter = db.session.scalars(
            sa_select(MasSubcategoryOrder)
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
        sa_select(MasSubcategoryOrder)
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
        sa_select(MasFieldDisplayConfig)
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
                subcategory_order.subcategory_code == MasFieldDisplayConfig.subcategory_code,
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
    from sqlalchemy import select as sa_select

    from app.models import MasFieldDisplayConfig, MasFormTypes
    from app.models.va_field_mapping import MasChoiceMappings, MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    field = db.session.scalar(
        sa_select(MasFieldDisplayConfig).where(
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
            sa_select(MasSubcategoryOrder)
            .where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == field.category_code,
            )
            .order_by(MasSubcategoryOrder.display_order)
        ).all()

    choices = db.session.scalars(
        sa_select(MasChoiceMappings)
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

        from app.services.field_mapping_service import get_mapping_service

        get_mapping_service().clear_cache()

        all_subcategories_for_row = db.session.scalars(
            sa_select(MasSubcategoryOrder).where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id
            )
        ).all()
        cat_name_map = {
            category.category_code: category.display_label or category.category_code
            for category in categories
        }
        subcat_name_map = {
            (subcategory.category_code, subcategory.subcategory_code): (
                subcategory.subcategory_name or subcategory.subcategory_code
            )
            for subcategory in all_subcategories_for_row
        }
        subcategories_by_category = {}
        for subcategory in all_subcategories_for_row:
            subcategories_by_category.setdefault(subcategory.category_code, []).append(
                subcategory
            )
        return render_template(
            "admin/panels/field_mapping_field_row.html",
            form_type_code=form_type_code,
            field=field,
            categories=categories,
            cat_name_map=cat_name_map,
            subcat_name_map=subcat_name_map,
            subcats_by_cat=subcategories_by_category,
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

    from sqlalchemy import select as sa_select

    from app.models import MasFieldDisplayConfig, MasFormTypes
    from app.models.va_field_mapping import MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    field = db.session.scalar(
        sa_select(MasFieldDisplayConfig).where(
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

    from app.services.field_mapping_service import get_mapping_service

    get_mapping_service().clear_cache()

    categories = _get_ordered_category_configs_for_form_type(form_type.form_type_id)
    all_subcategories = db.session.scalars(
        sa_select(MasSubcategoryOrder).where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id
        )
    ).all()
    cat_name_map = {
        category.category_code: category.display_label or category.category_code
        for category in categories
    }
    subcat_name_map = {
        (subcategory.category_code, subcategory.subcategory_code): (
            subcategory.subcategory_name or subcategory.subcategory_code
        )
        for subcategory in all_subcategories
    }
    subcategories_by_category = {}
    for subcategory in all_subcategories:
        subcategories_by_category.setdefault(subcategory.category_code, []).append(
            subcategory
        )

    return render_template(
        "admin/panels/field_mapping_field_row.html",
        form_type_code=form_type_code,
        field=field,
        categories=categories,
        cat_name_map=cat_name_map,
        subcat_name_map=subcat_name_map,
        subcats_by_cat=subcategories_by_category,
    )


@admin.patch("/panels/field-mapping/field/<form_type_code>/<field_id>/order")
@role_required("admin")
def admin_panel_field_mapping_field_quick_order(form_type_code, field_id):
    """Quick inline update of field display_order. Returns updated table row HTML."""
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from sqlalchemy import select as sa_select

    from app.models import MasFieldDisplayConfig, MasFormTypes
    from app.models.va_field_mapping import MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    field = db.session.scalar(
        sa_select(MasFieldDisplayConfig).where(
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

    from app.services.field_mapping_service import get_mapping_service

    get_mapping_service().clear_cache()

    categories = _get_ordered_category_configs_for_form_type(form_type.form_type_id)
    all_subcategories = db.session.scalars(
        sa_select(MasSubcategoryOrder).where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id
        )
    ).all()
    cat_name_map = {
        category.category_code: category.display_label or category.category_code
        for category in categories
    }
    subcat_name_map = {
        (subcategory.category_code, subcategory.subcategory_code): (
            subcategory.subcategory_name or subcategory.subcategory_code
        )
        for subcategory in all_subcategories
    }
    subcategories_by_category = {}
    for subcategory in all_subcategories:
        subcategories_by_category.setdefault(subcategory.category_code, []).append(
            subcategory
        )

    return render_template(
        "admin/panels/field_mapping_field_row.html",
        form_type_code=form_type_code,
        field=field,
        categories=categories,
        cat_name_map=cat_name_map,
        subcat_name_map=subcat_name_map,
        subcats_by_cat=subcategories_by_category,
    )


@admin.get("/panels/field-mapping/categories")
@role_required("admin")
def admin_panel_field_mapping_categories():
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from sqlalchemy import select as sa_select

    from app.models import MasFormTypes

    form_type_code = request.args.get("form_type", "").strip()
    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
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

    from sqlalchemy import select as sa_select

    from app.models import MasFieldDisplayConfig, MasFormTypes
    from app.models.va_field_mapping import MasChoiceMappings

    form_type_code = request.args.get("form_type", "WHO_2022_VA")
    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    rows = db.session.execute(
        sa_select(
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
