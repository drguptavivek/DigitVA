"""add mas_icd10_2019_2 table

Revision ID: c1d2e3f4a5b6
Revises: ad0e1f2a3b4c
Create Date: 2026-04-20 15:00:00.000000
"""

import csv
from datetime import datetime, timezone
from pathlib import Path

from alembic import op
import sqlalchemy as sa


revision = "c1d2e3f4a5b6"
down_revision = "ad0e1f2a3b4c"
branch_labels = None
depends_on = None


CSV_SOURCE_PATH = Path(
    "docs/icd-causegrp-mappings/migration-artifacts/"
    "icd10-2019-base-2026-04-27/icd10_2019_hierarchy.csv"
)
SOURCE_VERSION = "ICD-10-2019"
CHUNK_SIZE = 1000


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _optional_text(value):
    cleaned = (value or "").strip()
    return cleaned or None


def _parse_bool(value):
    normalized = (value or "").strip().lower()
    if not normalized:
        return None
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"Invalid boolean value in ICD seed CSV: {value!r}")


def _load_seed_rows():
    csv_path = _repo_root() / CSV_SOURCE_PATH
    if not csv_path.exists():
        raise ValueError(f"ICD seed CSV not found for migration: {csv_path}")

    created_at = datetime.now(timezone.utc)
    rows = []
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for sort_order, row in enumerate(reader, start=1):
            code = (row.get("code") or "").strip()
            if not code:
                raise ValueError("ICD seed CSV contains a row with empty code")
            rows.append(
                {
                    "code": code,
                    "title": (row.get("title") or "").strip(),
                    "node_type": (row.get("node_type") or "").strip(),
                    "semantic_level": (row.get("semantic_level") or "").strip(),
                    "sort_order": sort_order,
                    "parent_code": _optional_text(row.get("parent_code")),
                    "chapter_code": _optional_text(row.get("chapter_code")),
                    "chapter_title": _optional_text(row.get("chapter_title")),
                    "block_code": _optional_text(row.get("block_code")),
                    "block_title": _optional_text(row.get("block_title")),
                    "three_character_code": _optional_text(row.get("three_character_code")),
                    "three_character_title": _optional_text(row.get("three_character_title")),
                    "has_children": bool(_parse_bool(row.get("has_children"))),
                    "is_leaf": bool(_parse_bool(row.get("is_leaf"))),
                    "is_three_character_code": bool(_parse_bool(row.get("is_three_character_code"))),
                    "is_detailed_code": bool(_parse_bool(row.get("is_detailed_code"))),
                    "is_coding_selectable": _parse_bool(row.get("is_coding_selectable")),
                    "sex_selectable": _optional_text(row.get("sex_selectable")),
                    "age_group_selectable": _optional_text(row.get("age_group_selectable")),
                    "policy_status": _optional_text(row.get("policy_status")) or "unreviewed",
                    "restriction_note": _optional_text(row.get("restriction_note")),
                    "source_version": SOURCE_VERSION,
                    "source_path": str(CSV_SOURCE_PATH),
                    "is_active": True,
                    "created_at": created_at,
                    "updated_at": created_at,
                }
            )
    return rows


def _seed_icd_rows():
    seed_rows = _load_seed_rows()
    icd_table = sa.table(
        "mas_icd10_2019_2",
        sa.column("code", sa.String(length=16)),
        sa.column("title", sa.Text()),
        sa.column("node_type", sa.String(length=16)),
        sa.column("semantic_level", sa.String(length=32)),
        sa.column("sort_order", sa.Integer()),
        sa.column("parent_code", sa.String(length=16)),
        sa.column("chapter_code", sa.String(length=16)),
        sa.column("chapter_title", sa.Text()),
        sa.column("block_code", sa.String(length=16)),
        sa.column("block_title", sa.Text()),
        sa.column("three_character_code", sa.String(length=16)),
        sa.column("three_character_title", sa.Text()),
        sa.column("has_children", sa.Boolean()),
        sa.column("is_leaf", sa.Boolean()),
        sa.column("is_three_character_code", sa.Boolean()),
        sa.column("is_detailed_code", sa.Boolean()),
        sa.column("is_coding_selectable", sa.Boolean()),
        sa.column("sex_selectable", sa.String(length=16)),
        sa.column("age_group_selectable", sa.String(length=32)),
        sa.column("policy_status", sa.String(length=32)),
        sa.column("restriction_note", sa.Text()),
        sa.column("source_version", sa.String(length=32)),
        sa.column("source_path", sa.String(length=512)),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    for start in range(0, len(seed_rows), CHUNK_SIZE):
        op.bulk_insert(icd_table, seed_rows[start : start + CHUNK_SIZE])


def upgrade():
    op.create_table(
        "mas_icd10_2019_2",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("node_type", sa.String(length=16), nullable=False),
        sa.Column("semantic_level", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("parent_code", sa.String(length=16), nullable=True),
        sa.Column("chapter_code", sa.String(length=16), nullable=True),
        sa.Column("chapter_title", sa.Text(), nullable=True),
        sa.Column("block_code", sa.String(length=16), nullable=True),
        sa.Column("block_title", sa.Text(), nullable=True),
        sa.Column("three_character_code", sa.String(length=16), nullable=True),
        sa.Column("three_character_title", sa.Text(), nullable=True),
        sa.Column("has_children", sa.Boolean(), nullable=False),
        sa.Column("is_leaf", sa.Boolean(), nullable=False),
        sa.Column("is_three_character_code", sa.Boolean(), nullable=False),
        sa.Column("is_detailed_code", sa.Boolean(), nullable=False),
        sa.Column("is_coding_selectable", sa.Boolean(), nullable=True),
        sa.Column("sex_selectable", sa.String(length=16), nullable=True),
        sa.Column("age_group_selectable", sa.String(length=32), nullable=True),
        sa.Column("policy_status", sa.String(length=32), nullable=False),
        sa.Column("restriction_note", sa.Text(), nullable=True),
        sa.Column("source_version", sa.String(length=32), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    _seed_icd_rows()
    op.create_index(
        "ix_mas_icd10_2019_2_parent_code",
        "mas_icd10_2019_2",
        ["parent_code"],
        unique=False,
    )
    op.create_index(
        "ix_mas_icd10_2019_2_chapter_code",
        "mas_icd10_2019_2",
        ["chapter_code"],
        unique=False,
    )
    op.create_index(
        "ix_mas_icd10_2019_2_block_code",
        "mas_icd10_2019_2",
        ["block_code"],
        unique=False,
    )
    op.create_index(
        "ix_mas_icd10_2019_2_three_character_code",
        "mas_icd10_2019_2",
        ["three_character_code"],
        unique=False,
    )
    op.create_index(
        "ix_mas_icd10_2019_2_semantic_level",
        "mas_icd10_2019_2",
        ["semantic_level"],
        unique=False,
    )
    op.create_index(
        "ix_mas_icd10_2019_2_is_active",
        "mas_icd10_2019_2",
        ["is_active"],
        unique=False,
    )
    op.execute(
        """
        UPDATE mas_icd10_2019_2
        SET
            is_coding_selectable = COALESCE(is_coding_selectable, TRUE),
            sex_selectable = COALESCE(sex_selectable, 'both'),
            age_group_selectable = COALESCE(age_group_selectable, 'all')
        WHERE
            semantic_level = 'three_character'
            AND code !~ '^[STUZ][0-9][0-9]$'
        """
    )


def downgrade():
    op.drop_index("ix_mas_icd10_2019_2_is_active", table_name="mas_icd10_2019_2")
    op.drop_index("ix_mas_icd10_2019_2_semantic_level", table_name="mas_icd10_2019_2")
    op.drop_index(
        "ix_mas_icd10_2019_2_three_character_code",
        table_name="mas_icd10_2019_2",
    )
    op.drop_index("ix_mas_icd10_2019_2_block_code", table_name="mas_icd10_2019_2")
    op.drop_index("ix_mas_icd10_2019_2_chapter_code", table_name="mas_icd10_2019_2")
    op.drop_index("ix_mas_icd10_2019_2_parent_code", table_name="mas_icd10_2019_2")
    op.drop_table("mas_icd10_2019_2")
