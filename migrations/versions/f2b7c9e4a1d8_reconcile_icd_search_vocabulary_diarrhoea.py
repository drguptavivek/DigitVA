"""reconcile the COD search vocabulary seed: diarrhoeal terms

Revision ID: f2b7c9e4a1d8
Revises: d8a1f4c7b2e6
Create Date: 2026-09-25 15:10:00.000000

Same reconcile as e9d4b6f8a3c2 (insert absent seed keys only; admin
edits and deactivations survive; inserted ids captured in a _mig_ table so
the downgrade removes exactly those). Found through telemetry on dev: every
"diarrhoea" query returned 0 results although A09 is among the most-used
final CODs (141 of 8,547) -- its ICD-10 title says "gastroenteritis and
colitis", and diarrhoea appears only in WHO inclusion notes. Added:
diarrhoea, acute diarrhoea, (acute) diarrhoeal disease, acute
gastroenteritis, loose motions, dysentery -> A09 / 1A40.Z (both in the
Diarrheal diseases VA bucket; ME05.1, the symptom code, deliberately not
used), and bacillary dysentery -> A03 / 1A02. "AGE" left out: its
normalized key "age" would hijack plain "age" queries.
"""

import csv
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "f2b7c9e4a1d8"
down_revision = "d8a1f4c7b2e6"
branch_labels = None
depends_on = None

CSV_SOURCE_PATH = Path("resource/icd_search_vocabulary_seed.csv")
TABLE = "mas_icd_search_terms"
CAPTURE_TABLE = "_mig_f2b7c9e4a1d8_inserted"

_SOURCES = ("seed_used_cod", "who_inclusion", "admin", "telemetry")
_CLASSIFICATIONS = ("icd10", "icd11")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_seed_rows() -> list[dict]:
    csv_path = _repo_root() / CSV_SOURCE_PATH
    if not csv_path.exists():
        raise ValueError(f"ICD search vocabulary seed CSV not found: {csv_path}")
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if (row.get("term_normalized") or "").strip()
        ]


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            f"CREATE TABLE {CAPTURE_TABLE} ("
            "term_id uuid PRIMARY KEY)"
        )
    )
    now = datetime.now(UTC)
    insert = sa.text(
        f"INSERT INTO {TABLE} (term_id, term, term_normalized, icd_classification, "
        "icd_code, source, note, is_active, created_at, updated_at) "
        "VALUES (:term_id, :term, :term_normalized, :icd_classification, "
        ":icd_code, :source, :note, true, :now, :now)"
    )
    capture = sa.text(f"INSERT INTO {CAPTURE_TABLE} (term_id) VALUES (:term_id)")
    inserted = 0
    for row in _load_seed_rows():
        classification = row["icd_classification"].strip()
        source = (row.get("source") or "").strip() or "seed_used_cod"
        if classification not in _CLASSIFICATIONS or source not in _SOURCES:
            raise ValueError(f"malformed seed row: {row!r}")
        exists = bind.execute(
            sa.text(
                f"SELECT exists (SELECT 1 FROM {TABLE} WHERE "
                "term_normalized = :term_normalized AND "
                "icd_classification = :icd_classification AND "
                "icd_code = :icd_code)"
            ),
            {
                "term_normalized": row["term_normalized"].strip(),
                "icd_classification": classification,
                "icd_code": row["icd_code"].strip(),
            },
        ).scalar()
        if exists:
            continue
        term_id = uuid.uuid4()
        bind.execute(
            insert,
            {
                "term_id": str(term_id),
                "term": row["term"].strip(),
                "term_normalized": row["term_normalized"].strip(),
                "icd_classification": classification,
                "icd_code": row["icd_code"].strip(),
                "source": source,
                "note": (row.get("note") or "").strip() or None,
                "now": now,
            },
        )
        bind.execute(capture, {"term_id": str(term_id)})
        inserted += 1
    print(f"reconcile: inserted {inserted} vocabulary links")


def downgrade() -> None:
    bind = op.get_bind()
    removed = bind.execute(
        sa.text(
            f"DELETE FROM {TABLE} WHERE term_id IN "
            f"(SELECT term_id FROM {CAPTURE_TABLE})"
        )
    ).rowcount
    bind.execute(sa.text(f"DROP TABLE {CAPTURE_TABLE}"))
    print(f"reconcile downgrade: removed {removed} vocabulary links")
