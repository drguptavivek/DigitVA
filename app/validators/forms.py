"""Form-configuration validators used by setup and admin mapping flows.

These helpers validate legacy `va_forms` identifiers, SmartVA option fields,
and ODK form uniqueness/connectivity. They intentionally stay outside route
modules so setup services, admin APIs, and bootstrap flows share one contract.
"""

import sqlalchemy as sa

from app.models import VaForms
from app.services.odk.client import va_odk_clientsetup
from app.services.smartva.legacy.countries import (
    smartva_allowed_countries,
)
from app.validators.users import fail


def validate_form_id(form_id, session):
    if not len(form_id) == 12:
        return fail(f"Inadequate form_id '{form_id}' length.")
    existing_form = session.scalar(
        sa.select(VaForms.form_id).where(VaForms.form_id == form_id)
    )
    if existing_form:
        return fail(f"Form ID '{form_id}' already exists.")
    return True


def validate_boolean_string(variable):
    allowed = ["True", "False"]
    if variable and variable not in allowed:
        return fail(f"SmartVA variables can only be: {allowed}.")
    return True


def validate_odk_form(odk_project_id, odk_form_id, session):
    if not isinstance(odk_form_id, str) or not isinstance(odk_project_id, (int, str)):
        return fail(
            f"Invalid odk_form_id '{odk_form_id}' or "
            f"odk_project_id '{odk_project_id}'."
        )
    exists = session.scalars(
        sa.select(VaForms).where(
            (VaForms.odk_form_id == odk_form_id)
            & (VaForms.odk_project_id == odk_project_id)
        )
    ).first()
    if exists:
        return fail(
            f"ODK form with odk_form_id '{odk_form_id}' and "
            f"odk_project_id '{odk_project_id}' already exists."
        )
    client = va_odk_clientsetup()
    try:
        test = client.submissions.get_table(
            form_id=odk_form_id,
            project_id=odk_project_id,
            table_name="Submissions",
            top=1,
        )
        if not isinstance(test, dict):
            return fail(
                f"Error authenticating odk_form_id '{odk_form_id}' and "
                f"odk_project_id '{odk_project_id}'."
            )
    except Exception as exc:
        return fail(f"No ODK form found: {exc}")
    return True


def validate_smartva_country(va_smartvacountry):
    if va_smartvacountry and va_smartvacountry not in smartva_allowed_countries:
        return fail(f"SmartVA country '{va_smartvacountry}' seems to be invalid.")
    return True
