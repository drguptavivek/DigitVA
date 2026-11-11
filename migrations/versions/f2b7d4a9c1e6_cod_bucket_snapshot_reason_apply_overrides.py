"""allow the apply_overrides reason on COD bucket scheme snapshots

Policy: docs/policy/icd11-cod-bucket-schemes.md ("WHO baseline and DigitVA
overrides"); bead digitva-ozd1. "Apply DigitVA overrides" snapshots the whole
scheme first, with reason ``apply_overrides``.

Additive and reversible: downgrade relabels any ``apply_overrides`` snapshot
``reset_scheme`` (both are whole-scheme snapshots taken before a whole-scheme
change; the payload is kept) and restores the old check.

Revision ID: f2b7d4a9c1e6
Revises: e5c1h7d3k9a2
Create Date: 2026-11-11
"""

from alembic import op

revision = "f2b7d4a9c1e6"
down_revision = "e5c1h7d3k9a2"
branch_labels = None
depends_on = None

TABLE = "va_cod_bucket_scheme_snapshots"
CHECK = "ck_va_cod_bucket_scheme_snapshots_reason"


def upgrade():
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.create_check_constraint(
        op.f(CHECK),
        TABLE,
        "reason IN ('reset_scheme', 'reset_age_band', 'cli_import', 'apply_overrides')",
    )


def downgrade():
    op.execute(
        f"UPDATE {TABLE} SET reason = 'reset_scheme' WHERE reason = 'apply_overrides'"
    )
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.create_check_constraint(
        op.f(CHECK),
        TABLE,
        "reason IN ('reset_scheme', 'reset_age_band', 'cli_import')",
    )
