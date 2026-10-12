"""Index va_allocations(va_allocated_to, va_allocation_for, va_allocation_createdat).

Serves the "user's most recent allocation of a kind" lookup behind
``last_allocated_project_id`` in ``coder_dashboard_service``: filter on the
user and kind, order by created_at descending, take one. Without this the
planner walks the created_at index backwards and filters out most rows.
Additive and reversible.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "j7n3q9w5y2e8"
down_revision = "h5m2r8v4z1d9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_va_allocations_to_for_createdat",
        "va_allocations",
        ["va_allocated_to", "va_allocation_for", "va_allocation_createdat"],
    )


def downgrade():
    op.drop_index("ix_va_allocations_to_for_createdat", table_name="va_allocations")
