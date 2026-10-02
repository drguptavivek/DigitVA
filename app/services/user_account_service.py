"""Invite-only user creation shared by every route that creates an account.

One place for the field validation, the ``VaUsers`` row and the invitation
emails, so the admin, data-manager and mentoring-institute routes cannot drift.
The caller owns authorization and the commit.
"""

from __future__ import annotations

import logging
import secrets

import sqlalchemy as sa

from app import db
from app.models import VaStatuses, VaUsers

log = logging.getLogger(__name__)


class UserAccountError(ValueError):
    """A field is missing or invalid; the message is safe to show the caller."""


class EmailInUseError(UserAccountError):
    """The address is already registered; callers that must not confirm that
    to the requester translate it to a generic refusal."""


def validate_new_user_payload(payload: dict) -> dict:
    """Return the cleaned email, name, phone and languages.

    Raises UserAccountError for a missing field, a mismatched email
    confirmation, an unknown language code or an email already in use.
    """
    from app.models.mas_languages import MasLanguages

    email = (payload.get("email") or "").strip().lower()
    email_confirm = (payload.get("email_confirm") or "").strip().lower()
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    languages = payload.get("languages")

    if not email or not email_confirm or not name:
        raise UserAccountError("email, email_confirm, and name are required.")
    if email != email_confirm:
        raise UserAccountError("Email confirmation does not match.")
    if not isinstance(languages, list) or not languages:
        raise UserAccountError("At least one language must be selected.")

    valid_codes = set(
        db.session.scalars(
            sa.select(MasLanguages.language_code).where(MasLanguages.is_active == True)  # noqa: E712
        ).all()
    )
    invalid = [code for code in languages if code not in valid_codes]
    if invalid:
        raise UserAccountError(f"Invalid language codes: {invalid}")

    if db.session.scalar(sa.select(VaUsers.user_id).where(VaUsers.email == email)):
        raise EmailInUseError("Email already in use.")
    return {"email": email, "name": name, "phone": phone, "languages": languages}


def create_invited_user(fields: dict, *, other: dict | None = None) -> VaUsers:
    """Add (and flush) an active user who sets their own password via invite."""
    user = VaUsers(
        email=fields["email"],
        name=fields["name"],
        phone=fields["phone"] or None,
        user_status=VaStatuses.active,
        vacode_language=fields["languages"],
        permission={},
        landing_page="coder",
        pw_reset_t_and_c=False,
        email_verified=False,
        other=other,
    )
    # Invite-only onboarding: user sets their own password via reset link.
    user.set_password(secrets.token_urlsafe(32))
    db.session.add(user)
    db.session.flush()
    return user


def send_invitation(user: VaUsers) -> None:
    """Queue the verification and password-setup emails; call after commit.

    Non-critical: the user can request a resend or reset, so a failure is
    logged without the address and swallowed.
    """
    try:
        from app.services.email_service import (
            send_password_reset_email,
            send_verification_email,
        )
        from app.services.token_service import generate_token

        send_verification_email(user, generate_token(user.user_id, "email_verify"))
        send_password_reset_email(
            user, generate_token(user.user_id, "password_reset"), invite_mode=True
        )
    except Exception as exc:
        log.warning("invitation email failed | user_id=%s | %s", user.user_id, type(exc).__name__)
