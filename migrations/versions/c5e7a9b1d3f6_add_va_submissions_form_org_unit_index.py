"""Index va_submissions (va_form_id, org_unit_id) for the unit coding-gate scan.

Revision ID: c5e7a9b1d3f6
Revises: b7e2d4f6a8c1
Create Date: 2026-10-23

``_get_excluded_org_units_for_coding`` (coder_workflow_service) lists the
distinct routed units of a coder's forms on every allocation request in a
project that has a unit coding gate. A partial index on the routed rows
covers it. Additive; built CONCURRENTLY, so outside the transaction.
"""

import sqlalchemy as sa
from alembic import op

revision = "c5e7a9b1d3f6"
down_revision = "b7e2d4f6a8c1"
branch_labels = None
depends_on = None

INDEX = "ix_va_submissions_form_org_unit"


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index(
            INDEX,
            "va_submissions",
            ["va_form_id", "org_unit_id"],
            postgresql_where=sa.text("org_unit_id IS NOT NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index(
            INDEX,
            table_name="va_submissions",
            postgresql_concurrently=True,
            if_exists=True,
        )
