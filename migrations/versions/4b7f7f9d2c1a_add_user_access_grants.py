"""add auth foundation tables

Revision ID: 4b7f7f9d2c1a
Revises: a395774fa312
Create Date: 2026-03-09 14:20:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "4b7f7f9d2c1a"
down_revision = "a395774fa312"
branch_labels = None
depends_on = None


access_role_enum = postgresql.ENUM(
    "admin",
    "project_pi",
    "site_pi",
    "collaborator",
    "coder",
    "reviewer",
    name="access_role_enum",
    create_type=False,
)

access_scope_enum = postgresql.ENUM(
    "global",
    "project",
    "project_site",
    name="access_scope_enum",
    create_type=False,
)

status_enum = postgresql.ENUM(
    "pending",
    "active",
    "deactive",
    name="status_enum",
    create_type=False,
)


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    access_role_enum.create(op.get_bind(), checkfirst=True)
    access_scope_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "va_project_master",
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("project_code", sa.String(length=6), nullable=True),
        sa.Column("project_name", sa.Text(), nullable=False),
        sa.Column("project_nickname", sa.Text(), nullable=False),
        sa.Column(
            "project_status",
            status_enum,
            nullable=False,
        ),
        sa.Column("project_registered_at", sa.DateTime(), nullable=False),
        sa.Column("project_updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_index(
        op.f("ix_va_project_master_project_id"),
        "va_project_master",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_project_master_project_status"),
        "va_project_master",
        ["project_status"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO va_project_master (
            project_id,
            project_code,
            project_name,
            project_nickname,
            project_status,
            project_registered_at,
            project_updated_at
        )
        SELECT
            project_id,
            project_code,
            project_name,
            project_nickname,
            project_status,
            project_registered_at,
            project_updated_at
        FROM va_research_projects
        """
    )

    op.create_table(
        "va_site_master",
        sa.Column("site_id", sa.String(length=4), nullable=False),
        sa.Column("site_name", sa.Text(), nullable=False),
        sa.Column("site_abbr", sa.Text(), nullable=False),
        sa.Column(
            "site_status",
            status_enum,
            nullable=False,
        ),
        sa.Column("site_registered_at", sa.DateTime(), nullable=False),
        sa.Column("site_updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("site_id"),
    )
    op.create_index(
        op.f("ix_va_site_master_site_id"),
        "va_site_master",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_site_master_site_status"),
        "va_site_master",
        ["site_status"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO va_site_master (
            site_id,
            site_name,
            site_abbr,
            site_status,
            site_registered_at,
            site_updated_at
        )
        SELECT
            site_id,
            site_name,
            site_abbr,
            site_status,
            site_registered_at,
            site_updated_at
        FROM va_sites
        """
    )

    op.create_table(
        "va_project_sites",
        sa.Column("project_site_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("site_id", sa.String(length=4), nullable=False),
        sa.Column(
            "project_site_status",
            status_enum,
            nullable=False,
        ),
        sa.Column("project_site_registered_at", sa.DateTime(), nullable=False),
        sa.Column("project_site_updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"]),
        sa.ForeignKeyConstraint(["site_id"], ["va_site_master.site_id"]),
        sa.PrimaryKeyConstraint("project_site_id"),
        sa.UniqueConstraint(
            "project_id",
            "site_id",
            name="uq_va_project_sites_project_site",
        ),
    )
    op.create_index(
        op.f("ix_va_project_sites_project_site_id"),
        "va_project_sites",
        ["project_site_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_project_sites_project_id"),
        "va_project_sites",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_project_sites_site_id"),
        "va_project_sites",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_project_sites_project_site_status"),
        "va_project_sites",
        ["project_site_status"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO va_project_sites (
            project_site_id,
            project_id,
            site_id,
            project_site_status,
            project_site_registered_at,
            project_site_updated_at
        )
        SELECT
            gen_random_uuid(),
            project_id,
            site_id,
            site_status,
            site_registered_at,
            site_updated_at
        FROM va_sites
        """
    )

    op.create_table(
        "va_user_access_grants",
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", access_role_enum, nullable=False),
        sa.Column("scope_type", access_scope_enum, nullable=False),
        sa.Column("project_id", sa.String(length=6), nullable=True),
        sa.Column("project_site_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("grant_status", status_enum, nullable=False),
        sa.Column("grant_created_at", sa.DateTime(), nullable=False),
        sa.Column("grant_updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            """
            (scope_type = 'global' AND project_id IS NULL AND project_site_id IS NULL) OR
            (scope_type = 'project' AND project_id IS NOT NULL AND project_site_id IS NULL) OR
            (scope_type = 'project_site' AND project_id IS NULL AND project_site_id IS NOT NULL)
            """,
            name="ck_va_user_access_grants_scope_shape",
        ),
        sa.CheckConstraint(
            """
            (role = 'admin' AND scope_type = 'global') OR
            (role = 'project_pi' AND scope_type = 'project') OR
            (role = 'site_pi' AND scope_type = 'project_site') OR
            (role IN ('collaborator', 'coder', 'reviewer') AND scope_type IN ('project', 'project_site'))
            """,
            name="ck_va_user_access_grants_role_scope",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"]),
        sa.ForeignKeyConstraint(["project_site_id"], ["va_project_sites.project_site_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["va_users.user_id"]),
        sa.PrimaryKeyConstraint("grant_id"),
    )
    op.create_index(
        op.f("ix_va_user_access_grants_grant_id"),
        "va_user_access_grants",
        ["grant_id"],
        unique=False,
    )
    op.create_index(
        "ix_va_user_access_grants_user_status",
        "va_user_access_grants",
        ["user_id", "grant_status"],
        unique=False,
    )
    op.create_index(
        "ix_va_user_access_grants_role_status",
        "va_user_access_grants",
        ["role", "grant_status"],
        unique=False,
    )
    op.create_index(
        "ix_va_user_access_grants_scope_lookup",
        "va_user_access_grants",
        ["scope_type", "project_id", "project_site_id", "grant_status"],
        unique=False,
    )
    op.create_index(
        "uq_va_user_access_grants_global",
        "va_user_access_grants",
        ["user_id", "role"],
        unique=True,
        postgresql_where=sa.text("scope_type = 'global'"),
    )
    op.create_index(
        "uq_va_user_access_grants_project",
        "va_user_access_grants",
        ["user_id", "role", "project_id"],
        unique=True,
        postgresql_where=sa.text("scope_type = 'project'"),
    )
    op.create_index(
        "uq_va_user_access_grants_project_site",
        "va_user_access_grants",
        ["user_id", "role", "project_site_id"],
        unique=True,
        postgresql_where=sa.text("scope_type = 'project_site'"),
    )

    # Grants are intentionally not backfilled in this migration.
    # Backfill should run as a separate idempotent step after the
    # new master and project-site foundation rows are validated.


def downgrade():
    op.drop_index("uq_va_user_access_grants_project_site", table_name="va_user_access_grants")
    op.drop_index("uq_va_user_access_grants_project", table_name="va_user_access_grants")
    op.drop_index("uq_va_user_access_grants_global", table_name="va_user_access_grants")
    op.drop_index("ix_va_user_access_grants_scope_lookup", table_name="va_user_access_grants")
    op.drop_index("ix_va_user_access_grants_role_status", table_name="va_user_access_grants")
    op.drop_index("ix_va_user_access_grants_user_status", table_name="va_user_access_grants")
    op.drop_index(op.f("ix_va_user_access_grants_grant_id"), table_name="va_user_access_grants")
    op.drop_table("va_user_access_grants")

    op.drop_index(op.f("ix_va_project_sites_project_site_status"), table_name="va_project_sites")
    op.drop_index(op.f("ix_va_project_sites_site_id"), table_name="va_project_sites")
    op.drop_index(op.f("ix_va_project_sites_project_id"), table_name="va_project_sites")
    op.drop_index(op.f("ix_va_project_sites_project_site_id"), table_name="va_project_sites")
    op.drop_table("va_project_sites")

    op.drop_index(op.f("ix_va_site_master_site_status"), table_name="va_site_master")
    op.drop_index(op.f("ix_va_site_master_site_id"), table_name="va_site_master")
    op.drop_table("va_site_master")

    op.drop_index(op.f("ix_va_project_master_project_status"), table_name="va_project_master")
    op.drop_index(op.f("ix_va_project_master_project_id"), table_name="va_project_master")
    op.drop_table("va_project_master")

    access_scope_enum.drop(op.get_bind(), checkfirst=True)
    access_role_enum.drop(op.get_bind(), checkfirst=True)
