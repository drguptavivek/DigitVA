import uuid
import traceback
import sqlalchemy as sa
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


def va_user_update(
    user_id,
    name=None,
    email=None,
    password=None,
    vacode_language=None,
    landing_page=None,
    permission_coder=None,
    permission_sitepi=None,
    permission_reviewer=None,
):
    session = db.session
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        print(f"Failed [Invalid UUID '{user_id}' format.]")
        print(traceback.format_exc())
        return
    user = session.scalars(
        sa.select(VaUsers).where(VaUsers.user_id == user_uuid)
    ).first()
    if not user:
        print(f"Failed [User ID {user_id} not found.]")
        return
    if name:
        user.name = name
    if email:
        if validate_email_format(email) and validate_email_uniqueness(session, email):
            user.email = email
        else:
            return
    if password:
        if validate_password_strength(password):
            user.set_password(password)
        else:
            return
    if vacode_language:
        if validate_languages_exist(vacode_language, session):
            user.vacode_language = vacode_language
        else:
            return
    if landing_page:
        if validate_landing_page(landing_page):
            user.landing_page = landing_page
        else:
            return
    if permission_coder or permission_reviewer or permission_sitepi:
        if validate_permissions_exist(
            permission_coder, permission_reviewer, permission_sitepi
        ):
            response = input(
                f"Warning: Permission update for '{user_id}' would require all level permissions. Continue? (y/n)"
            )
            if response != "y":
                print(f"Failed [User '{user_id}' update aborted by admin.]")
                return
            permission = {}
            if permission_coder:
                permission[VaRoles.coder.value] = permission_coder
            if permission_reviewer:
                permission[VaRoles.reviewer.value] = permission_reviewer
            if permission_sitepi:
                permission[VaRoles.sitepi.value] = permission_sitepi
            try:
                validate_permissions(permission, session)
            except ValueError as e:
                print(f"Failed [{e}]")
                print(traceback.format_exc())
                return
            user.permission = permission
    session.commit()
    print(f"Success [User '{user_id}' updated.]")
