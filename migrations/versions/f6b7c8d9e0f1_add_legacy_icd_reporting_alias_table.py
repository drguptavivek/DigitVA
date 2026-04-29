"""add legacy icd reporting alias table

Revision ID: f6b7c8d9e0f1
Revises: f4b5c6d7e8f9
Create Date: 2026-04-29 12:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f6b7c8d9e0f1"
down_revision = "f4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS map_icd10_legacy_reporting_aliases (
                legacy_code VARCHAR(16) PRIMARY KEY,
                reporting_code VARCHAR(16) NOT NULL REFERENCES mas_icd10_2019_2(code),
                note TEXT NULL
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_map_icd10_legacy_reporting_aliases_reporting_code
            ON map_icd10_legacy_reporting_aliases (reporting_code)
            """
        )
    )

    alias_table = sa.table(
        "map_icd10_legacy_reporting_aliases",
        sa.column("legacy_code", sa.String),
        sa.column("reporting_code", sa.String),
        sa.column("note", sa.Text),
    )

    seed_rows = [
        {
            "legacy_code": "A90",
            "reporting_code": "A97",
            "note": (
                "Legacy dengue code normalized to the ICD-10 2019 "
                "three-character dengue category for reporting."
            ),
        },
        {
            "legacy_code": "A91",
            "reporting_code": "A97",
            "note": (
                "Legacy dengue haemorrhagic fever code normalized to the "
                "ICD-10 2019 three-character dengue category for reporting."
            ),
        },
        {
            "legacy_code": "I84",
            "reporting_code": "K64",
            "note": (
                "Legacy haemorrhoids code normalized to the ICD-10 2019 "
                "three-character haemorrhoids category for reporting."
            ),
        },
    ]
    for row in seed_rows:
        bind.execute(
            sa.text(
                """
                INSERT INTO map_icd10_legacy_reporting_aliases (legacy_code, reporting_code, note)
                VALUES (:legacy_code, :reporting_code, :note)
                ON CONFLICT (legacy_code) DO UPDATE
                SET reporting_code = EXCLUDED.reporting_code,
                    note = EXCLUDED.note
                """
            ),
            row,
        )


def downgrade():
    op.execute(
        sa.text("DROP INDEX IF EXISTS ix_map_icd10_legacy_reporting_aliases_reporting_code")
    )
    op.execute(sa.text("DROP TABLE IF EXISTS map_icd10_legacy_reporting_aliases"))
