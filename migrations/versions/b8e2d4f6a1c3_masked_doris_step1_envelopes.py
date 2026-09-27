"""Masked DORIS Step 1: DORIS envelopes on the initial assessment tables.

Revision ID: b8e2d4f6a1c3
Revises: a3f7c1d8e5b2
Create Date: 2026-09-27 00:00:01.000000

digitva-0n3 phase 2. Design record .tasks/2026-09-27-icd11-means-doris.md.

A masked ICD-11 project enters the DORIS certificate in Step 1, so the
Step 1 rows carry the same verified envelopes as the final tables:
`doris_certificate`, `doris_result`, `codedit_result` and
`cod_entry_mode_snapshot`, nullable JSONB on `va_initial_assessments` and
`va_reviewer_initial_assessments`. Additive: existing rows stay NULL.
Downgrade drops the columns (their Step 1 DORIS envelopes are lost; the
text COD columns remain).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b8e2d4f6a1c3"
down_revision = "a3f7c1d8e5b2"
branch_labels = None
depends_on = None

TABLES = ("va_initial_assessments", "va_reviewer_initial_assessments")
COLUMNS = (
    "doris_certificate",
    "doris_result",
    "codedit_result",
    "cod_entry_mode_snapshot",
)


def upgrade():
    for table in TABLES:
        for column in COLUMNS:
            op.add_column(table, sa.Column(column, postgresql.JSONB(), nullable=True))


def downgrade():
    for table in reversed(TABLES):
        for column in reversed(COLUMNS):
            op.drop_column(table, column)
