import sqlalchemy as sa
from app.models import VaResearchProjects, VaSites, VaForms
from app.utils.va_user.va_user_02_variablevalidators import fail
from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup
from app.utils.va_smartva.va_smartva_06_smartvacountries import smartva_allowed_countries


def validate_form_id(form_id, session):
    if not len(form_id) == 12:
        return fail(f"Inadequte form_id '{form_id}' length.")
    existing_form_ids = set(session.scalars(sa.select(VaForms.form_id)).all())
    if form_id in existing_form_ids:
        return fail(f"Form ID '{form_id}' already exists.")
    return True


def validate_project_id(project_id, session, foriegnkey=False):
    if not len(project_id) == 6:
        return fail(f"Inadequate project_id '{project_id}' length.")
    valid_project_ids = set(
        session.scalars(sa.select(VaResearchProjects.project_id)).all()
    )
    if project_id not in valid_project_ids and foriegnkey:
        return fail(f"No research project with project_id '{project_id}' exists.")
    if project_id in valid_project_ids and not foriegnkey:
        return fail(f"Project with project_id '{project_id}' already exists.")
    return True


def validate_site_id(site_id, session, foreignkey=False):
    if not len(site_id) == 4:
        return fail(f"Inadequate site_id '{site_id}' length.")
    valid_site_ids = set(session.scalars(sa.select(VaSites.site_id)).all())
    if site_id not in valid_site_ids and foreignkey:
        return fail(f"No site with site_id '{site_id}' exists.")
    if site_id in valid_site_ids and not foreignkey:
        return fail(f"Site with side_id '{site_id}' already exists.")
    return True


def validate_boolean_string(variable):
    allowed = ["True", "False"]
    if variable and variable not in allowed:
        return fail(f"SmartVA variables can only be: {allowed}.")
    return True


def validate_odk_form(odk_project_id, odk_form_id, session):
    if not (isinstance(odk_form_id, str) or isinstance(odk_project_id.str)):
        return fail(f"Invalid odk_form_id '{odk_form_id}' or odk_project_id '{odk_project_id}', string expected.")
    exists = session.scalars(
        sa.select(VaForms).where(
            (VaForms.odk_form_id == odk_form_id)
            & (VaForms.odk_project_id == odk_project_id)
        )
    ).first()
    if exists:
        return fail(f"ODK form with odk_form_id '{odk_form_id}' and odk_project_id '{odk_project_id}' already exists.")
    client = va_odk_clientsetup()
    try:
        test = client.submissions.get_table(
            form_id=odk_form_id,
            project_id=odk_project_id,
            table_name="Submissions",
            top=1,
        )
        if not isinstance(test, dict):
            return fail(f"Error authenticating odk_form_id '{odk_form_id}' and odk_project_id '{odk_project_id}'.")
    except Exception as e:
        return fail(f"No ODK form found: {e}")
    return True


def validate_smartva_country(va_smartvacountry):
    if va_smartvacountry and va_smartvacountry not in smartva_allowed_countries:
        return fail(f"SmartVA country '{va_smartvacountry}' seems to be invalid.")
    return True
