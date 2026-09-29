"""The death register entry becomes the case: states, source, audit.

Revision ID: c4e8a2f6b9d3
Revises: a7c3e9f1b5d2
Create Date: 2026-09-30 12:00:00.000000

digitva-vzk.4 (interviewer worklist phases 2 and 3). Policy:
docs/policy/web-intake.md, "Case worklist and interview states"; plan:
.tasks/2026-09-28-interviewer-worklist.md.

Additive and reversible:

- ``deceased_name``, ``date_of_death`` and ``deceased_sex`` become nullable:
  a direct start creates its case before the form has captured any identity
  (state ``draft_identity``). A CHECK keeps all three required outside
  ``draft_identity`` and ``cancelled``.
- ``source`` (register | direct), ``started_by_user_id``, and the duplicate /
  cancel flag columns (``pending_flag``, ``duplicate_of_death_id``).
- ``status`` moves to the case states; old values map forward
  (va_in_progress -> in_progress, va_submitted -> submitted; registered and
  cancelled keep their names). ``started_by_user_id`` is backfilled from the
  earliest draft of each case.
- ``map_case_transitions``: one audit row per state change or flag.

Downgrade maps the new states back onto the old four and refuses to run while
any case has no identity yet, rather than deleting or inventing data.
Downgrade drops ``map_case_transitions``, so the case audit history is lost.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c4e8a2f6b9d3"
down_revision = "a7c3e9f1b5d2"
branch_labels = None
depends_on = None

CASE_STATES = (
    "draft_identity", "registered", "scheduled", "in_progress", "paused",
    "not_reachable", "refused", "submitted", "duplicate", "cancelled",
)
STATUS_CHECK = "status IN (" + ", ".join(f"'{s}'" for s in CASE_STATES) + ")"
SOURCE_CHECK = "source IN ('register', 'direct')"
IDENTITY_CHECK = (
    "status IN ('draft_identity', 'cancelled') OR "
    "(deceased_name IS NOT NULL AND date_of_death IS NOT NULL AND deceased_sex IS NOT NULL)"
)
FLAG_CHECK = "pending_flag IN ('duplicate', 'cancel')"


def upgrade():
    op.add_column(
        "va_death_register",
        sa.Column("source", sa.String(length=16), nullable=False, server_default="register"),
    )
    op.add_column("va_death_register", sa.Column("started_by_user_id", sa.Uuid(), nullable=True))
    op.add_column("va_death_register", sa.Column("pending_flag", sa.String(length=16), nullable=True))
    op.add_column("va_death_register", sa.Column("duplicate_of_death_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_va_death_register_started_by_user_id_va_users",
        "va_death_register", "va_users", ["started_by_user_id"], ["user_id"],
    )
    op.create_foreign_key(
        "fk_va_death_register_duplicate_of_death_id_va_death_register",
        "va_death_register", "va_death_register", ["duplicate_of_death_id"], ["death_id"],
    )
    op.alter_column("va_death_register", "deceased_name", existing_type=sa.Text(), nullable=True)
    op.alter_column("va_death_register", "date_of_death", existing_type=sa.Date(), nullable=True)
    op.alter_column("va_death_register", "deceased_sex", existing_type=sa.String(length=16), nullable=True)

    op.execute("UPDATE va_death_register SET status = 'in_progress' WHERE status = 'va_in_progress'")
    op.execute("UPDATE va_death_register SET status = 'submitted' WHERE status = 'va_submitted'")
    # Whoever opened the first draft started the interview.
    op.execute(
        """
        UPDATE va_death_register d SET started_by_user_id = first_draft.user_id
        FROM (
            SELECT DISTINCT ON (death_id) death_id, user_id
            FROM va_web_intake_drafts
            WHERE death_id IS NOT NULL
            ORDER BY death_id, created_at
        ) first_draft
        WHERE first_draft.death_id = d.death_id
          AND d.status IN ('in_progress', 'submitted')
        """
    )

    op.create_check_constraint(op.f("ck_va_death_register_status"), "va_death_register", STATUS_CHECK)
    op.create_check_constraint(op.f("ck_va_death_register_source"), "va_death_register", SOURCE_CHECK)
    op.create_check_constraint(op.f("ck_va_death_register_identity"), "va_death_register", IDENTITY_CHECK)
    op.create_check_constraint(op.f("ck_va_death_register_pending_flag"), "va_death_register", FLAG_CHECK)

    op.create_table(
        "map_case_transitions",
        sa.Column("transition_id", sa.Uuid(), nullable=False),
        sa.Column("death_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("from_state", sa.String(length=16), nullable=True),
        sa.Column("to_state", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("transition_id"),
        sa.ForeignKeyConstraint(
            ["death_id"], ["va_death_register.death_id"],
            name="fk_map_case_transitions_death_id_va_death_register",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["va_users.user_id"],
            name="fk_map_case_transitions_actor_user_id_va_users",
        ),
    )
    op.create_index("ix_map_case_transitions_death_created", "map_case_transitions", ["death_id", "created_at"])
    op.create_index("ix_map_case_transitions_actor", "map_case_transitions", ["actor_user_id", "death_id"])
    # The worklist pages team cases by last activity.
    op.create_index("ix_va_death_register_updated", "va_death_register", ["updated_at", "death_id"])


def downgrade():
    bind = op.get_bind()
    pending = bind.execute(
        sa.text(
            "SELECT count(*) FROM va_death_register "
            "WHERE deceased_name IS NULL OR date_of_death IS NULL OR deceased_sex IS NULL"
        )
    ).scalar_one()
    if pending:
        raise RuntimeError(
            f"{pending} case(s) have no name, date of death or sex yet (direct starts). "
            "The previous schema cannot hold them; complete or remove them deliberately "
            "before downgrading. Nothing was changed."
        )

    op.drop_index("ix_va_death_register_updated", table_name="va_death_register")
    op.drop_index("ix_map_case_transitions_actor", table_name="map_case_transitions")
    op.drop_index("ix_map_case_transitions_death_created", table_name="map_case_transitions")
    op.drop_table("map_case_transitions")

    op.drop_constraint(op.f("ck_va_death_register_pending_flag"), "va_death_register", type_="check")
    op.drop_constraint(op.f("ck_va_death_register_identity"), "va_death_register", type_="check")
    op.drop_constraint(op.f("ck_va_death_register_source"), "va_death_register", type_="check")
    op.drop_constraint(op.f("ck_va_death_register_status"), "va_death_register", type_="check")

    op.execute(
        "UPDATE va_death_register SET status = CASE status "
        "WHEN 'in_progress' THEN 'va_in_progress' "
        "WHEN 'paused' THEN 'va_in_progress' "
        "WHEN 'not_reachable' THEN 'va_in_progress' "
        "WHEN 'refused' THEN 'va_in_progress' "
        "WHEN 'submitted' THEN 'va_submitted' "
        "WHEN 'scheduled' THEN 'registered' "
        "WHEN 'duplicate' THEN 'cancelled' "
        "ELSE status END"
    )

    op.alter_column("va_death_register", "deceased_sex", existing_type=sa.String(length=16), nullable=False)
    op.alter_column("va_death_register", "date_of_death", existing_type=sa.Date(), nullable=False)
    op.alter_column("va_death_register", "deceased_name", existing_type=sa.Text(), nullable=False)
    op.drop_constraint(
        "fk_va_death_register_duplicate_of_death_id_va_death_register", "va_death_register", type_="foreignkey"
    )
    op.drop_constraint("fk_va_death_register_started_by_user_id_va_users", "va_death_register", type_="foreignkey")
    op.drop_column("va_death_register", "duplicate_of_death_id")
    op.drop_column("va_death_register", "pending_flag")
    op.drop_column("va_death_register", "started_by_user_id")
    op.drop_column("va_death_register", "source")
