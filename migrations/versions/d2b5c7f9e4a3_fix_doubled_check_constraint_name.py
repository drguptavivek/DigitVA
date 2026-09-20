"""Fix the doubled, truncated CHECK constraint name on mas_instrument_locales

Revision ID: d2b5c7f9e4a3
Revises: c1a4b6e8d3f2
Create Date: 2026-09-20

digitva-we0: the naming convention in app/__init__.py is
``ck_%(table_name)s_%(constraint_name)s``, and both the model
(app/models/mas_instrument_locales.py) and migration a3f7c1d9e6b4 passed the
already-prefixed full name (``ck_mas_instrument_locales_active_requires_approved``)
as ``constraint_name``, so the prefix applied twice and Postgres truncated the
result at 63 characters to
``ck_mas_instrument_locales_ck_mas_instrument_locales_act_5121``. The model
now passes only the discriminator, ``active_requires_approved``, so the
convention renders the intended
``ck_mas_instrument_locales_active_requires_approved``. a3f7c1d9e6b4 is
already applied and pushed and must not be edited, so this migration renames
the live constraint instead of recreating it -- no data or rule changes,
Create and drop are unaffected.

Reversible: downgrade renames it back to the doubled name, matching
a3f7c1d9e6b4 exactly, so a downgrade to that revision still finds the
constraint it expects.
"""

from alembic import op

revision = 'd2b5c7f9e4a3'
down_revision = 'c1a4b6e8d3f2'
branch_labels = None
depends_on = None

TABLE = "mas_instrument_locales"
OLD_NAME = "ck_mas_instrument_locales_ck_mas_instrument_locales_act_5121"
NEW_NAME = "ck_mas_instrument_locales_active_requires_approved"


def upgrade():
    op.execute(
        f'ALTER TABLE {TABLE} RENAME CONSTRAINT "{OLD_NAME}" TO "{NEW_NAME}"'
    )


def downgrade():
    op.execute(
        f'ALTER TABLE {TABLE} RENAME CONSTRAINT "{NEW_NAME}" TO "{OLD_NAME}"'
    )
