"""Add the optional death-site GPS fix to va_death_register.

Revision ID: q7w2e5r8t1y4
Revises: m4v8r2t6q1w9
Create Date: 2026-10-13 10:00:00.000000

latitude, longitude, accuracy_m and captured_at, all nullable: a full fix or
none. Additive and reversible (docs/policy/web-intake.md, "Death-site GPS
location"). Downgrade drops the columns and so the captured coordinates.
"""
import sqlalchemy as sa
from alembic import op

revision = "q7w2e5r8t1y4"
down_revision = "m4v8r2t6q1w9"
branch_labels = None
depends_on = None

TABLE = "va_death_register"
# Bare names: the naming convention prefixes "ck_va_death_register_".
CHECKS = {
    "location_range": "(latitude IS NULL OR latitude BETWEEN -90 AND 90) "
                      "AND (longitude IS NULL OR longitude BETWEEN -180 AND 180)",
    "location_all_or_none": "(latitude IS NULL) = (longitude IS NULL) "
                            "AND (latitude IS NULL) = (captured_at IS NULL) "
                            "AND (latitude IS NOT NULL OR accuracy_m IS NULL)",
    "location_accuracy": "accuracy_m IS NULL OR accuracy_m >= 0",
}


def upgrade():
    op.add_column(TABLE, sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column(TABLE, sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column(TABLE, sa.Column("accuracy_m", sa.Float(), nullable=True))
    op.add_column(TABLE, sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True))
    for name, expr in CHECKS.items():
        op.create_check_constraint(name, TABLE, expr)


def downgrade():
    for name in CHECKS:
        op.drop_constraint(op.f(f"ck_{TABLE}_{name}"), TABLE, type_="check")
    for column in ("captured_at", "accuracy_m", "longitude", "latitude"):
        op.drop_column(TABLE, column)
