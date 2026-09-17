"""add mas_icd11_mms table

Seeds from the checked-in generated CSV (resource/icd11_mms_2026_01_hierarchy.csv),
itself generated from the frozen WHO Simple Tabulation export under
docs/icd-causegrp-mappings/migration-artifacts/icd11-mms-2026-01-base-2026-09-16/.
See docs/policy/icd11-reference-catalog.md.

Revision ID: b6edb1b7d01a
Revises: c8d2e4f6a1b3
Create Date: 2026-09-17 00:00:00.000000
"""

import csv
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "b6edb1b7d01a"
down_revision = "c8d2e4f6a1b3"
branch_labels = None
depends_on = None


CSV_SOURCE_PATH = Path("resource/icd11_mms_2026_01_hierarchy.csv")
RELEASE = "2026-01"
SOURCE_VERSION = "ICD-11-MMS-2026-01"
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
    return normalized == "true"


def _load_seed_rows():
    csv_path = _repo_root() / CSV_SOURCE_PATH
    if not csv_path.exists():
        raise ValueError(f"ICD-11 seed CSV not found for migration: {csv_path}")

    created_at = datetime.now(UTC)
    rows = []
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            linearization_uri = (row.get("linearization_uri") or "").strip()
            if not linearization_uri:
                raise ValueError("ICD-11 seed CSV contains a row with empty linearization_uri")
            depth_raw = _optional_text(row.get("depth_in_kind"))
            sort_order_raw = _optional_text(row.get("sort_order")) or "0"
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "release": RELEASE,
                    "linearization_uri": linearization_uri,
                    "foundation_uri": _optional_text(row.get("foundation_uri")),
                    "code": _optional_text(row.get("code")),
                    "block_id": _optional_text(row.get("block_id")),
                    "title": (row.get("title") or "").strip(),
                    "class_kind": (row.get("class_kind") or "").strip(),
                    "depth_in_kind": int(depth_raw) if depth_raw is not None else None,
                    "chapter_no": _optional_text(row.get("chapter_no")),
                    "is_residual": bool(_parse_bool(row.get("is_residual"))),
                    "is_leaf": bool(_parse_bool(row.get("is_leaf"))),
                    "primary_tabulation": _parse_bool(row.get("primary_tabulation")),
                    "coding_note": _optional_text(row.get("coding_note")),
                    "sort_order": int(sort_order_raw),
                    "parent_foundation_uri": _optional_text(row.get("parent_foundation_uri")),
                    "parent_linearization_uri": _optional_text(
                        row.get("parent_linearization_uri")
                    ),
                    "is_coding_selectable": None,
                    "sex_selectable": None,
                    "age_group_selectable": None,
                    "policy_status": "unreviewed",
                    "restriction_note": None,
                    "is_active": True,
                    "source_version": SOURCE_VERSION,
                    "source_path": str(CSV_SOURCE_PATH),
                    "created_at": created_at,
                    "updated_at": created_at,
                }
            )
    return rows


def _seed_icd11_rows():
    seed_rows = _load_seed_rows()
    icd_table = sa.table(
        "mas_icd11_mms",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("release", sa.String(length=16)),
        sa.column("linearization_uri", sa.Text()),
        sa.column("foundation_uri", sa.Text()),
        sa.column("code", sa.String(length=16)),
        sa.column("block_id", sa.String(length=64)),
        sa.column("title", sa.Text()),
        sa.column("class_kind", sa.String(length=16)),
        sa.column("depth_in_kind", sa.Integer()),
        sa.column("chapter_no", sa.String(length=8)),
        sa.column("is_residual", sa.Boolean()),
        sa.column("is_leaf", sa.Boolean()),
        sa.column("primary_tabulation", sa.Boolean()),
        sa.column("coding_note", sa.Text()),
        sa.column("sort_order", sa.Integer()),
        sa.column("parent_foundation_uri", sa.Text()),
        sa.column("parent_linearization_uri", sa.Text()),
        sa.column("is_coding_selectable", sa.Boolean()),
        sa.column("sex_selectable", sa.String(length=16)),
        sa.column("age_group_selectable", sa.String(length=32)),
        sa.column("policy_status", sa.String(length=32)),
        sa.column("restriction_note", sa.Text()),
        sa.column("is_active", sa.Boolean()),
        sa.column("source_version", sa.String(length=32)),
        sa.column("source_path", sa.String(length=512)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    for start in range(0, len(seed_rows), CHUNK_SIZE):
        op.bulk_insert(icd_table, seed_rows[start : start + CHUNK_SIZE])


def upgrade():
    op.create_table(
        "mas_icd11_mms",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("release", sa.String(length=16), nullable=False),
        sa.Column("linearization_uri", sa.Text(), nullable=False),
        sa.Column("foundation_uri", sa.Text(), nullable=True),
        sa.Column("code", sa.String(length=16), nullable=True),
        sa.Column("block_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("class_kind", sa.String(length=16), nullable=False),
        sa.Column("depth_in_kind", sa.Integer(), nullable=True),
        sa.Column("chapter_no", sa.String(length=8), nullable=True),
        sa.Column("is_residual", sa.Boolean(), nullable=False),
        sa.Column("is_leaf", sa.Boolean(), nullable=False),
        sa.Column("primary_tabulation", sa.Boolean(), nullable=True),
        sa.Column("coding_note", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("parent_foundation_uri", sa.Text(), nullable=True),
        sa.Column("parent_linearization_uri", sa.Text(), nullable=True),
        sa.Column("is_coding_selectable", sa.Boolean(), nullable=True),
        sa.Column("sex_selectable", sa.String(length=16), nullable=True),
        sa.Column("age_group_selectable", sa.String(length=32), nullable=True),
        sa.Column("policy_status", sa.String(length=32), nullable=False),
        sa.Column("restriction_note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("source_version", sa.String(length=32), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "release", "linearization_uri", name="uq_mas_icd11_mms_release_linearization"
        ),
    )
    op.create_index("ix_mas_icd11_mms_code", "mas_icd11_mms", ["code"], unique=False)
    op.create_index("ix_mas_icd11_mms_release", "mas_icd11_mms", ["release"], unique=False)
    op.create_index(
        "ix_mas_icd11_mms_parent_linearization_uri",
        "mas_icd11_mms",
        ["parent_linearization_uri"],
        unique=False,
    )
    op.create_index(
        "ix_mas_icd11_mms_chapter_no", "mas_icd11_mms", ["chapter_no"], unique=False
    )
    op.create_index(
        "ix_mas_icd11_mms_is_active", "mas_icd11_mms", ["is_active"], unique=False
    )
    _seed_icd11_rows()


def downgrade():
    op.drop_index("ix_mas_icd11_mms_is_active", table_name="mas_icd11_mms")
    op.drop_index("ix_mas_icd11_mms_chapter_no", table_name="mas_icd11_mms")
    op.drop_index("ix_mas_icd11_mms_parent_linearization_uri", table_name="mas_icd11_mms")
    op.drop_index("ix_mas_icd11_mms_release", table_name="mas_icd11_mms")
    op.drop_index("ix_mas_icd11_mms_code", table_name="mas_icd11_mms")
    op.drop_table("mas_icd11_mms")
