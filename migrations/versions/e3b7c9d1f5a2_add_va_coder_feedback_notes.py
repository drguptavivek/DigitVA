"""Add va_coder_feedback_notes: a mentor's note on one coder's coded case.

Revision ID: e3b7c9d1f5a2
Revises: d8a2f4c6e1b3
Create Date: 2026-11-20

Additive (digitva-oux5, docs/policy/mentor-view.md "Feedback notes"). Nothing
else reads or writes it. Also indexes va_coding_episodes.started_by, which
the per-coder recode count filters on. Downgrade drops the table and its
notes (take a backup first if any note must be kept) and that index.
"""

import sqlalchemy as sa
from alembic import op

revision = "e3b7c9d1f5a2"
down_revision = "d8a2f4c6e1b3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "va_coder_feedback_notes",
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("va_sid", sa.String(length=64), nullable=False),
        sa.Column("coder_user_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("author_basis", sa.String(length=16), nullable=False),
        sa.Column("institute_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("org_unit_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retracted_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 2000", name="body_length"
        ),
        sa.ForeignKeyConstraint(
            ["va_sid"], ["va_submissions.va_sid"],
            name="fk_va_coder_feedback_notes_va_sid_va_submissions", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["coder_user_id"], ["va_users.user_id"],
            name="fk_va_coder_feedback_notes_coder_user_id_va_users",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"], ["va_users.user_id"],
            name="fk_va_coder_feedback_notes_author_user_id_va_users",
        ),
        sa.ForeignKeyConstraint(
            ["retracted_by"], ["va_users.user_id"],
            name="fk_va_coder_feedback_notes_retracted_by_va_users",
        ),
        sa.ForeignKeyConstraint(
            ["institute_id"], ["mas_mentor_institute.institute_id"],
            name="fk_va_coder_feedback_notes_institute_id_mas_mentor_institute",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["va_project_master.project_id"],
            name="fk_va_coder_feedback_notes_project_id_va_project_master",
        ),
        sa.ForeignKeyConstraint(
            ["org_unit_id"], ["mas_org_unit.org_unit_id"],
            name="fk_va_coder_feedback_notes_org_unit_id_mas_org_unit",
        ),
        sa.PrimaryKeyConstraint("note_id", name="pk_va_coder_feedback_notes"),
    )
    op.create_index(
        "ix_va_coder_feedback_notes_coder_created", "va_coder_feedback_notes",
        ["coder_user_id", "created_at"],
    )
    op.create_index("ix_va_coder_feedback_notes_va_sid", "va_coder_feedback_notes", ["va_sid"])
    op.create_index("ix_va_coding_episodes_started_by", "va_coding_episodes", ["started_by"])


def downgrade():
    op.drop_index("ix_va_coding_episodes_started_by", table_name="va_coding_episodes")
    op.drop_index("ix_va_coder_feedback_notes_va_sid", table_name="va_coder_feedback_notes")
    op.drop_index("ix_va_coder_feedback_notes_coder_created", table_name="va_coder_feedback_notes")
    op.drop_table("va_coder_feedback_notes")
