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
from app.admin_support.field_mapping import (
    get_ordered_category_configs_for_form_type as _get_ordered_category_configs_for_form_type,
    ordered_field_lists_for_form_type as _ordered_field_lists_for_form_type,
    serialize_category_browser_state as _serialize_category_browser_state,
)
from app.http.responses import json_error as _json_error
from app.admin_support.odk import (
    get_odk_client_for_connection as _get_odk_client_for_connection,
)


def _load_form_type(form_type_code):
    from app.models import MasFormTypes

    return db.session.scalar(
        sa.select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )


def _clear_mapping_cache():
    from app.services.forms.field_mapping import get_mapping_service

    get_mapping_service().clear_cache()


def _build_field_row_context(form_type_code, form_type_id, field):
    from app.models.va_field_mapping import MasSubcategoryOrder

    categories = _get_ordered_category_configs_for_form_type(form_type_id)
    all_subcategories = db.session.scalars(
        sa.select(MasSubcategoryOrder).where(
            MasSubcategoryOrder.form_type_id == form_type_id
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

    return {
        "form_type_code": form_type_code,
        "field": field,
        "categories": categories,
        "cat_name_map": cat_name_map,
        "subcat_name_map": subcat_name_map,
        "subcats_by_cat": subcategories_by_category,
    }
