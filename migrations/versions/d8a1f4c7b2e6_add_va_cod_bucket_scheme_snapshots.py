"""add va_cod_bucket_scheme_snapshots, the pre-reset JSON safety net

Revision ID: d8a1f4c7b2e6
Revises: c4e7b1d8f2a9
Create Date: 2026-09-25 16:00:00.000000

digitva-tet. Policy: docs/policy/icd11-cod-bucket-schemes.md.

"Reset from source" rebuilds a COD bucket scheme from its workbook, which
destroys anything the workbook does not know about: admin edits, ICD-11
rows, manual overrides. From now on every reset (and every CLI re-import
over an existing scheme) snapshots the whole scheme as JSON into this table
first, in the same transaction, and the reset is refused if the snapshot
fails. Restore is the existing JSON import
(``import_cod_bucket_scheme_json``) -- there is no restore endpoint here.

Operational log, deliberately outside the ``mas_*`` / ``map_*`` / ``auth_*``
conventions (matches ``va_db_backups``). No retention/prune job yet.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "d8a1f4c7b2e6"
down_revision = "c4e7b1d8f2a9"
branch_labels = None
depends_on = None

TABLE = "va_cod_bucket_scheme_snapshots"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column(
            "snapshot_id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("scheme_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("scheme_code", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("age_scope", sa.String(length=32), nullable=True),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("snapshot_id", name=op.f("pk_va_cod_bucket_scheme_snapshots")),
        sa.ForeignKeyConstraint(
            ["scheme_id"],
            ["mas_cod_bucket_schemes.scheme_id"],
            name=op.f("fk_va_cod_bucket_scheme_snapshots_scheme_id_mas_cod_bucket_schemes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["va_users.user_id"],
            name="fk_va_cod_bucket_scheme_snapshots_created_by_user_id",
        ),
        sa.CheckConstraint(
            "reason IN ('reset_scheme', 'reset_age_band', 'cli_import')",
            name=op.f("ck_va_cod_bucket_scheme_snapshots_reason"),
        ),
    )
    op.create_index(
        "ix_va_cod_bucket_scheme_snapshots_scheme_code_created_at",
        TABLE,
        ["scheme_code", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_va_cod_bucket_scheme_snapshots_scheme_code_created_at",
        table_name=TABLE,
    )
    op.drop_table(TABLE)
