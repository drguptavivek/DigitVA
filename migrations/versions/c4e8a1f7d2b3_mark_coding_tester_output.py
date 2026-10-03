"""Mark coding_tester output so it never counts as a coder's result.

A coding_tester's final COD, Step 1 COD and not-codeable report are stored
deactive with ``is_tester`` true; the case returns to the coding pool
(digitva-ggc3, docs/policy/access-control-model.md "coding_tester").

Existing rows default to false: grants carry no history, so earlier tester
rows cannot be told apart from a coder's reliably and are not backfilled.

Revision ID: c4e8a1f7d2b3
Revises: b7d4e9f2a6c1
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op

revision = "c4e8a1f7d2b3"
down_revision = "b7d4e9f2a6c1"
branch_labels = None
depends_on = None

_TABLES = ("va_final_assessments", "va_initial_assessments", "va_coder_review")


def upgrade():
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("is_tester", sa.Boolean(), nullable=False, server_default="false"),
        )


def downgrade():
    for table in _TABLES:
        op.drop_column(table, "is_tester")
