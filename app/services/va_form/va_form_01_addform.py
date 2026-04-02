from app import db
from app.models import VaForms
from app.utils import (
    validate_form_id,
    validate_project_id,
    validate_site_id,
    validate_boolean_string,
    validate_odk_form,
    validate_smartva_country,
)


def va_form_addform(
    form_id,
    project_id,
    site_id,
    odk_form_id,
    odk_project_id,
    form_type,
    form_smartvahiv=None,
    form_smartvamalaria=None,
    form_smartvahce=None,
    form_smartvafreetext=None,
    form_smartvacountry=None,
):
    session = db.session
    if not all(
        [
            validate_form_id(form_id, session),
            validate_project_id(project_id, session, True),
            validate_site_id(site_id, session, True),
            validate_boolean_string(form_smartvafreetext),
            validate_boolean_string(form_smartvahce),
            validate_boolean_string(form_smartvahiv),
            validate_boolean_string(form_smartvamalaria),
            validate_odk_form(odk_project_id, odk_form_id, session),
            validate_smartva_country(form_smartvacountry),
        ]
    ):
        return
    data = {
        "form_id": form_id,
        "project_id": project_id,
        "site_id": site_id,
        "odk_form_id": odk_form_id,
        "odk_project_id": odk_project_id,
        "form_type": form_type,
    }
    if form_smartvahiv:
        data["form_smartvahiv"] = form_smartvahiv
    if form_smartvamalaria:
        data["form_smartvamalaria"] = form_smartvamalaria
    if form_smartvahce:
        data["form_smartvahce"] = form_smartvahce
    if form_smartvafreetext:
        data["form_smartvafreetext"] = form_smartvafreetext
    if form_smartvacountry:
        data["form_smartvacountry"] = form_smartvacountry

    va_form = VaForms(**data)
    session.add(va_form)
    session.commit()
    print(f"Success. [Form '{form_id}' added.]")
