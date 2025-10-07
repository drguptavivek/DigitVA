import traceback
from app import db
from app.models import VaUsers
from app.utils import (
    VaRoles,
    validate_permissions,
    validate_email_format,
    validate_password_strength,
    validate_permissions_exist,
    validate_email_uniqueness,
    validate_languages_exist,
    validate_landing_page,
)


def va_user_create(
    name,
    email,
    password,
    vacode_language,
    landing_page,
    permission_coder=None,
    permission_sitepi=None,
    permission_reviewer=None,
):
    session = db.session
    if not all(
        [
            validate_email_format(email),
            validate_password_strength(password),
            validate_permissions_exist(
                permission_coder, permission_reviewer, permission_sitepi
            ),
            validate_email_uniqueness(session, email),
            validate_languages_exist(vacode_language, session),
            validate_landing_page(landing_page),
        ]
    ):
        return
    permission = {}
    if permission_coder:
        permission[VaRoles.coder.value] = permission_coder
    if permission_sitepi:
        permission[VaRoles.sitepi.value] = permission_sitepi
    if permission_reviewer:
        permission[VaRoles.reviewer.value] = permission_reviewer
    try:
        validate_permissions(permission, session)
    except ValueError as e:
        print(f"Failed [{e}]")
        print(traceback.format_exc())
        return
    user = VaUsers(
        name=name,
        email=email,
        vacode_language=vacode_language,
        permission=permission,
        landing_page=landing_page,
    )
    user.set_password(password)
    session.add(user)
    session.commit()
    print(f"Success [User '{email}' created.]")
