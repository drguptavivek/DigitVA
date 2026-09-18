"""add web intake: interviewer role, project mode, form source, death register, drafts

Revision ID: e5f6a7b8c9d1
Revises: d9e3f5a7b2c4
Create Date: 2026-09-18 01:00:00.000000

Additive. Plan: docs/planning/who-va-2022-web-intake-plan.md.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d1"
down_revision = "d9e3f5a7b2c4"
branch_labels = None
depends_on = None

ROLE_SCOPE_BEFORE = """
    (role = 'admin' AND scope_type = 'global') OR
    (role = 'project_pi' AND scope_type = 'project') OR
    (role = 'site_pi' AND scope_type IN ('project_site', 'org_unit')) OR
    (role IN ('collaborator', 'coder', 'coding_tester', 'reviewer', 'data_manager') AND scope_type IN ('project', 'project_site', 'org_unit'))
"""
ROLE_SCOPE_AFTER = """
    (role = 'admin' AND scope_type = 'global') OR
    (role = 'project_pi' AND scope_type = 'project') OR
    (role = 'site_pi' AND scope_type IN ('project_site', 'org_unit')) OR
    (role IN ('collaborator', 'coder', 'coding_tester', 'reviewer', 'data_manager', 'interviewer') AND scope_type IN ('project', 'project_site', 'org_unit'))
"""


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE access_role_enum ADD VALUE IF NOT EXISTS 'interviewer'")

    op.drop_constraint("ck_va_user_access_grants_role_scope", "va_user_access_grants", type_="check")
    op.create_check_constraint(
        "ck_va_user_access_grants_role_scope", "va_user_access_grants", ROLE_SCOPE_AFTER
    )

    op.add_column(
        "va_project_master",
        sa.Column("web_intake_mode", sa.String(length=16), nullable=False, server_default="off"),
    )
    op.create_check_constraint(
        "ck_va_project_master_web_intake_mode",
        "va_project_master",
        "web_intake_mode IN ('off', 'direct', 'death_register', 'both')",
    )
    op.add_column(
        "va_forms",
        sa.Column("form_source", sa.String(length=8), nullable=False, server_default="odk"),
    )
    op.create_check_constraint(
        "ck_va_forms_form_source", "va_forms", "form_source IN ('odk', 'web')"
    )

    op.execute("CREATE SEQUENCE IF NOT EXISTS va_death_register_number_seq START 1")

    op.create_table(
        "va_death_register",
        sa.Column("death_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("site_id", sa.String(length=4), nullable=False),
        sa.Column("org_unit_id", sa.Uuid(), nullable=True),
        sa.Column("death_number", sa.BigInteger(), nullable=False),
        sa.Column("unique_id", sa.String(length=64), nullable=False),
        sa.Column("deceased_name", sa.Text(), nullable=False),
        sa.Column("deceased_sex", sa.String(length=16), nullable=False),
        sa.Column("abha_number", sa.String(length=17), nullable=True),
        sa.Column("abha_address", sa.String(length=64), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("age_years", sa.Integer(), nullable=True),
        sa.Column("date_of_death", sa.Date(), nullable=False),
        sa.Column("place_of_death", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("informant_name", sa.Text(), nullable=True),
        sa.Column("informant_phone", sa.String(length=32), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="registered"),
        sa.Column("va_sid", sa.String(length=64), nullable=True),
        sa.Column("registered_by", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("death_id"),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"]),
        sa.ForeignKeyConstraint(["site_id"], ["va_site_master.site_id"]),
        sa.ForeignKeyConstraint(["org_unit_id"], ["mas_org_unit.org_unit_id"]),
        sa.ForeignKeyConstraint(["va_sid"], ["va_submissions.va_sid"]),
        sa.ForeignKeyConstraint(["registered_by"], ["va_users.user_id"]),
        sa.UniqueConstraint("unique_id", name="uq_va_death_register_unique_id"),
    )
    op.create_index("ix_va_death_register_project_status", "va_death_register", ["project_id", "status"])
    op.create_index("ix_va_death_register_org_unit", "va_death_register", ["org_unit_id"])

    op.create_table(
        "va_web_intake_drafts",
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("site_id", sa.String(length=4), nullable=False),
        sa.Column("org_unit_id", sa.Uuid(), nullable=True),
        sa.Column("death_id", sa.Uuid(), nullable=True),
        sa.Column("form_id", sa.String(length=12), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("unique_id", sa.String(length=64), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prefill", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_section", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("va_sid", sa.String(length=64), nullable=True),
        sa.Column("client_valid", sa.Boolean(), nullable=True),
        sa.Column("client_issue_count", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("draft_id"),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"]),
        sa.ForeignKeyConstraint(["site_id"], ["va_site_master.site_id"]),
        sa.ForeignKeyConstraint(["org_unit_id"], ["mas_org_unit.org_unit_id"]),
        sa.ForeignKeyConstraint(["death_id"], ["va_death_register.death_id"]),
        sa.ForeignKeyConstraint(["form_id"], ["va_forms.form_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["va_users.user_id"]),
        sa.ForeignKeyConstraint(["va_sid"], ["va_submissions.va_sid"]),
    )
    op.create_index("ix_va_web_intake_drafts_user_status", "va_web_intake_drafts", ["user_id", "status"])
    op.create_index("ix_va_web_intake_drafts_project", "va_web_intake_drafts", ["project_id"])
    op.create_index("ix_va_web_intake_drafts_death", "va_web_intake_drafts", ["death_id"])

    op.create_table(
        "va_web_intake_draft_sections",
        sa.Column("section_row_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("section_name", sa.String(length=64), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("section_row_id"),
        sa.ForeignKeyConstraint(["draft_id"], ["va_web_intake_drafts.draft_id"]),
        sa.UniqueConstraint("draft_id", "section_name", name="uq_va_web_intake_draft_sections"),
    )
    op.create_index("ix_va_web_intake_draft_sections_draft_id", "va_web_intake_draft_sections", ["draft_id"])


def downgrade():
    op.drop_table("va_web_intake_draft_sections")
    op.drop_table("va_web_intake_drafts")
    op.drop_table("va_death_register")
    op.execute("DROP SEQUENCE IF EXISTS va_death_register_number_seq")
    op.drop_constraint("ck_va_forms_form_source", "va_forms", type_="check")
    op.drop_column("va_forms", "form_source")
    op.drop_constraint("ck_va_project_master_web_intake_mode", "va_project_master", type_="check")
    op.drop_column("va_project_master", "web_intake_mode")
    op.drop_constraint("ck_va_user_access_grants_role_scope", "va_user_access_grants", type_="check")
    op.create_check_constraint(
        "ck_va_user_access_grants_role_scope", "va_user_access_grants", ROLE_SCOPE_BEFORE
    )
    # The 'interviewer' enum value stays: PostgreSQL cannot drop enum values.
