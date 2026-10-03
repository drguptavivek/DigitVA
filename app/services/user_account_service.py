"""Invite-only user creation shared by every route that creates an account.

One place for the field validation, the ``VaUsers`` row and the invitation
emails, so the admin, data-manager and mentoring-institute routes cannot drift.
The caller owns authorization and the commit.
"""

from __future__ import annotations

import logging
import re
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


MOBILE_IN_USE_MESSAGE = "This mobile number is already used by another account."
MOBILE_REQUIRED_MESSAGE = (
    "An account without an email needs a 10-digit mobile number that no other "
    "account uses."
)

#: The stored phone, normalised in SQL exactly as ``canonical_mobile`` does in
#: Python: digits only, then a leading ``0`` or ``91`` in front of ten digits
#: dropped. A result that is not ten digits never equals a canonical number.
PHONE_CANONICAL = sa.func.regexp_replace(
    sa.func.regexp_replace(VaUsers.phone, "[^0-9]", "", "g"),
    "^(0|91)([0-9]{10})$",
    r"\2",
)


def canonical_mobile(value) -> str | None:
    """The ten-digit form of a typed mobile number, or None.

    Keeps the digits only (spaces, dashes, brackets and ``+`` go), then drops
    a trunk ``0`` (eleven digits) or the country code ``91`` (twelve digits).
    Anything that is not then exactly ten digits is not a full number, so a
    partial or padded number never matches (docs/policy/mobile-sign-in.md
    section 1). ``PHONE_CANONICAL`` applies the same rule to the stored phone.
    """
    digits = re.sub(r"[^0-9]", "", value or "")
    if (len(digits) == 11 and digits.startswith("0")) or (
        len(digits) == 12 and digits.startswith("91")
    ):
        digits = digits[-10:]
    return digits if len(digits) == 10 else None


def mask_mobile(mobile: str | None) -> str | None:
    """``******3210`` for display where an identifier is needed; never the
    whole number (it is personal data, mobile-sign-in.md section 4)."""
    return f"******{mobile[-4:]}" if mobile else None


def mobile_held_by_other(mobile: str, user_id=None) -> bool:
    """Whether another account holds *mobile*, as its sign-in number or as
    the canonical form of its free-text phone (shared numbers left over from
    before mobile sign-in live only in ``phone``).

    ponytail: PHONE_CANONICAL is a sequential scan of va_users (hundreds of
    rows); add an expression index on it if the table grows large.
    """
    stmt = sa.select(sa.exists().where(
        sa.or_(VaUsers.mobile_login == mobile, PHONE_CANONICAL == mobile),
        *([VaUsers.user_id != user_id] if user_id is not None else []),
    ))
    return bool(db.session.scalar(stmt))


def assign_phone(user: VaUsers, raw_phone) -> None:
    """Set ``phone`` and keep ``mobile_login`` in step with it.

    A phone that canonicalises becomes the sign-in number; one another
    account holds is refused. A blank or malformed phone clears the sign-in
    number, which a mobile-only account may never lose. Raises
    UserAccountError with a message safe to show. Caller flushes/commits and
    should catch ``IntegrityError`` for the race two concurrent writers lose
    (``translate_integrity_error``).
    """
    phone = (raw_phone or "").strip() or None
    if phone is not None and len(phone) > 15:
        raise UserAccountError("Phone number is too long.")
    mobile = canonical_mobile(phone)
    if mobile is not None and mobile_held_by_other(mobile, user.user_id):
        raise UserAccountError(MOBILE_IN_USE_MESSAGE)
    if mobile is None and user.email is None:
        raise UserAccountError(MOBILE_REQUIRED_MESSAGE)
    user.phone = phone
    user.mobile_login = mobile


def translate_integrity_error(exc) -> UserAccountError | None:
    """The plain message for a unique-constraint race on email or mobile, or
    None when *exc* is some other integrity failure."""
    text = str(getattr(exc, "orig", exc))
    if "va_users_mobile_login_key" in text:
        return UserAccountError(MOBILE_IN_USE_MESSAGE)
    if "va_users_email_key" in text or "ix_va_users_email" in text:
        return EmailInUseError("Email already in use.")
    return None


def validate_new_user_payload(payload: dict, *, allow_mobile_only: bool = False) -> dict:
    """Return the cleaned email, name, phone, mobile and languages.

    *allow_mobile_only*: the caller can show a one-time sign-in code, so an
    account with a mobile number and no email may be created (admin and the
    data-manager page). ``email`` is then None.

    Raises UserAccountError for a missing field, a mismatched email
    confirmation, an unknown language code, an email already in use or a
    mobile number another account holds.
    """
    from app.models.mas_languages import MasLanguages

    email = (payload.get("email") or "").strip().lower()
    email_confirm = (payload.get("email_confirm") or "").strip().lower()
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    languages = payload.get("languages")
    mobile = canonical_mobile(phone)

    if allow_mobile_only and not email and not email_confirm:
        if not name:
            raise UserAccountError("name is required.")
        if mobile is None:
            raise UserAccountError(MOBILE_REQUIRED_MESSAGE)
    else:
        if not email or not email_confirm or not name:
            raise UserAccountError("email, email_confirm, and name are required.")
        if email != email_confirm:
            raise UserAccountError("Email confirmation does not match.")
    if len(phone) > 15:
        raise UserAccountError("Phone number is too long.")
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

    if email and db.session.scalar(sa.select(VaUsers.user_id).where(VaUsers.email == email)):
        raise EmailInUseError("Email already in use.")
    if mobile is not None and mobile_held_by_other(mobile):
        raise UserAccountError(MOBILE_IN_USE_MESSAGE)
    return {
        "email": email or None,
        "name": name,
        "phone": phone,
        "mobile": mobile,
        "languages": languages,
    }


def create_invited_user(fields: dict, *, other: dict | None = None) -> VaUsers:
    """Add (and flush) an active user.

    An email account sets its own password via the invitation; a mobile-only
    account (``fields["email"]`` None) gets its password from a sign-in code
    (mobile_sign_in_service.issue_code), so its random one is never used.
    Raises UserAccountError if a concurrent writer took the email or number.
    """
    from sqlalchemy.exc import IntegrityError

    user = VaUsers(
        email=fields["email"],
        name=fields["name"],
        phone=fields["phone"] or None,
        mobile_login=fields.get("mobile"),
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
    try:
        with db.session.begin_nested():
            db.session.flush()
    except IntegrityError as exc:
        error = translate_integrity_error(exc)
        if error is None:
            raise
        raise error from exc
    return user


def send_invitation(user: VaUsers) -> None:
    """Queue the verification and password-setup emails; call after commit.

    Non-critical: the user can request a resend or reset, so a failure is
    logged without the address and swallowed. A mobile-only account gets no
    email (email_service refuses an empty recipient anyway).
    """
    if not user.email:
        return
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
