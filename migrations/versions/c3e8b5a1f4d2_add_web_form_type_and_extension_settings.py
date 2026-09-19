"""Web form type and the two extension settings become project configuration.

Revision ID: c3e8b5a1f4d2
Revises: f2a9c4d7e1b3
Create Date: 2026-09-19 16:00:00.000000

WP1 of docs/planning/web-capture-project-configuration-plan.md. A project
names the form type its browser questionnaire carries and switches the two
extensions the data model had nothing to derive them from:

- ``va_project_master.web_intake_form_type_id`` — NULL keeps today's
  behaviour, the web form is ``WHO_2022_VA``.
- ``va_project_master.web_intake_intake_note`` — NULL means the system
  default welcome note (a module constant, so its wording changes without a
  migration); an empty string means no welcome screen.
- ``va_project_master.web_intake_death_summary_enabled`` — on for every
  project, which is what the deployed ICMRVA forms already collect.
- ``mas_form_types.base_instrument_code`` — the standard instrument a form
  type layers on, backfilled from the naming convention
  ``instrument_code_for()`` applied until now. It is the column
  docs/policy/va-web-form-options.md recorded as the follow-up: no prefix
  rule covers two instrument families.

Purely additive. The downgrade drops the four columns and rewrites no other
data; a project's stored form type is lost on downgrade, which is the
documented cost of the column not existing.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3e8b5a1f4d2"
down_revision = "f2a9c4d7e1b3"
branch_labels = None
depends_on = None

PROJECTS = "va_project_master"
FORM_TYPES = "mas_form_types"


def upgrade():
    op.add_column(
        PROJECTS,
        sa.Column("web_intake_form_type_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_va_project_master_web_intake_form_type",
        PROJECTS,
        FORM_TYPES,
        ["web_intake_form_type_id"],
        ["form_type_id"],
    )
    op.add_column(
        PROJECTS,
        sa.Column("web_intake_intake_note", sa.Text(), nullable=True),
    )
    op.add_column(
        PROJECTS,
        sa.Column(
            "web_intake_death_summary_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )
    op.add_column(
        FORM_TYPES,
        sa.Column("base_instrument_code", sa.String(length=32), nullable=True),
    )
    # The prefix rule this column replaces, frozen as plain SQL: every
    # WHO_2022_VA* code is a layer on the one bundled WHO 2022 VA instrument.
    op.execute(
        "UPDATE mas_form_types SET base_instrument_code = 'WHO_2022_VA' "
        "WHERE form_type_code LIKE 'WHO_2022_VA%'"
    )


def downgrade():
    op.drop_column(FORM_TYPES, "base_instrument_code")
    op.drop_column(PROJECTS, "web_intake_death_summary_enabled")
    op.drop_column(PROJECTS, "web_intake_intake_note")
    op.drop_constraint(
        "fk_va_project_master_web_intake_form_type", PROJECTS, type_="foreignkey"
    )
    op.drop_column(PROJECTS, "web_intake_form_type_id")
