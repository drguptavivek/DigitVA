"""reconcile the bare tuberculosis search-vocabulary links

Revision ID: b7e2a9c4d6f1
Revises: a5f7c3d92b18
Create Date: 2026-09-25 20:00:00.000000

Add the owner-approved plain-language term for the unspecified pulmonary
tuberculosis codes. A verbal autopsy cannot establish bacteriological
confirmation, and A15/A16/1B10.x share the Pulmonary tuberculosis VA bucket.
Existing exact keys are left untouched; only rows inserted here are removed
by downgrade.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "b7e2a9c4d6f1"
down_revision = "a5f7c3d92b18"
branch_labels = None
depends_on = None

TABLE = "mas_icd_search_terms"
CAPTURE_TABLE = "_mig_b7e2a9c4d6f1_inserted"
DEFAULT_SORT_ORDER = 100
RATIONALE = (
    "VA cannot know bacteriological confirmation; "
    "A15/A16/1B10.x share the Pulmonary tuberculosis bucket"
)

# (term, normalized term, classification, code, source, note, sort order)
TUBERCULOSIS_ROWS = (
    ("tuberculosis", "tuberculosis", "icd10", "A16", "seed_used_cod", RATIONALE, 100),
    ("tuberculosis", "tuberculosis", "icd11", "1B10.Z", "seed_used_cod", RATIONALE, 100),
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(f"CREATE TABLE {CAPTURE_TABLE} (term_id uuid PRIMARY KEY)"))
    now = datetime.now(UTC)
    insert = sa.text(
        f"INSERT INTO {TABLE} (term_id, term, term_normalized, icd_classification, "
        "icd_code, source, note, sort_order, is_active, created_at, updated_at) "
        "VALUES (:term_id, :term, :term_normalized, :icd_classification, "
        ":icd_code, :source, :note, :sort_order, true, :now, :now)"
    )
    capture = sa.text(f"INSERT INTO {CAPTURE_TABLE} (term_id) VALUES (:term_id)")
    inserted = 0

    for row in TUBERCULOSIS_ROWS:
        term, normalized, classification, code, source, note, sort_order = row
        exists = bind.execute(
            sa.text(
                f"SELECT exists (SELECT 1 FROM {TABLE} WHERE "
                "term_normalized = :term_normalized AND "
                "icd_classification = :icd_classification AND "
                "icd_code = :icd_code)"
            ),
            {
                "term_normalized": normalized,
                "icd_classification": classification,
                "icd_code": code,
            },
        ).scalar()
        if exists:
            continue

        term_id = uuid.uuid4()
        bind.execute(
            insert,
            {
                "term_id": str(term_id),
                "term": term,
                "term_normalized": normalized,
                "icd_classification": classification,
                "icd_code": code,
                "source": source,
                "note": note,
                "sort_order": (sort_order if sort_order is not None else DEFAULT_SORT_ORDER),
                "now": now,
            },
        )
        bind.execute(capture, {"term_id": str(term_id)})
        inserted += 1

    print(f"tuberculosis vocabulary reconcile: inserted {inserted} links")


def downgrade() -> None:
    bind = op.get_bind()
    removed = bind.execute(
        sa.text(f"DELETE FROM {TABLE} WHERE term_id IN (SELECT term_id FROM {CAPTURE_TABLE})")
    ).rowcount
    bind.execute(sa.text(f"DROP TABLE {CAPTURE_TABLE}"))
    print(f"tuberculosis vocabulary downgrade: removed {removed} links")
