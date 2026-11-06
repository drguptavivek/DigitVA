"""Per-project timezone: the project clock.

Revision ID: a7d3f9c2e5b1
Revises: e4b7c2d9a6f1
Create Date: 2026-11-06

digitva-apee (stage 1), owner decision 2026-11-06: each project's "today" for
the coding gate and the coder daily allocation cap is taken on
``va_project_master.timezone`` (IANA name). Policy:
docs/policy/project-clock-and-gates.md ("Project clock").

Additive: every existing project gets the 'Asia/Kolkata' server default.
Downgrade drops the column; the gates fall back to UTC days as before. No new
index: the coder cap count is served by ix_va_allocations_to_for_createdat.
"""

import sqlalchemy as sa
from alembic import op

revision = "a7d3f9c2e5b1"
down_revision = "e4b7c2d9a6f1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_project_master",
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="Asia/Kolkata",
        ),
    )


def downgrade():
    op.drop_column("va_project_master", "timezone")
