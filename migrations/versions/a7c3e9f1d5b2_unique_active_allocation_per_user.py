"""One active allocation per user and kind.

The allocators check for a held allocation and then insert, and the only
lock taken is the submission's workflow row, so two concurrent requests
from one coder for different cases both committed (bead digitva-igq7). A
partial unique index on (va_allocated_to, va_allocation_for) WHERE active
makes the second insert fail; the allocators then resume the winner.

Existing duplicates are resolved first, without deleting a row: for each
(user, kind) holding more than one active allocation the newest (by
va_allocation_createdat, then va_allocation_id) stays active and the others
are marked deactive, each with a va_submissions_auditlog row
("va_allocation_deactivated_duplicate_active", role vasystem, operation d,
entity the allocation id), like the release path's own audit row. The
release path's workflow transitions and artifact deactivations are not
replayed here: a migration cannot run them, and inventing workflow events
would misstate history. A case behind a demoted allocation therefore keeps
its in-progress workflow state with no active allocation; the upgrade
prints how many it demoted so an operator can return those cases.

Downgrade drops the index only; demoted allocations stay deactive.

Revision ID: a7c3e9f1d5b2
Revises: e2b7d4a9c6f1
Create Date: 2026-10-22
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a7c3e9f1d5b2"
down_revision = "e2b7d4a9c6f1"
branch_labels = None
depends_on = None

INDEX = "uq_va_allocations_active_to_for"


def upgrade():
    demoted = op.get_bind().execute(sa.text(
        """
        WITH ranked AS (
            SELECT va_allocation_id,
                   row_number() OVER (
                       PARTITION BY va_allocated_to, va_allocation_for
                       ORDER BY va_allocation_createdat DESC, va_allocation_id DESC
                   ) AS rn
            FROM va_allocations
            WHERE va_allocation_status = 'active'
        ),
        demoted AS (
            UPDATE va_allocations AS a
            SET va_allocation_status = 'deactive',
                va_allocation_updatedat = (now() AT TIME ZONE 'utc')
            FROM ranked
            WHERE ranked.va_allocation_id = a.va_allocation_id AND ranked.rn > 1
            RETURNING a.va_allocation_id, a.va_sid
        ),
        audited AS (
            INSERT INTO va_submissions_auditlog (
                va_sid, va_audit_byrole, va_audit_by, va_audit_operation,
                va_audit_action, va_audit_entityid, va_audit_createdat
            )
            SELECT va_sid, 'vasystem', NULL, 'd',
                   'va_allocation_deactivated_duplicate_active', va_allocation_id,
                   (now() AT TIME ZONE 'utc')
            FROM demoted
            RETURNING 1
        )
        SELECT count(*) FROM audited
        """
    )).scalar()
    print(f"a7c3e9f1d5b2: deactivated {demoted} duplicate active allocation(s)")
    op.create_index(
        INDEX,
        "va_allocations",
        ["va_allocated_to", "va_allocation_for"],
        unique=True,
        postgresql_where=sa.text("va_allocation_status = 'active'"),
    )


def downgrade():
    op.drop_index(INDEX, table_name="va_allocations")
