"""allow the json_import reason on COD bucket scheme snapshots

Bead digitva-9xn9.10 (D10). "Import JSON" on a COD scheme replaces every node
and mapping, so it snapshots the whole scheme first with reason ``json_import``.

Additive and reversible: downgrade relabels any ``json_import`` snapshot
``reset_scheme`` (a whole-scheme snapshot taken before a whole-scheme change;
the payload is kept) and restores the previous check.

Revision ID: a9d3e6b1c4f8
Revises: f2b7d4a9c1e6
Create Date: 2026-11-12
"""

from alembic import op

revision = "a9d3e6b1c4f8"
down_revision = "f2b7d4a9c1e6"
branch_labels = None
depends_on = None

TABLE = "va_cod_bucket_scheme_snapshots"
CHECK = "ck_va_cod_bucket_scheme_snapshots_reason"


def upgrade():
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.create_check_constraint(
        op.f(CHECK),
        TABLE,
        "reason IN ('reset_scheme', 'reset_age_band', 'cli_import', 'apply_overrides', 'json_import')",
    )


def downgrade():
    op.execute(f"UPDATE {TABLE} SET reason = 'reset_scheme' WHERE reason = 'json_import'")
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.create_check_constraint(
        op.f(CHECK),
        TABLE,
        "reason IN ('reset_scheme', 'reset_age_band', 'cli_import', 'apply_overrides')",
    )
