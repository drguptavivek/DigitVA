from app.services.field_mapping_service import get_mapping_service
from app.utils.va_form.va_form_02_formtyperesolution import (
    va_get_form_type_code_for_form,
)
from app.utils.va_render.va_render_06_processcategorydata import va_render_processcategorydata

va_renderforall = ["vainterviewdetails", "vademographicdetails", "vaneonatalperioddetails", "vainjuriesdetails", "vahealthhistorydetails",
                   "vageneralsymptoms", "varespiratorycardiacsymptoms", "vaabdominalsymptoms", "vaneurologicalsymptoms", "vaskinmucosalsymptoms",
                   "vaneonatalfeedingsymptoms", "vamaternalsymptoms", "vahealthserviceutilisation"]

def va_preprocess_categoriestodisplay(va_data, va_form_id):
    category_list = []
    try:
        mapping_svc = get_mapping_service()
        form_type_code = va_get_form_type_code_for_form(va_form_id)
        va_mapping_fieldsitepi = mapping_svc.get_fieldsitepi(form_type_code)
        va_mapping_choice = mapping_svc.get_choices(form_type_code)
        for va_category in va_renderforall:
            category_list.append(va_category) if va_render_processcategorydata(va_data, va_form_id, va_mapping_fieldsitepi, va_mapping_choice, va_category) else None
        category_list.append("vanarrationanddocuments")
    except Exception as e:
        print(va_data)
        raise Exception(
            f"VA Submission ({va_data.get('sid')}): Error in forming available categories for a submission. Error: {e}"
        )
    return category_list
