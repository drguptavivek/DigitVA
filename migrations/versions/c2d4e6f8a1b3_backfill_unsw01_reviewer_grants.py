"""backfill unsw01 reviewer grants

Revision ID: c2d4e6f8a1b3
Revises: 91d6c3b2e4f1
Create Date: 2026-03-09 17:05:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "c2d4e6f8a1b3"
down_revision = "91d6c3b2e4f1"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        INSERT INTO va_user_access_grants (
            grant_id,
            user_id,
            role,
            scope_type,
            project_id,
            project_site_id,
            notes,
            grant_status,
            grant_created_at,
            grant_updated_at
        )
        SELECT
            gen_random_uuid(),
            u.user_id,
            'reviewer',
            'project',
            'UNSW01',
            NULL,
            'Backfilled reviewer project grant for UNSW01',
            'active',
            now(),
            now()
        FROM va_users AS u
        WHERE u.email = 'anand.drk@gmail.com'
          AND u.user_status = 'active'
          AND NOT EXISTS (
              SELECT 1
              FROM va_user_access_grants AS g
              WHERE g.user_id = u.user_id
                AND g.role = 'reviewer'
                AND g.scope_type = 'project'
                AND g.project_id = 'UNSW01'
          )
        """
    )

    op.execute(
        """
        INSERT INTO va_user_access_grants (
            grant_id,
            user_id,
            role,
            scope_type,
            project_id,
            project_site_id,
            notes,
            grant_status,
            grant_created_at,
            grant_updated_at
        )
        SELECT
            gen_random_uuid(),
            u.user_id,
            'reviewer',
            'project_site',
            NULL,
            ps.project_site_id,
            'Backfilled reviewer grant for UNSW01',
            'active',
            now(),
            now()
        FROM (
            VALUES
                ('apoorva.sindhu@yahoo.com', 'NC01'),
                ('bijusoman@sctimst.ac.in', 'KL01'),
                ('drmubi@gmail.com', 'KA01'),
                ('drsubratabaidya@gmail.com', 'TR01')
        ) AS assignments(email, site_id)
        JOIN va_users AS u
            ON u.email = assignments.email
        JOIN va_project_sites AS ps
            ON ps.project_id = 'UNSW01'
           AND ps.site_id = assignments.site_id
        WHERE u.user_status = 'active'
          AND ps.project_site_status = 'active'
          AND NOT EXISTS (
              SELECT 1
              FROM va_user_access_grants AS g
              WHERE g.user_id = u.user_id
                AND g.role = 'reviewer'
                AND g.scope_type = 'project_site'
                AND g.project_site_id = ps.project_site_id
          )
        """
    )


def downgrade():
    op.execute(
        """
        DELETE FROM va_user_access_grants
        WHERE role = 'reviewer'
          AND scope_type = 'project'
          AND project_id = 'UNSW01'
          AND notes = 'Backfilled reviewer project grant for UNSW01'
        """
    )
    op.execute(
        """
        DELETE FROM va_user_access_grants
        WHERE role = 'reviewer'
          AND scope_type = 'project_site'
          AND notes = 'Backfilled reviewer grant for UNSW01'
        """
    )
