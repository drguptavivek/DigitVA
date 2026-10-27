"""Add mas_consent_notice_versions.source and the standalone bundle identity.

Revision ID: f3d9b5c7a2e4
Revises: c7a3e9d1f5b8
Create Date: 2026-10-27 18:00:00.000000

A Collect Plus phone used without a server (Path C) records consent against
the notice bundled in the app; the push carries the exact text the respondent
saw, and the server stores it as a notice version with ``source =
'standalone'`` (docs/policy/offline-api-contract.md section 17,
docs/policy/respondent-consent-notice-draft.md "Standalone notice").
``bundle_version`` and ``bundle_sha256`` name the bundled notice it came from.

Every existing row is a project's own notice (``source`` defaults to
``project``). The (project, version, language) unique key now holds for
project notices only: a standalone row has no version number of the project's
(it is stored as version 1) and is found again by its text hash instead, one
row per (project, language, text_sha256).

Downgrade restores the full unique key, so it fails while a standalone row
shares a project notice's version and language: nothing is deleted for it.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f3d9b5c7a2e4"
down_revision = "c7a3e9d1f5b8"
branch_labels = None
depends_on = None

TABLE = "mas_consent_notice_versions"
OLD_UNIQUE = "uq_mas_consent_notice_versions_project_version_language"
PROJECT_UNIQUE = "uq_mas_consent_notice_versions_project_notice"
STANDALONE_UNIQUE = "uq_mas_consent_notice_versions_standalone_text"
SOURCE_CHECK = "source"


def upgrade():
    op.add_column(TABLE, sa.Column("source", sa.String(16), nullable=False, server_default="project"))
    op.add_column(TABLE, sa.Column("bundle_version", sa.String(64), nullable=True))
    op.add_column(TABLE, sa.Column("bundle_sha256", sa.String(64), nullable=True))
    # The bare discriminator: the naming convention prefixes it (ck_<table>_source).
    op.create_check_constraint(SOURCE_CHECK, TABLE, "source IN ('project', 'standalone')")
    op.drop_constraint(OLD_UNIQUE, TABLE, type_="unique")
    op.create_index(PROJECT_UNIQUE, TABLE, ["project_id", "version", "language"], unique=True,
                    postgresql_where=sa.text("source = 'project'"))
    op.create_index(STANDALONE_UNIQUE, TABLE, ["project_id", "language", "text_sha256"], unique=True,
                    postgresql_where=sa.text("source = 'standalone'"))


def downgrade():
    op.drop_index(STANDALONE_UNIQUE, table_name=TABLE)
    op.drop_index(PROJECT_UNIQUE, table_name=TABLE)
    op.create_unique_constraint(OLD_UNIQUE, TABLE, ["project_id", "version", "language"])
    op.drop_constraint(op.f(f"ck_{TABLE}_{SOURCE_CHECK}"), TABLE, type_="check")
    op.drop_column(TABLE, "bundle_sha256")
    op.drop_column(TABLE, "bundle_version")
    op.drop_column(TABLE, "source")
