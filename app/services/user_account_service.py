"""Invite-only user creation shared by every route that creates an account.

One place for the field validation, the ``VaUsers`` row and the invitation
emails, so the admin, data-manager and mentoring-institute routes cannot drift.
The caller owns authorization and the commit.
"""

from __future__ import annotations

import logging
import re
import secrets
import unicodedata

import sqlalchemy as sa

from app import db
from app.models import VaStatuses, VaUsers
from app.services.security_event_service import record_security_event

log = logging.getLogger(__name__)


class UserAccountError(ValueError):
    """A field is missing or invalid; the message is safe to show the caller."""


class EmailInUseError(UserAccountError):
    """The address is already registered; callers that must not confirm that
    to the requester translate it to a generic refusal."""


#: Resend verification when nothing was queued (delivery off, recipient
#: suppressed): said plainly, never "sent".
VERIFICATION_NOT_SENT_MESSAGE = (
    "Email delivery is off for this address; no verification email was sent."
)
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


#: A public-demo username (docs/policy/public-demo.md section 2): 3-30
#: characters, lower-case letters, digits, dot, underscore and hyphen, starting
#: with a letter. ``clean_username`` also refuses one that canonicalises to a
#: mobile number, so the sign-in identifier branch never reads it as one.
USERNAME_RE = re.compile(r"^[a-z][a-z0-9._-]{2,29}$")
USERNAME_RULE_MESSAGE = (
    "A username is 3 to 30 characters: lower-case letters, digits, dot, "
    "underscore or hyphen, starting with a letter."
)
USERNAME_IN_USE_MESSAGE = "That username is already taken."
#: Names that could pass for staff or the service (policy section 8). Compared
#: after dropping ``.``, ``_`` and ``-``, so ``a.d_min`` is ``admin``: an exact
#: match here, or any name starting with ``RESERVED_USERNAME_PREFIXES``.
RESERVED_USERNAMES = frozenset({
    "admin", "administrator", "root", "support", "help", "system", "digitva", "staff",
    "moderator", "owner", "security", "test", "null", "demo", "official", "who",
})
RESERVED_USERNAME_PREFIXES = ("support", "root", "security", "who", "official", "admin", "digitva")
_USERNAME_SEPARATORS = str.maketrans("", "", "._-")
USERNAME_RESERVED_MESSAGE = "That username is not available."


def clean_username(value) -> str:
    """The lower-cased username, or UserAccountError (message safe to show):
    refused when it breaks the pattern, reads as a mobile number or is
    reserved."""
    name = (value or "").strip().lower() if isinstance(value, str) else ""
    if not USERNAME_RE.fullmatch(name) or canonical_mobile(name) is not None:
        raise UserAccountError(USERNAME_RULE_MESSAGE)
    squashed = name.translate(_USERNAME_SEPARATORS)
    if squashed in RESERVED_USERNAMES or squashed.startswith(RESERVED_USERNAME_PREFIXES):
        raise UserAccountError(USERNAME_RESERVED_MESSAGE)
    return name


def sign_in_identifier(value) -> tuple[str, str]:
    """How a typed sign-in identifier is read: ``("email", lower-cased)`` when
    it has ``@``; ``("mobile", canonical)`` when it canonicalises to a mobile
    number; ``("username", lower-cased)`` when it matches the username rule and
    the public demo is on; otherwise ``("mobile", "")``, which matches no
    account. Never looks anything up, so the caller's answer cannot depend on
    whether the account exists (authentication-factors.md section 1). The one
    reading of an identifier for the web login and device sign-in."""
    from flask import current_app

    typed = (value or "").strip() if isinstance(value, str) else ""
    if "@" in typed:
        return "email", typed.lower()
    mobile = canonical_mobile(typed)
    if mobile is not None:
        return "mobile", mobile
    if current_app.config.get("PUBLIC_DEMO_ENABLED") and USERNAME_RE.fullmatch(typed.lower()):
        return "username", typed.lower()
    return "mobile", ""


def find_sign_in_user(kind: str, value: str) -> VaUsers | None:
    """The account a ``sign_in_identifier`` result names, or None. A mobile
    number matches only a unique sign-in number (``mobile_login``); a username
    only while the public demo is on."""
    from flask import current_app

    if not value:
        return None
    if kind == "email":
        column = VaUsers.email
    elif kind == "mobile":
        column = VaUsers.mobile_login
    elif kind == "username" and current_app.config.get("PUBLIC_DEMO_ENABLED"):
        column = VaUsers.username
    else:
        return None
    return db.session.scalar(sa.select(VaUsers).where(column == value))


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
    if "uq_va_users_username" in text:
        return UserAccountError(USERNAME_IN_USE_MESSAGE)
    if "va_users_email_key" in text or "ix_va_users_email" in text:
        return EmailInUseError("Email already in use.")
    return None


JOB_TITLE_MAX_LENGTH = 120


def clean_job_title(value) -> str | None:
    """The one validator every job-title write goes through: trimmed text of
    at most 120 characters with no control, format (bidi override, zero-width)
    or line/paragraph-separator character; blank or None clears.
    Raises UserAccountError (message safe to show) otherwise."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise UserAccountError("Job title must be text.")
    title = value.strip()
    if len(title) > JOB_TITLE_MAX_LENGTH:
        raise UserAccountError(f"Job title is at most {JOB_TITLE_MAX_LENGTH} characters.")
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") for ch in title):
        raise UserAccountError("Job title cannot contain control or invisible characters.")
    return title or None


def validate_new_user_payload(payload: dict, *, allow_mobile_only: bool = False) -> dict:
    """Return the cleaned email, name, job title, phone, mobile and languages.

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
    job_title = clean_job_title(payload.get("job_title"))
    profile = VaUsers()
    try:
        profile.set_interviewer_profile(payload.get("year_of_birth"), payload.get("sex"))
    except ValueError as exc:
        raise UserAccountError(str(exc)) from exc

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
        "job_title": job_title,
        "year_of_birth": profile.year_of_birth,
        "sex": profile.sex,
    }


def creation_other(via: str, actor_user_id=None, extra: dict | None = None) -> dict:
    """The ``VaUsers.other`` stamp every new account carries: who made it.

    ``created_by_user_id`` is the signed-in actor's id as text, or None when
    no human did (cli, seed, system, self_signup, sso); ``created_via`` says
    which path (cli, seed, system, self_signup, sso, admin, data_manager,
    mentor_institute, import). Pass this as ``other=`` when constructing a
    VaUsers. The creator is read for admin-only scoping (training bulk
    picker, data-manager edit rights) and is never sent to other users.
    """
    stamp = dict(extra or {})
    stamp["created_by_user_id"] = str(actor_user_id) if actor_user_id else None
    stamp["created_via"] = via
    return stamp


def create_invited_user(
    fields: dict, *, via: str, actor_user_id=None, other: dict | None = None
) -> VaUsers:
    """Add (and flush) an active user and audit ``account_created``.

    Nobody chooses a password (account-onboarding-and-passwords.md section
    1): an email account gets a generated one by email when it verifies the
    address; a mobile-only account (``fields["email"]`` None) gets one by
    redeeming a sign-in code (mobile_sign_in_service.issue_code). The random
    placeholder set here is never known to anyone; the one exception, a
    public-demo sign-up (``fields["username"]`` and ``fields["is_public_demo"]``,
    public_demo_service), replaces it with the password the person chose.
    *via* names the creating path in the audit event (``admin``,
    ``data_manager``, ``mentor_institute``, ``self_signup``). *other* holds
    extra ``other`` keys; the creator stamp is added here. Raises
    UserAccountError if a concurrent writer took the email, number or username.
    """
    from sqlalchemy.exc import IntegrityError

    user = VaUsers(
        email=fields["email"],
        name=fields["name"],
        job_title=fields.get("job_title"),
        year_of_birth=fields.get("year_of_birth"),
        sex=fields.get("sex"),
        phone=fields["phone"] or None,
        mobile_login=fields.get("mobile"),
        username=fields.get("username"),
        is_public_demo=bool(fields.get("is_public_demo")),
        user_status=VaStatuses.active,
        vacode_language=fields["languages"],
        permission={},
        landing_page="coder",
        pw_reset_t_and_c=False,
        email_verified=False,
        other=creation_other(via, actor_user_id, other),
    )
    # Unknown placeholder until verification or a code generates the real one.
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
    record_account_created(user, via=via, actor_user_id=actor_user_id)
    return user


def record_account_created(user: VaUsers, *, via: str, actor_user_id=None) -> None:
    """Audit a new account (onboarding policy section 9): path and whether it
    is mobile-only, never an identifier. Caller commits."""
    record_security_event(
        user_id=user.user_id, actor_user_id=actor_user_id, event_type="account_created",
        detail={"via": via, "mobile_only": user.is_mobile_only},
    )


def accept_terms(user: VaUsers, *, via: str) -> None:
    """Record the person's acceptance of the terms of use (onboarding policy
    5.2, 5.4): clears the terms gate (``pw_reset_t_and_c``) and audits
    ``terms_accepted`` with the path (``web``, ``api``, ``device``,
    ``sign_in_code``, ``cli``), since the flag itself keeps no time. A no-op when
    already accepted. Caller commits."""
    if user.pw_reset_t_and_c:
        return
    user.pw_reset_t_and_c = True
    record_security_event(user_id=user.user_id, event_type="terms_accepted", detail={"via": via})


def send_invitation(user: VaUsers, *, actor_user_id=None) -> None:
    """Queue the verification email; call after commit. Opening its link
    generates the password and emails it (section 5.1), so no second email
    goes now.

    Non-critical: the creator can resend, so a failure is logged without the
    address and swallowed. A mobile-only account gets no email (email_service
    refuses an empty recipient anyway).
    """
    if not user.email:
        return
    try:
        from app.services.email_service import send_verification_email
        from app.services.token_service import generate_token

        send_verification_email(
            user, generate_token(user.user_id, "email_verify"), actor_user_id=actor_user_id
        )
    except Exception as exc:
        log.warning("invitation email failed | user_id=%s | %s", user.user_id, type(exc).__name__)


class PasswordEmailFailed(RuntimeError):
    """The password email could not be sent; the caller rolls back so the
    old password (if any) keeps working, and shows a retryable message."""

    message = "We could not send your password email. Please try again in a few minutes."


def has_usable_password(user: VaUsers) -> bool:
    """Whether *user* already knows a working password, so verifying an
    email must not replace it (account-onboarding-and-passwords.md 5.3).

    True once the person has signed in and accepted the terms
    (``pw_reset_t_and_c``) or has redeemed a sign-in code
    (``mobile_verified_at``). A new invitee -- and one invited before
    generated passwords, still holding the random placeholder -- has
    neither. Edge: someone whose email is changed after a reset but before
    they accept the terms again gets a fresh password at the new address.
    """
    return bool(user.pw_reset_t_and_c) or user.mobile_verified_at is not None


def email_new_password(user: VaUsers, *, path: str, actor_user_id=None) -> None:
    """Generate a password for *user*, end their sessions and email it to
    their address synchronously (never queued: the password must not sit in
    the broker). Order: generate (raises PasswordGenerationUnavailable before
    any write), set, send. Raises PasswordEmailFailed if the send fails; the
    caller then rolls back, otherwise commits. Never logs the password.
    """
    from app.services import mobile_sign_in_service
    from app.services.email_service import send_password_email

    password = mobile_sign_in_service.set_new_password(
        user, path=path, actor_user_id=actor_user_id
    )
    try:
        send_password_email(user, password)
    except Exception as exc:
        # Type only: an SMTP error could echo message content.
        log.warning("password email failed | user_id=%s | %s", user.user_id, type(exc).__name__)
        raise PasswordEmailFailed() from exc
