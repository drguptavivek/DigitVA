"""Request-scoped authorization helpers."""

import uuid

from flask import session

from app import db
from app.authz.scope import user_has_role
from app.models import VaUsers


def request_user_from_session():
    user_id = session.get("_user_id")
    if not user_id:
        return None
    try:
        return db.session.get(VaUsers, uuid.UUID(user_id))
    except (TypeError, ValueError):
        return None


def request_user_has_role(role: str) -> bool:
    user = request_user_from_session()
    if user is None:
        return False
    return user_has_role(user, role)
