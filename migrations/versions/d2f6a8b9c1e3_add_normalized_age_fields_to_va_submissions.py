"""add normalized age fields to va_submissions

Revision ID: d2f6a8b9c1e3
Revises: 4e935fa699e0
Create Date: 2026-03-20 11:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d2f6a8b9c1e3"
down_revision = "4e935fa699e0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_submissions",
        sa.Column("va_deceased_age_normalized_days", sa.Numeric(), nullable=True),
    )
    op.add_column(
        "va_submissions",
        sa.Column("va_deceased_age_normalized_years", sa.Numeric(), nullable=True),
    )
    op.add_column(
        "va_submissions",
        sa.Column("va_deceased_age_source", sa.String(length=32), nullable=True),
    )

    op.execute(
        """
        WITH base AS (
            SELECT
                s.va_sid,
                CASE
                    WHEN NULLIF(BTRIM(COALESCE(s.va_data ->> 'age_neonate_hours', '')), '') ~ '^-?\\d+(\\.\\d+)?$'
                        THEN (s.va_data ->> 'age_neonate_hours')::numeric
                    ELSE NULL
                END AS age_neonate_hours_num,
                CASE
                    WHEN NULLIF(BTRIM(COALESCE(s.va_data ->> 'age_neonate_days', '')), '') ~ '^-?\\d+(\\.\\d+)?$'
                        THEN (s.va_data ->> 'age_neonate_days')::numeric
                    ELSE NULL
                END AS age_neonate_days_num,
                CASE
                    WHEN NULLIF(BTRIM(COALESCE(s.va_data ->> 'ageInDays', '')), '') ~ '^-?\\d+(\\.\\d+)?$'
                        THEN (s.va_data ->> 'ageInDays')::numeric
                    ELSE NULL
                END AS age_in_days_num,
                CASE
                    WHEN NULLIF(BTRIM(COALESCE(s.va_data ->> 'ageInMonths', '')), '') ~ '^-?\\d+(\\.\\d+)?$'
                        THEN (s.va_data ->> 'ageInMonths')::numeric
                    ELSE NULL
                END AS age_in_months_num,
                CASE
                    WHEN NULLIF(BTRIM(COALESCE(s.va_data ->> 'ageInYears', '')), '') ~ '^-?\\d+(\\.\\d+)?$'
                        THEN (s.va_data ->> 'ageInYears')::numeric
                    ELSE NULL
                END AS age_in_years_num,
                CASE
                    WHEN NULLIF(BTRIM(COALESCE(s.va_data ->> 'ageInYears2', '')), '') ~ '^-?\\d+(\\.\\d+)?$'
                        THEN (s.va_data ->> 'ageInYears2')::numeric
                    ELSE NULL
                END AS age_in_years2_num,
                CASE
                    WHEN NULLIF(BTRIM(COALESCE(s.va_data ->> 'finalAgeInYears', '')), '') ~ '^-?\\d+(\\.\\d+)?$'
                        THEN (s.va_data ->> 'finalAgeInYears')::numeric
                    ELSE NULL
                END AS final_age_years_num,
                COALESCE(s.va_data ->> 'isNeonatal', '') IN ('1', '1.0', 'true', 'True') AS is_neonatal,
                COALESCE(s.va_data ->> 'isChild', '') IN ('1', '1.0', 'true', 'True') AS is_child,
                COALESCE(s.va_data ->> 'isAdult', '') IN ('1', '1.0', 'true', 'True') AS is_adult
            FROM va_submissions s
        ),
        normalized AS (
            SELECT
                b.va_sid,
                CASE
                    WHEN b.age_neonate_hours_num IS NOT NULL THEN 'age_neonate_hours'
                    WHEN b.age_neonate_days_num IS NOT NULL THEN 'age_neonate_days'
                    WHEN b.is_neonatal AND b.age_in_days_num IS NOT NULL THEN 'ageInDays'
                    WHEN b.is_child AND b.age_in_days_num IS NOT NULL THEN 'ageInDays'
                    WHEN b.is_child AND b.age_in_months_num IS NOT NULL THEN 'ageInMonths'
                    WHEN b.is_child AND b.age_in_years_num IS NOT NULL THEN 'ageInYears'
                    WHEN b.is_child AND b.age_in_years2_num IS NOT NULL THEN 'ageInYears2'
                    WHEN b.is_child AND b.final_age_years_num IS NOT NULL THEN 'finalAgeInYears'
                    WHEN b.is_adult AND b.age_in_years_num IS NOT NULL THEN 'ageInYears'
                    WHEN b.is_adult AND b.age_in_years2_num IS NOT NULL THEN 'ageInYears2'
                    WHEN b.is_adult AND b.final_age_years_num IS NOT NULL THEN 'finalAgeInYears'
                    WHEN b.age_in_years_num IS NOT NULL THEN 'ageInYears'
                    WHEN b.age_in_days_num IS NOT NULL THEN 'ageInDays'
                    WHEN b.age_in_months_num IS NOT NULL THEN 'ageInMonths'
                    WHEN b.age_in_years2_num IS NOT NULL THEN 'ageInYears2'
                    WHEN b.final_age_years_num IS NOT NULL THEN 'finalAgeInYears'
                    ELSE NULL
                END AS normalized_age_source,
                CASE
                    WHEN b.age_neonate_hours_num IS NOT NULL THEN 0::numeric
                    WHEN b.age_neonate_days_num IS NOT NULL THEN b.age_neonate_days_num
                    WHEN b.is_neonatal AND b.age_in_days_num IS NOT NULL THEN b.age_in_days_num
                    WHEN b.is_child AND b.age_in_days_num IS NOT NULL THEN b.age_in_days_num
                    WHEN b.is_child AND b.age_in_months_num IS NOT NULL THEN b.age_in_months_num * 30.4375
                    WHEN b.is_child AND b.age_in_years_num IS NOT NULL THEN b.age_in_years_num * 365.25
                    WHEN b.is_child AND b.age_in_years2_num IS NOT NULL THEN b.age_in_years2_num * 365.25
                    WHEN b.is_child AND b.final_age_years_num IS NOT NULL THEN b.final_age_years_num * 365.25
                    WHEN b.is_adult AND b.age_in_years_num IS NOT NULL THEN b.age_in_years_num * 365.25
                    WHEN b.is_adult AND b.age_in_years2_num IS NOT NULL THEN b.age_in_years2_num * 365.25
                    WHEN b.is_adult AND b.final_age_years_num IS NOT NULL THEN b.final_age_years_num * 365.25
                    WHEN b.age_in_years_num IS NOT NULL THEN b.age_in_years_num * 365.25
                    WHEN b.age_in_days_num IS NOT NULL THEN b.age_in_days_num
                    WHEN b.age_in_months_num IS NOT NULL THEN b.age_in_months_num * 30.4375
                    WHEN b.age_in_years2_num IS NOT NULL THEN b.age_in_years2_num * 365.25
                    WHEN b.final_age_years_num IS NOT NULL THEN b.final_age_years_num * 365.25
                    ELSE NULL
                END AS normalized_age_days,
                CASE
                    WHEN b.age_neonate_hours_num IS NOT NULL THEN 0::numeric
                    WHEN b.age_neonate_days_num IS NOT NULL THEN b.age_neonate_days_num / 365.25
                    WHEN b.is_neonatal AND b.age_in_days_num IS NOT NULL THEN b.age_in_days_num / 365.25
                    WHEN b.is_child AND b.age_in_days_num IS NOT NULL THEN b.age_in_days_num / 365.25
                    WHEN b.is_child AND b.age_in_months_num IS NOT NULL THEN b.age_in_months_num / 12
                    WHEN b.is_child AND b.age_in_years_num IS NOT NULL THEN b.age_in_years_num
                    WHEN b.is_child AND b.age_in_years2_num IS NOT NULL THEN b.age_in_years2_num
                    WHEN b.is_child AND b.final_age_years_num IS NOT NULL THEN b.final_age_years_num
                    WHEN b.is_adult AND b.age_in_years_num IS NOT NULL THEN b.age_in_years_num
                    WHEN b.is_adult AND b.age_in_years2_num IS NOT NULL THEN b.age_in_years2_num
                    WHEN b.is_adult AND b.final_age_years_num IS NOT NULL THEN b.final_age_years_num
                    WHEN b.age_in_years_num IS NOT NULL THEN b.age_in_years_num
                    WHEN b.age_in_days_num IS NOT NULL THEN b.age_in_days_num / 365.25
                    WHEN b.age_in_months_num IS NOT NULL THEN b.age_in_months_num / 12
                    WHEN b.age_in_years2_num IS NOT NULL THEN b.age_in_years2_num
                    WHEN b.final_age_years_num IS NOT NULL THEN b.final_age_years_num
                    ELSE NULL
                END AS normalized_age_years,
                COALESCE(b.final_age_years_num::integer, 0) AS legacy_age_years
            FROM base b
        )
        UPDATE va_submissions AS s
        SET
            va_deceased_age = n.legacy_age_years,
            va_deceased_age_normalized_days = n.normalized_age_days,
            va_deceased_age_normalized_years = n.normalized_age_years,
            va_deceased_age_source = n.normalized_age_source
        FROM normalized AS n
        WHERE s.va_sid = n.va_sid
        """
    )


def downgrade():
    op.drop_column("va_submissions", "va_deceased_age_source")
    op.drop_column("va_submissions", "va_deceased_age_normalized_years")
    op.drop_column("va_submissions", "va_deceased_age_normalized_days")
