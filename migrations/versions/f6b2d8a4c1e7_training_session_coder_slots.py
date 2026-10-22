"""Training sessions choose their number of coder slots.

Revision ID: f6b2d8a4c1e7
Revises: d4a7c9e2f5b1
Create Date: 2026-10-22

Additive: ``mas_training_sessions.coder_slots`` (1..100, existing rows get the
old fixed 20). The checks that fixed every session at 20 slots and 200 cases
widen to 100 slots (``map_training_cases.coder_slot``,
``map_training_participants.coder_slot``) and 1000 cases
(``map_training_cases.case_number``). Downgrade narrows them again and refuses
while any session has more than 20 slots: its case copies and participants
are retained records (docs/policy/training-demo-project.md). Bead digitva-palj.
"""

import sqlalchemy as sa
from alembic import op

revision = "f6b2d8a4c1e7"
down_revision = "d4a7c9e2f5b1"
branch_labels = None
depends_on = None


def _set_checks(slots: int, cases: int) -> None:
    for table, name, condition in (
        ("map_training_cases", "ck_map_training_cases_case_number", f"case_number BETWEEN 1 AND {cases}"),
        ("map_training_cases", "ck_map_training_cases_coder_slot", f"coder_slot BETWEEN 1 AND {slots}"),
        ("map_training_participants", "ck_map_training_participants_coder_slot",
         f"coder_slot IS NULL OR coder_slot BETWEEN 1 AND {slots}"),
    ):
        op.drop_constraint(op.f(name), table, type_="check")
        op.create_check_constraint(op.f(name), table, condition)


def upgrade():
    op.add_column(
        "mas_training_sessions",
        sa.Column("coder_slots", sa.Integer(), server_default="20", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_mas_training_sessions_coder_slots"), "mas_training_sessions", "coder_slots BETWEEN 1 AND 100"
    )
    _set_checks(100, 1000)


def downgrade():
    wide = op.get_bind().execute(
        sa.text("SELECT count(*) FROM mas_training_sessions WHERE coder_slots > 20")
    ).scalar()
    if wide:
        raise RuntimeError(
            f"{wide} training session(s) have more than 20 coder slots; their case copies and "
            "participants are retained records. Back them up and remove them deliberately before downgrading."
        )
    _set_checks(20, 200)
    op.drop_constraint(op.f("ck_mas_training_sessions_coder_slots"), "mas_training_sessions", type_="check")
    op.drop_column("mas_training_sessions", "coder_slots")
