"""add trigram GIN indexes for the coding-search ILIKE arms

Revision ID: c4e7b1d8f2a9
Revises: b8f2d6a9c4e1
Create Date: 2026-09-25 14:00:00.000000

digitva-zpe.3. The spelling/hyphen variant pipeline widened the coding
search's ILIKE arms (spelling fold + hyphen-insensitive translate arm), so
the code and title columns get trigram GIN indexes the same way
d0e1f2a3b4c6 gave va_icd_codes one. The catalogues are small (12k ICD-10 /
37k ICD-11 rows; the plain OR is ~40ms cold) — this is future-proofing, not
a fix. The translate() arm is deliberately unindexed: translate() is not
indexable and stays a cheap seq-scan arm inside the same scan.
"""

from alembic import op

revision = "c4e7b1d8f2a9"
down_revision = "b8f2d6a9c4e1"
branch_labels = None
depends_on = None

_INDEXES = (
    ("ix_mas_icd10_2019_2_title_trgm", "mas_icd10_2019_2", "title"),
    ("ix_mas_icd10_2019_2_code_trgm", "mas_icd10_2019_2", "code"),
    ("ix_mas_icd11_mms_title_trgm", "mas_icd11_mms", "title"),
    ("ix_mas_icd11_mms_code_trgm", "mas_icd11_mms", "code"),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, column in _INDEXES:
        op.execute(f"CREATE INDEX {name} ON {table} USING gin ({column} gin_trgm_ops)")


def downgrade() -> None:
    for name, _, _ in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
