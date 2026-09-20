"""Add approval lifecycle to mas_instrument_locales.

Revision ID: a3f7c1d9e6b4
Revises: e1b6c9a3d7f4
Create Date: 2026-09-20 00:00:00.000000

Decided 2026-09-20: a locale must not be served to interviewers unless a
human has approved it, and that approval must be recorded. Adds
``lifecycle_state`` (``draft`` / ``in_review`` / ``approved``),
``approved_by_user_id`` and ``approved_at`` to ``mas_instrument_locales``, plus
a CHECK constraint that only an ``approved`` locale may be ``is_active``.
Coverage still decides nothing (2026-09-19 decision stands); this is a human
approval gate, not a coverage gate.

**OPERATOR NOTE -- this is not a no-op backfill.** Every existing locale is
backfilled to ``lifecycle_state='in_review'`` and, deliberately,
``is_active=false`` -- the constraint below cannot otherwise be satisfied
against a database that already has active locales, and there is no
lifecycle history to infer an existing "approved" state from. After this
upgrade, interviewers fall back to English per string for every locale that
was previously active, until an administrator reviews each one, approves it
and re-activates it. See docs/current-state/admin-and-setup.md ("Instrument
Translations Panel -- operator note after this upgrade") for the estimated
translation work remaining per locale.

Reversible, but not purely additive: ``upgrade`` clears ``is_active`` on
every row, so the set of locales that were active before it ran is captured
into ``_mig_a3f7c1d9e6b4_prior_active`` first and ``downgrade`` restores
``is_active`` from it. Without that table a downgrade would leave every locale
inactive with no record of which had been live, which is exactly the kind of
one-way door CLAUDE.md forbids ("no bulk ... overwrite ... without a verified
backup and recovery path").
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a3f7c1d9e6b4"
down_revision = "e1b6c9a3d7f4"
branch_labels = None
depends_on = None

TABLE = "mas_instrument_locales"
CHECK_NAME = "ck_mas_instrument_locales_active_requires_approved"
#: Holds which locales were active before this migration deactivated them,
#: so downgrade can put them back. Dropped by downgrade.
PRIOR_ACTIVE_TABLE = "_mig_a3f7c1d9e6b4_prior_active"


def upgrade():
    op.add_column(
        TABLE,
        sa.Column(
            "lifecycle_state",
            sa.String(length=16),
            nullable=False,
            server_default="draft",
        ),
    )
    op.add_column(
        TABLE,
        sa.Column("approved_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        TABLE,
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_mas_instrument_locales_approved_by_user_id",
        TABLE,
        "va_users",
        ["approved_by_user_id"],
        ["user_id"],
    )

    # Recovery path for the mass-deactivation below. IF NOT EXISTS, not a
    # DROP-then-CREATE: were this migration ever re-applied after a stamp, the
    # second run would find nothing active and a fresh capture would destroy
    # the real record of what had been live.
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {PRIOR_ACTIVE_TABLE} AS "
        f"SELECT instrument_code, locale_code FROM {TABLE} WHERE is_active"
    )

    # Deliberate mass-deactivation, not a no-op backfill -- see the module
    # docstring. This must run before the CHECK constraint below, or the
    # constraint would fail against any row that is already active.
    op.execute(
        f"UPDATE {TABLE} SET lifecycle_state = 'in_review', is_active = false, "
        "approved_by_user_id = NULL, approved_at = NULL"
    )

    op.create_check_constraint(
        CHECK_NAME,
        TABLE,
        "is_active = false OR lifecycle_state = 'approved'",
    )


def downgrade():
    """Restore the pre-upgrade ``is_active`` flags, then drop the lifecycle.

    The constraint goes first: while it stands, no row may be active unless it
    is approved, and the rows being restored are ``in_review``.
    """
    op.drop_constraint(CHECK_NAME, TABLE, type_="check")
    op.execute(
        f"UPDATE {TABLE} t SET is_active = true "
        f"FROM {PRIOR_ACTIVE_TABLE} p "
        "WHERE t.instrument_code = p.instrument_code "
        "AND t.locale_code = p.locale_code"
    )
    op.drop_constraint(
        "fk_mas_instrument_locales_approved_by_user_id", TABLE, type_="foreignkey"
    )
    op.drop_column(TABLE, "approved_at")
    op.drop_column(TABLE, "approved_by_user_id")
    op.drop_column(TABLE, "lifecycle_state")
    op.execute(f"DROP TABLE IF EXISTS {PRIOR_ACTIVE_TABLE}")
