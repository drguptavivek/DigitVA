"""Dynamic submission summary service.

Builds the "Symptoms on VA Interview" summary live from the DB-backed field
mapping configuration rather than the legacy generated static summary modules.
"""

from sqlalchemy import select

from app import db
from app.models import MasFieldDisplayConfig
from app.services.field_mapping_service import get_mapping_service


SPECIAL_VALUE_SUMMARY_FIELDS = {"Id10121", "Id10122", "Id10120", "Id10436"}


def _list_as_text(value):
    """A list answer (Collect submits multi-selects as arrays) as its space-joined string."""
    return " ".join(str(item) for item in value) if isinstance(value, list) else value


def _normalize_boolean_like(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().lower()
    return str(value).strip().lower()


def summary_fields(form_type_code: str) -> list[tuple[str, str, bool]]:
    """The summary fields in display order as ``(field_id, label, flip_color)``; empty for an unknown form type."""
    form_type = get_mapping_service().get_form_type(form_type_code)
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
    return [
        (field.field_id, field.summary_label or field.short_label or field.field_id, bool(field.flip_color))
        for field in fields
    ]


def build_submission_summary(form_type_code: str, va_data: dict | None) -> list[str]:
    """Build summary badges live from DB-backed field metadata."""
    if not form_type_code or not va_data:
        return []

    choices = get_mapping_service().get_choices(form_type_code)
    summary_items: list[str] = []

    for field_id, label, flip_color in summary_fields(form_type_code):
        if field_id not in va_data:
            continue

        raw_value = _list_as_text(va_data.get(field_id))
        if raw_value in (None, "", [], {}):
            continue

        normalized_value = _normalize_boolean_like(raw_value)

        if field_id in SPECIAL_VALUE_SUMMARY_FIELDS:
            display_value = choices.get(field_id, {}).get(str(raw_value), raw_value)
            summary_items.append(f"{label}: {display_value}")
            continue

        if flip_color:
            if normalized_value == "no":
                summary_items.append(label)
            continue

        if normalized_value == "yes":
            summary_items.append(label)

    return summary_items
