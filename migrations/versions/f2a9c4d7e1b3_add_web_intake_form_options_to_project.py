"""Add web intake form options to va_project_master.

Revision ID: f2a9c4d7e1b3
Revises: b8e3d1f7a2c4
Create Date: 2026-09-19 10:00:00.000000

The four tier-2 options of docs/policy/va-web-form-options.md that the
project owns and the intake form has no other way to learn: the display
locale it opens in, the locales its users may switch to, the languages a
narrative may be recorded in, and whether source guidance notes render.

Explicit columns rather than a settings blob, matching every other project
setting on this table. Purely additive: the two NOT NULL columns carry
server defaults equal to today's hardcoded behaviour ('en', guidance off),
and the two list columns are nullable, where NULL keeps its documented
meaning (every active language / no narration languages offered). The
downgrade drops the four columns and rewrites no other data.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "f2a9c4d7e1b3"
down_revision = "b8e3d1f7a2c4"
branch_labels = None
depends_on = None

TABLE = "va_project_master"


def upgrade():
    op.add_column(
        TABLE,
        sa.Column(
            "web_intake_default_locale",
            sa.String(length=16),
            nullable=False,
            server_default="en",
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "web_intake_available_locales",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "web_intake_narration_languages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "web_intake_show_guidance",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade():
    op.drop_column(TABLE, "web_intake_show_guidance")
    op.drop_column(TABLE, "web_intake_narration_languages")
    op.drop_column(TABLE, "web_intake_available_locales")
    op.drop_column(TABLE, "web_intake_default_locale")
