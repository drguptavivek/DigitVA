import sqlalchemy as sa
from app.models import VaForms
from app.models import VaStatuses
from app.models import VaUsers, VaSubmissions
from app.utils.va_user.va_user_01_rolesenum import VaRoles
from email_validator import validate_email, EmailNotValidError


def fail(reason):
    print(f"Failed [{reason}]")
    return False


def validate_email_format(email):
    try:
        validate_email(email)
        return True
    except EmailNotValidError as e:
        return fail(f"Invalid email: {e}")


def validate_password_strength(password):
    return (
        True if len(password) >= 8 else fail(f"Password '{password}' must be at least 8 characters.")
    )


def validate_permissions_exist(*roles):
    if not any(roles):
        return fail("No user permissions provided.")
    return True


def validate_landing_page(landing_page):
    landing_pages = [
        "admin",
        "coder",
        "reviewer",
        "sitepi",
    ]
    return (
        True
        if landing_page in landing_pages
        else fail(f"Landing page '{landing_page}' must be one of: {landing_pages}")
    )


def validate_email_uniqueness(session, email):
    exists = session.scalars(sa.select(VaUsers).where(VaUsers.email == email)).first()
    return not exists or fail(f"User with same email '{email}' already exists.")


def validate_languages_exist(vacode_language, session):
    if not isinstance(vacode_language, list):
        return fail(f"vacode_language '{vacode_language}' must be a list.")

    valid_languages = set(
        session.scalars(sa.select(VaSubmissions.va_narration_language)).all()
    )

    for lang in vacode_language:
        if lang not in valid_languages:
            print(f"Warning: Language '{lang}' not in VA submissions. Continue? (y/n)")
            response = input().strip()
            if response != "y":
                return fail("VA user creation aborted by admin.")
    return True


def validate_permissions(va_user_permissionsdict, va_dbsession):
    if not isinstance(va_user_permissionsdict, dict):
        raise ValueError(f"Permissions '{va_user_permissionsdict}' must be a dictionary.")

    stmt = sa.select(VaForms.form_id).where(VaForms.form_status == VaStatuses.active)
    va_validformids = set(va_dbsession.scalars(stmt).all())

    for role, forms in va_user_permissionsdict.items():
        if role not in VaRoles._value2member_map_:
            raise ValueError(f"Invalid role '{role}' specified.")
        if not isinstance(forms, list):
            raise ValueError(f"Permissions for role '{role}' must be a list")
        for form in forms:
            if form not in va_validformids:
                raise ValueError(
                    f"VA form '{form}' under role '{role}' is not a valid VA form."
                )
