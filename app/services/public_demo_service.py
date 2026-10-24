"""Public demo (digitva-77v5): self sign-up, per-account limits and project setup.

Policy: docs/policy/public-demo.md. Everything here is inert unless
``PUBLIC_DEMO_ENABLED``: sign-up raises ``not_enabled``, the limits and the
default unit apply only to the demo project (``PUBLIC_DEMO_PROJECT_ID``) on a
demo deployment, and setup refuses. Confinement lives elsewhere, at the shared
choke points: the grant guard (``authz.grant_cache``), the own-case filter
(``authz.predicates``), the death-register checks (``web_intake_service``)
and the virtual-grant exclusion (``authz.grants._resolve``).

Nothing logged or audited here carries a username or a password.
"""

from __future__ import annotations

import ipaddress
import logging
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from flask import current_app
from flask_limiter.util import get_remote_address

from app import db
from app.models import (
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaProjectMaster,
    VaResearchProjects,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
    VaWebIntakeDraft,
)
from app.services import user_account_service as accounts
from app.services.case_transition_service import WebIntakeError
from app.utils.password_policy import (
    BREACH_CHECK_UNAVAILABLE_MESSAGE,
    password_breach_error_message,
)

log = logging.getLogger(__name__)

PROJECT_NAME = "Public demo (WHO 2022, ICD-11)"
NARRATION_LANGUAGES = ("english", "hindi")
ACCOUNT_LANGUAGES = ["english", "hindi"]
RECODE_WINDOW_MINUTES = 5
DEMO_UNIT_CODE = "PUBDEMO"
#: The only grants a public-demo account may hold, all at project scope on
#: the demo project (policy section 3).
DEMO_ROLES = (VaAccessRoles.interviewer, VaAccessRoles.coder, VaAccessRoles.reviewer)
PASSWORD_MIN_LENGTH = 12
#: Serialises sign-ups so two at the cap cannot both pass the count.
_SIGNUP_LOCK = "public_demo_signup"

#: The sign-up notice (policy section 2), shown on the page and accepted with
#: one checkbox together with the terms of use.
NOTICE = (
    "This is a public demo. Do not enter real personal or health data. "
    "Entries are visible to the demo team. Your account and everything it "
    "created are deleted 30 days after your last sign-in."
)
CAP_REACHED_MESSAGE = "The demo is full; try again later."
WRONG_DATABASE_MESSAGE = "The demo is not ready yet. Please try again later."
LIMIT_CODE = "demo_limit"


class PublicDemoError(ValueError):
    """A refused sign-up or setup; ``message`` is safe to show the caller,
    ``code`` a fixed machine code, ``status_code`` the HTTP answer."""

    def __init__(self, message: str, code: str, status_code: int = 400, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.field = field


def enabled() -> bool:
    return bool(current_app.config.get("PUBLIC_DEMO_ENABLED"))


def demo_project_id() -> str:
    return current_app.config.get("PUBLIC_DEMO_PROJECT_ID") or "PUB01"


def foreign_projects_exist() -> bool:
    """Whether ``va_project_master`` holds a project other than the demo's: the
    sign of a demo deployment pointed at the main database by mistake
    (policy section 8a). One primary-key-bounded query on a table of a handful
    of rows."""
    return db.session.scalar(
        sa.select(VaProjectMaster.project_id).where(VaProjectMaster.project_id != demo_project_id()).limit(1)
    ) is not None


def log_main_database_refusal() -> None:
    log.error(
        "public demo refused: va_project_master holds a project other than %s; this looks like the "
        "main database. Check DATABASE_URL on the demo deployment.", demo_project_id(),
    )


def require_demo_database() -> None:
    """Refuse demo work (sign-up, setup, the beat allowlist, purge, eviction)
    on a database that holds any other project. Raises PublicDemoError
    ``wrong_database`` (503); logs one clear error."""
    if foreign_projects_exist():
        log_main_database_refusal()
        raise PublicDemoError(WRONG_DATABASE_MESSAGE, "wrong_database", 503)


def is_demo_project(project_id: str | None) -> bool:
    """Whether *project_id* is the demo project on a demo deployment."""
    return enabled() and bool(project_id) and project_id == demo_project_id()


def allowed_grant(role, scope_type, project_id) -> bool:
    """The grant guard's rule: interviewer, coder or reviewer at project scope
    on the demo project (policy section 3)."""
    return (
        role in DEMO_ROLES
        and scope_type == VaAccessScopeTypes.project
        and project_id == demo_project_id()
    )


# ---------------------------------------------------------------------------
# Sign-up
# ---------------------------------------------------------------------------


def _check_password(username: str, password, confirm) -> str:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
        raise PublicDemoError(
            f"Choose a password of at least {PASSWORD_MIN_LENGTH} characters.",
            "invalid_password", field="password",
        )
    if confirm is not None and password != confirm:
        raise PublicDemoError("The two passwords do not match.", "invalid_password", field="confirm")
    if password.strip().lower() == username:
        raise PublicDemoError(
            "The password must not be the username.", "invalid_password", field="password"
        )
    error = password_breach_error_message(password)
    if error == BREACH_CHECK_UNAVAILABLE_MESSAGE:
        # Retryable (password-breach-checks.md): nothing was written.
        raise PublicDemoError(error, "breach_check_unavailable", 503, field="password")
    if error is not None:
        raise PublicDemoError(error, "breached_password", field="password")
    return password


def active_account_count() -> int:
    """Active public-demo accounts (``ix_va_users_public_demo_status``)."""
    return db.session.scalar(
        sa.select(sa.func.count()).select_from(VaUsers).where(
            VaUsers.is_public_demo.is_(True), VaUsers.user_status == VaStatuses.active,
        )
    )


def create_account(username, password, *, confirm=None, via: str = "web") -> VaUsers:
    """Create a public-demo account with interviewer, coder and reviewer on
    the demo project, terms accepted; returns the flushed user. *confirm*,
    when given, must equal *password* (the web form; the JSON endpoint sends
    one). *via* is the terms-acceptance path (``web`` or ``api``).

    Raises PublicDemoError: ``not_enabled`` (404) with the flag off,
    ``project_missing`` (503) before setup, ``invalid_username``,
    ``username_taken`` (409), ``invalid_password``, ``breached_password``,
    ``breach_check_unavailable`` (503, retryable), ``wrong_database`` (503,
    the database holds a project other than the demo's), ``cap_reached``
    (503, "The demo is full; try again later."). At the cap, with
    ``PUBLIC_DEMO_PURGE_ENABLED``, the account idle longest (at least
    ``PUBLIC_DEMO_EVICT_IDLE_DAYS``) is deleted first, in this transaction
    (``public_demo_purge_service.evict_one``; policy section 8).
    Writes nothing on a refusal. The caller commits, in one transaction
    with everything here (policy section 3: granted at sign-up).
    """
    if not enabled():
        raise PublicDemoError("Not found.", "not_enabled", 404)
    require_demo_database()
    try:
        name = accounts.clean_username(username)
    except accounts.UserAccountError as exc:
        raise PublicDemoError(str(exc), "invalid_username", field="username") from None
    _check_password(name, password, confirm)
    project_id = demo_project_id()
    project = db.session.get(VaProjectMaster, project_id)
    if project is None or project.project_status != VaStatuses.active:
        raise PublicDemoError("The demo is not ready yet. Please try again later.", "project_missing", 503)
    db.session.execute(sa.text("SELECT pg_advisory_xact_lock(hashtext(:name))"), {"name": _SIGNUP_LOCK})
    if db.session.scalar(sa.select(VaUsers.user_id).where(VaUsers.username == name)):
        raise PublicDemoError(accounts.USERNAME_IN_USE_MESSAGE, "username_taken", 409, field="username")
    if active_account_count() >= int(current_app.config["PUBLIC_DEMO_MAX_ACCOUNTS"]):
        # Lazy: the purge service imports this module.
        from app.services import public_demo_purge_service as purge

        if not purge.evict_one():
            log.warning("public demo sign-up refused: account cap reached")
            raise PublicDemoError(CAP_REACHED_MESSAGE, "cap_reached", 503)
    try:
        user = accounts.create_invited_user(
            {
                "email": None, "name": name, "phone": None, "mobile": None,
                "languages": list(ACCOUNT_LANGUAGES), "username": name, "is_public_demo": True,
            },
            via="self_signup",
        )
    except accounts.UserAccountError as exc:
        raise PublicDemoError(str(exc), "username_taken", 409, field="username") from None
    user.set_password(password)
    accounts.accept_terms(user, via=via)
    for role in DEMO_ROLES:
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project,
            project_id=project_id, grant_status=VaStatuses.active, notes="Public demo sign-up",
        ))
    db.session.flush()
    log.info("public demo account created | user=%s", user.user_id)
    return user


# ---------------------------------------------------------------------------
# Per-account limits (policy section 8), enforced where drafts and
# submissions are written; both web and device paths pass through them.
# ---------------------------------------------------------------------------


def _applies(user, project_id: str) -> bool:
    return bool(getattr(user, "is_public_demo", False)) and is_demo_project(project_id)


def _lock_account(user) -> None:
    """Serialise this account's limit checks until the transaction ends, so
    parallel requests cannot all count below a limit and then all write
    (policy section 8). The caller writes and commits in the same
    transaction."""
    db.session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"public_demo_user:{user.user_id}"},
    )


def signup_client_key(client_ip: str | None) -> str:
    """The sign-up limiter key for a client address: the address itself for
    IPv4, the /64 prefix for IPv6 (one household or carrier hands a device a
    whole /64, so per-address keys would let one machine rotate through
    millions). An IPv4-mapped IPv6 address keys as its IPv4 address; anything
    unparsable keys as itself."""
    try:
        ip = ipaddress.ip_address((client_ip or "").strip())
    except ValueError:
        return client_ip or ""
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def signup_remote_key() -> str:
    """``key_func`` for the sign-up routes' own limiter: the request's
    address through ``signup_client_key``. Never empty (an empty key makes
    flask-limiter skip the limit): a request without an address keys as the
    limiter's own fallback, the same one ``hit_signup_quota`` is called with."""
    return signup_client_key(get_remote_address())


def hit_signup_quota(client_ip: str) -> bool:
    """Spend one sign-up from the per-client quota
    (``PUBLIC_DEMO_SIGNUP_RATE_LIMIT``, keyed by ``signup_client_key``) and
    from the demo-wide one (``PUBLIC_DEMO_SIGNUP_GLOBAL_RATE_LIMIT``, one
    shared key), each in one atomic storage hit; False when any window is
    exhausted. The client windows are hit first and a refusal stops there, so
    one address cannot drain the demo-wide quota. Called by the sign-up
    handlers after the account is flushed and before commit, so parallel
    requests cannot pass a check-then-hit gap. True when the limiter is
    disabled."""
    from limits import parse_many

    from app import limiter

    if not getattr(limiter, "enabled", True):
        return True
    config = current_app.config
    # The limiter's own key prefix (RATELIMIT_KEY_PREFIX), which a direct
    # storage hit does not add by itself.
    prefix = [config["RATELIMIT_KEY_PREFIX"]] if config.get("RATELIMIT_KEY_PREFIX") else []
    client = signup_client_key(client_ip)
    per_client = parse_many(config.get("PUBLIC_DEMO_SIGNUP_RATE_LIMIT") or "30 per hour;200 per day")
    overall = parse_many(config.get("PUBLIC_DEMO_SIGNUP_GLOBAL_RATE_LIMIT") or "100 per hour")
    return all(
        limiter.limiter.hit(item, *prefix, "public_demo_signup", client) for item in per_client
    ) and all(
        limiter.limiter.hit(item, *prefix, "public_demo_signup_all") for item in overall
    )


def icd_rate_limit() -> str:
    """The per-account limit on ICD-11 / DORIS lookups (policy section 8),
    for a public-demo account only (``not_demo_user`` exempts the rest)."""
    return current_app.config.get("PUBLIC_DEMO_ICD_RATE_LIMIT") or "300 per hour"


def icd_global_rate_limit() -> str:
    """The limit on ICD-11 / DORIS lookups across every demo account, so the
    demo cannot starve the main deployment's coders on the shared WHO
    container (policy section 8)."""
    return current_app.config.get("PUBLIC_DEMO_ICD_GLOBAL_RATE_LIMIT") or "2000 per hour"


def icd_global_key() -> str:
    """``key_func`` of the demo-wide ICD bucket: one key for everybody."""
    return "public_demo_icd_all"


def not_demo_user() -> bool:
    """``exempt_when`` for the demo-only limits: True for anyone else."""
    from flask_login import current_user

    return not getattr(current_user, "is_public_demo", False)


def check_new_draft(user, project_id: str) -> None:
    """Refuse a new draft beyond the open-draft limit, or beyond the drafts
    started per day (rolling 24 hours) or in total, whatever their status, so
    starting and discarding cannot loop (429 ``demo_limit``). One query on the
    user's drafts, under the account lock."""
    if not _applies(user, project_id):
        return
    _lock_account(user)
    limit = int(current_app.config.get("PUBLIC_DEMO_OPEN_DRAFTS", 3))
    per_day = int(current_app.config.get("PUBLIC_DEMO_DRAFTS_PER_DAY", 10))
    total_limit = int(current_app.config.get("PUBLIC_DEMO_DRAFTS_TOTAL", 30))
    since = datetime.now(UTC) - timedelta(days=1)
    open_drafts, today, total = db.session.execute(
        sa.select(
            sa.func.count().filter(VaWebIntakeDraft.status == "draft"),
            sa.func.count().filter(VaWebIntakeDraft.created_at >= since),
            sa.func.count(),
        ).where(VaWebIntakeDraft.user_id == user.user_id)
    ).one()
    if open_drafts >= limit:
        raise WebIntakeError(
            f"The demo allows {limit} open interviews at a time. Submit or discard one first.",
            429, LIMIT_CODE,
        )
    if total >= total_limit:
        raise WebIntakeError(f"The demo allows {total_limit} interviews per account.", 429, LIMIT_CODE)
    if today >= per_day:
        raise WebIntakeError(
            f"The demo allows {per_day} new interviews a day. Please try again tomorrow.", 429, LIMIT_CODE
        )


def check_new_submission(user, project_id: str) -> None:
    """Refuse a submission beyond the daily (rolling 24 hours) or total
    limit (429 ``demo_limit``). One query on the user's submitted drafts."""
    if not _applies(user, project_id):
        return
    _lock_account(user)
    per_day = int(current_app.config.get("PUBLIC_DEMO_SUBMISSIONS_PER_DAY", 5))
    total_limit = int(current_app.config.get("PUBLIC_DEMO_SUBMISSIONS_TOTAL", 10))
    since = datetime.now(UTC) - timedelta(days=1)
    total, today = db.session.execute(
        sa.select(
            sa.func.count(),
            sa.func.count().filter(VaWebIntakeDraft.submitted_at >= since),
        ).where(VaWebIntakeDraft.user_id == user.user_id, VaWebIntakeDraft.status == "submitted")
    ).one()
    if total >= total_limit:
        raise WebIntakeError(f"The demo allows {total_limit} submissions per account.", 429, LIMIT_CODE)
    if today >= per_day:
        raise WebIntakeError(
            f"The demo allows {per_day} submissions a day. Please try again tomorrow.", 429, LIMIT_CODE
        )


def check_new_registration(user, project_id: str) -> None:
    """Refuse a death registration beyond the daily (rolling 24 hours) or
    total limit (429 ``demo_limit``); direct starts are not registrations.
    One query on ``ix_va_death_register_registered_by``."""
    if not _applies(user, project_id):
        return
    _lock_account(user)
    per_day = int(current_app.config.get("PUBLIC_DEMO_REGISTRATIONS_PER_DAY", 5))
    total_limit = int(current_app.config.get("PUBLIC_DEMO_REGISTRATIONS_TOTAL", 25))
    since = datetime.now(UTC) - timedelta(days=1)
    total, today = db.session.execute(
        sa.select(
            sa.func.count(),
            sa.func.count().filter(VaDeathRegister.created_at >= since),
        ).where(VaDeathRegister.registered_by == user.user_id, VaDeathRegister.source == "register")
    ).one()
    if total >= total_limit:
        raise WebIntakeError(f"The demo allows {total_limit} death registrations per account.", 429, LIMIT_CODE)
    if today >= per_day:
        raise WebIntakeError(
            f"The demo allows {per_day} death registrations a day. Please try again tomorrow.",
            429, LIMIT_CODE,
        )


def attachment_limits(project_id: str) -> tuple[int, int] | None:
    """``(max bytes per file, max files per draft)`` on the demo project, or
    None elsewhere (the caller keeps its own limits)."""
    if not is_demo_project(project_id):
        return None
    config = current_app.config
    return (
        int(config.get("PUBLIC_DEMO_ATTACHMENT_MAX_BYTES", 10 * 1024 * 1024)),
        int(config.get("PUBLIC_DEMO_ATTACHMENTS_PER_DRAFT", 6)),
    )


def default_org_unit_id(project_id: str):
    """The demo project's one unit, which every demo draft uses (the project
    has levels, so a draft needs a unit); None elsewhere or before setup."""
    if not is_demo_project(project_id):
        return None
    return db.session.scalar(
        sa.select(MasOrgUnit.org_unit_id).where(
            MasOrgUnit.project_id == project_id,
            MasOrgUnit.unit_code == DEMO_UNIT_CODE,
            MasOrgUnit.is_active.is_(True),
        )
    )


# ---------------------------------------------------------------------------
# Setup (flask public-demo setup)
# ---------------------------------------------------------------------------


def _project_defaults(project_id: str) -> dict:
    return dict(
        project_id=project_id,
        project_code=project_id,
        project_name=PROJECT_NAME,
        project_nickname="Public demo",
        project_structure_mode="organization",
        web_intake_mode="both",
        coding_intake_mode="pick_and_choose",
        self_coding_enabled=True,
        icd_classification="icd11",
        cod_entry_mode="doris",
        masked_cod_required=False,
        narrative_qa_enabled=False,
        social_autopsy_enabled=False,
        reviewer_social_autopsy_enabled=False,
        web_intake_default_locale="en",
        web_intake_available_locales=["en"],
        web_intake_narration_languages=list(NARRATION_LANGUAGES),
        web_intake_intake_note="",
        web_intake_death_summary_enabled=True,
        web_intake_medical_records_enabled=True,
        recode_window_minutes=RECODE_WINDOW_MINUTES,
        demo_training_enabled=False,
    )


#: Settings setup resets on an existing demo project (policy section 4).
_ENFORCED = (
    "project_structure_mode", "web_intake_mode", "self_coding_enabled", "icd_classification",
    "cod_entry_mode", "masked_cod_required", "narrative_qa_enabled", "social_autopsy_enabled",
    "reviewer_social_autopsy_enabled", "web_intake_narration_languages",
    "web_intake_death_summary_enabled", "web_intake_medical_records_enabled",
    "recode_window_minutes", "demo_training_enabled",
)


def setup_public_demo_project(actor: VaUsers) -> dict:
    """Create the demo project, or bring an existing one to the policy's
    settings (section 4). Idempotent; commits.

    Creates or keeps: the project, its automatic site and web form, the
    template levels and the one unit ``PUBDEMO`` every demo draft uses, and
    respondent consent required with the seeded English and Hindi notice
    approved by *actor* (an active admin: the consent audit's actor). Raises
    PublicDemoError ``not_enabled`` with the flag off, ``admin_required``,
    ``project_collision`` when a legacy research project holds the id.
    """
    from app.services import consent_service
    from app.services import organization_service as org

    if not enabled():
        raise PublicDemoError("PUBLIC_DEMO_ENABLED is off on this deployment.", "not_enabled")
    if actor is None or not actor.is_active or not actor.is_admin():
        raise PublicDemoError("--by must name an active admin account.", "admin_required")
    require_demo_database()
    project_id = demo_project_id()
    created = {"project": False, "unit": False, "notices_seeded": 0, "notices_approved": 0,
               "settings_reset": []}
    try:
        project = db.session.get(VaProjectMaster, project_id)
        defaults = _project_defaults(project_id)
        if project is None:
            if db.session.get(VaResearchProjects, project_id):
                raise PublicDemoError("A legacy project already uses that id.", "project_collision")
            project = VaProjectMaster(**defaults)
            db.session.add(project)
            db.session.flush()
            created["project"] = True
        else:
            for name in _ENFORCED:
                if getattr(project, name) != defaults[name]:
                    setattr(project, name, defaults[name])
                    created["settings_reset"].append(name)
        org.ensure_organization_site(project_id)
        org.seed_default_organization(project_id, include_cadres=False)
        if org.find_unit_by_code(project_id, DEMO_UNIT_CODE) is None:
            top = org.list_levels(project_id)[0]
            org.create_unit(project_id, org_level_id=top.org_level_id,
                            unit_code=DEMO_UNIT_CODE, unit_name="Public demo")
            created["unit"] = True
        if not consent_service.active_versions(project_id):
            created["notices_seeded"] = len(consent_service.seed_notice_versions(actor, project_id))
        for version in consent_service.active_versions(project_id):
            if version.approved_at is None:
                consent_service.approve_notice_version(actor, project_id, str(version.notice_version_id))
                created["notices_approved"] += 1
        consent_service.save_settings(actor, project_id, {"consent_required": True})
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    log.info("public demo project set up | project=%s | created=%s", project_id, created)
    return created
