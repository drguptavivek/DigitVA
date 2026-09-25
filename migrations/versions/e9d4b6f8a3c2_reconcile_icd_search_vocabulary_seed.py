"""reconcile the COD search vocabulary seed (add missing links only)

Revision ID: e9d4b6f8a3c2
Revises: c5a8d2e7f1b4
Create Date: 2026-09-25 11:30:00.000000

digitva-zpe.1 addendum. The first seeding migration runs only when the
table is empty, so databases already seeded (or hand-curated in the admin
panel) never see seed growth. This migration reconciles: it inserts every
seed row whose (term_normalized, icd_classification, icd_code) key is
absent and leaves every existing row untouched -- admin edits and
deactivations survive. The ids it inserts are captured in a _mig_ table
(prefix excluded from drift detection) so the downgrade removes exactly
those rows and nothing an administrator added.

Seed additions in this pass: cor pulmonale, uremia/uraemia, head
injury/trauma, road traffic injury, suicide/self-harm, assault (now with
its ICD-11 counterpart PF2Z), drowning, accident, the cancer shorthand
set (kidney, bladder, cervical, gall bladder, blood, uterine/womb,
prostate), drug reaction, allergic reaction, anaphylaxis, and miliary/
disseminated tuberculosis. Terms the lexical search already finds (e.g.
"miliary tuberculosis", A19's own title) are deliberately absent.
"""

import csv
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "e9d4b6f8a3c2"
down_revision = "c5a8d2e7f1b4"
branch_labels = None
depends_on = None

CSV_SOURCE_PATH = Path("resource/icd_search_vocabulary_seed.csv")
TABLE = "mas_icd_search_terms"
CAPTURE_TABLE = "_mig_e9d4b6f8a3c2_inserted"

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
