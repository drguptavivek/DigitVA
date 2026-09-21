import uuid

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB
from app import db
from typing import Optional
from datetime import date, datetime, timezone
from app.models.va_selectives import VaStatuses


class VaProjectMaster(db.Model):
    __tablename__ = "va_project_master"
    __table_args__ = (
        # The naming convention (app/__init__.py) already prefixes these with
        # "ck_%(table_name)s_"; pass only the discriminator (digitva-liu).
        sa.CheckConstraint(
            "web_intake_mode IN ('off', 'direct', 'death_register', 'both')",
            name="web_intake_mode",
        ),
        sa.CheckConstraint(
            "above_scope_coding_mode IN ('code_any', 'view_only')",
            name="above_scope_coding_mode",
        ),
        sa.CheckConstraint(
            "project_structure_mode IN ('sites', 'organization')",
            name="project_structure_mode",
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
    # How the project is structured: 'sites' (the older Project > Site > Form
    # shape) or 'organization' (a health-system unit tree). Only an
    # organization project may have its tree edited.
    # Policy: docs/policy/organization-model.md ("Project structure mode").
    project_structure_mode: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default="sites", server_default="sites"
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
    # Tier-2 web form options (docs/policy/va-web-form-options.md), served by
    # GET /api/v1/organization/<project_id>/form-options. Explicit columns, not
    # a settings blob, like every other project setting on this table.
    #
    # The language the form opens in. Must be an active mas_languages code.
    web_intake_default_locale: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default="en", server_default="en"
    )
    # Language codes this project's users may switch to. NULL means every
    # active language in mas_languages.
    web_intake_available_locales: so.Mapped[Optional[list]] = so.mapped_column(
        JSONB, nullable=True
    )
    # Language codes offered for `narr_language` -- the language the narrative
    # was *recorded* in, distinct from the display locale. NULL means none
    # are offered.
    web_intake_narration_languages: so.Mapped[Optional[list]] = so.mapped_column(
        JSONB, nullable=True
    )
    # Whether source guidance notes render. An interviewer-training setting.
    web_intake_show_guidance: so.Mapped[bool] = so.mapped_column(
        sa.Boolean(), nullable=False, default=False, server_default="false"
    )
    # The form type the project's browser questionnaire carries
    # (docs/policy/va-form-project-configuration.md). NULL means WHO_2022_VA,
    # the behaviour before the column existed.
    web_intake_form_type_id: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey(
            "mas_form_types.form_type_id",
            name="fk_va_project_master_web_intake_form_type",
        ),
        nullable=True,
    )
    # The welcome note shown before the questionnaire starts. NULL means the
    # system default text (DEFAULT_INTAKE_NOTE in app/services/
    # web_intake_service.py, a constant so the wording changes without a
    # migration); an empty string means no welcome screen at all.
    web_intake_intake_note: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text, nullable=True
    )
    # Whether the questionnaire offers the death summary document upload
    # section. On for every project; a project may opt out.
    web_intake_death_summary_enabled: so.Mapped[bool] = so.mapped_column(
        sa.Boolean(), nullable=False, default=True, server_default="true"
    )
    # Whether the questionnaire carries the medical-record fields (md_available
    # / md_count / md_im1..30). On for every project; a project may opt out.
    web_intake_medical_records_enabled: so.Mapped[bool] = so.mapped_column(
        sa.Boolean(), nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:
        return f"VA Project Master -> {self.project_id} ({self.project_status})"
