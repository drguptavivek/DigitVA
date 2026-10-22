"""Sealed-personal-data columns on the death register and the audit table.

Revision ID: e5a2c7b9d3f1
Revises: d4f1b8c2a6e9
Create Date: 2026-10-21

PII slice 2, task T1 (docs/kb/pii-slice-2.md; policy: docs/policy/
pii-encryption-at-rest.md, "Register design"). Additive: nothing is sealed at
upgrade; rows are written sealed only with ``REGISTER_PII_SPLIT_ENABLED`` on.

``va_death_register``: ``pii_sealed`` and its wrapped DEK, key id, blind key
id and time; four blind indexes (two phones, ABHA number and address); four
presence flags (``has_deceased_name``, ``has_informant_phone``,
``has_informant_phone_2``, ``has_location``) filled here from the plaintext
columns. ``updated_at`` is left alone (the fill is plain SQL, no ``onupdate``).

The identity and location CHECKs read the flags, so a row whose plaintext is
NULL because it is sealed still satisfies them.

``map_case_transitions``: ``changes_dek_wrapped`` and ``changes_key_id`` for
sealed old/new values in ``changes``.

Downgrade restores the old CHECKs and drops the columns, and refuses while any
row is sealed: the values exist nowhere else (run the register backfill
restore first).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e5a2c7b9d3f1"
down_revision = "d4f1b8c2a6e9"
branch_labels = None
depends_on = None

TABLE = "va_death_register"
IDENTITY_CK = "ck_va_death_register_identity"
LOCATION_CK = "ck_va_death_register_location_all_or_none"

IDENTITY_OLD = (
    "status IN ('draft_identity', 'cancelled') OR "
    "(deceased_name IS NOT NULL AND date_of_death IS NOT NULL AND deceased_sex IS NOT NULL)"
)
IDENTITY_NEW = (
    "status IN ('draft_identity', 'cancelled') OR "
    "(has_deceased_name AND date_of_death IS NOT NULL AND deceased_sex IS NOT NULL)"
)
LOCATION_OLD = (
    "(latitude IS NULL) = (longitude IS NULL) "
    "AND (latitude IS NULL) = (captured_at IS NULL) "
    "AND (latitude IS NOT NULL OR accuracy_m IS NULL)"
)
LOCATION_NEW = (
    "(latitude IS NULL) = (longitude IS NULL) "
    "AND (has_location = (captured_at IS NOT NULL)) "
    "AND (has_location OR accuracy_m IS NULL) "
    "AND (latitude IS NULL OR has_location)"
)

BIDX_COLUMNS = ("informant_phone_bidx", "informant_phone_2_bidx", "abha_number_bidx", "abha_address_bidx")
# presence flag -> the plaintext column it mirrors
FLAGS = {
    "has_deceased_name": "deceased_name",
    "has_informant_phone": "informant_phone",
    "has_informant_phone_2": "informant_phone_2",
    "has_location": "latitude",
}


def _index_name(column):
    return f"ix_va_death_register_project_{column}"


def upgrade():
    op.add_column(TABLE, sa.Column("pii_sealed", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column(TABLE, sa.Column("pii_dek_wrapped", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("pii_key_id", sa.String(16), nullable=True))
    op.add_column(TABLE, sa.Column("pii_blind_key_id", sa.String(8), nullable=True))
    op.add_column(TABLE, sa.Column("pii_sealed_at", sa.DateTime(timezone=True), nullable=True))
    for column in BIDX_COLUMNS:
        op.add_column(TABLE, sa.Column(column, sa.String(128), nullable=True))
    for flag in FLAGS:
        op.add_column(TABLE, sa.Column(flag, sa.Boolean(), server_default=sa.false(), nullable=False))

    # Fill the flags before the CHECKs that read them. Plain SQL, so the ORM
    # ``onupdate`` does not run and ``updated_at`` stays as it was.
    assignments = ", ".join(f"{flag} = ({column} IS NOT NULL)" for flag, column in FLAGS.items())
    op.execute(sa.text(f"UPDATE {TABLE} SET {assignments}"))

    op.drop_constraint(op.f(IDENTITY_CK), TABLE, type_="check")
    op.create_check_constraint(op.f(IDENTITY_CK), TABLE, IDENTITY_NEW)
    op.drop_constraint(op.f(LOCATION_CK), TABLE, type_="check")
    op.create_check_constraint(op.f(LOCATION_CK), TABLE, LOCATION_NEW)

    for column in BIDX_COLUMNS:
        op.create_index(
            _index_name(column), TABLE, ["project_id", column],
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
        )
    op.create_index(
        "ix_va_death_register_pii_key", TABLE, ["pii_key_id"],
        postgresql_where=sa.text("pii_sealed IS NOT NULL"),
    )

    op.add_column("map_case_transitions", sa.Column("changes_dek_wrapped", sa.Text(), nullable=True))
    op.add_column("map_case_transitions", sa.Column("changes_key_id", sa.String(16), nullable=True))


def downgrade():
    bind = op.get_bind()
    sealed = bind.execute(sa.text(f"SELECT count(*) FROM {TABLE} WHERE pii_sealed IS NOT NULL")).scalar()
    sealed_audit = bind.execute(
        sa.text("SELECT count(*) FROM map_case_transitions WHERE changes_dek_wrapped IS NOT NULL")
    ).scalar()
    if sealed or sealed_audit:
        raise RuntimeError(
            f"{sealed} register row(s) and {sealed_audit} audit row(s) hold sealed personal data that exists "
            "nowhere else; restore it to plaintext (or restore the pre-seal dump) first, then downgrade."
        )
    op.drop_column("map_case_transitions", "changes_key_id")
    op.drop_column("map_case_transitions", "changes_dek_wrapped")

    op.drop_index("ix_va_death_register_pii_key", table_name=TABLE)
    for column in BIDX_COLUMNS:
        op.drop_index(_index_name(column), table_name=TABLE)

    op.drop_constraint(op.f(LOCATION_CK), TABLE, type_="check")
    op.drop_constraint(op.f(IDENTITY_CK), TABLE, type_="check")
    op.create_check_constraint(op.f(IDENTITY_CK), TABLE, IDENTITY_OLD)
    op.create_check_constraint(op.f(LOCATION_CK), TABLE, LOCATION_OLD)

    for flag in FLAGS:
        op.drop_column(TABLE, flag)
    for column in BIDX_COLUMNS:
        op.drop_column(TABLE, column)
    for column in ("pii_sealed_at", "pii_blind_key_id", "pii_key_id", "pii_dek_wrapped", "pii_sealed"):
        op.drop_column(TABLE, column)
