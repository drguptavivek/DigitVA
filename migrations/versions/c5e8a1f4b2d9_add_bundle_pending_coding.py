"""Bundle coding results held until their case is ready.

Revision ID: c5e8a1f4b2d9
Revises: a7d3e9b2c4f6
Create Date: 2026-10-21

Additive: one empty table, ``va_bundle_pending_coding``. A bundle
``coding_result`` whose case is still at SmartVA or attachments is stored
here with outcome ``pending`` and applied by the Celery applier once the case
is ready (docs/policy/offline-bundle-and-transfer.md 5.5). It holds the masked
coding fields only, no personal data and no ciphertext. Downgrade drops it and
refuses while a row is still ``pending``: those are coding results the server
promised a final outcome for. Bead digitva-gb8w.2.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c5e8a1f4b2d9"
down_revision = "a7d3e9b2c4f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "va_bundle_pending_coding",
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("bundle_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("project_id", sa.String(6), nullable=False),
        sa.Column("va_sid", sa.String(64), nullable=False),
        sa.Column("death_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'applied', 'rejected')",
                           name=op.f("ck_va_bundle_pending_coding_status")),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"],
                                name=op.f("fk_va_bundle_pending_coding_project_id_va_project_master")),
        sa.ForeignKeyConstraint(["va_sid"], ["va_submissions.va_sid"],
                                name=op.f("fk_va_bundle_pending_coding_va_sid_va_submissions")),
        sa.ForeignKeyConstraint(["death_id"], ["va_death_register.death_id"],
                                name=op.f("fk_va_bundle_pending_coding_death_id_va_death_register")),
        sa.ForeignKeyConstraint(["actor_user_id"], ["va_users.user_id"],
                                name=op.f("fk_va_bundle_pending_coding_actor_user_id_va_users")),
        sa.PrimaryKeyConstraint("client_id", name=op.f("pk_va_bundle_pending_coding")),
    )
    op.create_index(op.f("ix_va_bundle_pending_coding_va_sid"), "va_bundle_pending_coding", ["va_sid"])
    op.create_index("ix_va_bundle_pending_coding_status_created", "va_bundle_pending_coding",
                    ["status", "created_at"])


def downgrade():
    pending = op.get_bind().execute(
        sa.text("SELECT count(*) FROM va_bundle_pending_coding WHERE status = 'pending'")).scalar()
    if pending:
        raise RuntimeError(
            f"va_bundle_pending_coding holds {pending} coding result(s) still pending, which stations "
            "keep waiting on. Apply or back up and clear them deliberately before downgrading."
        )
    op.drop_index("ix_va_bundle_pending_coding_status_created", table_name="va_bundle_pending_coding")
    op.drop_index(op.f("ix_va_bundle_pending_coding_va_sid"), table_name="va_bundle_pending_coding")
    op.drop_table("va_bundle_pending_coding")
