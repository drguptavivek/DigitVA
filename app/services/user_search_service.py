"""User rows as the admin and data-manager user APIs serve them: the
serializer, contact masking outside the caller's reach, and the search filter.

Moved out of ``app.routes.admin`` so ``app.routes.data_management`` shares
them without importing the admin module's privates (digitva-r8nh.13).
"""

import re

import sqlalchemy as sa
from flask_login import current_user

from app import db
from app.models import VaStatuses, VaUserAccessGrants, VaUsers


def _serialize_user(user, *, include_profile=False):
    """``include_profile`` adds the interviewer year of birth and sex (PII):
    only for admin-only responses, never the project PI user search."""
    data = {
        "user_id": str(user.user_id),
        "email": user.email,
        "name": user.name,
        "job_title": user.job_title,
        "status": user.user_status.value,
        "email_verified": bool(user.email_verified),
        "mobile_only": user.is_mobile_only,
        "mobile_verified": user.mobile_verified_at is not None,
        "phone": user.phone,
        "landing_page": user.landing_page,
        "languages": user.vacode_language or [],
        "is_admin": user.is_admin(),
    }
    if include_profile:
        data["year_of_birth"] = user.year_of_birth
        data["sex"] = user.sex
        from app.services import public_demo_service as demo

        # The kept mark exists only on a demo deployment (public-demo.md section 8).
        if demo.enabled() and user.is_public_demo:
            data["public_demo_keep"] = bool(user.public_demo_keep)
    return data


def _mask_email(email):
    """``vi***@gmail.com``: two characters of a local part of five or more,
    else one; an address without ``@`` shows its first character only."""
    if not email:
        return email
    local, at, domain = email.partition("@")
    if not at:
        return f"{email[:1]}***"
    return f"{local[:2] if len(local) >= 5 else local[:1]}***@{domain}"


def _mask_phone(phone):
    """``******4321``: the last four digits of a number of eight or more
    digits; a shorter number is masked whole."""
    if not phone:
        return phone
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 8:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]


def users_in_caller_reach(user_ids) -> set:
    """Of *user_ids*, those whose contact details the current user sees in
    full: holders of an active grant in the caller's own project, site or
    unit reach (``authz.user_list_filter``, the Users page's rule), the
    caller themself, and everyone for an admin. One query.
    Policy: dm-user-grant-management.md, "User listing" (digitva-9xn9.22)."""
    from app.services import authz

    ids = set(user_ids)
    if not ids or authz.resolve_grants(current_user).is_admin:
        return ids
    found = set(db.session.scalars(
        sa.select(VaUserAccessGrants.user_id).where(
            VaUserAccessGrants.user_id.in_(ids),
            VaUserAccessGrants.grant_status == VaStatuses.active,
            authz.user_list_filter(current_user),
        ).distinct()
    ))
    if current_user.user_id in ids:
        found.add(current_user.user_id)
    return found


def serialize_searched_users(users) -> list[dict]:
    """``_serialize_user`` rows for a platform-wide user search. A user outside
    the caller's reach (``users_in_caller_reach``) keeps name, user id and
    status, with email and phone masked and every other key null;
    ``contact_masked`` says which."""
    in_reach = users_in_caller_reach(u.user_id for u in users)
    rows = []
    for user in users:
        data = _serialize_user(user)
        if user.user_id in in_reach:
            rows.append({**data, "contact_masked": False})
            continue
        # Allow-list: every other key stays, as null, so the shape is unchanged.
        rows.append({
            **dict.fromkeys(data),
            "user_id": data["user_id"], "name": data["name"], "status": data["status"],
            "email": _mask_email(user.email), "phone": _mask_phone(user.phone),
            "contact_masked": True,
        })
    return rows


def user_search_condition(query):
    """A user search matches *query* as a literal substring of email, name or
    phone (``autoescape``: %, _ and \\ match themselves)."""
    return sa.or_(
        VaUsers.email.icontains(query, autoescape=True),
        VaUsers.name.icontains(query, autoescape=True),
        VaUsers.phone.icontains(query, autoescape=True),
    )
