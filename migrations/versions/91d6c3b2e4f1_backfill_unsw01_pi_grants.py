"""backfill unsw01 pi grants

Revision ID: 91d6c3b2e4f1
Revises: 7c8a6d1f4e2b
Create Date: 2026-03-09 16:45:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "91d6c3b2e4f1"
down_revision = "7c8a6d1f4e2b"
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
            'project_pi',
            'project',
            'UNSW01',
            NULL,
            'Backfilled project PI grant for UNSW01',
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
                AND g.role = 'project_pi'
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
            'site_pi',
            'project_site',
            NULL,
            ps.project_site_id,
            'Backfilled site PI grant for UNSW01',
            'active',
            now(),
            now()
        FROM (
            VALUES
                ('anand.drk@gmail.com', 'NC01'),
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
                AND g.role = 'site_pi'
                AND g.scope_type = 'project_site'
                AND g.project_site_id = ps.project_site_id
          )
        """
    )


def downgrade():
    op.execute(
        """
        DELETE FROM va_user_access_grants
        WHERE role = 'project_pi'
          AND scope_type = 'project'
          AND project_id = 'UNSW01'
          AND notes = 'Backfilled project PI grant for UNSW01'
        """
    )
    op.execute(
        """
        DELETE FROM va_user_access_grants
        WHERE role = 'site_pi'
          AND scope_type = 'project_site'
          AND notes = 'Backfilled site PI grant for UNSW01'
        """
    )
