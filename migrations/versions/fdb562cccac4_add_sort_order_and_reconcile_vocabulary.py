"""add sort_order to mas_icd_search_terms and reconcile the seed

Revision ID: fdb562cccac4
Revises: f2b7c9e4a1d8
Create Date: 2026-09-25 16:00:00.000000

digitva-3t2. Owner: the more common target among a multi-code term's rows
must list first (TB -> A16 lists before A15: 143 vs 123 final CODs, but
`_load_links` ordered by `icd_code` alone put A15 first). Adds
`sort_order` (smallint, default 100, lower first) and reconciles the seed
CSV (`resource/icd_search_vocabulary_seed.csv`) the same way e9d4b6f8a3c2
and f2b7c9e4a1d8 did:

  (a) add the column;
  (b) insert every CSV row whose (term_normalized, icd_classification,
      icd_code) key is absent, with its sort_order (blank -> 100);
  (c) for an EXISTING row whose key is in the CSV with a non-blank
      sort_order and whose current sort_order is still the column default
      (100), set it to the CSV value -- an admin who already changed the
      sort_order is left alone;
  (d) deactivate (never delete) existing ACTIVE rows matching one of the
      43 keys this pass's CSV removed as not coding-selectable, whose
      source is still seed_used_cod/who_inclusion -- an admin who
      re-sourced one of these as 'admin' is left alone. Three families:
        - S/T injury-chapter and other external-cause targets (head
          injury/trauma, accident-family terms retargeted onto the V89.2
          three-character bucket instead) are never selectable as a COD,
          and injury/allergy terms (drug reaction, anaphylaxis, ALD/
          cardiac-failure superseded targets) fan out to external-cause
          buckets rather than a single code;
        - a verbal autopsy cannot know bacteriological or histological
          confirmation, and A15/A16/1B10.x all share the Pulmonary
          tuberculosis VA bucket, so every TB-shorthand term (TB, Kochs,
          consumption, pulmonary TB/tuberculosis) now links A16 / 1B10.Z
          only, not the bacteriologically-confirmed A15/1B10.0/1B10.1;
        - V89 (3-character "Other transport accident") is not itself
          coding-selectable, so road-traffic/accident terms now link the
          detailed V89.2 code instead.
      (c) and (d) use `.all()`, not `.first()`: the key is deliberately
      NOT unique (an admin duplicate at the same key must not be
      silently skipped). Everything captured in _mig_ tables (excluded
      from drift detection) so the downgrade reverses exactly what this
      migration did and nothing an administrator did separately.

On a fresh chain, c5a8d2e7f1b4/e9d4b6f8a3c2/f2b7c9e4a1d8 already seed from
the CURRENT (live) CSV, so by the time this migration runs the 120 new
links are already present and the 43 dead keys were never inserted --
steps (b) and (d) become no-ops there. Step (c) still runs: those earlier
migrations insert before the column exists, so every row starts at the
default 100 and (c) sets the CSV's non-blank sort_order values.
"""

import csv
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "fdb562cccac4"
down_revision = "f2b7c9e4a1d8"
branch_labels = None
depends_on = None

CSV_SOURCE_PATH = Path("resource/icd_search_vocabulary_seed.csv")
TABLE = "mas_icd_search_terms"
INSERTED_TABLE = "_mig_fdb562cccac4_inserted"
SORT_ORDER_TABLE = "_mig_fdb562cccac4_sort_order"
DEACTIVATED_TABLE = "_mig_fdb562cccac4_deactivated"

_SOURCES = ("seed_used_cod", "who_inclusion", "admin", "telemetry")
_CLASSIFICATIONS = ("icd10", "icd11")
_DEFAULT_SORT_ORDER = 100

# The exact 43 (term_normalized, icd_classification, icd_code) keys this
# pass's CSV drops because their target is not coding-selectable (policy
# repair 2026-09-25): S/T injury-chapter and superseded I50/I11/K70/I27.9
# targets, TB-shorthand terms narrowed off the bacteriologically-confirmed
# A15/1B10.0/1B10.1 codes, and traffic/accident terms retargeted off the
# non-selectable V89 three-character bucket. Fixed list, not re-derived
# from git at migration time -- a migration must not depend on git history
# being available at upgrade time.
_DEAD_KEYS = (
    ("accident", "icd10", "V89"),
    ("ald", "icd10", "K70"),
    ("allergic reaction", "icd10", "T78.4"),
    ("anaphylaxis", "icd10", "T78.2"),
    ("any condition in i50 - i51 4-i51 9 due to hypertension", "icd10", "I11"),
    ("cardiac failure", "icd10", "I50"),
    ("ccf", "icd10", "I50"),
    ("chf", "icd10", "I50"),
    ("congestive cardiac failure", "icd10", "I50"),
    ("congestive heart failure", "icd10", "I50"),
    ("consumption", "icd10", "A15"),
    ("consumption", "icd11", "1B10.0"),
    ("cor pulmonale", "icd10", "I27.9"),
    ("drug reaction", "icd10", "T88.7"),
    ("drug reaction", "icd11", "NF09"),
    ("head injury", "icd10", "S06.9"),
    ("head injury", "icd11", "NA07"),
    ("head trauma", "icd10", "S06.9"),
    ("head trauma", "icd11", "NA07"),
    ("heart failure", "icd10", "I50"),
    ("hhd", "icd10", "I11"),
    ("koch disease", "icd10", "A15"),
    ("koch disease", "icd11", "1B10.0"),
    ("koch disease", "icd11", "1B10.1"),
    ("koch s disease", "icd10", "A15"),
    ("koch s disease", "icd11", "1B10.0"),
    ("koch s disease", "icd11", "1B10.1"),
    ("kochs", "icd10", "A15"),
    ("kochs", "icd11", "1B10.0"),
    ("kochs", "icd11", "1B10.1"),
    ("motor vehicle accident", "icd10", "V89"),
    ("mva", "icd10", "V89"),
    ("pulmonary tb", "icd10", "A15"),
    ("pulmonary tb", "icd11", "1B10.0"),
    ("pulmonary tuberculosis", "icd10", "A15"),
    ("pulmonary tuberculosis", "icd11", "1B10.0"),
    ("road accident", "icd10", "V89"),
    ("road traffic accident", "icd10", "V89"),
    ("road traffic injury", "icd10", "V89"),
    ("rta", "icd10", "V89"),
    ("tb", "icd10", "A15"),
    ("tb", "icd11", "1B10.0"),
    ("tb", "icd11", "1B10.1"),
)


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


def _parsed_sort_order(raw: str | None) -> int:
    value = (raw or "").strip()
    return int(value) if value else _DEFAULT_SORT_ORDER


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        TABLE,
        sa.Column(
            "sort_order",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("100"),
        ),
    )

    bind.execute(sa.text(f"CREATE TABLE {INSERTED_TABLE} (term_id uuid PRIMARY KEY)"))
    bind.execute(
        sa.text(
            f"CREATE TABLE {SORT_ORDER_TABLE} ("
            "term_id uuid PRIMARY KEY, previous_sort_order smallint NOT NULL)"
        )
    )
    bind.execute(sa.text(f"CREATE TABLE {DEACTIVATED_TABLE} (term_id uuid PRIMARY KEY)"))

    seed_rows = _load_seed_rows()

    # (b) insert rows absent by key.
    insert = sa.text(
        f"INSERT INTO {TABLE} (term_id, term, term_normalized, icd_classification, "
        "icd_code, source, note, sort_order, is_active, created_at, updated_at) "
        "VALUES (:term_id, :term, :term_normalized, :icd_classification, "
        ":icd_code, :source, :note, :sort_order, true, :now, :now)"
    )
    capture_inserted = sa.text(f"INSERT INTO {INSERTED_TABLE} (term_id) VALUES (:term_id)")
    now = datetime.now(UTC)
    inserted = 0
    for row in seed_rows:
        classification = row["icd_classification"].strip()
        source = (row.get("source") or "").strip() or "seed_used_cod"
        if classification not in _CLASSIFICATIONS or source not in _SOURCES:
            raise ValueError(f"malformed seed row: {row!r}")
        term_normalized = row["term_normalized"].strip()
        icd_code = row["icd_code"].strip()
        exists = bind.execute(
            sa.text(
                f"SELECT exists (SELECT 1 FROM {TABLE} WHERE "
                "term_normalized = :term_normalized AND "
                "icd_classification = :icd_classification AND icd_code = :icd_code)"
            ),
            {
                "term_normalized": term_normalized,
                "icd_classification": classification,
                "icd_code": icd_code,
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
                "term_normalized": term_normalized,
                "icd_classification": classification,
                "icd_code": icd_code,
                "source": source,
                "note": (row.get("note") or "").strip() or None,
                "sort_order": _parsed_sort_order(row.get("sort_order")),
                "now": now,
            },
        )
        bind.execute(capture_inserted, {"term_id": str(term_id)})
        inserted += 1

    # (c) set sort_order for existing rows the CSV gives a non-blank
    # sort_order, only while they still carry the column default -- an
    # admin-set value is left untouched.
    updated_sort_order = 0
    for row in seed_rows:
        raw_sort_order = (row.get("sort_order") or "").strip()
        if not raw_sort_order:
            continue
        csv_sort_order = int(raw_sort_order)
        # `.all()`, not `.first()`: the key is deliberately not unique -- an
        # admin duplicate at the same key must not be silently skipped.
        existing_rows = bind.execute(
            sa.text(
                f"SELECT term_id, sort_order FROM {TABLE} WHERE "
                "term_normalized = :term_normalized AND "
                "icd_classification = :icd_classification AND icd_code = :icd_code"
            ),
            {
                "term_normalized": row["term_normalized"].strip(),
                "icd_classification": row["icd_classification"].strip(),
                "icd_code": row["icd_code"].strip(),
            },
        ).mappings().all()
        for existing in existing_rows:
            if existing["sort_order"] != _DEFAULT_SORT_ORDER:
                continue
            if existing["sort_order"] == csv_sort_order:
                continue
            bind.execute(
                sa.text(f"INSERT INTO {SORT_ORDER_TABLE} (term_id, previous_sort_order) "
                         "VALUES (:term_id, :previous) ON CONFLICT DO NOTHING"),
                {"term_id": str(existing["term_id"]), "previous": existing["sort_order"]},
            )
            bind.execute(
                sa.text(f"UPDATE {TABLE} SET sort_order = :sort_order WHERE term_id = :term_id"),
                {"sort_order": csv_sort_order, "term_id": str(existing["term_id"])},
            )
            updated_sort_order += 1

    # (d) deactivate active rows at a dead key, seeded/WHO source only.
    deactivated = 0
    for term_normalized, classification, icd_code in _DEAD_KEYS:
        # `.all()`, not `.first()`: same non-uniqueness as above.
        dead_rows = bind.execute(
            sa.text(
                f"SELECT term_id FROM {TABLE} WHERE term_normalized = :term_normalized "
                "AND icd_classification = :icd_classification AND icd_code = :icd_code "
                "AND is_active = true AND source IN ('seed_used_cod', 'who_inclusion')"
            ),
            {
                "term_normalized": term_normalized,
                "icd_classification": classification,
                "icd_code": icd_code,
            },
        ).mappings().all()
        for row in dead_rows:
            bind.execute(
                sa.text(f"UPDATE {TABLE} SET is_active = false WHERE term_id = :term_id"),
                {"term_id": str(row["term_id"])},
            )
            bind.execute(
                sa.text(f"INSERT INTO {DEACTIVATED_TABLE} (term_id) VALUES (:term_id)"),
                {"term_id": str(row["term_id"])},
            )
            deactivated += 1

    print(
        f"reconcile: inserted {inserted}, sort_order updated {updated_sort_order}, "
        f"deactivated {deactivated}"
    )


def downgrade() -> None:
    bind = op.get_bind()

    reactivated = bind.execute(
        sa.text(
            f"UPDATE {TABLE} SET is_active = true WHERE term_id IN "
            f"(SELECT term_id FROM {DEACTIVATED_TABLE})"
        )
    ).rowcount
    bind.execute(sa.text(f"DROP TABLE {DEACTIVATED_TABLE}"))

    restored = bind.execute(
        sa.text(
            f"UPDATE {TABLE} t SET sort_order = s.previous_sort_order "
            f"FROM {SORT_ORDER_TABLE} s WHERE t.term_id = s.term_id"
        )
    ).rowcount
    bind.execute(sa.text(f"DROP TABLE {SORT_ORDER_TABLE}"))

    removed = bind.execute(
        sa.text(
            f"DELETE FROM {TABLE} WHERE term_id IN "
            f"(SELECT term_id FROM {INSERTED_TABLE})"
        )
    ).rowcount
    bind.execute(sa.text(f"DROP TABLE {INSERTED_TABLE}"))

    op.drop_column(TABLE, "sort_order")
    print(
        f"reconcile downgrade: reactivated {reactivated}, sort_order restored {restored}, "
        f"removed {removed}"
    )
