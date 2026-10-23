"""One active allocation per user, kind and side (training or real work).

A coder or reviewer holding a training case could not take a real one, nor
the reverse, because the active-allocation unique index was per (user, kind)
(bead digitva-rcwt). Adds ``va_allocations.va_allocation_training`` (NOT NULL,
default false), marks the allocations that sit in the configured training
project (``DIGITVA_TRAINING_PROJECT_ID``, default TRN01 as in config.py; set
empty, nothing is marked), and
rebuilds ``uq_va_allocations_active_to_for`` over (user, kind, side).

The new index is strictly weaker than the old one, so existing rows satisfy
it. Downgrade restores the old index; it fails if a user then holds an active
allocation on both sides, in which case release one first.

Revision ID: d6a1f3b8c2e4
Revises: c5e7a9b1d3f6
Create Date: 2026-10-23
"""
import os

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d6a1f3b8c2e4"
down_revision = "c5e7a9b1d3f6"
branch_labels = None
depends_on = None

INDEX = "uq_va_allocations_active_to_for"
WHERE = sa.text("va_allocation_status = 'active'")


def upgrade():
    op.add_column(
        "va_allocations",
        sa.Column("va_allocation_training", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    project_id = os.environ.get("DIGITVA_TRAINING_PROJECT_ID", "TRN01").strip()
    op.get_bind().execute(
        sa.text(
            """
            UPDATE va_allocations a SET va_allocation_training = true
            FROM va_submissions s JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE s.va_sid = a.va_sid AND f.project_id = :project_id
            """
        ),
        {"project_id": project_id},
    )
    op.drop_index(INDEX, table_name="va_allocations")
    op.create_index(
        INDEX,
        "va_allocations",
        ["va_allocated_to", "va_allocation_for", "va_allocation_training"],
        unique=True,
        postgresql_where=WHERE,
    )


def downgrade():
    op.drop_index(INDEX, table_name="va_allocations")
    op.create_index(
        INDEX,
        "va_allocations",
        ["va_allocated_to", "va_allocation_for"],
        unique=True,
        postgresql_where=WHERE,
    )
    op.drop_column("va_allocations", "va_allocation_training")
