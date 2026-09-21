"""ICD classification on COD bucket mappings; ICD-11 method on schemes.

Revision ID: 62a637f5c38a
Revises: a4c7e2f9b1d6
Create Date: 2026-09-21 18:00:00.000000

digitva-712.1. Policy: docs/policy/icd11-cod-bucket-schemes.md ("Data").

- map_icd_cod_buckets.icd_classification ('icd10' | 'icd11', server default
  'icd10'), part of the unique key and of the upper(icd_code) unique index,
  so one scheme can hold an ICD-10 and an ICD-11 mapping table side by side.
- mas_cod_bucket_schemes.icd11_method ('crosswalk' | 'native' | NULL).

Additive: every existing mapping becomes 'icd10', every scheme NULL. No row
is changed otherwise. Downgrade refuses while ICD-11 rows exist, because
dropping the column would silently turn them into ICD-10 mappings; they are
regenerable (`flask cod-buckets generate-icd11`), so delete them first.

CHECKs are added with raw SQL under their final names so the naming
convention in app/__init__.py cannot prefix them twice (see fd232fab5987).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "62a637f5c38a"
down_revision = "a4c7e2f9b1d6"
branch_labels = None
depends_on = None

MAP_TABLE = "map_icd_cod_buckets"
SCHEME_TABLE = "mas_cod_bucket_schemes"
CLASSIFICATION_CHECK = "ck_map_icd_cod_buckets_icd_classification"
METHOD_CHECK = "ck_mas_cod_bucket_schemes_icd11_method"
OLD_UNIQUE = "uq_map_icd_cod_buckets_scheme_scope_icd"
NEW_UNIQUE = "uq_map_icd_cod_buckets_scheme_class_scope_icd"
OLD_NORM_INDEX = "ux_map_icd_cod_buckets_scheme_scope_icd_norm"
NEW_NORM_INDEX = "ux_map_icd_cod_buckets_scheme_class_scope_icd_norm"


def upgrade():
    op.add_column(
        MAP_TABLE,
        sa.Column(
            "icd_classification",
            sa.String(length=8),
            nullable=False,
            server_default="icd10",
        ),
    )
    op.execute(
        f'ALTER TABLE {MAP_TABLE} ADD CONSTRAINT "{CLASSIFICATION_CHECK}" '
        "CHECK (icd_classification IN ('icd10', 'icd11'))"
    )
    op.drop_constraint(OLD_UNIQUE, MAP_TABLE, type_="unique")
    op.create_unique_constraint(
        NEW_UNIQUE,
        MAP_TABLE,
        ["scheme_id", "icd_classification", "age_scope", "icd_code"],
    )
    op.execute(f"DROP INDEX IF EXISTS {OLD_NORM_INDEX}")
    op.execute(
        f"CREATE UNIQUE INDEX {NEW_NORM_INDEX} ON {MAP_TABLE} "
        "(scheme_id, icd_classification, COALESCE(age_scope, ''), upper(icd_code))"
    )

    op.add_column(
        SCHEME_TABLE,
        sa.Column("icd11_method", sa.String(length=16), nullable=True),
    )
    op.execute(
        f'ALTER TABLE {SCHEME_TABLE} ADD CONSTRAINT "{METHOD_CHECK}" '
        "CHECK (icd11_method IN ('crosswalk', 'native'))"
    )


def downgrade():
    icd11_rows = op.get_bind().execute(
        sa.text(f"SELECT count(*) FROM {MAP_TABLE} WHERE icd_classification = 'icd11'")
    ).scalar()
    if icd11_rows:
        raise RuntimeError(
            f"{icd11_rows} ICD-11 COD bucket mappings exist; dropping "
            "icd_classification would turn them into ICD-10 mappings. Delete "
            "them first (they are regenerable with flask cod-buckets generate-icd11)."
        )

    op.execute(f'ALTER TABLE {SCHEME_TABLE} DROP CONSTRAINT IF EXISTS "{METHOD_CHECK}"')
    op.drop_column(SCHEME_TABLE, "icd11_method")

    op.execute(f"DROP INDEX IF EXISTS {NEW_NORM_INDEX}")
    op.execute(
        f"CREATE UNIQUE INDEX {OLD_NORM_INDEX} ON {MAP_TABLE} "
        "(scheme_id, COALESCE(age_scope, ''), upper(icd_code))"
    )
    op.drop_constraint(NEW_UNIQUE, MAP_TABLE, type_="unique")
    op.create_unique_constraint(
        OLD_UNIQUE, MAP_TABLE, ["scheme_id", "age_scope", "icd_code"]
    )
    op.execute(f'ALTER TABLE {MAP_TABLE} DROP CONSTRAINT IF EXISTS "{CLASSIFICATION_CHECK}"')
    op.drop_column(MAP_TABLE, "icd_classification")
