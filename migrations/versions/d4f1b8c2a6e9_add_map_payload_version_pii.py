"""Side table for the sealed personal data of a payload version.

Revision ID: d4f1b8c2a6e9
Revises: c7e3a9d1f5b2
Create Date: 2026-10-21

Additive and empty at upgrade: rows are written only by ``flask pii
split-payloads --apply`` or with ``PAYLOAD_PII_SPLIT_ENABLED`` on (PII slice
1b part II-A). ``sealed_ids`` is the sealed set the row's ``pii_digest`` was
computed under, so a later ``is_pii`` toggle never mixes two sets in one
comparison. Downgrade drops the table and refuses while it holds any row:
the sealed fields exist nowhere else, so run ``flask pii split-payloads
--restore`` first. Policy: docs/policy/pii-encryption-at-rest.md, "Payload
design"; docs/kb/pii-slice-1b.md.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d4f1b8c2a6e9"
down_revision = "c7e3a9d1f5b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "map_payload_version_pii",
        sa.Column("payload_version_id", sa.Uuid(), nullable=False),
        sa.Column("va_sid", sa.String(64), nullable=False),
        sa.Column("sealed", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dek_wrapped", sa.Text(), nullable=False),
        sa.Column("key_id", sa.String(16), nullable=False),
        sa.Column("pii_digest", sa.String(128), nullable=False),
        sa.Column("sealed_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("abha_number_bidx", sa.String(128), nullable=True),
        sa.Column("abha_address_bidx", sa.String(128), nullable=True),
        sa.Column("blind_key_id", sa.String(8), nullable=False),
        sa.Column(
            "review_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["payload_version_id"], ["va_submission_payload_versions.payload_version_id"],
            name=op.f("fk_map_payload_version_pii_payload_version_id_va_submission_payload_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["va_sid"], ["va_submissions.va_sid"],
            name=op.f("fk_map_payload_version_pii_va_sid_va_submissions"),
        ),
        sa.PrimaryKeyConstraint("payload_version_id", name=op.f("pk_map_payload_version_pii")),
    )
    op.create_index(
        op.f("ix_map_payload_version_pii_va_sid"), "map_payload_version_pii", ["va_sid"]
    )
    op.create_index("ix_map_payload_version_pii_key", "map_payload_version_pii", ["key_id"])
    op.create_index(
        "ix_map_payload_version_pii_abha_number_bidx",
        "map_payload_version_pii", ["abha_number_bidx"],
        postgresql_where=sa.text("abha_number_bidx IS NOT NULL"),
    )
    op.create_index(
        "ix_map_payload_version_pii_abha_address_bidx",
        "map_payload_version_pii", ["abha_address_bidx"],
        postgresql_where=sa.text("abha_address_bidx IS NOT NULL"),
    )


def downgrade():
    rows = op.get_bind().execute(sa.text("SELECT count(*) FROM map_payload_version_pii")).scalar()
    if rows:
        raise RuntimeError(
            f"map_payload_version_pii holds {rows} row(s) of sealed personal data that exist nowhere "
            "else; run `flask pii split-payloads --restore` first, then downgrade."
        )
    op.drop_table("map_payload_version_pii")
