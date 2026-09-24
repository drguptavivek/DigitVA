"""Bring WHO_2022_VA_2026's ICD-11 rows to the owner's 2026-09-24 decisions.

Revision ID: dc762caa67dd
Revises: fba41e2f1f9d
Create Date: 2026-09-24 18:00:00.000000

digitva-712.4. Policy: docs/policy/icd10-to-icd11-transition.md section 6
(decisions 4, 5a, 5b, 9 and 10). The generator now reads the decisions from
docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_icd11_owner_decisions.csv
and was rerun; its output is frozen in
resource/who_2022_va_2026_icd11_native_mappings.csv (18,505 rows, no ICD-11
code unmapped). The rows it replaces, as seeded by 6c11b620f48f, are frozen
in resource/who_2022_va_2026_icd11_native_mappings_2026-09-21.csv.

Upgrade touches only WHO_2022_VA_2026's ICD-11 rows, code by code, and never
deletes. A code with no row is inserted. A row that still holds the
2026-09-21 generated value (node, match type and note), or already holds the
new one, is set to the new value. Any other row was edited in admin after the
seed and is left alone and counted: the admin's choice is newer than either
generated value, so overwriting it would lose a decision. A row whose node
is missing is skipped and counted. mapping_version is bumped only when a row
changed, so a rerun is a no-op.

Downgrade is the reverse for rows that still hold the new value: a code that
was in the 2026-09-21 table gets that value back, a code this migration
added is deleted. Rows edited since are left alone.
"""

import csv
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "dc762caa67dd"
down_revision = "fba41e2f1f9d"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

SCHEME_CODE = "WHO_2022_VA_2026"
NEW_CSV_PATH = Path("resource/who_2022_va_2026_icd11_native_mappings.csv")
OLD_CSV_PATH = Path("resource/who_2022_va_2026_icd11_native_mappings_2026-09-21.csv")
# 6c11b620f48f stamped every row with the cause list as its source.
OLD_SOURCE_SHEET = "who_2022_va_cause_list_icd10_icd11.csv"
CHUNK_SIZE = 1000

MAP_TABLE = sa.table(
    "map_icd_cod_buckets",
    sa.column("mapping_id", sa.Uuid(as_uuid=True)),
    sa.column("scheme_id", sa.Uuid(as_uuid=True)),
    sa.column("age_scope", sa.String(length=32)),
    sa.column("icd_code", sa.String(length=16)),
    sa.column("icd_classification", sa.String(length=8)),
    sa.column("node_id", sa.Uuid(as_uuid=True)),
    sa.column("source_sheet", sa.String(length=128)),
    sa.column("source_row_number", sa.Integer()),
    sa.column("source_category", sa.String(length=256)),
    sa.column("match_type", sa.String(length=32)),
    sa.column("mapping_note", sa.Text()),
    sa.column("is_active", sa.Boolean()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

UPDATE_SQL = sa.text(
    "UPDATE map_icd_cod_buckets SET node_id = :node_id, source_sheet = :source_sheet, "
    "source_row_number = :source_row_number, source_category = :source_category, "
    "match_type = :match_type, mapping_note = :mapping_note, is_active = true, "
    "updated_at = :now WHERE mapping_id = :mapping_id"
)


def _load(path, default_source_sheet=None):
    """`{(age_scope, icd_code): row}` of a frozen CSV, values normalised to
    what the table holds (None for empty)."""
    csv_path = Path(__file__).resolve().parents[2] / path
    if not csv_path.exists():
        raise ValueError(f"ICD-11 bucket CSV not found for migration: {csv_path}")
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        return {
            (row["age_scope"], row["icd_code"]): {
                "node_code": row["node_code"],
                "match_type": row["match_type"] or None,
                "mapping_note": row["mapping_note"] or None,
                "source_category": row["source_category"] or None,
                "source_row_number": int(row["source_row_number"]) if row["source_row_number"] else None,
                "source_sheet": row.get("source_sheet") or default_source_sheet,
            }
            for row in csv.DictReader(handle)
            if row["scheme_code"] == SCHEME_CODE
        }


def _generated_key(row):
    """What identifies a row as generator output rather than an admin edit."""
    return (row["node_code"], row["match_type"], row["mapping_note"])


def _state(bind):
    """`(scheme_id, nodes, current)` for the scheme, or None when it is absent."""
    scheme_id = bind.execute(
        sa.text("SELECT scheme_id FROM mas_cod_bucket_schemes WHERE scheme_code = :code"),
        {"code": SCHEME_CODE},
    ).scalar()
    if scheme_id is None:
        return None
    nodes = {
        (row.age_scope or "", row.node_code): row.node_id
        for row in bind.execute(
            sa.text(
                "SELECT node_id, age_scope, node_code FROM mas_cod_bucket_nodes "
                "WHERE scheme_id = :scheme AND node_type = 'field'"
            ),
            {"scheme": scheme_id},
        )
    }
    current = {
        (row.age_scope or "", row.icd_code): dict(row._mapping)
        for row in bind.execute(
            sa.text(
                "SELECT m.mapping_id, m.age_scope, m.icd_code, n.node_code, m.match_type, "
                "m.mapping_note, m.source_sheet, m.source_category, m.source_row_number "
                "FROM map_icd_cod_buckets m JOIN mas_cod_bucket_nodes n ON n.node_id = m.node_id "
                "WHERE m.scheme_id = :scheme AND m.icd_classification = 'icd11'"
            ),
            {"scheme": scheme_id},
        )
    }
    return scheme_id, nodes, current


def _update_params(mapping_id, node_id, row, now):
    return {
        "mapping_id": mapping_id,
        "node_id": node_id,
        "source_sheet": row["source_sheet"],
        "source_row_number": row["source_row_number"],
        "source_category": row["source_category"],
        "match_type": row["match_type"],
        "mapping_note": row["mapping_note"],
        "now": now,
    }


def _finish(bind, scheme_id, changed, now):
    if not changed:
        return
    bind.execute(
        sa.text(
            "UPDATE mas_cod_bucket_schemes SET mapping_version = COALESCE(mapping_version, 0) + 1, "
            "updated_at = :now WHERE scheme_id = :scheme"
        ),
        {"scheme": scheme_id, "now": now},
    )


def upgrade():
    bind = op.get_bind()
    state = _state(bind)
    if state is None:
        log.info("%s does not exist; no ICD-11 decisions applied.", SCHEME_CODE)
        return
    scheme_id, nodes, current = state
    new_rows = _load(NEW_CSV_PATH)
    old_rows = _load(OLD_CSV_PATH, OLD_SOURCE_SHEET)
    now = datetime.now(UTC)
    inserts, updates = [], []
    edited = missing_node = 0
    for key, new in new_rows.items():
        node_id = nodes.get((key[0], new["node_code"]))
        if node_id is None:
            missing_node += 1
            continue
        row = current.get(key)
        if row is None:
            inserts.append(
                {
                    "mapping_id": uuid.uuid4(),
                    "scheme_id": scheme_id,
                    "age_scope": key[0] or None,
                    "icd_code": key[1],
                    "icd_classification": "icd11",
                    "node_id": node_id,
                    "source_sheet": new["source_sheet"],
                    "source_row_number": new["source_row_number"],
                    "source_category": new["source_category"],
                    "match_type": new["match_type"],
                    "mapping_note": new["mapping_note"],
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            continue
        if all(row[name] == value for name, value in new.items()):
            continue
        old = old_rows.get(key)
        if _generated_key(row) in {_generated_key(new), old and _generated_key(old)}:
            updates.append(_update_params(row["mapping_id"], node_id, new, now))
        else:
            edited += 1
    for start in range(0, len(inserts), CHUNK_SIZE):
        op.bulk_insert(MAP_TABLE, inserts[start : start + CHUNK_SIZE])
    if updates:
        bind.execute(UPDATE_SQL, updates)
    _finish(bind, scheme_id, inserts or updates, now)
    log.info(
        "%s ICD-11 owner decisions: inserted %s, updated %s; left %s admin-edited rows and "
        "skipped %s rows whose node is missing.",
        SCHEME_CODE, len(inserts), len(updates), edited, missing_node,
    )


def downgrade():
    bind = op.get_bind()
    state = _state(bind)
    if state is None:
        return
    scheme_id, nodes, current = state
    new_rows = _load(NEW_CSV_PATH)
    old_rows = _load(OLD_CSV_PATH, OLD_SOURCE_SHEET)
    now = datetime.now(UTC)
    deletes, updates = [], []
    for key, new in new_rows.items():
        row = current.get(key)
        if row is None or _generated_key(row) != _generated_key(new):
            continue
        old = old_rows.get(key)
        if old is None:
            deletes.append({"mapping_id": row["mapping_id"]})
            continue
        if _generated_key(old) == _generated_key(new):
            continue
        node_id = nodes.get((key[0], old["node_code"]))
        if node_id is not None:
            updates.append(_update_params(row["mapping_id"], node_id, old, now))
    if deletes:
        bind.execute(sa.text("DELETE FROM map_icd_cod_buckets WHERE mapping_id = :mapping_id"), deletes)
    if updates:
        bind.execute(UPDATE_SQL, updates)
    _finish(bind, scheme_id, deletes or updates, now)
    log.info(
        "%s ICD-11 owner decisions reverted: deleted %s, restored %s.",
        SCHEME_CODE, len(deletes), len(updates),
    )
