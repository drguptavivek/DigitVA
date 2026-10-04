"""One open web-intake draft per interviewer per case.

Parallel interviews (digitva-xz83, docs/policy/web-intake.md): several
interviewers may each hold a draft on one case, but never two of the same
interviewer. The partial unique index enforces it. If existing data already
breaks the rule the upgrade fails on index creation; nothing is remapped or
deleted, resolve the duplicates by hand and rerun.

Revision ID: e6a2c9d4f1b7
Revises: d5f1b8a3c6e2
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

revision = "e6a2c9d4f1b7"
down_revision = "d5f1b8a3c6e2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_va_web_intake_drafts_user_death_open",
        "va_web_intake_drafts",
        ["death_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft' AND death_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_va_web_intake_drafts_user_death_open", table_name="va_web_intake_drafts")
