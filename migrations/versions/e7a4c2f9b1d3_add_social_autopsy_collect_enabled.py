"""Split Collect Social Autopsy from Coder Social Autopsy.

Revision ID: e7a4c2f9b1d3
Revises: b5e2c8d4a9f7
Create Date: 2026-11-26

digitva-rglh, owner decision 2026-11-26: ``social_autopsy_enabled`` used to
both add the ``social_autopsy`` form layer to web and DigitVA Collect forms
and turn on the coder's analysis form. The new
``va_project_master.social_autopsy_collect_enabled`` takes over the layer;
coder and reviewer analysis stay effective only while it is on. Policy:
docs/policy/social-autopsy-analysis.md.

Chained onto b5e2c8d4a9f7. Additive: the column is added with a true default,
then set equal to ``social_autopsy_enabled`` on every existing project, so no
project's form or coding changes on deploy. Downgrade drops the column; the
coder switch again decides the layer.
"""

import sqlalchemy as sa
from alembic import op

revision = "e7a4c2f9b1d3"
down_revision = "b5e2c8d4a9f7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_project_master",
        sa.Column(
            "social_autopsy_collect_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.execute(
        sa.text(
            "UPDATE va_project_master "
            "SET social_autopsy_collect_enabled = social_autopsy_enabled"
        )
    )


def downgrade():
    op.drop_column("va_project_master", "social_autopsy_collect_enabled")
