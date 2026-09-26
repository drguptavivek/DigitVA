"""add DORIS project modes and final assessment payloads

Revision ID: c7a4e2d9f1b6
Revises: d9e0f1a2b3c4
Create Date: 2026-09-26 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c7a4e2d9f1b6"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_project_master",
        sa.Column(
            "masked_cod_required",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.add_column(
        "va_project_master",
        sa.Column(
            "cod_entry_mode",
            sa.String(length=16),
            server_default="simple",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_va_project_master_cod_entry_mode"),
        "va_project_master",
        "cod_entry_mode IN ('simple', 'doris')",
    )
    op.create_check_constraint(
        op.f("ck_va_project_master_cod_entry_mode_masking"),
        "va_project_master",
        "NOT (masked_cod_required AND cod_entry_mode = 'doris')",
    )
    op.create_check_constraint(
        op.f("ck_va_project_master_doris_requires_icd11"),
        "va_project_master",
        "cod_entry_mode <> 'doris' OR icd_classification = 'icd11'",
    )

    for table in ("va_final_assessments", "va_reviewer_final_assessments"):
        op.add_column(table, sa.Column("va_immediate_cod", sa.Text(), nullable=True))
        op.add_column(
            table,
            sa.Column("immediate_icd11_provenance", postgresql.JSONB(), nullable=True),
        )
        op.add_column(table, sa.Column("va_other_conditions", sa.Text(), nullable=True))
        op.add_column(
            table, sa.Column("doris_certificate", postgresql.JSONB(), nullable=True)
        )
        op.add_column(table, sa.Column("doris_result", postgresql.JSONB(), nullable=True))
        op.add_column(
            table, sa.Column("codedit_result", postgresql.JSONB(), nullable=True)
        )
        op.add_column(
            table,
            sa.Column("cod_entry_mode_snapshot", postgresql.JSONB(), nullable=True),
        )

    # Preserve historical rows while preventing two active final artifacts
    # for the same submission and payload version in either role.
    op.create_index(
        "uq_va_final_assessments_active_sid_payload",
        "va_final_assessments",
        ["va_sid", "payload_version_id"],
        unique=True,
        postgresql_where=sa.text(
            "va_finassess_status = 'active' AND payload_version_id IS NOT NULL"
        ),
    )
    op.create_index(
        "uq_va_reviewer_final_assessments_active_sid_payload",
        "va_reviewer_final_assessments",
        ["va_sid", "payload_version_id"],
        unique=True,
        postgresql_where=sa.text(
            "va_rfinassess_status = 'active' AND payload_version_id IS NOT NULL"
        ),
    )


def downgrade():
    op.drop_index(
        "uq_va_reviewer_final_assessments_active_sid_payload",
        table_name="va_reviewer_final_assessments",
    )
    op.drop_index(
        "uq_va_final_assessments_active_sid_payload",
        table_name="va_final_assessments",
    )

    for table in ("va_reviewer_final_assessments", "va_final_assessments"):
        for column in (
            "cod_entry_mode_snapshot",
            "codedit_result",
            "doris_result",
            "doris_certificate",
            "va_other_conditions",
            "immediate_icd11_provenance",
            "va_immediate_cod",
        ):
            op.drop_column(table, column)

    op.drop_constraint(
        op.f("ck_va_project_master_doris_requires_icd11"),
        "va_project_master",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_va_project_master_cod_entry_mode_masking"),
        "va_project_master",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_va_project_master_cod_entry_mode"),
        "va_project_master",
        type_="check",
    )
    op.drop_column("va_project_master", "cod_entry_mode")
    op.drop_column("va_project_master", "masked_cod_required")
