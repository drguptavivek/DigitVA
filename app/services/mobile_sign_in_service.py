"""One-time sign-in codes and server-generated passwords for every account.
Baseline: docs/policy/mobile-sign-in.md section 3 and
docs/policy/account-onboarding-and-passwords.md.

A data manager, In-charge or admin issues an 8-character code (capitals and digits, shown XXXX-XXXX) for a person; the
person redeems it with their email or mobile number and gets a generated
password, shown once. ``set_new_password`` is the one place any other path
(email verification, reset link, Profile, CLI) generates a password. Codes are stored only as keyed hashes, expire after 90 minutes,
are voided by a newer code or by five wrong attempts, and work once. Every
issue, void, redemption and regeneration is audited in
``auth_security_events`` without the code, password or number.

Callers own authorization (``may_issue_code``; from the data-management
pages ``may_issue_code_from_data_management``; from a project roster
``may_issue_code_in_project``) and the commit, except
``redeem_code_and_accept_terms``, the whole redemption both "I have a code"
paths (web page, ``POST /api/v1/auth/sign-in-code/redeem``) run, which commits.
"""

from __future__ import annotations

import hmac
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import sqlalchemy as sa
from flask import current_app

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
from app.services.user_account_service import accept_terms, canonical_mobile
from app.utils.password_policy import (
    BREACH_CHECK_UNAVAILABLE_MESSAGE,
    password_breach_error_message,
)

CODE_TTL = timedelta(minutes=90)


def code_lifetime():
    """The issue responses' lifetime fields: ``expires_in_minutes``, and
    ``expires_in_hours`` kept for callers that read the older field."""
    minutes = int(CODE_TTL.total_seconds() // 60)
    return {"expires_in_minutes": minutes, "expires_in_hours": minutes / 60}
# Capitals and digits without the look-alikes 0 O 1 I L: read aloud or copied by hand without mistakes.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
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
    privileged (``_PRIVILEGED_ROLES`` or global scope), and only when the
    target has no verified email: such an account resets by email, so a
    manager cannot take it over by redeeming their own code with its address
    (security review of digitva-kmoy). A code replaces the person's
    password, so managing one of several grants is not enough
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
    verified_email = sa.exists().where(
        VaUsers.user_id == target_user_id,
        VaUsers.email.is_not(None),
        VaUsers.email_verified.is_(True),
    )
    return bool(db.session.scalar(sa.select(sa.and_(
        sa.exists().where(*active),
        sa.not_(sa.exists().where(*active, unmanaged)),
        sa.not_(verified_email),
    ))))


def _roster_rule(actor, project_id: str, user_id_col):
    """The clauses ``issuable_user_ids`` and ``editable_user_ids`` share, for a
    non-admin *actor*: a clause, or None when *actor* does not manage
    *project_id*'s roster (``authz.roster_project_ids``).

    *clause* holds when the account *user_id_col* is on *project_id*'s roster
    (``organization_service.on_project_roster``), a member of no project
    outside the actor's managed ones (``_outside_member``), and either
    (a) holds at least one active grant, every one managed by the actor
    (``authz.grant_list_filter``) and none privileged (``_PRIVILEGED_ROLES``
    or global scope), or (b) is an unplaced member: no active grant
    anywhere, a member of *project_id*, account active.
    """
    grants = authz.resolve_grants(actor)
    managed_projects = authz.roster_project_ids(grants)
    if project_id not in managed_projects:
        return None
    from app.models import MapProjectMember
    from app.services.organization_service import on_project_roster

    U, G, M = VaUsers, VaUserAccessGrants, MapProjectMember
    active = (G.user_id == user_id_col, G.grant_status == VaStatuses.active)
    # coalesce: a NULL from the filter's comparisons must count as outside.
    managed = sa.func.coalesce(authz.grant_list_filter(actor, _grants=grants), sa.false())
    unmanaged = sa.or_(
        sa.not_(managed),
        G.role.in_(_PRIVILEGED_ROLES),
        G.scope_type == VaAccessScopeTypes.global_scope,
    )
    rule_a = sa.and_(sa.exists().where(*active), sa.not_(sa.exists().where(*active, unmanaged)))
    rule_b = sa.and_(
        sa.not_(sa.exists().where(*active)),
        U.user_status == VaStatuses.active,
        sa.exists().where(M.user_id == user_id_col, M.project_id == project_id),
    )
    return sa.and_(
        on_project_roster(project_id, user_id_col),
        sa.not_(_outside_member(user_id_col, managed_projects)),
        sa.or_(rule_a, rule_b),
    )


def issuable_user_ids(actor, project_id: str, user_ids) -> set[uuid.UUID]:
    """The ids among *user_ids* that *actor* may issue a code for from
    *project_id*'s People roster (``may_issue_code_in_project``), in one
    query whatever the number of ids; the roster grid flags every row with it.

    Admin: all of them. Anyone else must manage *project_id*'s roster, and
    then a target must pass ``_roster_rule`` (on the roster, a member of no
    project the actor does not manage, every active grant managed and none
    privileged, or an unplaced member), have no live phone sign-in and no
    verified email. The roster, membership and live-phone clauses apply to
    both of ``_roster_rule``'s branches: without them a PI could add another
    project's member to their roster, or grant an arbitrary account a role
    here, and take it over with a code (docs/policy/mobile-sign-in.md
    section 3).
    """
    ids = {uuid.UUID(str(u)) for u in user_ids}
    if not ids:
        return set()
    if authz.resolve_grants(actor).is_admin:
        return ids
    U = VaUsers
    clause = _roster_rule(actor, project_id, U.user_id)
    if clause is None:
        return set()
    verified_email = sa.and_(U.email.is_not(None), U.email_verified.is_(True))
    return set(db.session.scalars(
        sa.select(U.user_id).where(
            U.user_id.in_(ids), clause,
            sa.not_(_live_phone(U.user_id)),
            sa.not_(verified_email),
        )
    ))


def editable_user_ids(actor, project_id: str, user_ids) -> set[uuid.UUID]:
    """The ids among *user_ids* whose account (name, year of birth, sex,
    languages, password reset email) *actor* may change from *project_id*'s
    roster user panel, in one query. Policy: dm-user-grant-management.md,
    "Roster User Panel".

    Admin: all of them. Anyone else, the project's PI included: the
    sign-in-code roster rule (``_roster_rule``) without its verified-email
    and live-phone clauses, for an active account. Such an account belongs
    to the actor's projects alone, so changing it touches no one else's.
    """
    ids = {uuid.UUID(str(u)) for u in user_ids}
    if not ids:
        return set()
    if authz.resolve_grants(actor).is_admin:
        return ids
    U = VaUsers
    clause = _roster_rule(actor, project_id, U.user_id)
    if clause is None:
        return set()
    return set(db.session.scalars(
        sa.select(U.user_id).where(U.user_id.in_(ids), clause, U.user_status == VaStatuses.active)
    ))


def may_edit_account(actor, target_user_id, project_id: str) -> bool:
    """Whether *actor* may change *target_user_id*'s account from
    *project_id*'s roster panel; the rule is ``editable_user_ids``."""
    return uuid.UUID(str(target_user_id)) in editable_user_ids(actor, project_id, [target_user_id])


def _outside_member(user_id_col, project_ids) -> sa.ColumnElement:
    """SQL: the account is a member (``map_project_members``) of a project
    outside *project_ids*: not the actor's to take over or edit."""
    from app.models import MapProjectMember

    M = MapProjectMember
    return sa.exists().where(M.user_id == user_id_col, M.project_id.not_in(sorted(project_ids)))


def _live_phone(user_id_col) -> sa.ColumnElement:
    """SQL: the account has a live phone sign-in
    (``device_auth_service.live_session_clauses``, the rule of the roster's
    ``phone_count``)."""
    from app.models import AuthDevice, AuthDeviceSession
    from app.services.device_auth_service import live_session_clauses

    S = AuthDeviceSession
    return sa.exists().where(
        S.user_id == user_id_col, S.device_id == AuthDevice.device_id, *live_session_clauses(datetime.now(UTC)),
    )


def _outside_or_signed_in(user_id_col, project_ids) -> sa.ColumnElement:
    """SQL: ``_outside_member`` or ``_live_phone``. Either refuses a
    non-admin's code: a member elsewhere is not theirs to take over, and
    someone signed in on a phone needs no code -- a person moving projects
    keeps their account, password and phone (owner 2026-11-16;
    docs/policy/mobile-sign-in.md section 3)."""
    return sa.or_(_outside_member(user_id_col, project_ids), _live_phone(user_id_col))


def may_issue_code_from_data_management(actor, target_user_id) -> bool:
    """Whether *actor* may issue a code for *target_user_id* from the
    data-management pages (``POST /data-management/api/users/<id>/sign-in-code``).

    Admin always. Anyone else needs ``may_issue_code`` and, because a data
    manager may grant a role to any account it looks up, the clauses of the
    roster rule that stop grant-then-issue: the target is a member of no
    project outside those of the actor's grant-writing grants
    (``authz.writer_grants``) and has no live phone sign-in
    (``_outside_or_signed_in``). Accepted residual: an account with no other
    grant, membership, phone or verified email can still be granted a role
    and given a code (docs/policy/mobile-sign-in.md section 3).
    """
    grants = authz.resolve_grants(actor)
    if grants.is_admin:
        return True
    if not may_issue_code(actor, target_user_id):
        return False
    projects = {x.project_id for x in authz.writer_grants(grants)}
    return not db.session.scalar(sa.select(_outside_or_signed_in(target_user_id, projects)))


def may_issue_code_in_project(actor, target_user_id, project_id: str) -> bool:
    """Whether *actor* may issue a code for *target_user_id* from
    *project_id*'s roster; the rule is ``issuable_user_ids``. ``may_issue_code``
    stays the rule for every other caller."""
    return uuid.UUID(str(target_user_id)) in issuable_user_ids(actor, project_id, [target_user_id])


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


def issue_code(user: VaUsers, *, actor_user_id, audit_detail: dict | None = None) -> str:
    """Issue a fresh 8-character code, shown as ``XXXX-XXXX``, for *user* (redeemed with their email or
    mobile number), voiding any live one, and return it in clear -- shown to
    the issuer once, never stored. Caller authorizes (``may_issue_code``:
    a verified-email account gets codes from an admin only) and commits.
    Raises ValueError for an account with neither an email nor a sign-in
    number (a public-demo username account): no code could ever be redeemed.
    *audit_detail* (no code in it) goes on the ``mobile_code_issued`` event,
    e.g. the project roster's project id and route.
    """
    if user.email is None and user.mobile_login is None:
        raise ValueError("This account has no email or mobile number to redeem a code with.")
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
    # Eight characters, letters included, so it is never mistaken for a numeric PIN; the hash covers them without the dash.
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    db.session.add(AuthMobileCode(
        user_id=user.user_id,
        code_hash=_code_hash(user.user_id, code),
        issued_by=actor_user_id,
        issued_at=now,
        expires_at=now + CODE_TTL,
    ))
    record_security_event(
        user_id=user.user_id, actor_user_id=actor_user_id, event_type="mobile_code_issued",
        detail=audit_detail,
    )
    db.session.flush()
    return f"{code[:4]}-{code[4:]}"


def _typed_code(code: str | None) -> str:
    """A typed code in capitals with its ``-`` and spaces removed, so
    ``K7PQ-M3XR``, ``k7pq m3xr`` and ``K7PQM3XR`` match. A live 6-digit code
    issued before the change still matches its hash."""
    return re.sub(r"[\s-]", "", code or "").upper()


def _well_formed(code: str) -> bool:
    """A code of the current alphabet, or a 6-digit one issued before letters."""
    return bool(code) and (code.isdigit() or all(c in CODE_ALPHABET for c in code))


def _set_generated_password(user: VaUsers, password: str) -> None:
    user.set_password(password)
    # mobile-sign-in.md section 3: the old password stops working and every
    # existing session ends.
    user.bump_session_version()


def redeem_code(identifier: str, code: str) -> tuple[VaUsers, str] | None:
    """Redeem a sign-in code typed with an email (contains ``@``) or a mobile
    number. Returns ``(user, password)`` once, or None for any mismatch --
    unknown email, unknown, shared or malformed number, inactive account, no
    live code, wrong code -- so the caller gives one answer for all.

    A redemption also sets ``mobile_verified_at`` ("has redeemed a code",
    ``VaUsers.sign_in_verified``): the code, handed over by the person's
    manager, proves the account as an email verification would.

    The password is generated before the number is looked up, so a breach
    check outage (PasswordGenerationUnavailable, raised before anything is
    read or written) cannot tell a caller whether the code was right. A
    wrong code counts against the live code under a row lock; the fifth
    voids it.
    Caller commits in every case (a counted failure must persist).
    """
    password = generate_password()
    typed = (identifier or "").strip()
    if "@" in typed:
        match = VaUsers.email == typed.lower()
    else:
        match = VaUsers.mobile_login == (canonical_mobile(typed) or "")
    code = _typed_code(code)
    now = datetime.now(UTC)
    # Every path runs the same three statements -- user lookup, locking read
    # of the live code, one counting write -- whether or not the number is
    # known or has a live code, so the work done reveals neither.
    user = db.session.scalar(sa.select(VaUsers).where(match))
    eligible = user is not None and user.is_active
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
    if not (live is not None and _well_formed(code) and same):
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
    record_security_event(
        user_id=user.user_id, event_type="password_generated", detail={"path": "sign_in_code"},
    )
    return user, password


def redeem_code_and_accept_terms(identifier: str, code: str) -> str | None:
    """"I have a code" for the web page and the app endpoint: ``redeem_code``,
    then record the terms acceptance the caller collected (onboarding policy
    5.2), commit whatever the answer (a counted failure must persist) and
    tell an email on file (no password, no code). Returns the generated
    password to show once, or None for any mismatch.

    Raises PasswordGenerationUnavailable after a rollback: nothing was read,
    written or counted, so the caller answers "try again".
    """
    try:
        result = redeem_code(identifier, code)
    except PasswordGenerationUnavailable:
        db.session.rollback()
        raise
    if result is not None:
        accept_terms(result[0], via="sign_in_code")
    db.session.commit()
    if result is None:
        return None
    user, password = result
    if user.email:
        # Security review: the address on file hears of the change.
        # Non-critical, so never blocks the redemption.
        try:
            from app.services.email_service import send_code_redeemed_notice

            send_code_redeemed_notice(user)
        except Exception as exc:
            current_app.logger.warning(
                "code redeemed notice failed | user_id=%s | %s", user.user_id, type(exc).__name__
            )
    return password


def set_new_password(user: VaUsers, *, path: str, actor_user_id=None) -> str:
    """Generate a password for *user*, set it and end every session, the
    caller's included; return it in clear for the caller to deliver once
    (email or screen) and never log. *path* names the flow in the audit
    event (``email_verification``, ``password_reset``, ``profile``, ``cli``;
    ``redeem_code`` records ``sign_in_code`` itself).
    Raises PasswordGenerationUnavailable before anything changes. Caller
    commits, or rolls back if delivery fails."""
    password = generate_password()
    _set_generated_password(user, password)
    record_security_event(
        user_id=user.user_id, actor_user_id=actor_user_id,
        event_type="password_generated", detail={"path": path},
    )
    return password
