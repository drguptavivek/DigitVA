"""add mas_va_cause_definitions, seeded with the WHO VA cause definitions

Revision ID: fba41e2f1f9d
Revises: 6c11b620f48f
Create Date: 2026-09-21 23:30:00.000000

digitva-oyq. Policy: docs/policy/va-cause-definitions.md.

One row per WHO VA cause code: the 62 VAs-NN.NN codes and VAs-99, with
definitions as sanitized rich text. Section headings (VAs-01 ... VAs-12) are
not codes and VAs-98 is treated as a group, so neither is stored. Seeded
from resource/va_cause_definitions_who_2022.json, frozen from
docs/kb/WHO_VA_2022_Docs/va_definitions.html by
`flask va-definitions generate-seed-json` (docs/ is not in the image). The
insert skips codes that already exist. Downgrade drops the table, and with it
any admin edits; export them first if they matter.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "fba41e2f1f9d"
down_revision = "6c11b620f48f"
branch_labels = None
depends_on = None

SEED_JSON_PATH = Path("resource/va_cause_definitions_who_2022.json")
TABLE = "mas_va_cause_definitions"


def _load_seed_rows():
    path = Path(__file__).resolve().parents[2] / SEED_JSON_PATH
    if not path.exists():
        raise ValueError(f"VA cause definitions seed JSON not found: {path}")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("va_code", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("definition_html", sa.Text(), server_default="", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["va_users.user_id"],
            name=op.f("fk_mas_va_cause_definitions_updated_by"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mas_va_cause_definitions")),
        sa.UniqueConstraint("va_code", name=op.f("mas_va_cause_definitions_va_code_key")),
    )

    now = datetime.now(UTC)
    insert = sa.text(
        f"INSERT INTO {TABLE} (id, va_code, title, definition_html, "
        "is_active, source, created_at, updated_at) "
        "VALUES (:id, :va_code, :title, :definition_html, "
        "true, :source, :now, :now) "
        "ON CONFLICT (va_code) DO NOTHING"
    )
    op.get_bind().execute(
        insert,
        [
            {
                "id": uuid.uuid4(),
                "va_code": row["va_code"],
                "title": row["title"],
                "definition_html": row["definition_html"],
                "source": row["source"],
                "now": now,
            }
            for row in _load_seed_rows()
        ],
    )


def downgrade():
    op.drop_table(TABLE)
