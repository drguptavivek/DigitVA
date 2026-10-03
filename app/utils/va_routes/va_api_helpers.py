from app.utils import va_mapping_fieldcoder
from app.services.category_rendering_service import get_category_rendering_service
from app.services.field_mapping_service import get_mapping_service


def va_get_render_datalevel(va_action, form_type_code, visible_category_codes=None):
    """
    Return category mapping for the requested action.

    Coder/reviewer views stay on the legacy static coder mapping where it exists.
    For coder-visible categories introduced in DB config but absent from the static
    dict (for example `social_autopsy`), fall back to the DB-backed mapping so the
    panel does not render empty.
    """
    mapping_svc = get_mapping_service()
    if va_action not in {"vacode", "vareview"}:
        return mapping_svc.get_fieldsitepi(form_type_code)

    merged_mapping = dict(va_mapping_fieldcoder)
    db_mapping = mapping_svc.get_fieldsitepi(form_type_code)
    category_svc = get_category_rendering_service()

    for category_code, category_mapping in db_mapping.items():
        if category_code in merged_mapping:
            continue
        if category_svc.is_category_enabled(
            form_type_code,
            va_action,
            visible_category_codes,
            category_code,
        ):
            merged_mapping[category_code] = category_mapping

    return merged_mapping
