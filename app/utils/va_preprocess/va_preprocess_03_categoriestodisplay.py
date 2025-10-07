from app.utils.va_mapping.va_mapping_01_fieldsitepi import va_mapping_fieldsitepi
from app.utils.va_mapping.va_mapping_03_choice import va_mapping_choice
from app.utils.va_render.va_render_06_processcategorydata import va_render_processcategorydata

va_renderforall = ["vainterviewdetails", "vademographicdetails", "vaneonatalperioddetails", "vainjuriesdetails", "vahealthhistorydetails",
                   "vageneralsymptoms", "varespiratorycardiacsymptoms", "vaabdominalsymptoms", "vaneurologicalsymptoms", "vaskinmucosalsymptoms",
                   "vaneonatalfeedingsymptoms", "vamaternalsymptoms", "vahealthserviceutilisation"]

def va_preprocess_categoriestodisplay(va_data, va_form_id):
    category_list = []
    try:
        for va_category in va_renderforall:
            category_list.append(va_category) if va_render_processcategorydata(va_data, va_form_id, va_mapping_fieldsitepi, va_mapping_choice, va_category) else None
        category_list.append("vanarrationanddocuments")
    except Exception as e:
        print(va_data)
        raise Exception(
            f"VA Submission ({va_data.get('sid')}): Error in forming available categories for a submission. Error: {e}"
        )
    return category_list