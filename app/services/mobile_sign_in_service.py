"""One-time sign-in codes and server-generated passwords for mobile-only
accounts. Baseline: docs/policy/mobile-sign-in.md section 3.

A data manager, In-charge or admin issues a 6-digit code for a person; the
person redeems it with their mobile number and gets a generated password,
shown once. Codes are stored only as keyed hashes, expire after 72 hours,
are voided by a newer code or by five wrong attempts, and work once. Every
issue, void, redemption and regeneration is audited in
``auth_security_events`` without the code, password or number.

Callers own authorization (``may_issue_code``) and the commit.
"""

from __future__ import annotations

import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models import (
    AuthMobileCode,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import authz
from app.services.security_event_service import record_security_event
from app.services.totp_service import keyed_hash
from app.services.user_account_service import canonical_mobile
from app.utils.password_policy import (
    BREACH_CHECK_UNAVAILABLE_MESSAGE,
    password_breach_error_message,
)

CODE_TTL = timedelta(hours=72)
MAX_CODE_FAILURES = 5
#: Breach-list hits before giving up; a hit is ~impossible for random words.
_MAX_PASSWORD_DRAWS = 5
_WORDS_PATH = Path(__file__).with_name("mobile_password_words.txt")
#: Matches no user or code row: stands in where there is none, so every
#: redemption runs the same statements (no timing hint of a live code).
_NO_ROW = uuid.UUID(int=0)
#: Grants that let their holder manage other people. Only an admin issues a
#: code for someone holding one: otherwise a data manager could take over a
#: peer, an In-charge or a PI by redeeming a code for them.
_PRIVILEGED_ROLES = (
    VaAccessRoles.admin,
    VaAccessRoles.project_pi,
    VaAccessRoles.site_pi,
    VaAccessRoles.data_manager,
)


class PasswordGenerationUnavailable(RuntimeError):
    """The breach check could not be reached; the caller shows a retryable
    error and changes nothing (password-breach-checks.md fail mode)."""

    message = BREACH_CHECK_UNAVAILABLE_MESSAGE


@lru_cache(maxsize=1)
def _words() -> tuple[str, ...]:
    """The bundled list: plain lowercase English words of 4-7 letters."""
    return tuple(w for w in _WORDS_PATH.read_text().split() if w)


def generate_password() -> str:
    """Three words and a 4-digit number joined by ``-``, e.g.
    ``maple-otter-candle-4821``: easy to read aloud and type on a phone.

    Words are 4-7 letters, so the result is always 19-26 characters. Entropy
    is 3 x log2(len(words)) + log2(10**4): about 45.8 bits with the 1823
    bundled words. Raises PasswordGenerationUnavailable when the breach check
    cannot be reached; a password on the breach list is redrawn.
    """
    words = _words()
    for _ in range(_MAX_PASSWORD_DRAWS):
        parts = [secrets.choice(words) for _ in range(3)]
        password = "-".join(parts + [f"{secrets.randbelow(10_000):04d}"])
        error = password_breach_error_message(password)
        if error is None:
            return password
        if error == BREACH_CHECK_UNAVAILABLE_MESSAGE:
            raise PasswordGenerationUnavailable()
    raise PasswordGenerationUnavailable()


def _code_hash(user_id, code: str) -> str:
    # Bound to the user so one code value never hashes alike for two people.
    return keyed_hash(f"{user_id}:{code}")


def may_issue_code(actor, target_user_id) -> bool:
    """Whether *actor* may issue a sign-in code for *target_user_id*.

    Admin always. Anyone else only when the target holds at least one active
    grant and the actor may manage **every** one of them (``authz.can_grant``,
    as ``grant_list_filter`` states it over the table), none of them
    privileged (``_PRIVILEGED_ROLES`` or global scope). A code replaces the
    person's password, so managing one of several grants is not enough
    (security review 2026-10-03).
    """
    grants = authz.resolve_grants(actor)
    if grants.is_admin:
        return True
    G = VaUserAccessGrants
    active = (G.user_id == target_user_id, G.grant_status == VaStatuses.active)
    # coalesce: a NULL from the filter's comparisons must count as outside.
    managed = sa.func.coalesce(authz.grant_list_filter(actor, _grants=grants), sa.false())
    unmanaged = sa.or_(
        sa.not_(managed),
        G.role.in_(_PRIVILEGED_ROLES),
        G.scope_type == VaAccessScopeTypes.global_scope,
    )
    return bool(db.session.scalar(sa.select(sa.and_(
        sa.exists().where(*active),
        sa.not_(sa.exists().where(*active, unmanaged)),
    ))))


def _void_live_codes(user_id, now) -> int:
    result = db.session.execute(
        sa.update(AuthMobileCode)
        .where(
            AuthMobileCode.user_id == user_id,
            AuthMobileCode.redeemed_at.is_(None),
            AuthMobileCode.voided_at.is_(None),
        )
        .values(voided_at=now)
    )
    return result.rowcount


def issue_code(user: VaUsers, *, actor_user_id) -> str:
    """Issue a fresh 6-digit code for a mobile-only *user*, voiding any live
    one, and return it in clear -- shown to the issuer once, never stored.
    Raises ValueError for an account that does not sign in by mobile only.
    Caller authorizes (``may_issue_code``) and commits.
    """
    if not user.is_mobile_only or not user.mobile_login:
        raise ValueError("Sign-in codes are only for accounts without an email.")
    now = datetime.now(UTC)
    # Serialise issuers for this person so two cannot each leave a live code
    # (the partial unique index on auth_mobile_codes is the backstop).
    db.session.execute(
        sa.select(VaUsers.user_id).where(VaUsers.user_id == user.user_id).with_for_update()
    )
    voided = _void_live_codes(user.user_id, now)
    if voided:
        record_security_event(
            user_id=user.user_id, actor_user_id=actor_user_id,
            event_type="mobile_code_voided", detail={"reason": "reissued"},
        )
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.session.add(AuthMobileCode(
        user_id=user.user_id,
        code_hash=_code_hash(user.user_id, code),
        issued_by=actor_user_id,
        issued_at=now,
        expires_at=now + CODE_TTL,
    ))
    record_security_event(
        user_id=user.user_id, actor_user_id=actor_user_id, event_type="mobile_code_issued",
    )
    db.session.flush()
    return code


def _set_generated_password(user: VaUsers, password: str) -> None:
    user.set_password(password)
    # mobile-sign-in.md section 3: the old password stops working and every
    # existing session ends.
    user.bump_session_version()


def redeem_code(raw_mobile: str, code: str) -> tuple[VaUsers, str] | None:
    """Redeem a sign-in code. Returns ``(user, password)`` once, or None for
    any mismatch -- unknown, shared or malformed number, inactive account,
    no live code, wrong code -- so the caller gives one answer for all.

    The password is generated before the number is looked up, so a breach
    check outage (PasswordGenerationUnavailable, raised before anything is
    read or written) cannot tell a caller whether the code was right. A
    wrong code counts against the live code under a row lock; the fifth
    voids it.
    Caller commits in every case (a counted failure must persist).
    """
    password = generate_password()
    mobile = canonical_mobile(raw_mobile)
    code = (code or "").strip()
    now = datetime.now(UTC)
    # Every path runs the same three statements -- user lookup, locking read
    # of the live code, one counting write -- whether or not the number is
    # known or has a live code, so the work done reveals neither.
    user = db.session.scalar(sa.select(VaUsers).where(VaUsers.mobile_login == (mobile or "")))
    eligible = user is not None and user.is_active and user.is_mobile_only
    # FOR UPDATE: concurrent guesses at one code queue here, and each sees
    # the count the previous one left, so a code is compared at most
    # MAX_CODE_FAILURES times in all.
    live = db.session.scalar(
        sa.select(AuthMobileCode).where(
            AuthMobileCode.user_id == (user.user_id if eligible else _NO_ROW),
            AuthMobileCode.redeemed_at.is_(None),
            AuthMobileCode.voided_at.is_(None),
            AuthMobileCode.expires_at > now,
            AuthMobileCode.failed_attempts < MAX_CODE_FAILURES,
        ).limit(1).with_for_update()
    )
    candidate = _code_hash(user.user_id if user else "-", code)
    same = hmac.compare_digest(live.code_hash if live else candidate, candidate)
    if not (live is not None and code.isdigit() and same):
        failures = db.session.execute(
            sa.update(AuthMobileCode)
            .where(AuthMobileCode.id == (live.id if live else _NO_ROW))
            .values(
                failed_attempts=AuthMobileCode.failed_attempts + 1,
                voided_at=sa.case(
                    (AuthMobileCode.failed_attempts + 1 >= MAX_CODE_FAILURES, now),
                    else_=AuthMobileCode.voided_at,
                ),
            )
            .returning(AuthMobileCode.failed_attempts)
        ).scalar()
        if failures is not None and failures >= MAX_CODE_FAILURES:
            record_security_event(
                user_id=user.user_id, event_type="mobile_code_voided",
                detail={"reason": "too_many_attempts"},
            )
        return None
    claimed = db.session.execute(
        sa.update(AuthMobileCode)
        .where(
            AuthMobileCode.id == live.id,
            AuthMobileCode.redeemed_at.is_(None),
            AuthMobileCode.voided_at.is_(None),
        )
        .values(redeemed_at=now)
    ).rowcount
    if claimed != 1:
        return None
    _set_generated_password(user, password)
    if user.mobile_verified_at is None:
        user.mobile_verified_at = now
    record_security_event(user_id=user.user_id, event_type="mobile_code_redeemed")
    return user, password


def regenerate_password(user: VaUsers) -> str:
    """A new generated password for a signed-in mobile-only *user* (the
    caller has checked reauthentication). Ends every session, the caller's
    included. Raises PasswordGenerationUnavailable or ValueError. Caller
    commits."""
    if not user.is_mobile_only:
        raise ValueError("Only accounts without an email get generated passwords.")
    password = generate_password()
    _set_generated_password(user, password)
    record_security_event(
        user_id=user.user_id, actor_user_id=user.user_id,
        event_type="mobile_password_regenerated",
    )
    return password
