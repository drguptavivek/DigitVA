import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db, login
from typing import Optional
from flask_login import UserMixin
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from werkzeug.security import generate_password_hash, check_password_hash


class VaUsers(UserMixin, db.Model):
    __tablename__ = "va_users"
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, index=True, primary_key=True
    )
    name: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    email: so.Mapped[str] = so.mapped_column(
        sa.String(128), unique=True, nullable=False, index=True
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
    other: so.Mapped[Optional[dict]] = so.mapped_column(JSONB, nullable=True)
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

    def __repr__(self):
        return f"VA User -> {self.email} ({self.user_status}): {self.name}"

    def get_id(self) -> str:
        return str(self.user_id)

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
        return url_for("va_main.va_index")

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

    def is_coder(self, va_form=None):
        coder_va_form = self.get_coder_va_forms()
        if va_form:
            return va_form in coder_va_form
        return bool(coder_va_form)

    def is_interviewer(self, va_form=None):
        interviewer_va_form = self.get_interviewer_va_forms()
        if va_form:
            return va_form in interviewer_va_form
        if interviewer_va_form:
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

    def is_coding_tester(self, va_form=None):
        tester_forms = self.get_coding_tester_va_forms()
        if va_form:
            return va_form in tester_forms
        return bool(tester_forms)

    def is_site_pi(self, va_form=None):
        site_pi_va_form = self.get_site_pi_va_forms()
        if va_form:
            return va_form in site_pi_va_form
        return bool(site_pi_va_form)

    def is_reviewer(self, va_form=None):
        reviewer_va_form = self.get_reviewer_va_forms()
        if va_form:
            return va_form in reviewer_va_form
        return bool(reviewer_va_form)

    def is_data_manager(self, project_id=None, site_id=None):
        if project_id and site_id:
            return self.has_data_manager_submission_access(project_id, site_id)
        if project_id:
            return project_id in self.get_data_manager_projects()
        return bool(
            self.get_data_manager_projects() or self.get_data_manager_project_sites()
        )

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

    def get_coding_tester_projects(self) -> set[str]:
        return self._get_granted_project_ids("coding_tester")

    def get_coding_tester_project_site_pairs(self) -> set[tuple[str, str]]:
        return self._get_granted_project_site_pairs("coding_tester")

    def get_site_pi_va_forms(self):
        return self._get_granted_va_forms("site_pi")

    def get_site_pi_sites(self, project_id=None):
        from app.models import (
            VaProjectSites,
            VaUserAccessGrants,
            VaAccessRoles,
            VaAccessScopeTypes,
            VaStatuses,
        )
        from app.services.org_grant_service import active_project_condition

        stmt = (
            sa.select(VaProjectSites.site_id)
            .join(
                VaUserAccessGrants,
                VaUserAccessGrants.project_site_id == VaProjectSites.project_site_id,
            )
            .where(
                VaUserAccessGrants.user_id == self.user_id,
                VaUserAccessGrants.role == VaAccessRoles.site_pi,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
                VaUserAccessGrants.grant_status == VaStatuses.active,
                VaProjectSites.project_site_status == VaStatuses.active,
                active_project_condition(VaProjectSites.project_id),
            )
        )
        if project_id:
            stmt = stmt.where(VaProjectSites.project_id == project_id)
        return set(db.session.scalars(stmt).all())

    def get_reviewer_va_forms(self):
        return self._get_granted_va_forms("reviewer")

    def get_data_manager_projects(self):
        return self._get_granted_project_ids("data_manager")

    def get_data_manager_va_forms(self):
        return self._get_granted_va_forms("data_manager")

    def get_data_manager_project_sites(self):
        return self._get_granted_project_site_pairs("data_manager")

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

    def get_dm_view_projects(self) -> set[str]:
        """Projects reachable for the data-management view: data_manager OR viewer."""
        return self.get_data_manager_projects() | self.get_viewer_projects()

    def get_dm_view_project_sites(self) -> set[tuple[str, str]]:
        """Project/site pairs reachable for the data-management view."""
        return self.get_data_manager_project_sites() | self.get_viewer_project_sites()

    def has_data_manager_submission_access(self, project_id: str, site_id: str) -> bool:
        if project_id in self.get_data_manager_projects():
            return True
        return (project_id, site_id) in self.get_data_manager_project_sites()

    def has_data_manager_form_access(self, va_form: str) -> bool:
        from app.models import VaForms

        row = db.session.execute(
            sa.select(VaForms.project_id, VaForms.site_id).where(VaForms.form_id == va_form)
        ).first()
        if not row:
            return False
        return self.has_data_manager_submission_access(row.project_id, row.site_id)

    def get_all_accessible_va_forms(self):
        all_va_forms = set()
        if self.permission:
            for role, va_forms in self.permission.items():
                all_va_forms.update(va_forms)
        return all_va_forms

    def has_va_form_access(self, va_form, role=None):
        if role == "coder":
            return va_form in self.get_coder_va_forms()
        if role == "reviewer":
            return va_form in self.get_reviewer_va_forms()
        if role == "sitepi":
            return va_form in self.get_site_pi_va_forms()
        if role:
            return role in self.permission and va_form in self.permission[role]
        if va_form in self.get_coder_va_forms():
            return True
        if va_form in self.get_reviewer_va_forms():
            return True
        if va_form in self.get_site_pi_va_forms():
            return True
        if self.has_data_manager_form_access(va_form):
            return True
        for legacy_role, va_forms in self.permission.items():
            if legacy_role in {"coder", "reviewer", "sitepi"}:
                continue
            if va_form in va_forms:
                return True
        return False

    def _get_granted_va_forms(self, role: str) -> set[str]:
        from app.models import (
            MasOrgUnit,
            VaForms,
            VaProjectSites,
            VaUserAccessGrants,
            VaAccessRoles,
            VaAccessScopeTypes,
            VaStatuses,
        )
        from app.services.demo_project_service import get_coder_demo_project_form_ids
        from app.services.org_grant_service import active_project_condition

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
        # A unit-scoped grant reaches the forms of its unit's project. Which
        # of that project's *submissions* the user may open is then narrowed by
        # the routed unit (see coder_workflow_service._org_unit_scope_filter);
        # a project without an organization tree has no unit grants, so this
        # adds nothing for it.
        org_unit_scope_exists = sa.exists(
            sa.select(1)
            .select_from(VaUserAccessGrants)
            .join(
                MasOrgUnit,
                MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id,
            )
            .where(
                VaUserAccessGrants.user_id == self.user_id,
                VaUserAccessGrants.role == role_enum,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
                VaUserAccessGrants.grant_status == active_status,
                MasOrgUnit.is_active.is_(True),
                MasOrgUnit.project_id == VaForms.project_id,
            )
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
        if role in ("coder", "coding_tester", "data_manager"):
            return granted_form_ids | get_coder_demo_project_form_ids()
        return granted_form_ids

    # -- unit-scoped grants (health-system projects) -----------------------
    #
    # These resolve grants to organization-unit ids. Coding and reviewer
    # enforcement still runs off va_forms (see _get_granted_va_forms); routing
    # submissions to units is phase 3 and enforcement phase 4, so nothing here
    # widens access on its own. See app/services/org_grant_service.py.

    def get_org_unit_scope_ids(self, role: str) -> set[uuid.UUID]:
        """Active units inside the subtree of any *role* unit-grant this user holds."""
        from app.models import VaAccessRoles
        from app.services.org_grant_service import scope_unit_ids

        return scope_unit_ids(self.user_id, VaAccessRoles(role))

    def get_org_unit_grant_units(self, role: str):
        """The units this user holds *role* at directly, without their subtrees."""
        from app.models import VaAccessRoles
        from app.services.org_grant_service import granted_units

        return granted_units(self.user_id, VaAccessRoles(role))

    def get_coder_org_unit_ids(self) -> set[uuid.UUID]:
        return self.get_org_unit_scope_ids("coder")

    def get_reviewer_org_unit_ids(self) -> set[uuid.UUID]:
        return self.get_org_unit_scope_ids("reviewer")

    def get_org_unit_projects(self, role: str) -> set[str]:
        """Projects this user holds *role* in through a unit-scoped grant."""
        from app.models import VaAccessRoles
        from app.services.org_grant_service import granted_project_ids

        return granted_project_ids(self.user_id, VaAccessRoles(role))

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
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        return None
    return db.session.get(VaUsers, uid)
