"""add mas_icd_search_terms, the COD search vocabulary, and seed it

Revision ID: c5a8d2e7f1b4
Revises: a3c9e1f7b2d4
Create Date: 2026-09-25 09:00:00.000000

digitva-zpe.1. Policy: docs/policy/icd-coding-search-vocabulary.md.

One row per term-code link: clinician shorthand and diagnosis synonyms
(`MI`, `CVA`, `Kochs`) that share no substring with any ICD title, so the
coding-search endpoints never find them lexically. Seeded from
resource/icd_search_vocabulary_seed.csv (ICD-10 codes actually used as
final CODs here plus WHO's own ICD-10 inclusion terms; docs/ is not in the
image, resource/ is). The seed runs only when the table is empty, so admin
edits are never overwritten by an upgrade. Downgrade drops the table, and
with it any admin edits; export them first if they matter.
"""

import csv
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "c5a8d2e7f1b4"
down_revision = "a3c9e1f7b2d4"
branch_labels = None
depends_on = None

CSV_SOURCE_PATH = Path("resource/icd_search_vocabulary_seed.csv")
TABLE = "mas_icd_search_terms"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_seed_rows() -> list[dict]:
    csv_path = _repo_root() / CSV_SOURCE_PATH
    if not csv_path.exists():
        raise ValueError(f"ICD search vocabulary seed CSV not found: {csv_path}")
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if (row.get("term_normalized") or "").strip()]


def _seed_if_empty(bind) -> int:
    """Insert the seed rows; 0 when the table already has vocabulary.

    The empty-table guard is the point: an admin-curated table must never be
    overwritten by an upgrade against a database already using it. Seed
    values ride the CHECK constraints -- a malformed CSV fails the migration
    loudly instead of quietly inserting an unusable row.
    """
    has_rows = bind.execute(sa.text(f"SELECT exists (SELECT 1 FROM {TABLE})")).scalar()
    if has_rows:
        return 0
    now = datetime.now(UTC)
    insert = sa.text(
        f"INSERT INTO {TABLE} (term_id, term, term_normalized, icd_classification, "
        "icd_code, source, note, is_active, created_at, updated_at) "
        "VALUES (gen_random_uuid(), :term, :term_normalized, :icd_classification, "
        ":icd_code, :source, :note, true, :now, :now)"
    )
    rows = _load_seed_rows()
    bind.execute(
        insert,
        [
            {
                "term": row["term"].strip(),
                "term_normalized": row["term_normalized"].strip(),
                "icd_classification": row["icd_classification"].strip(),
                "icd_code": row["icd_code"].strip(),
                "source": row["source"].strip(),
                "note": (row.get("note") or "").strip() or None,
                "now": now,
            }
            for row in rows
        ],
    )
    return len(rows)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column(
            "term_id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column("term_normalized", sa.Text(), nullable=False),
        sa.Column("icd_classification", sa.String(length=6), nullable=False),
        sa.Column("icd_code", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=24), server_default="admin", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("term_id", name=op.f("pk_mas_icd_search_terms")),
        sa.CheckConstraint(
            "icd_classification IN ('icd10', 'icd11')",
            name="icd_classification",
        ),
        sa.CheckConstraint(
            "source IN ('seed_used_cod', 'who_inclusion', 'admin', 'telemetry')",
            name="source",
        ),
    )
    op.create_index(
        "ix_mas_icd_search_terms_lookup",
        TABLE,
        ["term_normalized", "icd_classification", "is_active"],
        unique=False,
    )
    _seed_if_empty(op.get_bind())


def downgrade() -> None:
    op.drop_index("ix_mas_icd_search_terms_lookup", table_name=TABLE)
    op.drop_table(TABLE)
