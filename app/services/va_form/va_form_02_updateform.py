import sqlalchemy as sa
from app import db
from app.models import VaForms
from app.utils import (
    validate_boolean_string,
    validate_odk_form,
    validate_smartva_country,
)


def va_form_updateform(
    form_id,
    odk_form_id=None,
    odk_project_id=None,
    form_type=None,
    form_smartvahiv=None,
    form_smartvamalaria=None,
    form_smartvahce=None,
    form_smartvafreetext=None,
    form_smartvacounty=None,
):
    session = db.session
    va_form = session.scalars(
        sa.select(VaForms).where(VaForms.form_id == form_id)
    ).first()
    if not va_form:
        print(f"Failed [Form ID {form_id} not found.]")
        return
    if odk_form_id or odk_project_id:
        if odk_form_id and not odk_project_id:
            opi = va_form.odk_project_id
            if not validate_odk_form(opi, odk_form_id, session):
                return
            va_form.odk_project_id = opi
            va_form.odk_form_id = odk_form_id
        elif odk_project_id and not odk_form_id:
            ofi = va_form.odk_form_id
            if not validate_odk_form(odk_project_id, ofi, session):
                return
            va_form.odk_project_id = odk_project_id
            va_form.odk_form_id = ofi
        else:
            if not validate_odk_form(odk_project_id, odk_form_id, session):
                return
            va_form.odk_project_id = odk_project_id
            va_form.odk_form_id = odk_form_id
    if form_type:
        va_form.form_type = form_type
    if form_smartvahiv:
        if validate_boolean_string(form_smartvahiv):
            va_form.form_smartvahiv = form_smartvahiv
        else:
            return
    if form_smartvamalaria:
        if validate_boolean_string(form_smartvamalaria):
            va_form.form_smartvamalaria = form_smartvamalaria
        else:
            return
    if form_smartvahce:
        if validate_boolean_string(form_smartvahce):
            va_form.form_smartvahce = form_smartvahce
        else:
            return
    if form_smartvafreetext:
        if validate_boolean_string(form_smartvafreetext):
            va_form.form_smartvafreetext = form_smartvafreetext
        else:
            return
    if form_smartvacounty:
        if validate_smartva_country(form_smartvacounty):
            va_form.form_smartvacounty = form_smartvacounty
        else:
            return
    session.commit()
    print(f"Success [Updated form '{form_id}'.]")
