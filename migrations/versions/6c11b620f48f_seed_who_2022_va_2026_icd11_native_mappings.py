"""Add the Fresh stillbirth bucket and seed WHO_2022_VA_2026's native ICD-11 mappings.

Revision ID: 6c11b620f48f
Revises: 62a637f5c38a
Create Date: 2026-09-21 20:00:00.000000

digitva-712.1. Owner, 2026-09-21: every environment gets the generated table,
not only one that ran `flask cod-buckets generate-icd11 --apply`. The rows
are frozen in resource/who_2022_va_2026_icd11_native_mappings.csv, exported
from dev after that command ran; the generator's review report is in
docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd11-native-2026-09-21/.
Policy: docs/policy/icd11-cod-bucket-schemes.md ("Native method").

First (owner, 2026-09-21) the scheme gains the field node `vas_11_01`
"Fresh stillbirth" under its `stillbirths` category, just before its sibling
`vas_11_02` "Macerated stillbirth", if it is missing. ICD-11 KD3B.1 maps to it
and KD3B.0 stays with `vas_11_02`; ICD-10 P95 cannot tell fresh from
macerated and stays with `vas_11_02`. A reset of the scheme from its source
workbook rebuilds its nodes without this one.

Then the ICD-11 rows: inserted only when the scheme exists and has no ICD-11 rows yet, so a database
where the generator already ran (dev) is left alone. Nodes are resolved by
scheme_code + node_code + age_scope; a row whose node is missing is skipped
and counted. Sets icd11_method='native' and bumps mapping_version.

Downgrade deletes exactly this scheme's ICD-11 rows, resets icd11_method to
NULL, and removes `vas_11_01` only if no mapping points at it any more.
"""

import csv
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "6c11b620f48f"
down_revision = "62a637f5c38a"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

CSV_SOURCE_PATH = Path("resource/who_2022_va_2026_icd11_native_mappings.csv")
SCHEME_CODE = "WHO_2022_VA_2026"
FRESH_STILLBIRTH_CODE = "vas_11_01"
FRESH_STILLBIRTH_LABEL = "Fresh stillbirth"
MACERATED_STILLBIRTH_CODE = "vas_11_02"
STILLBIRTHS_CATEGORY_CODE = "stillbirths"
SOURCE_SHEET = "who_2022_va_cause_list_icd10_icd11.csv"
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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_csv_rows():
    csv_path = _repo_root() / CSV_SOURCE_PATH
    if not csv_path.exists():
        raise ValueError(f"ICD-11 bucket seed CSV not found for migration: {csv_path}")
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row["scheme_code"] == SCHEME_CODE]


def _ensure_fresh_stillbirth_node(bind, scheme_id, now):
    """Add `vas_11_01` beside `vas_11_02` under `stillbirths`, if missing.

    Sort order is per sibling set: one less than `vas_11_02` (48 today).
    """
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM mas_cod_bucket_nodes WHERE scheme_id = :scheme "
            "AND node_type = 'field' AND node_code = :code"
        ),
        {"scheme": scheme_id, "code": FRESH_STILLBIRTH_CODE},
    ).scalar()
    if exists:
        return
    sibling = bind.execute(
        sa.text(
            "SELECT f.age_scope, f.parent_node_id, f.sort_order FROM mas_cod_bucket_nodes f "
            "JOIN mas_cod_bucket_nodes c ON c.node_id = f.parent_node_id "
            "WHERE f.scheme_id = :scheme AND f.node_type = 'field' AND f.node_code = :sibling "
            "AND c.node_code = :category"
        ),
        {"scheme": scheme_id, "sibling": MACERATED_STILLBIRTH_CODE, "category": STILLBIRTHS_CATEGORY_CODE},
    ).mappings().first()
    if sibling is None:
        log.info("%s has no %s under %s; %s not added.", SCHEME_CODE,
                 MACERATED_STILLBIRTH_CODE, STILLBIRTHS_CATEGORY_CODE, FRESH_STILLBIRTH_CODE)
        return
    bind.execute(
        sa.text(
            "INSERT INTO mas_cod_bucket_nodes (node_id, scheme_id, age_scope, node_type, "
            "parent_node_id, node_code, node_label, sort_order, is_active, created_at, updated_at) "
            "VALUES (:id, :scheme, :age_scope, 'field', :parent, :code, :label, :sort_order, "
            "true, :now, :now)"
        ),
        {
            "id": uuid.uuid4(),
            "scheme": scheme_id,
            "age_scope": sibling["age_scope"],
            "parent": sibling["parent_node_id"],
            "code": FRESH_STILLBIRTH_CODE,
            "label": FRESH_STILLBIRTH_LABEL,
            "sort_order": sibling["sort_order"] - 1,
            "now": now,
        },
    )
    log.info("Added %s %s to %s.", FRESH_STILLBIRTH_CODE, FRESH_STILLBIRTH_LABEL, SCHEME_CODE)


def upgrade():
    bind = op.get_bind()
    scheme_id = bind.execute(
        sa.text("SELECT scheme_id FROM mas_cod_bucket_schemes WHERE scheme_code = :code"),
        {"code": SCHEME_CODE},
    ).scalar()
    if scheme_id is None:
        log.info("%s does not exist; no ICD-11 mappings seeded.", SCHEME_CODE)
        return
    now = datetime.now(UTC)
    _ensure_fresh_stillbirth_node(bind, scheme_id, now)
    existing = bind.execute(
        sa.text(
            "SELECT count(*) FROM map_icd_cod_buckets "
            "WHERE scheme_id = :scheme AND icd_classification = 'icd11'"
        ),
        {"scheme": scheme_id},
    ).scalar()
    if existing:
        log.info("%s already has %s ICD-11 mappings; left as they are.", SCHEME_CODE, existing)
        return

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
    rows = []
    skipped = 0
    for row in _load_csv_rows():
        node_id = nodes.get((row["age_scope"], row["node_code"]))
        if node_id is None:
            skipped += 1
            continue
        rows.append(
            {
                "mapping_id": uuid.uuid4(),
                "scheme_id": scheme_id,
                "age_scope": row["age_scope"] or None,
                "icd_code": row["icd_code"],
                "icd_classification": "icd11",
                "node_id": node_id,
                "source_sheet": SOURCE_SHEET,
                "source_row_number": int(row["source_row_number"]) if row["source_row_number"] else None,
                "source_category": row["source_category"] or None,
                "match_type": row["match_type"] or None,
                "mapping_note": row["mapping_note"] or None,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        )
    for start in range(0, len(rows), CHUNK_SIZE):
        op.bulk_insert(MAP_TABLE, rows[start : start + CHUNK_SIZE])
    bind.execute(
        sa.text(
            "UPDATE mas_cod_bucket_schemes "
            "SET icd11_method = 'native', mapping_version = COALESCE(mapping_version, 0) + 1, "
            "updated_at = :now WHERE scheme_id = :scheme"
        ),
        {"scheme": scheme_id, "now": now},
    )
    log.info(
        "Seeded %s ICD-11 mappings into %s; skipped %s rows whose node does not exist.",
        len(rows), SCHEME_CODE, skipped,
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM map_icd_cod_buckets WHERE icd_classification = 'icd11' AND scheme_id = "
            "(SELECT scheme_id FROM mas_cod_bucket_schemes WHERE scheme_code = :code)"
        ),
        {"code": SCHEME_CODE},
    )
    bind.execute(
        sa.text("UPDATE mas_cod_bucket_schemes SET icd11_method = NULL WHERE scheme_code = :code"),
        {"code": SCHEME_CODE},
    )
    bind.execute(
        sa.text(
            "DELETE FROM mas_cod_bucket_nodes n USING mas_cod_bucket_schemes s "
            "WHERE n.scheme_id = s.scheme_id AND s.scheme_code = :code "
            "AND n.node_type = 'field' AND n.node_code = :node_code "
            "AND NOT EXISTS (SELECT 1 FROM map_icd_cod_buckets m WHERE m.node_id = n.node_id)"
        ),
        {"code": SCHEME_CODE, "node_code": FRESH_STILLBIRTH_CODE},
    )
