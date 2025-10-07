import os
from collections import OrderedDict
from flask import url_for, current_app
from app.utils.va_render.va_render_05_mapchoicevalue import va_render_mapchoicevalue
from app.utils.va_render.va_render_02_standardizedate import va_render_standardizedate
from app.utils.va_render.va_render_04_cleannumericvalue import va_render_cleannumericvalue
from app.utils.va_render.va_render_03_formatdatetimeindian import va_render_formatdatetimeindian


va_dealwithdates = ["Id10021", "Id10023", "Id10024", "Id10012", "Id10071"]
va_dealwithdatetimes = ["Id10011", "Id10481"]
va_zeroskipfields = ["isNeonatal", "isChild", "isAdult"]
va_skipvalues = ["ref", "dk"]
va_isattachment = ["Id10476_audio", "imagenarr", "md_im1", "md_im2", "md_im3", "md_im4", "md_im5", "md_im6",
                   "md_im7", "md_im8", "md_im9", "md_im10", "md_im11", "md_im12", "md_im13", "md_im14",
                   "md_im15", "md_im16", "md_im17", "md_im18", "md_im19", "md_im20", "md_im21", "md_im22",
                   "md_im23", "md_im24", "md_im25", "md_im26", "md_im27", "md_im28", "md_im29", "md_im30",
                   "ds_im1", "ds_im2", "ds_im3", "ds_im4", "ds_im5"]
va_multipleselect = ["Id10173_nc", "Id10199", "Id10235", "Id10477", "Id10478", "Id10479"]


def va_render_processcategorydata(
    va_data, va_form_id, va_datalevel, va_mapping_choice, va_partial
):
    if not va_data:
        return {}
    va_categoryresult = {}
    for va_subcat, va_fieldmap in va_datalevel.get(va_partial).items():
        va_subcatresult = OrderedDict()
        for va_fieldid, va_label in va_fieldmap.items():
            if va_fieldid in va_data and va_data.get(va_fieldid) is not None:
                value = va_data.get(va_fieldid)
                if (isinstance(value, str) and value.lower() in va_skipvalues) or (
                    va_fieldid in va_zeroskipfields
                    and (value == 0 or value == "0" or value == "0.0")
                ):
                    continue
                if va_fieldid in va_dealwithdates:
                    value = va_render_standardizedate(value)
                if va_fieldid in va_dealwithdatetimes:
                    value = va_render_formatdatetimeindian(value)
                if va_fieldid in va_mapping_choice:
                    value = va_mapping_choice[va_fieldid].get(str(value), value)
                if va_fieldid in va_zeroskipfields and (
                    value == 1 or value == "1" or value == "1.0"
                ):
                    value = "True"
                if va_fieldid in va_multipleselect:
                    value = va_render_mapchoicevalue(
                        va_fieldid, value, va_mapping_choice
                    )
                if va_fieldid in va_isattachment:
                    if value.endswith(".amr"):
                        value = value.replace(".amr", ".mp3")
                    if os.path.exists(
                        os.path.join(
                            current_app.config["APP_DATA"], va_form_id, "media", value
                        )
                    ):
                        value = url_for(
                            "va_api.va_servemedia",
                            va_form_id=va_form_id,
                            va_filename=value,
                        )
                    else:
                        continue
                value = va_render_cleannumericvalue(value)
                va_subcatresult[va_label] = value
        if va_subcatresult:
            va_categoryresult[va_subcat] = va_subcatresult
    return va_categoryresult
