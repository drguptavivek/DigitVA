"""Fix the remaining doubled, sometimes-truncated CHECK constraint names

Revision ID: fd232fab5987
Revises: 7134cb5dc7b6
Create Date: 2026-09-20

digitva-liu: the naming convention in app/__init__.py is
``ck_%(table_name)s_%(constraint_name)s``. Thirteen model declarations (all
but ``mas_instrument_locales``, already fixed by d2b5c7f9e4a3) passed the
already-prefixed full name as ``constraint_name``, so the prefix applied
twice; four results exceeded 63 characters and Postgres truncated them with
a hash suffix. The models now pass only the discriminator.

Verified against ``pg_constraint`` rather than assumed: the live dev database
(migrated incrementally over time) shows only eleven of these thirteen
doubled today -- ``va_smartva_form_runs_outcome`` and
``va_submission_payload_versions_status`` already carry their clean,
undoubled names there, even though their model declarations passed the
doubled form. That is because a name is only re-run through the convention
when a migration creates or alters the constraint through the convention's
codepath (``op.create_check_constraint``, or ``op.create_table``/
``op.add_column`` bound to the app's naming-convention metadata); how each
of these thirteen got its current name depends on which one the migration
that created it used, and evidently differs from what a fresh
``flask db upgrade`` from an empty database now reproduces -- replaying the
full chain against an empty database doubles all thirteen, including the two
that are clean on the long-lived dev database. So each rename below is
guarded by an existence check against the doubled/truncated name rather than
applied unconditionally: a no-op where the name is already correct, a rename
where it is not. This keeps the migration safe to run against either kind of
database. Downgrade is the mirror: guarded on the clean name existing, so it
is also a no-op where the constraint was never touched forward.

No data or rule changes; each CHECK's condition is untouched, only its name.
"""

from alembic import op

revision = "fd232fab5987"
down_revision = "7134cb5dc7b6"
branch_labels = None
depends_on = None

# (table, old/doubled name as currently in pg_constraint, new/clean name)
RENAMES = [
    ("va_forms", "ck_va_forms_ck_va_forms_form_source", "ck_va_forms_form_source"),
    (
        "va_submissions",
        "ck_va_submissions_ck_va_submissions_org_unit_resolution_pair",
        "ck_va_submissions_org_unit_resolution_pair",
    ),
    (
        "va_submissions",
        "ck_va_submissions_ck_va_submissions_org_unit_resolution_value",
        "ck_va_submissions_org_unit_resolution_value",
    ),
    (
        "va_submissions",
        "ck_va_submissions_ck_va_submissions_org_unit_pin_manual",
        "ck_va_submissions_org_unit_pin_manual",
    ),
    (
        "va_project_master",
        "ck_va_project_master_ck_va_project_master_web_intake_mode",
        "ck_va_project_master_web_intake_mode",
    ),
    (
        "va_project_master",
        # Postgres-truncated at 63 characters with a hash suffix.
        "ck_va_project_master_ck_va_project_master_above_scope_c_108a",
        "ck_va_project_master_above_scope_coding_mode",
    ),
    (
        "va_user_access_grants",
        "ck_va_user_access_grants_ck_va_user_access_grants_scope_shape",
        "ck_va_user_access_grants_scope_shape",
    ),
    (
        "va_user_access_grants",
        "ck_va_user_access_grants_ck_va_user_access_grants_role_scope",
        "ck_va_user_access_grants_role_scope",
    ),
    (
        "va_user_access_grants",
        "ck_va_user_access_grants_ck_va_user_access_grants_cadre_scope",
        "ck_va_user_access_grants_cadre_scope",
    ),
    (
        "map_project_site_odk",
        # Postgres-truncated at 63 characters with a hash suffix.
        "ck_map_project_site_odk_ck_map_project_site_odk_icd_cla_9c4d",
        "ck_map_project_site_odk_icd_classification",
    ),
    (
        "mas_org_level",
        "ck_mas_org_level_ck_mas_org_level_depth_positive",
        "ck_mas_org_level_depth_positive",
    ),
    (
        "va_smartva_form_runs",
        "ck_va_smartva_form_runs_ck_va_smartva_form_runs_outcome",
        "ck_va_smartva_form_runs_outcome",
    ),
    (
        "va_submission_payload_versions",
        # Postgres-truncated at 63 characters with a hash suffix.
        "ck_va_submission_payload_versions_ck_va_submission_payl_5c38",
        "ck_va_submission_payload_versions_status",
    ),
]

_RENAME_IF_EXISTS = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = '{table}'::regclass AND conname = '{old}'
    ) THEN
        ALTER TABLE {table} RENAME CONSTRAINT "{old}" TO "{new}";
    END IF;
END $$;
"""


def upgrade():
    for table, old, new in RENAMES:
        op.execute(_RENAME_IF_EXISTS.format(table=table, old=old, new=new))


def downgrade():
    for table, old, new in RENAMES:
        op.execute(_RENAME_IF_EXISTS.format(table=table, old=new, new=old))
