"""Add map_submission_cod_bucket and mas_cod_bucket_schemes.reporting_rows_built_at.

Revision ID: d3c8e5a1f7b4
Revises: c7a3f9e1b5d2
Create Date: 2026-11-04 12:00:00.000000

Each death's COD bucket per active scheme and matching age band, precomputed
so the bucket reports count from indexed rows instead of re-deriving buckets
per request (docs/policy/cod-bucket-reporting.md, "Precomputed reporting
rows"). Additive only and no backfill: every scheme's stamp starts NULL, so
the reports keep deriving live until `flask cod-buckets rebuild` or the
worker's sweep builds it. Downgrade drops the table and the column; the
reports then derive live again, as before.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d3c8e5a1f7b4"
down_revision = "c7a3f9e1b5d2"
branch_labels = None
depends_on = None

TABLE = "map_submission_cod_bucket"


def upgrade():
    op.add_column(
        "mas_cod_bucket_schemes",
        sa.Column("reporting_rows_built_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        TABLE,
        sa.Column("va_sid", sa.String(length=64), nullable=False),
        sa.Column("scheme_id", sa.Uuid(), nullable=False),
        sa.Column("age_band_id", sa.Uuid(), nullable=False),
        sa.Column("age_scope", sa.String(length=32), nullable=True),
        sa.Column("icd_classification", sa.String(length=8), nullable=False),
        sa.Column("final_icd", sa.Text(), nullable=False),
        sa.Column("reporting_icd", sa.Text(), nullable=True),
        sa.Column("node_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.String(length=6), nullable=True),
        sa.Column("site_id", sa.String(length=4), nullable=True),
        sa.Column("form_id", sa.String(length=12), nullable=False),
        sa.Column("org_unit_id", sa.Uuid(), nullable=True),
        sa.Column("gender", sa.String(length=20), nullable=True),
        sa.Column("age_days", sa.Numeric(), nullable=False),
        sa.Column("age_years", sa.Numeric(), nullable=True),
        sa.Column("submission_date", sa.Date(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("is_reportable", sa.Boolean(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "icd_classification IN ('icd10', 'icd11')",
            name=op.f("ck_map_submission_cod_bucket_icd_classification"),
        ),
        sa.ForeignKeyConstraint(
            ["va_sid"],
            ["va_submissions.va_sid"],
            name="fk_map_submission_cod_bucket_va_sid",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scheme_id"],
            ["mas_cod_bucket_schemes.scheme_id"],
            name="fk_map_submission_cod_bucket_scheme",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["age_band_id"],
            ["mas_cod_bucket_scheme_age_bands.age_band_id"],
            name="fk_map_submission_cod_bucket_age_band",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["mas_cod_bucket_nodes.node_id"],
            name="fk_map_submission_cod_bucket_node",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "va_sid", "scheme_id", "age_band_id", name=op.f("pk_map_submission_cod_bucket")
        ),
    )
    op.create_index(
        "ix_map_submission_cod_bucket_report",
        TABLE,
        ["scheme_id", "project_id", "site_id", "form_id"],
        postgresql_include=[
            "age_band_id",
            "node_id",
            "gender",
            "submission_date",
            "event_date",
            "age_days",
            "org_unit_id",
        ],
        postgresql_where=sa.text("is_reportable"),
    )
    op.create_index(
        "ix_map_submission_cod_bucket_unit",
        TABLE,
        ["scheme_id", "org_unit_id"],
        postgresql_where=sa.text("is_reportable"),
    )
    op.create_index(
        "ix_map_submission_cod_bucket_scheme_band", TABLE, ["scheme_id", "age_band_id"]
    )
    op.create_index("ix_map_submission_cod_bucket_node", TABLE, ["node_id"])


def downgrade():
    op.drop_table(TABLE)
    op.drop_column("mas_cod_bucket_schemes", "reporting_rows_built_at")
