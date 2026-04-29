"""dedupe_cod_bucket_mappings_and_add_null_safe_unique_index

Revision ID: f4b5c6d7e8f9
Revises: d6e7f8a9b0c1
Create Date: 2026-04-29 12:55:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f4b5c6d7e8f9"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    mapping_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY scheme_id, COALESCE(age_scope, ''), UPPER(icd_code)
                        ORDER BY created_at, mapping_id
                    ) AS rn
                FROM map_icd_cod_buckets
            )
            DELETE FROM map_icd_cod_buckets m
            USING ranked r
            WHERE m.mapping_id = r.mapping_id
              AND r.rn > 1
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_map_icd_cod_buckets_scheme_scope_icd_norm
            ON map_icd_cod_buckets (scheme_id, COALESCE(age_scope, ''), upper(icd_code))
            """
        )
    )


def downgrade():
    op.execute(
        sa.text("DROP INDEX IF EXISTS ux_map_icd_cod_buckets_scheme_scope_icd_norm")
    )
