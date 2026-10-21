"""Death registration identifier types, encrypted values and audit.

Revision ID: c7e3a9d1f5b2
Revises: b8d2f4a6c901
Create Date: 2026-10-20

Additive; no backfill (no numbers exist yet). Policy:
docs/policy/death-registration-identifiers.md, bead digitva-kzyp.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c7e3a9d1f5b2"
down_revision = "b8d2f4a6c901"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mas_death_identifier_type",
        sa.Column("identifier_type_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(6), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("min_length", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_length", sa.Integer(), server_default="64", nullable=False),
        sa.Column("char_type", sa.String(32), nullable=True),
        sa.Column("pattern", sa.String(200), nullable=True),
        sa.Column("example", sa.String(64), nullable=True),
        sa.Column("required_at_report", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("uniqueness_scope", sa.String(16), server_default="project", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "uniqueness_scope IN ('none', 'project')",
            name=op.f("ck_mas_death_identifier_type_uniqueness_scope"),
        ),
        sa.CheckConstraint(
            "min_length >= 1 AND max_length <= 64 AND min_length <= max_length",
            name=op.f("ck_mas_death_identifier_type_length_range"),
        ),
        sa.CheckConstraint(
            "char_type IS NULL OR char_type IN "
            "('digits', 'letters', 'letters_digits', 'letters_digits_hyphen_slash')",
            name=op.f("ck_mas_death_identifier_type_char_type"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["va_project_master.project_id"],
            name=op.f("fk_mas_death_identifier_type_project_id_va_project_master"),
        ),
        sa.PrimaryKeyConstraint("identifier_type_id", name=op.f("pk_mas_death_identifier_type")),
        sa.UniqueConstraint("project_id", "code", name="uq_mas_death_identifier_type_project_code"),
    )
    op.create_index(
        op.f("ix_mas_death_identifier_type_project_id"),
        "mas_death_identifier_type", ["project_id"],
    )

    op.create_table(
        "map_death_identifier",
        sa.Column("death_identifier_id", sa.Uuid(), nullable=False),
        sa.Column("death_id", sa.Uuid(), nullable=False),
        sa.Column("identifier_type_id", sa.Uuid(), nullable=False),
        sa.Column("value_ciphertext", sa.Text(), nullable=False),
        sa.Column("dek_wrapped", sa.Text(), nullable=False),
        sa.Column("value_blind_index", sa.String(128), nullable=False),
        sa.Column("key_id", sa.String(16), nullable=False),
        sa.Column("entered_by", sa.Uuid(), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["death_id"], ["va_death_register.death_id"],
            name=op.f("fk_map_death_identifier_death_id_va_death_register"),
        ),
        sa.ForeignKeyConstraint(
            ["identifier_type_id"], ["mas_death_identifier_type.identifier_type_id"],
            name=op.f("fk_map_death_identifier_identifier_type_id_mas_death_identifier_type"),
        ),
        sa.ForeignKeyConstraint(
            ["entered_by"], ["va_users.user_id"],
            name=op.f("fk_map_death_identifier_entered_by_va_users"),
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["va_users.user_id"],
            name=op.f("fk_map_death_identifier_updated_by_va_users"),
        ),
        sa.PrimaryKeyConstraint("death_identifier_id", name=op.f("pk_map_death_identifier")),
        sa.UniqueConstraint(
            "death_id", "identifier_type_id", name="uq_map_death_identifier_death_type"
        ),
    )
    op.create_index(
        "ix_map_death_identifier_type_bidx",
        "map_death_identifier", ["identifier_type_id", "value_blind_index"],
    )
    op.create_index("ix_map_death_identifier_key", "map_death_identifier", ["key_id"])

    op.create_table(
        "map_identifier_audit",
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(6), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_role", sa.String(30), nullable=False),
        sa.Column("identifier_type_id", sa.Uuid(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["va_project_master.project_id"],
            name=op.f("fk_map_identifier_audit_project_id_va_project_master"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["va_users.user_id"],
            name=op.f("fk_map_identifier_audit_actor_user_id_va_users"),
        ),
        sa.PrimaryKeyConstraint("audit_id", name=op.f("pk_map_identifier_audit")),
    )
    op.create_index(
        "ix_map_identifier_audit_project_created",
        "map_identifier_audit", ["project_id", "created_at"],
    )


def downgrade():
    op.drop_table("map_identifier_audit")
    op.drop_table("map_death_identifier")
    op.drop_table("mas_death_identifier_type")
