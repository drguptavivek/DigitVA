"""Per-project coder recode window.

Revision ID: c8e4a2f6b1d3
Revises: e3b7d1a9c4f2
Create Date: 2026-10-22

digitva-yeg3.2, owner decision 2026-10-20: the coder recode / reviewer-
eligibility window, hard-coded at 24 hours, becomes
``va_project_master.recode_window_minutes`` (1 to 10080, default 1440). Policy:
docs/policy/coding-workflow-state-machine.md ("Recode Window").

Additive: every existing project gets the 1440 server default, so behaviour is
unchanged. Data step: a TRN01 row present when this runs is set to 60 (owner
2026-10-22, docs/policy/training-demo-project.md); ``flask training-demo
setup`` sets the same on a TRN01 created later. Downgrade drops the column; the
window reverts to the hard-coded 24 hours of the previous release.

The CHECK is added with raw SQL under its final name so the naming convention
in app/__init__.py cannot prefix it twice (see fd232fab5987).
"""

import sqlalchemy as sa
from alembic import op

revision = "c8e4a2f6b1d3"
down_revision = "e3b7d1a9c4f2"
branch_labels = None
depends_on = None

CHECK_NAME = "ck_va_project_master_recode_window_minutes"


def upgrade():
    op.add_column(
        "va_project_master",
        sa.Column(
            "recode_window_minutes",
            sa.Integer(),
            nullable=False,
            server_default="1440",
        ),
    )
    op.execute(
        f'ALTER TABLE va_project_master ADD CONSTRAINT "{CHECK_NAME}" '
        "CHECK (recode_window_minutes BETWEEN 1 AND 10080)"
    )
    op.execute(
        "UPDATE va_project_master SET recode_window_minutes = 60 "
        "WHERE project_id = 'TRN01'"
    )


def downgrade():
    op.execute(f'ALTER TABLE va_project_master DROP CONSTRAINT IF EXISTS "{CHECK_NAME}"')
    op.drop_column("va_project_master", "recode_window_minutes")
