"""Training sessions carry a type; participants a graduation time.

Revision ID: b4e8c2a6d0f3
Revises: a9d3e6b1c4f8
Create Date: 2026-11-15

Additive (docs/policy/training-session-types.md):

- ``mas_training_sessions.session_type`` (NULL, or ``interviewer``,
  ``coder``, ``self_coding``). NULL is a legacy mixed session (S001, S002),
  unchanged.
- The slots check widens to 0..100 and ties zero slots to the interviewer
  type: an interviewer session has no coder slot, every other session at
  least one.
- ``map_training_participants.graduated_at`` (nullable), set by graduation
  in a later phase.

Downgrade refuses while a typed session exists: its participants and grants
are retained records (docs/policy/training-demo-project.md).
"""

import sqlalchemy as sa
from alembic import op

revision = "b4e8c2a6d0f3"
down_revision = "a9d3e6b1c4f8"
branch_labels = None
depends_on = None

TABLE = "mas_training_sessions"
SLOTS = "ck_mas_training_sessions_coder_slots"
TYPE = "ck_mas_training_sessions_session_type"


def upgrade():
    op.add_column(TABLE, sa.Column("session_type", sa.String(16), nullable=True))
    op.create_check_constraint(
        op.f(TYPE), TABLE, "session_type IS NULL OR session_type IN ('interviewer', 'coder', 'self_coding')"
    )
    op.drop_constraint(op.f(SLOTS), TABLE, type_="check")
    op.create_check_constraint(
        op.f(SLOTS),
        TABLE,
        "coder_slots BETWEEN 0 AND 100 AND "
        "(coder_slots = 0) = (session_type IS NOT DISTINCT FROM 'interviewer')",
    )
    op.add_column(
        "map_training_participants", sa.Column("graduated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    typed = op.get_bind().execute(
        sa.text(f"SELECT count(*) FROM {TABLE} WHERE session_type IS NOT NULL")
    ).scalar()
    if typed:
        raise RuntimeError(
            f"{typed} typed training session(s) exist; their participants and grants are retained "
            "records. Back them up and remove them deliberately before downgrading."
        )
    op.drop_column("map_training_participants", "graduated_at")
    op.drop_constraint(op.f(SLOTS), TABLE, type_="check")
    op.create_check_constraint(op.f(SLOTS), TABLE, "coder_slots BETWEEN 1 AND 100")
    op.drop_constraint(op.f(TYPE), TABLE, type_="check")
    op.drop_column(TABLE, "session_type")
