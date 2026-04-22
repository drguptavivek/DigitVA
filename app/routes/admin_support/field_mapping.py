from decimal import Decimal

from app import db


def ordered_field_lists_for_form_type(form_type_id):
    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import aliased

    from app.models import MasFieldDisplayConfig
    from app.models.va_field_mapping import MasSubcategoryOrder

    subcat_order = aliased(MasSubcategoryOrder)
    rows = db.session.execute(
        sa_select(
            MasFieldDisplayConfig.category_code,
            MasFieldDisplayConfig.subcategory_code,
            MasFieldDisplayConfig.field_id,
            MasFieldDisplayConfig.short_label,
            MasFieldDisplayConfig.display_order,
            MasFieldDisplayConfig.flip_color,
            MasFieldDisplayConfig.is_info,
            MasFieldDisplayConfig.is_pii,
            MasFieldDisplayConfig.summary_include,
            subcat_order.display_order.label("subcategory_display_order"),
        )
        .outerjoin(
            subcat_order,
            (subcat_order.form_type_id == MasFieldDisplayConfig.form_type_id)
            & (subcat_order.category_code == MasFieldDisplayConfig.category_code)
            & (subcat_order.subcategory_code == MasFieldDisplayConfig.subcategory_code)
            & (subcat_order.is_active == True)
        )
        .where(
            MasFieldDisplayConfig.form_type_id == form_type_id,
            MasFieldDisplayConfig.is_active == True,
            MasFieldDisplayConfig.category_code.is_not(None),
        )
        .order_by(
            subcat_order.display_order.is_(None),
            subcat_order.display_order,
            MasFieldDisplayConfig.subcategory_code,
            MasFieldDisplayConfig.display_order,
            MasFieldDisplayConfig.field_id,
        )
    ).all()

    by_category = {}
    by_subcategory = {}
    for row in rows:
        field_data = {
            "field_id": row.field_id,
            "label": row.short_label or row.field_id,
            "display_order": str(row.display_order),
            "subcategory_code": row.subcategory_code,
            "flip_color": bool(getattr(row, "flip_color", False)),
            "is_info": bool(getattr(row, "is_info", False)),
            "is_pii": bool(getattr(row, "is_pii", False)),
            "summary_include": bool(getattr(row, "summary_include", False)),
        }
        by_category.setdefault(row.category_code, []).append(field_data)
        if row.subcategory_code:
            by_subcategory.setdefault((row.category_code, row.subcategory_code), []).append(field_data)
    return by_category, by_subcategory


def get_ordered_category_configs_for_form_type(form_type_id):
    from sqlalchemy import select as sa_select

    from app.models.va_field_mapping import MasCategoryDisplayConfig

    return db.session.scalars(
        sa_select(MasCategoryDisplayConfig)
        .where(
            MasCategoryDisplayConfig.form_type_id == form_type_id,
            MasCategoryDisplayConfig.is_active == True,
        )
        .order_by(MasCategoryDisplayConfig.display_order, MasCategoryDisplayConfig.nav_label)
    ).all()


def serialize_category_browser_state(form_type, category_code):
    from sqlalchemy import select as sa_select

    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasSubcategoryOrder

    category = db.session.scalar(
        sa_select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == category_code,
            MasCategoryDisplayConfig.is_active == True,
        )
    )
    if not category:
        return None

    fields_by_category, fields_by_subcategory = ordered_field_lists_for_form_type(
        form_type.form_type_id
    )
    subcategories = db.session.scalars(
        sa_select(MasSubcategoryOrder)
        .where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.category_code == category_code,
        )
        .order_by(MasSubcategoryOrder.display_order)
    ).all()

    return {
        "category": {
            "category_code": category.category_code,
            "category_name": category.display_label,
            "display_order": category.display_order,
            "ordered_fields": fields_by_category.get(category_code, []),
        },
        "subcategories": [
            {
                "subcategory_code": sub.subcategory_code,
                "subcategory_name": sub.subcategory_name,
                "display_order": sub.display_order,
                "render_mode": sub.render_mode,
                "ordered_fields": fields_by_subcategory.get(
                    (category_code, sub.subcategory_code), []
                ),
            }
            for sub in subcategories
        ],
    }
