"""backfill unsw01 coder grants

Revision ID: 7c8a6d1f4e2b
Revises: 4b7f7f9d2c1a
Create Date: 2026-03-09 16:15:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "7c8a6d1f4e2b"
down_revision = "4b7f7f9d2c1a"
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
            'coder',
            'project_site',
            NULL,
            ps.project_site_id,
            'Backfilled from legacy coder permissions for UNSW01',
            'active',
            now(),
            now()
        FROM va_users AS u
        CROSS JOIN LATERAL jsonb_array_elements_text(
            COALESCE(u.permission -> 'coder', '[]'::jsonb)
        ) AS perm(form_id)
        JOIN va_forms AS f
            ON f.form_id = perm.form_id
        JOIN va_project_sites AS ps
            ON ps.project_id = f.project_id
           AND ps.site_id = f.site_id
        WHERE u.user_status = 'active'
          AND f.form_status = 'active'
          AND ps.project_site_status = 'active'
          AND f.project_id = 'UNSW01'
          AND NOT EXISTS (
              SELECT 1
              FROM va_user_access_grants AS g
              WHERE g.user_id = u.user_id
                AND g.role = 'coder'
                AND g.scope_type = 'project_site'
                AND g.project_site_id = ps.project_site_id
          )
        """
    )


def downgrade():
    op.execute(
        """
        DELETE FROM va_user_access_grants
        WHERE role = 'coder'
          AND scope_type = 'project_site'
          AND notes = 'Backfilled from legacy coder permissions for UNSW01'
        """
    )
