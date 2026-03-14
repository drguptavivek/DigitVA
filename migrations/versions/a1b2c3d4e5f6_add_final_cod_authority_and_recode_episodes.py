"""add final cod authority and recode episodes

Revision ID: a1b2c3d4e5f6
Revises: f2a3b4c5d6e7
Create Date: 2026-03-14 19:15:00.000000
"""

from alembic import op
import sqlalchemy as sa
import uuid


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "va_coding_episodes",
        sa.Column("episode_id", sa.Uuid(), nullable=False),
        sa.Column("va_sid", sa.String(length=64), nullable=False),
        sa.Column("episode_type", sa.String(length=32), nullable=False),
        sa.Column("episode_status", sa.String(length=32), nullable=False),
        sa.Column("started_by", sa.Uuid(), nullable=False),
        sa.Column("base_final_assessment_id", sa.Uuid(), nullable=True),
        sa.Column("replacement_final_assessment_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("abandoned_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["va_sid"], ["va_submissions.va_sid"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["started_by"], ["va_users.user_id"]),
        sa.ForeignKeyConstraint(
            ["base_final_assessment_id"], ["va_final_assessments.va_finassess_id"]
        ),
        sa.ForeignKeyConstraint(
            ["replacement_final_assessment_id"],
            ["va_final_assessments.va_finassess_id"],
        ),
        sa.PrimaryKeyConstraint("episode_id"),
    )
    op.create_index(
        op.f("ix_va_coding_episodes_episode_id"),
        "va_coding_episodes",
        ["episode_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_coding_episodes_episode_status"),
        "va_coding_episodes",
        ["episode_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_coding_episodes_episode_type"),
        "va_coding_episodes",
        ["episode_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_coding_episodes_started_at"),
        "va_coding_episodes",
        ["started_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_coding_episodes_va_sid"),
        "va_coding_episodes",
        ["va_sid"],
        unique=False,
    )
    op.create_index(
        "uq_va_coding_episodes_active_recode",
        "va_coding_episodes",
        ["va_sid"],
        unique=True,
        postgresql_where=sa.text(
            "episode_type = 'recode' AND episode_status = 'active'"
        ),
    )

    op.create_table(
        "va_final_cod_authority",
        sa.Column("authority_id", sa.Uuid(), nullable=False),
        sa.Column("va_sid", sa.String(length=64), nullable=False),
        sa.Column("authoritative_final_assessment_id", sa.Uuid(), nullable=True),
        sa.Column("authority_source_role", sa.String(length=32), nullable=True),
        sa.Column("authority_reason", sa.String(length=128), nullable=True),
        sa.Column("effective_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["authoritative_final_assessment_id"],
            ["va_final_assessments.va_finassess_id"],
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["va_users.user_id"]),
        sa.ForeignKeyConstraint(["va_sid"], ["va_submissions.va_sid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("authority_id"),
        sa.UniqueConstraint(
            "authoritative_final_assessment_id",
            name="uq_va_final_cod_authority_final_assessment_id",
        ),
        sa.UniqueConstraint("va_sid", name="uq_va_final_cod_authority_sid"),
    )
    op.create_index(
        op.f("ix_va_final_cod_authority_authority_id"),
        "va_final_cod_authority",
        ["authority_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_final_cod_authority_created_at"),
        "va_final_cod_authority",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_final_cod_authority_effective_at"),
        "va_final_cod_authority",
        ["effective_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_final_cod_authority_va_sid"),
        "va_final_cod_authority",
        ["va_sid"],
        unique=False,
    )

    connection = op.get_bind()
    active_finals = connection.execute(
        sa.text(
            """
            SELECT f.va_sid, f.va_finassess_id, f.va_finassess_createdat
            FROM va_final_assessments f
            LEFT JOIN va_final_cod_authority a ON a.va_sid = f.va_sid
            WHERE f.va_finassess_status = 'active'
              AND a.va_sid IS NULL
            ORDER BY f.va_sid, f.va_finassess_createdat DESC
            """
        )
    ).mappings()
    seen_sids = set()
    for row in active_finals:
        if row["va_sid"] in seen_sids:
            continue
        seen_sids.add(row["va_sid"])
        connection.execute(
            sa.text(
                """
                INSERT INTO va_final_cod_authority (
                    authority_id,
                    va_sid,
                    authoritative_final_assessment_id,
                    authority_source_role,
                    authority_reason,
                    effective_at,
                    created_at,
                    updated_at
                ) VALUES (
                    :authority_id,
                    :va_sid,
                    :authoritative_final_assessment_id,
                    'vacoder',
                    'backfill_from_active_final_assessment',
                    :effective_at,
                    NOW(),
                    NOW()
                )
                """
            ),
            {
                "authority_id": uuid.uuid4(),
                "va_sid": row["va_sid"],
                "authoritative_final_assessment_id": row["va_finassess_id"],
                "effective_at": row["va_finassess_createdat"],
            },
        )
    
def downgrade():
    op.drop_index(op.f("ix_va_final_cod_authority_va_sid"), table_name="va_final_cod_authority")
    op.drop_index(op.f("ix_va_final_cod_authority_effective_at"), table_name="va_final_cod_authority")
    op.drop_index(op.f("ix_va_final_cod_authority_created_at"), table_name="va_final_cod_authority")
    op.drop_index(op.f("ix_va_final_cod_authority_authority_id"), table_name="va_final_cod_authority")
    op.drop_table("va_final_cod_authority")

    op.drop_index("uq_va_coding_episodes_active_recode", table_name="va_coding_episodes")
    op.drop_index(op.f("ix_va_coding_episodes_va_sid"), table_name="va_coding_episodes")
    op.drop_index(op.f("ix_va_coding_episodes_started_at"), table_name="va_coding_episodes")
    op.drop_index(op.f("ix_va_coding_episodes_episode_type"), table_name="va_coding_episodes")
    op.drop_index(op.f("ix_va_coding_episodes_episode_status"), table_name="va_coding_episodes")
    op.drop_index(op.f("ix_va_coding_episodes_episode_id"), table_name="va_coding_episodes")
    op.drop_table("va_coding_episodes")
