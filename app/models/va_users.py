import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db, login
from typing import Optional
from flask_login import UserMixin
from datetime import UTC, datetime, timezone
from app.models.va_selectives import VaStatuses
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from werkzeug.security import generate_password_hash, check_password_hash

#: Interviewer sex, as WHO VA 2022 Id10010b's choices.
USER_SEX_VALUES = ("female", "male", "undetermined")


class VaUsers(UserMixin, db.Model):
    __tablename__ = "va_users"
    # docs/policy/mobile-sign-in.md section 1: an account has an email, a
    # sign-in mobile number, or both; never neither.
    __table_args__ = (
        sa.CheckConstraint(
            "email IS NOT NULL OR mobile_login IS NOT NULL", name="email_or_mobile"
        ),
    )
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, index=True, primary_key=True
    )
    name: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    # Null for a mobile-only account (docs/policy/mobile-sign-in.md).
    email: so.Mapped[str | None] = so.mapped_column(
        sa.String(128), unique=True, nullable=True, index=True
    )
    password: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(256), nullable=False
    )
    vacode_language: so.Mapped[list[str]] = so.mapped_column(
        ARRAY(sa.String), nullable=False
    )
    timezone: so.Mapped[str] = so.mapped_column(
        sa.String(64), default='Asia/Kolkata', nullable=False, server_default='Asia/Kolkata'
    )
    vacode_formcount: so.Mapped[int] = so.mapped_column(
        sa.Integer, default=0, nullable=False
    )
    permission: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False)
    landing_page: so.Mapped[str] = so.mapped_column(sa.String(255), nullable=False)
    pw_reset_t_and_c: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=False, nullable=False)
    email_verified: so.Mapped[bool] = so.mapped_column(sa.Boolean, default=False, nullable=False)
    phone: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(15), nullable=True
    )
    # The canonical 10-digit number used for sign-in: set only when ``phone``
    # canonicalises and no other account holds it (user_account_service.
    # assign_phone). ``phone`` stays the free text that was typed.
    mobile_login: so.Mapped[str | None] = so.mapped_column(
        sa.String(10), unique=True, nullable=True
    )
    # When a mobile-only account first redeemed a sign-in code: its
    # equivalent of email_verified (mobile-sign-in.md section 2).
    mobile_verified_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    other: so.Mapped[Optional[dict]] = so.mapped_column(JSONB, nullable=True)
    # Interviewer demographics (PII, optional; digitva-vzk.3). Web intake
    # prefills and locks WHO Id10010a (age, from year_of_birth at interview
    # time) and Id10010b (sex: one of USER_SEX_VALUES). Never logged or exported.
    year_of_birth: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    sex: so.Mapped[str | None] = so.mapped_column(sa.String(16), nullable=True)
    user_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    user_created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    user_updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # Bumped by a factor reset, a password reset and the break-glass CLI to
    # invalidate every session and remember cookie for this user (docs/policy/
    # authentication-factors.md section 8). 0 means "no version": get_id()
    # then returns the bare user_id so sessions issued before this column
    # existed keep working.
    auth_session_version: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )

    def __repr__(self):
        return f"VA User -> {self.email} ({self.user_status}): {self.name}"

    @property
    def is_mobile_only(self) -> bool:
        """No email: signs in by mobile number with a server-generated
        password and may never choose one (mobile-sign-in.md section 3)."""
        return self.email is None

    @property
    def sign_in_verified(self) -> bool:
        """The login's "verified" check: a verified email, or a redeemed
        sign-in code. Either is enough, so adding an email to a mobile-only
        account that already redeemed a code does not lock its holder out."""
        return bool(self.email_verified) or self.mobile_verified_at is not None

    def get_id(self) -> str:
        if self.auth_session_version:
            return f"{self.user_id}:{self.auth_session_version}"
        return str(self.user_id)

    def bump_session_version(self) -> None:
        """Invalidate every existing session/remember cookie for this user.

        Caller commits. Used by password reset, an admin factor reset and
        the break-glass CLI (see app.services.totp_service.reset_factors).
        """
        self.auth_session_version = (self.auth_session_version or 0) + 1

    def landing_url(self) -> str:
        """Return the correct post-login URL for this user's landing_page."""
        from flask import url_for
        if self.landing_page == "admin":
            return url_for("admin.admin_index")
        if self.landing_page == "data_manager":
            return url_for("data_management.dashboard")
        if self.landing_page == "coder" and self.is_coder():
            return url_for("coding.dashboard")
        if self.landing_page == "reviewer" and self.is_reviewer():
            return url_for("reviewing.dashboard")
        if self.landing_page == "sitepi" and self.is_site_pi():
            return url_for("sitepi.dashboard")
        if self.landing_page == "intake" and self.is_interviewer():
            return url_for("intake.dashboard")
        if self.is_coder():
            return url_for("coding.dashboard")
        if self.is_data_manager():
            return url_for("data_management.dashboard")
        if self.is_reviewer():
            return url_for("reviewing.dashboard")
        if self.is_site_pi():
            return url_for("sitepi.dashboard")
        if self.is_interviewer():
            return url_for("intake.dashboard")
        if self.is_viewer():
            return url_for("data_management.dashboard")
        return url_for("va_main.va_index")

    @property
    def is_active(self):
        """Flask-Login hook: only active users may log in or keep a session."""
        return self.user_status == VaStatuses.active

    def set_interviewer_profile(self, year_of_birth, sex) -> None:
        """Validate and set the optional year of birth and sex (vzk.3).

        Blank or None clears a value. A year must be a whole number from
        1900 to the current year; sex one of ``USER_SEX_VALUES`` (the WHO
        Id10010b choices). Raises ``ValueError`` with a caller-safe message.
        """
        if year_of_birth in (None, ""):
            year = None
        else:
            try:
                year = int(year_of_birth)
            except (TypeError, ValueError) as exc:
                raise ValueError("Year of birth must be a whole number.") from exc
            if not 1900 <= year <= datetime.now(UTC).year:
                raise ValueError("Year of birth must be between 1900 and this year.")
        sex = (sex or "").strip().lower() or None
        if sex is not None and sex not in USER_SEX_VALUES:
            raise ValueError("Sex must be one of " + ", ".join(USER_SEX_VALUES) + ".")
        self.year_of_birth = year
        self.sex = sex

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

    def is_coder(self):
        """Role gate only; which submissions the user codes is authz's."""
        return bool(self.get_coder_va_forms()) or self._holds_unit_grant("coder")

    def is_interviewer(self):
        if self.get_interviewer_va_forms():
            return True
        # Unit-scoped grants do not resolve to va_forms (see
        # _get_granted_va_forms), but web intake supports them: the project,
        # site and unit a questionnaire may be filled for are still decided by
        # web_intake_service.interviewer_context()/_require_scope(), so this
        # only opens the role gate, not the scope.
        return bool(self.get_interviewer_org_units())

    def get_interviewer_org_units(self):
        from app.models import VaAccessRoles
        from app.services.org_grant_service import granted_units

        return granted_units(self.user_id, VaAccessRoles.interviewer)

    def get_interviewer_va_forms(self):
        return self._get_granted_va_forms("interviewer")

    def is_interview_supervisor(self):
        """Role gate for intake supervision, as ``authz.effective_roles`` says:
        an ``interview_supervisor`` unit grant, the In-charge (site_pi at a
        unit) and project_pi on a tree project.

        Opens the role gate only: which cases the user supervises is
        ``case_transition_service.is_interview_supervisor_for``.
        """
        from app.services.authz import effective_roles

        return "interview_supervisor" in effective_roles(self)

    def is_coding_tester(self):
        """Role gate only; which submissions the user codes is authz's."""
        return bool(self.get_coding_tester_va_forms()) or self._holds_unit_grant("coding_tester")

    def is_site_pi(self):
        """The role gate, as ``authz.effective_roles`` says (a live site_pi
        grant on a pair or a unit, the In-charge). Scope is authz's."""
        from app.services.authz import effective_roles

        return "site_pi" in effective_roles(self)

    def is_reviewer(self):
        """Role gate only; which submissions the user reviews is authz's."""
        return bool(self._get_granted_va_forms("reviewer")) or self._holds_unit_grant("reviewer")

    def _holds_unit_grant(self, role: str) -> bool:
        """Holds a live unit grant of *role* (role gate only, never scope).

        A unit grant resolves to the forms its subtree actually holds (see
        _get_granted_va_forms), so a subtree with nothing in it yet has no
        forms; the role gate must still open, as it does for interviewers.
        """
        from app.models import VaAccessRoles
        from app.services.org_grant_service import granted_units

        return bool(granted_units(self.user_id, VaAccessRoles(role)))

    def is_data_manager(self):
        """Role gate for data management, as ``authz.effective_roles`` says:
        a data_manager grant at any scope, site_pi at a unit (the In-charge)
        and project_pi on a tree project (policy: access-control-model.md,
        "Role To Scope Rules"). Opens the gate only; scope is authz's."""
        from app.services.authz import effective_roles

        return "data_manager" in effective_roles(self)

    def is_mentor_institute_admin(self) -> bool:
        """Administers a mentoring institute (flag on the membership, not a grant)."""
        from app.services.mentor_institute_service import administered_institutes

        return bool(administered_institutes(self.user_id))

    def is_admin(self):
        from app.models import (
            VaAccessRoles,
            VaAccessScopeTypes,
            VaUserAccessGrants,
            VaStatuses,
        )

        stmt = sa.select(sa.exists().where(
            VaUserAccessGrants.user_id == self.user_id,
            VaUserAccessGrants.role == VaAccessRoles.admin,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.global_scope,
            VaUserAccessGrants.grant_status == VaStatuses.active,
        ))
        return bool(db.session.scalar(stmt))

    def is_project_pi(self) -> bool:
        """Answer the project_pi role gate: does the user hold any live PI grant?

        Scope — *which* projects — is answered by get_project_pi_projects();
        this is an EXISTS over the same four conditions plus the active-project
        rule, so the gate costs one indexed lookup instead of a project-id set.
        """
        from app.models import (
            VaAccessRoles,
            VaAccessScopeTypes,
            VaUserAccessGrants,
            VaStatuses,
        )
        from app.services.org_grant_service import active_project_condition

        stmt = sa.select(sa.exists().where(
            VaUserAccessGrants.user_id == self.user_id,
            VaUserAccessGrants.role == VaAccessRoles.project_pi,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            active_project_condition(VaUserAccessGrants.project_id),
        ))
        return bool(db.session.scalar(stmt))

    def has_any_active_grant(self) -> bool:
        """Whether the user holds any active grant, of any role or scope.

        Gates the area dashboard's navbar link. Deliberately loose: a grant on
        a closed project still shows the link, and the page then shows an
        empty area rather than an error (docs/policy/area-dashboard.md).
        """
        from app.models import VaStatuses, VaUserAccessGrants

        stmt = sa.select(sa.exists().where(
            VaUserAccessGrants.user_id == self.user_id,
            VaUserAccessGrants.grant_status == VaStatuses.active,
        ))
        return bool(db.session.scalar(stmt))

    def has_demo_training_access(self) -> bool:
        from app.services.demo_project_service import get_demo_training_project_ids

        return bool(get_demo_training_project_ids())

    def can_access_coding_dashboard(self) -> bool:
        return (
            self.is_admin()
            or self.is_coder()
            or self.is_coding_tester()
            or self.has_demo_training_access()
        )

    def get_project_pi_projects(self):
        from app.models import (
            VaAccessRoles,
            VaAccessScopeTypes,
            VaUserAccessGrants,
            VaStatuses,
        )
        from app.services.org_grant_service import active_project_condition

        stmt = sa.select(VaUserAccessGrants.project_id).where(
            VaUserAccessGrants.user_id == self.user_id,
            VaUserAccessGrants.role == VaAccessRoles.project_pi,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            active_project_condition(VaUserAccessGrants.project_id),
        )
        return set(db.session.scalars(stmt).all())

    def can_manage_project(self, project_id):
        return project_id in self.get_project_pi_projects()

    def get_coder_va_forms(self):
        return self._get_granted_va_forms("coder")

    def get_coding_tester_va_forms(self):
        return self._get_granted_va_forms("coding_tester")

    def get_data_manager_va_forms(self):
        return self._get_granted_va_forms("data_manager")

    def get_viewer_projects(self) -> set[str]:
        """Projects granted to this user as a read-only viewer.

        ``collaborator`` and ``collaborator_pii`` have identical reach — the
        only difference is whether personal data is redacted once access is
        granted (app/services/viewer_pii_service.py), which is decided
        separately from scope. Combined here so a scope check only has to
        ask once. See docs/policy/access-control-model.md, "collaborator".
        """
        return (
            self._get_granted_project_ids("collaborator")
            | self._get_granted_project_ids("collaborator_pii")
        )

    def get_viewer_project_sites(self) -> set[tuple[str, str]]:
        return (
            self._get_granted_project_site_pairs("collaborator")
            | self._get_granted_project_site_pairs("collaborator_pii")
        )

    def get_viewer_org_unit_ids(self):
        """Org units reachable through a collaborator/collaborator_pii grant.

        Reuses the shared subtree resolution in org_grant_service rather
        than walking ``path`` (ltree) itself.
        """
        from app.models import VaAccessRoles
        from app.services.org_grant_service import scope_unit_ids_for_roles

        return scope_unit_ids_for_roles(
            self.user_id,
            (VaAccessRoles.collaborator, VaAccessRoles.collaborator_pii),
        )

    def is_viewer(self) -> bool:
        """Whether this user holds any active collaborator/collaborator_pii grant."""
        return bool(
            self.get_viewer_projects()
            or self.get_viewer_project_sites()
            or self.get_viewer_org_unit_ids()
        )

    def _get_granted_va_forms(self, role: str) -> set[str]:
        from app.models import (
            MapProjectSiteOdk,
            VaForms,
            VaProjectSites,
            VaSubmissions,
            VaUserAccessGrants,
            VaAccessRoles,
            VaAccessScopeTypes,
            VaStatuses,
        )
        from app.services.demo_project_service import get_coder_demo_project_form_ids
        from app.services.org_grant_service import (
            active_project_condition,
            scope_unit_ids_select,
        )

        role_enum = VaAccessRoles(role)
        active_status = VaStatuses.active
        project_scope_exists = sa.exists(
            sa.select(1).where(
                VaUserAccessGrants.user_id == self.user_id,
                VaUserAccessGrants.role == role_enum,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
                VaUserAccessGrants.grant_status == active_status,
                VaUserAccessGrants.project_id == VaForms.project_id,
            )
        )
        project_site_scope_exists = sa.exists(
            sa.select(1)
            .select_from(VaUserAccessGrants)
            .join(
                VaProjectSites,
                VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
            )
            .where(
                VaUserAccessGrants.user_id == self.user_id,
                VaUserAccessGrants.role == role_enum,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
                VaUserAccessGrants.grant_status == active_status,
                VaProjectSites.project_site_status == active_status,
                VaProjectSites.project_id == VaForms.project_id,
                VaProjectSites.site_id == VaForms.site_id,
            )
        )
        active_project_site_exists = sa.exists(
            sa.select(1).where(
                VaProjectSites.project_id == VaForms.project_id,
                VaProjectSites.site_id == VaForms.site_id,
                VaProjectSites.project_site_status == active_status,
            )
        )
        # A unit-scoped grant reaches only the forms under its subtree: a
        # form with a submission routed into the subtree, or whose ODK
        # mapping falls back to a unit inside it. Never the whole project:
        # that failed open for every form-level gate. Which submissions of
        # such a form the user may open is still narrowed by the routed unit
        # (authz.scope_filter).
        subtree = scope_unit_ids_select(self.user_id, [role_enum])
        org_unit_scope_exists = sa.or_(
            sa.exists(
                sa.select(1).where(
                    VaSubmissions.va_form_id == VaForms.form_id,
                    VaSubmissions.org_unit_id.in_(subtree),
                )
            ),
            sa.exists(
                sa.select(1).where(
                    MapProjectSiteOdk.project_id == VaForms.project_id,
                    MapProjectSiteOdk.site_id == VaForms.site_id,
                    MapProjectSiteOdk.odk_form_id == VaForms.odk_form_id,
                    sa.cast(MapProjectSiteOdk.odk_project_id, sa.Text)
                    == VaForms.odk_project_id,
                    MapProjectSiteOdk.org_unit_id.in_(subtree),
                )
            ),
        )
        stmt = (
            sa.select(VaForms.form_id)
            .where(VaForms.form_status == active_status)
            # A closed project resolves no grant of any scope, so one
            # condition on the form's project covers all three branches
            # below (docs/policy/access-control-model.md, "Closed projects").
            .where(active_project_condition(VaForms.project_id))
            .where(
                sa.or_(
                    project_scope_exists,
                    project_site_scope_exists,
                    org_unit_scope_exists,
                )
            )
        )
        if role == "coder":
            stmt = stmt.where(active_project_site_exists)
        granted_form_ids = set(db.session.scalars(stmt).all())
        if role in ("coder", "coding_tester", "reviewer") and self._demo_eligible():
            return granted_form_ids | get_coder_demo_project_form_ids()
        return granted_form_ids

    def _demo_eligible(self) -> bool:
        """Whether demo projects are open to this user: authz adds the demo
        grants only for admins and people who code or review somewhere
        (owner 2026-10-03), so the answer is whether any were added."""
        from app.services.authz import resolve_grants

        return any(g.virtual for g in resolve_grants(self).grants)

    # -- grant resolvers behind the getters above ----------------------------

    def _get_granted_project_ids(self, role: str) -> set[str]:
        """Projects the user holds *role* in through a project-scoped grant.

        Closed projects are excluded here, upstream of every caller -- see
        ``org_grant_service.active_project_condition``.
        """
        from app.models import (
            VaAccessRoles,
            VaAccessScopeTypes,
            VaUserAccessGrants,
            VaStatuses,
        )
        from app.services.org_grant_service import active_project_condition

        stmt = sa.select(VaUserAccessGrants.project_id).where(
            VaUserAccessGrants.user_id == self.user_id,
            VaUserAccessGrants.role == VaAccessRoles(role),
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            active_project_condition(VaUserAccessGrants.project_id),
        )
        return {
            project_id
            for project_id in db.session.scalars(stmt).all()
            if project_id is not None
        }

    def _get_granted_project_site_pairs(self, role: str) -> set[tuple[str, str]]:
        """Active (project_id, site_id) pairs the user holds *role* on.

        Excludes pairs of a closed project -- see
        ``org_grant_service.active_project_condition``.
        """
        from app.models import (
            VaAccessRoles,
            VaAccessScopeTypes,
            VaProjectSites,
            VaUserAccessGrants,
            VaStatuses,
        )
        from app.services.org_grant_service import active_project_condition

        stmt = (
            sa.select(VaProjectSites.project_id, VaProjectSites.site_id)
            .join(
                VaUserAccessGrants,
                VaUserAccessGrants.project_site_id == VaProjectSites.project_site_id,
            )
            .where(
                VaUserAccessGrants.user_id == self.user_id,
                VaUserAccessGrants.role == VaAccessRoles(role),
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
                VaUserAccessGrants.grant_status == VaStatuses.active,
                VaProjectSites.project_site_status == VaStatuses.active,
                active_project_condition(VaProjectSites.project_id),
            )
        )
        return {(project_id, site_id) for project_id, site_id in db.session.execute(stmt)}


@login.user_loader
def load_user(user_id: str):
    # get_id() encodes "<uuid>:<version>" once a user's session version is
    # bumped, bare "<uuid>" otherwise (see VaUsers.get_id). A UUID never
    # contains a colon, so rpartition is unambiguous either way.
    raw_uid, sep, raw_version = user_id.rpartition(":")
    if not sep:
        raw_uid, raw_version = user_id, "0"
    try:
        uid = uuid.UUID(raw_uid)
        version = int(raw_version)
    except (ValueError, TypeError):
        return None
    user = db.session.get(VaUsers, uid)
    # A deactivated user's existing session or remember cookie stops working,
    # and so does one whose session version no longer matches (factor reset,
    # password reset, break-glass CLI).
    if user is None or not user.is_active:
        return None
    if (user.auth_session_version or 0) != version:
        return None
    return user


@login.request_loader
def load_user_from_device_token(request):
    """``Authorization: Bearer <access token>`` for the device API only.

    Scoped to ``/api/v1/device/`` so a stolen device token can never drive
    the browser UI or any other API. Resolves only a live, unrevoked session
    on an unrevoked device (``device_auth_service.resolve_access_token``) and
    stamps it on ``g.device_session``; the device blueprint requires that
    stamp, so a cookie session cannot stand in for it there. Flask-Login
    tries the session cookie first, so on these paths a cookie simply leaves
    the stamp unset and the call is refused.
    """
    from flask import g

    from app.services.device_auth_service import DEVICE_API_PREFIX, resolve_access_token

    if not request.path.startswith(DEVICE_API_PREFIX):
        return None
    scheme, _sep, token = request.headers.get("Authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return None
    resolved = resolve_access_token(token)
    if resolved is None:
        return None
    g.device_session, user = resolved
    return user
