import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses, VaAccessRoles, VaAccessScopeTypes


class VaUserAccessGrants(db.Model):
    __tablename__ = "va_user_access_grants"
    _role_enum = sa.Enum(
        VaAccessRoles,
        name="access_role_enum",
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    )
    _scope_enum = sa.Enum(
        VaAccessScopeTypes,
        name="access_scope_enum",
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    )
    __table_args__ = (
        sa.CheckConstraint(
            """
            (scope_type = 'global' AND project_id IS NULL AND project_site_id IS NULL) OR
            (scope_type = 'project' AND project_id IS NOT NULL AND project_site_id IS NULL) OR
            (scope_type = 'project_site' AND project_id IS NULL AND project_site_id IS NOT NULL)
            """,
            name="ck_va_user_access_grants_scope_shape",
        ),
        sa.CheckConstraint(
            """
            (role = 'admin' AND scope_type = 'global') OR
            (role = 'project_pi' AND scope_type = 'project') OR
            (role = 'site_pi' AND scope_type = 'project_site') OR
            (role IN ('collaborator', 'coder', 'coding_tester', 'reviewer', 'data_manager') AND scope_type IN ('project', 'project_site'))
            """,
            name="ck_va_user_access_grants_role_scope",
        ),
        sa.Index(
            "ix_va_user_access_grants_user_status",
            "user_id",
            "grant_status",
        ),
        sa.Index(
            "ix_va_user_access_grants_role_status",
            "role",
            "grant_status",
        ),
        sa.Index(
            "ix_va_user_access_grants_scope_lookup",
            "scope_type",
            "project_id",
            "project_site_id",
            "grant_status",
        ),
        sa.Index(
            "uq_va_user_access_grants_global",
            "user_id",
            "role",
            unique=True,
            postgresql_where=sa.text("scope_type = 'global'"),
        ),
        sa.Index(
            "uq_va_user_access_grants_project",
            "user_id",
            "role",
            "project_id",
            unique=True,
            postgresql_where=sa.text("scope_type = 'project'"),
        ),
        sa.Index(
            "uq_va_user_access_grants_project_site",
            "user_id",
            "role",
            "project_site_id",
            unique=True,
            postgresql_where=sa.text("scope_type = 'project_site'"),
        ),
    )

    grant_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True, index=True
    )
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    role: so.Mapped[VaAccessRoles] = so.mapped_column(
        _role_enum,
        nullable=False,
    )
    scope_type: so.Mapped[VaAccessScopeTypes] = so.mapped_column(
        _scope_enum,
        nullable=False,
    )
    project_id: so.Mapped[str | None] = so.mapped_column(
        sa.String(6),
        sa.ForeignKey("va_project_master.project_id"),
        nullable=True,
    )
    project_site_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_project_sites.project_site_id"),
        nullable=True,
    )
    notes: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    grant_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
    )
    grant_created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    grant_updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            "VA User Access Grant -> "
            f"{self.user_id} {self.role.value} {self.scope_type.value} "
            f"{self.project_id}/{self.project_site_id}"
        )
