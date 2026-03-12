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
        if self.landing_page:
            return url_for("va_main.va_dashboard", va_role=self.landing_page)
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

    def get_project_pi_projects(self):
        from app.models import (
            VaAccessRoles,
            VaAccessScopeTypes,
            VaUserAccessGrants,
            VaStatuses,
        )

        stmt = sa.select(VaUserAccessGrants.project_id).where(
            VaUserAccessGrants.user_id == self.user_id,
            VaUserAccessGrants.role == VaAccessRoles.project_pi,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            VaUserAccessGrants.grant_status == VaStatuses.active,
        )
        return set(db.session.scalars(stmt).all())

    def can_manage_project(self, project_id):
        return project_id in self.get_project_pi_projects()

    def get_coder_va_forms(self):
        return self._get_granted_va_forms("coder")

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
            )
        )
        if project_id:
            stmt = stmt.where(VaProjectSites.project_id == project_id)
        return set(db.session.scalars(stmt).all())

    def get_reviewer_va_forms(self):
        return self._get_granted_va_forms("reviewer")

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
        for legacy_role, va_forms in self.permission.items():
            if legacy_role in {"coder", "reviewer", "sitepi"}:
                continue
            if va_form in va_forms:
                return True
        return False

    def _get_granted_va_forms(self, role: str) -> set[str]:
        from app.models import (
            VaForms,
            VaProjectSites,
            VaUserAccessGrants,
            VaAccessRoles,
            VaAccessScopeTypes,
            VaStatuses,
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
        stmt = (
            sa.select(VaForms.form_id)
            .where(VaForms.form_status == active_status)
            .where(sa.or_(project_scope_exists, project_site_scope_exists))
        )
        return set(db.session.scalars(stmt).all())


@login.user_loader
def load_user(user_id: str):
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        return None
    return db.session.get(VaUsers, uid)
