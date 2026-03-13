"""Dynamic submission summary service.

Builds the "Symptoms on VA Interview" summary live from the DB-backed field
mapping configuration rather than the legacy generated static summary modules.
"""

from sqlalchemy import select

from app import db
from app.models import MasFieldDisplayConfig
from app.services.field_mapping_service import get_mapping_service


SPECIAL_VALUE_SUMMARY_FIELDS = {"Id10121", "Id10122", "Id10120", "Id10436"}


def _normalize_boolean_like(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().lower()
    return str(value).strip().lower()


def build_submission_summary(form_type_code: str, va_data: dict | None) -> list[str]:
    """Build summary badges live from DB-backed field metadata."""
    if not form_type_code or not va_data:
        return []

    mapping_service = get_mapping_service()
    form_type = mapping_service.get_form_type(form_type_code)
    if not form_type:
        return []

    fields = db.session.scalars(
        select(MasFieldDisplayConfig)
        .where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.is_active == True,
            MasFieldDisplayConfig.summary_include == True,
        )
        .order_by(MasFieldDisplayConfig.display_order)
    ).all()

    choices = mapping_service.get_choices(form_type_code)
    summary_items: list[str] = []

    for field in fields:
        if field.field_id not in va_data:
            continue

        raw_value = va_data.get(field.field_id)
        if raw_value in (None, "", [], {}):
            continue

        label = field.summary_label or field.short_label or field.field_id
        normalized_value = _normalize_boolean_like(raw_value)

        if field.field_id in SPECIAL_VALUE_SUMMARY_FIELDS:
            display_value = choices.get(field.field_id, {}).get(str(raw_value), raw_value)
            summary_items.append(f"{label}: {display_value}")
            continue

        if field.flip_color:
            if normalized_value == "no":
                summary_items.append(label)
            continue

        if normalized_value == "yes":
            summary_items.append(label)

    return summary_items
