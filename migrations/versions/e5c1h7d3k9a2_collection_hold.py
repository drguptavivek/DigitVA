"""collection hold on DigitVA interviews, and a note on submission audit rows

Policy: docs/policy/project-clock-and-gates.md ("Uploads outside the
collection period are accepted and held"); bead digitva-nuy9. A DigitVA
interview (web intake or Collect app; its ``va_web_intake_drafts`` row) whose
start date was outside its site or unit collection gate at first upload is
``held``; a data manager may ``release`` or ``reject`` it. NULL (every
existing row, and every ODK submission, which has no draft) is not held.
``va_submissions_auditlog.va_audit_note`` keeps the data manager's optional
note with the audit row.

Additive and reversible: downgrade drops the columns, check and index.

Revision ID: e5c1h7d3k9a2
Revises: d8a4c6e2f1b3
Create Date: 2026-11-08
"""

import sqlalchemy as sa
from alembic import op

revision = "e5c1h7d3k9a2"
down_revision = "d8a4c6e2f1b3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("va_web_intake_drafts", sa.Column("collection_hold", sa.String(16), nullable=True))
    op.add_column("va_web_intake_drafts", sa.Column("collection_hold_reason", sa.String(32), nullable=True))
    op.add_column("va_web_intake_drafts", sa.Column("collection_hold_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "collection_hold",  # named ck_va_web_intake_drafts_collection_hold by the convention
        "va_web_intake_drafts",
        "collection_hold IS NULL OR collection_hold IN ('held', 'released', 'rejected')",
    )
    op.create_index(
        "ix_va_web_intake_drafts_collection_hold",
        "va_web_intake_drafts",
        ["project_id", "site_id", "org_unit_id"],
        postgresql_where=sa.text("collection_hold IN ('held', 'rejected')"),
    )
    op.add_column("va_submissions_auditlog", sa.Column("va_audit_note", sa.String(500), nullable=True))


def downgrade():
    op.drop_column("va_submissions_auditlog", "va_audit_note")
    op.drop_index("ix_va_web_intake_drafts_collection_hold", table_name="va_web_intake_drafts")
    op.drop_constraint("collection_hold", "va_web_intake_drafts", type_="check")
    op.drop_column("va_web_intake_drafts", "collection_hold_at")
    op.drop_column("va_web_intake_drafts", "collection_hold_reason")
    op.drop_column("va_web_intake_drafts", "collection_hold")
