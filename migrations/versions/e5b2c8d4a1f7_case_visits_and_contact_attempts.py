"""Case visit dates, contact attempts, second phone and structured address.

Revision ID: e5b2c8d4a1f7
Revises: d7f3b1a9c5e2
Create Date: 2026-09-30 20:00:00.000000

digitva-vzk.9 (interviewer worklist phase 5). Policy:
docs/policy/web-intake.md, "Built in phase 5". Additive and reversible:

- ``va_death_register`` gains ``next_visit_at`` and ``last_contact_at``
  (timestamptz), ``informant_phone_2`` and the structured address
  (``address_house_street``, ``address_village_ward``, ``address_landmark``)
  beside the free-text ``address``. All nullable; existing rows keep NULL.
- ``ix_va_death_register_next_visit`` serves the worklist sort.
- ``map_case_contact_attempts``: one row per contact attempt, outcome only
  (reached / no_answer / wrong_number / moved / refused), no notes.

Downgrade drops the table and the columns, so contact-attempt history, visit
dates, second phones and structured addresses are lost.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e5b2c8d4a1f7"
down_revision = "d7f3b1a9c5e2"
branch_labels = None
depends_on = None

OUTCOME_CHECK = "outcome IN ('reached', 'no_answer', 'wrong_number', 'moved', 'refused')"
NEW_TEXT_COLUMNS = ("address_house_street", "address_village_ward", "address_landmark")


def upgrade():
    op.add_column("va_death_register", sa.Column("next_visit_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("va_death_register", sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("va_death_register", sa.Column("informant_phone_2", sa.String(length=32), nullable=True))
    for name in NEW_TEXT_COLUMNS:
        op.add_column("va_death_register", sa.Column(name, sa.Text(), nullable=True))
    op.create_index(
        "ix_va_death_register_next_visit", "va_death_register", ["next_visit_at", "updated_at", "death_id"]
    )

    op.create_table(
        "map_case_contact_attempts",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("death_id", sa.Uuid(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("next_visit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.ForeignKeyConstraint(
            ["death_id"], ["va_death_register.death_id"],
            name="fk_map_case_contact_attempts_death_id_va_death_register",
        ),
        sa.ForeignKeyConstraint(
            ["by_user_id"], ["va_users.user_id"],
            name="fk_map_case_contact_attempts_by_user_id_va_users",
        ),
        sa.CheckConstraint(OUTCOME_CHECK, name=op.f("ck_map_case_contact_attempts_outcome")),
    )
    op.create_index(
        "ix_map_case_contact_attempts_death_attempted", "map_case_contact_attempts", ["death_id", "attempted_at"]
    )
    op.create_index(
        "ix_map_case_contact_attempts_by_user", "map_case_contact_attempts", ["by_user_id", "death_id"]
    )


def downgrade():
    op.drop_index("ix_map_case_contact_attempts_by_user", table_name="map_case_contact_attempts")
    op.drop_index("ix_map_case_contact_attempts_death_attempted", table_name="map_case_contact_attempts")
    op.drop_table("map_case_contact_attempts")
    op.drop_index("ix_va_death_register_next_visit", table_name="va_death_register")
    for name in reversed(NEW_TEXT_COLUMNS):
        op.drop_column("va_death_register", name)
    op.drop_column("va_death_register", "informant_phone_2")
    op.drop_column("va_death_register", "last_contact_at")
    op.drop_column("va_death_register", "next_visit_at")
