"""Legacy VaForms CRUD helpers used by setup/bootstrap flows."""

import sqlalchemy as sa

from app import db
from app.models import VaForms, VaStatuses
from app.utils import (
    validate_boolean_string,
    validate_form_id,
    validate_odk_form,
    validate_project_id,
    validate_site_id,
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


def va_form_updateform(
    form_id,
    odk_form_id=None,
    odk_project_id=None,
    form_type=None,
    form_smartvahiv=None,
    form_smartvamalaria=None,
    form_smartvahce=None,
    form_smartvafreetext=None,
    form_smartvacountry=None,
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
    if form_smartvacountry:
        if validate_smartva_country(form_smartvacountry):
            va_form.form_smartvacountry = form_smartvacountry
        else:
            return
    session.commit()
    print(f"Success [Updated form '{form_id}'.]")


def va_form_deleteform(form_id):
    session = db.session
    va_form = session.scalars(
        sa.select(VaForms).where(VaForms.form_id == form_id)
    ).first()
    if not va_form:
        print(f"Failed [Form ID {form_id} not found.]")
        return
    va_form.form_status = VaStatuses.deactive
    session.commit()
    print(f"Success [Deleted form '{form_id}'.]")
