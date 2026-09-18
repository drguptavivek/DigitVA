import uuid

import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from typing import Optional
from datetime import date, datetime, timezone
from app.models.va_selectives import VaStatuses


class VaProjectMaster(db.Model):
    __tablename__ = "va_project_master"
    __table_args__ = (
        sa.CheckConstraint(
            "web_intake_mode IN ('off', 'direct', 'death_register', 'both')",
            name="ck_va_project_master_web_intake_mode",
        ),
        sa.CheckConstraint(
            "above_scope_coding_mode IN ('code_any', 'view_only')",
            name="ck_va_project_master_above_scope_coding_mode",
        ),
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), primary_key=True, index=True
    )
    project_code: so.Mapped[Optional[str]] = so.mapped_column(sa.String(6))
    project_name: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    project_nickname: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    project_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    project_registered_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    project_updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # Admin-set target date the DM burndown KPI projects against
    # (app/routes/api/dm_kpi/dm_kpi_burndown.py).
    project_target_completion_date: so.Mapped[Optional[date]] = so.mapped_column(
        sa.Date(), nullable=True
    )
    narrative_qa_enabled: so.Mapped[bool] = so.mapped_column(
        sa.Boolean(), nullable=False, default=False, server_default="false"
    )
    social_autopsy_enabled: so.Mapped[bool] = so.mapped_column(
        sa.Boolean(), nullable=False, default=True, server_default="true"
    )
    reviewer_social_autopsy_enabled: so.Mapped[bool] = so.mapped_column(
        sa.Boolean(), nullable=False, default=True, server_default="true"
    )
    coding_intake_mode: so.Mapped[str] = so.mapped_column(
        sa.String(32),
        nullable=False,
        default="random_form_allocation",
        server_default="random_form_allocation",
    )
    # Health-system projects: the level within which a death may be coded.
    # A coder assigned at or below this level codes inside their own unit's
    # subtree; one assigned above it is governed by above_scope_coding_mode.
    # NULL means no unit-based coding scope — the project codes as before.
    # Policy: docs/policy/organization-model.md.
    coding_scope_level_id: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_org_level.org_level_id", name="fk_va_project_master_coding_scope_level"),
        nullable=True,
    )
    # What a coder granted *above* the coding scope level may do:
    # 'code_any' — code anything in their own subtree; 'view_only' — see coded
    # and uncoded work but code nothing.
    above_scope_coding_mode: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default="view_only", server_default="view_only"
    )
    demo_training_enabled: so.Mapped[bool] = so.mapped_column(
        sa.Boolean(), nullable=False, default=False, server_default="false"
    )
    demo_retention_minutes: so.Mapped[int] = so.mapped_column(
        sa.Integer(),
        nullable=False,
        default=10,
        server_default="10",
    )
    # Phase 4a of docs/planning/s3-attachment-plan.md: DigitVA keeps its own
    # permanent copy of every attachment and serves from that store first.
    # When true, a store miss on a live submission is self-healed by fetching
    # the original from this project's ODK Central connection; when false, a
    # store miss is a 404 exactly as before.
    attachment_central_fetch_enabled: so.Mapped[bool] = so.mapped_column(
        sa.Boolean(), nullable=False, default=False, server_default="false"
    )
    # Web intake of WHO VA 2022 questionnaires (docs/policy/web-intake.md):
    # off | direct | death_register | both.
    web_intake_mode: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default="off", server_default="off"
    )

    def __repr__(self) -> str:
        return f"VA Project Master -> {self.project_id} ({self.project_status})"
