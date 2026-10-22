"""Training sessions for the Training & demo project (TRN01).

Revision ID: e3b7d1a9c4f2
Revises: a7c3e9f1d5b2
Create Date: 2026-10-22

Additive: three empty tables. ``mas_training_sessions`` (one training: code,
name, root unit, status), ``map_training_cases`` (each pseudonymised case copy
with its coder slot and the source case's final cause, the trainer's answer
key) and ``map_training_participants`` (an existing user added to a session in
one role, with the grants written for it). No existing table changes.
Downgrade drops them and refuses while any session exists: the sessions, their
case copies and the participant list are retained records of a training
(docs/policy/training-demo-project.md). Bead digitva-vd0g.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e3b7d1a9c4f2"
down_revision = "a7c3e9f1d5b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mas_training_sessions",
        sa.Column("training_session_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(6), nullable=False),
        sa.Column("session_code", sa.String(8), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("org_unit_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.CheckConstraint("status IN ('active', 'closed')", name=op.f("ck_mas_training_sessions_status")),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"],
                                name=op.f("fk_mas_training_sessions_project_id_va_project_master")),
        sa.ForeignKeyConstraint(["created_by"], ["va_users.user_id"],
                                name=op.f("fk_mas_training_sessions_created_by_va_users")),
        sa.ForeignKeyConstraint(["org_unit_id"], ["mas_org_unit.org_unit_id"],
                                name=op.f("fk_mas_training_sessions_org_unit_id_mas_org_unit")),
        sa.PrimaryKeyConstraint("training_session_id", name=op.f("pk_mas_training_sessions")),
        sa.UniqueConstraint("project_id", "session_code", name="uq_mas_training_sessions_project_code"),
        sa.UniqueConstraint("org_unit_id", name="uq_mas_training_sessions_org_unit"),
    )
    op.create_index("ix_mas_training_sessions_project_created", "mas_training_sessions",
                    ["project_id", "created_at"])

    op.create_table(
        "map_training_cases",
        sa.Column("va_sid", sa.String(64), nullable=False),
        sa.Column("training_session_id", sa.Uuid(), nullable=False),
        sa.Column("case_number", sa.Integer(), nullable=False),
        sa.Column("coder_slot", sa.Integer(), nullable=False),
        sa.Column("source_va_sid", sa.String(64), nullable=False),
        sa.Column("source_final_cod", sa.Text(), nullable=True),
        sa.CheckConstraint("case_number BETWEEN 1 AND 200", name=op.f("ck_map_training_cases_case_number")),
        sa.CheckConstraint("coder_slot BETWEEN 1 AND 20", name=op.f("ck_map_training_cases_coder_slot")),
        sa.ForeignKeyConstraint(["va_sid"], ["va_submissions.va_sid"],
                                name=op.f("fk_map_training_cases_va_sid_va_submissions")),
        sa.ForeignKeyConstraint(["training_session_id"], ["mas_training_sessions.training_session_id"],
                                name=op.f("fk_map_training_cases_training_session_id_mas_training_sessions")),
        sa.PrimaryKeyConstraint("va_sid", name=op.f("pk_map_training_cases")),
        sa.UniqueConstraint("training_session_id", "case_number", name="uq_map_training_cases_session_number"),
    )
    op.create_index("ix_map_training_cases_session_slot", "map_training_cases",
                    ["training_session_id", "coder_slot"])

    op.create_table(
        "map_training_participants",
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("training_session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("coder_slot", sa.Integer(), nullable=True),
        sa.Column("grant_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("added_by", sa.Uuid(), nullable=False),
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.CheckConstraint(
            "role IN ('death_reporter', 'interview_supervisor', 'interviewer', 'coder', "
            "'reviewer_data_manager')",
            name=op.f("ck_map_training_participants_role")),
        sa.CheckConstraint("coder_slot IS NULL OR coder_slot BETWEEN 1 AND 20",
                           name=op.f("ck_map_training_participants_coder_slot")),
        sa.CheckConstraint("(role = 'coder') = (coder_slot IS NOT NULL)",
                           name=op.f("ck_map_training_participants_coder_slot_role")),
        sa.CheckConstraint("status IN ('active', 'removed')", name=op.f("ck_map_training_participants_status")),
        sa.ForeignKeyConstraint(
            ["training_session_id"], ["mas_training_sessions.training_session_id"],
            name=op.f("fk_map_training_participants_training_session_id_mas_training_sessions")),
        sa.ForeignKeyConstraint(["user_id"], ["va_users.user_id"],
                                name=op.f("fk_map_training_participants_user_id_va_users")),
        sa.ForeignKeyConstraint(["added_by"], ["va_users.user_id"],
                                name=op.f("fk_map_training_participants_added_by_va_users")),
        sa.PrimaryKeyConstraint("participant_id", name=op.f("pk_map_training_participants")),
        sa.UniqueConstraint("training_session_id", "user_id", "role",
                            name="uq_map_training_participants_session_user_role"),
    )
    op.create_index("ix_map_training_participants_session_role", "map_training_participants",
                    ["training_session_id", "role"])
    op.create_index("uq_map_training_participants_session_slot", "map_training_participants",
                    ["training_session_id", "coder_slot"], unique=True,
                    postgresql_where=sa.text("coder_slot IS NOT NULL"))
    op.create_index("ix_map_training_participants_pending_onboarding", "map_training_participants",
                    ["user_id"], postgresql_where=sa.text("status = 'active' AND onboarded_at IS NULL"))


def downgrade():
    sessions = op.get_bind().execute(sa.text("SELECT count(*) FROM mas_training_sessions")).scalar()
    if sessions:
        raise RuntimeError(
            f"mas_training_sessions holds {sessions} training session(s), which are retained records "
            "with their case copies and participants. Back them up and remove them deliberately "
            "before downgrading."
        )
    op.drop_index("ix_map_training_participants_pending_onboarding", table_name="map_training_participants")
    op.drop_index("uq_map_training_participants_session_slot", table_name="map_training_participants")
    op.drop_index("ix_map_training_participants_session_role", table_name="map_training_participants")
    op.drop_table("map_training_participants")
    op.drop_index("ix_map_training_cases_session_slot", table_name="map_training_cases")
    op.drop_table("map_training_cases")
    op.drop_index("ix_mas_training_sessions_project_created", table_name="mas_training_sessions")
    op.drop_table("mas_training_sessions")
