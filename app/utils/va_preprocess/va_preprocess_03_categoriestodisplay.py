from app.services.field_mapping_service import get_mapping_service
from app.utils.va_form.va_form_02_formtyperesolution import (
    va_get_form_type_code_for_form,
)
from app.utils.va_render.va_render_06_processcategorydata import va_render_processcategorydata


def va_preprocess_categoriestodisplay(va_data, va_form_id, *, form_type_code=None):
    category_list = []
    try:
        from app.services.category_rendering_service import get_category_rendering_service

        mapping_svc = get_mapping_service()
        category_svc = get_category_rendering_service()
        effective_form_type_code = form_type_code or va_get_form_type_code_for_form(
            va_form_id
        )
        va_mapping_fieldsitepi = mapping_svc.get_fieldsitepi(effective_form_type_code)
        va_mapping_choice = mapping_svc.get_choices(effective_form_type_code)
        for category in category_svc.get_all_active_categories(effective_form_type_code):
            if category.always_include:
                category_list.append(category.category_code)
                continue
            if va_render_processcategorydata(
                va_data,
                va_form_id,
                va_mapping_fieldsitepi,
                va_mapping_choice,
                category.category_code,
            ):
                category_list.append(category.category_code)
    except Exception as e:
        raise Exception(
            f"VA Submission ({va_data.get('sid')}): Error in forming available categories for a submission. Error: {e}"
        )
    return category_list
