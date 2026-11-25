"""Add map_org_level_cadre.allowed_roles, backfilled from today's grid and grants.

Revision ID: c3a7e1f9d4b2
Revises: 1f037b4717e4
Create Date: 2026-11-25

Migration A of digitva-4650 (docs/policy/organization-model.md, "Allowed and
default roles per level x cadre"). Purely additive: ``allowed_roles``
(unit-scope roles, same CHECK set as ``default_roles``) is backfilled from what
is true today, so nobody loses a role they hold:

- the ticked flags (can_code_va_form -> coder, can_supervise_interviews ->
  interview_supervisor, can_report_deaths -> death_reporter, can_fill_va_form
  -> interviewer);
- the row's default_roles;
- every role of an active unit grant of that cadre at a unit of that level.
  A grant held by an active mentoring-institute member counts only when an
  active worker record (same user, unit and cadre) backs it: otherwise its
  cadre was borrowed, and must not widen a health-system cadre.

No grant is changed here. Borrowed mentor cadres are cleared, and cadre-less
health-system grants revoked, by ``flask org cadreless-grants --apply`` after
owner approval. The five flag columns stay (the code stops reading them); a
later migration drops them. Downgrade drops the column; the new code never
writes the flags, so four of them are first recomputed from allowed_roles so a
rolled-back app sees the grid as last edited. can_edit_interviews is left as
it was: it has no allowed role of its own, and setting it would widen
interview correction under the old code.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "c3a7e1f9d4b2"
down_revision = "1f037b4717e4"
branch_labels = None
depends_on = None

CHECK_NAME = "ck_map_org_level_cadre_allowed_roles_unit_roles"
# The unit-scope roles in the role enum's order (org_grant_service.ROLES_ALLOWING_ORG_UNIT).
_UNIT_ROLES = (
    "site_pi", "collaborator", "collaborator_pii", "coder", "coding_tester",
    "reviewer", "data_manager", "interviewer", "interview_supervisor", "death_reporter",
)
_UNIT_ROLES_SQL = "ARRAY[" + ", ".join(f"'{r}'" for r in _UNIT_ROLES) + "]::varchar[]"


def upgrade():
    op.add_column(
        "map_org_level_cadre",
        sa.Column(
            "allowed_roles", ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")
        ),
    )
    # Plain SQL with the full name: op.create_check_constraint would apply the
    # ck_ naming convention a second time (see g3k7o1s5w9a2).
    op.execute(
        f'ALTER TABLE map_org_level_cadre ADD CONSTRAINT "{CHECK_NAME}" '
        f"CHECK (allowed_roles <@ {_UNIT_ROLES_SQL})"
    )
    op.execute(f"""
        UPDATE map_org_level_cadre lc SET allowed_roles = ARRAY(
            SELECT r FROM (
                SELECT 'coder'::varchar WHERE lc.can_code_va_form
                UNION SELECT 'interview_supervisor' WHERE lc.can_supervise_interviews
                UNION SELECT 'death_reporter' WHERE lc.can_report_deaths
                UNION SELECT 'interviewer' WHERE lc.can_fill_va_form
                UNION SELECT unnest(lc.default_roles)
                UNION SELECT g.role::text FROM va_user_access_grants g
                    JOIN mas_org_unit u ON u.org_unit_id = g.org_unit_id
                    WHERE g.scope_type = 'org_unit' AND g.grant_status = 'active'
                      AND g.cadre_id = lc.cadre_id AND u.org_level_id = lc.org_level_id
                      AND (
                          g.user_id NOT IN (
                              SELECT mu.user_id FROM map_mentor_institute_user mu
                              JOIN mas_mentor_institute mi ON mi.institute_id = mu.institute_id
                              WHERE mu.is_active AND mi.is_active
                          )
                          OR EXISTS (
                              SELECT 1 FROM mas_org_unit_worker w
                              WHERE w.user_id = g.user_id AND w.org_unit_id = g.org_unit_id
                                AND w.cadre_id = g.cadre_id AND w.is_active
                          )
                      )
            ) s(r)
            WHERE r = ANY({_UNIT_ROLES_SQL})
            ORDER BY array_position({_UNIT_ROLES_SQL}, r)
        )
    """)


def downgrade():
    op.execute("""
        UPDATE map_org_level_cadre SET
            can_fill_va_form = 'interviewer' = ANY(allowed_roles),
            can_code_va_form = 'coder' = ANY(allowed_roles),
            can_supervise_interviews = 'interview_supervisor' = ANY(allowed_roles),
            can_report_deaths = 'death_reporter' = ANY(allowed_roles)
    """)
    op.execute(f'ALTER TABLE map_org_level_cadre DROP CONSTRAINT IF EXISTS "{CHECK_NAME}"')
    op.drop_column("map_org_level_cadre", "allowed_roles")
