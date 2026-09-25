"""Owner decisions 15, 16 (ICD-10) and 17 (ICD-11) for WHO_2022_VA_2026, plus stillbirth vocabulary.

Revision ID: a5f7c3d92b18
Revises: fdb562cccac4
Create Date: 2026-09-25 20:00:00.000000

digitva-g2n. Policy: docs/policy/icd10-to-icd11-transition.md section 6
(decisions 15-18) and docs/policy/who-2022-icd10-coding-allowability.md
"Transport codes are selectable only at the level where WHO decides the
bucket".

- 15: the 88 ICD-10 three-character V01-V89/Y85 rows that are currently
  coding-selectable become not selectable (V90-V99 stay selectable; every
  one of the 88 has selectable fourth-character subcodes already). A
  saved final assessment keeps its code; this only changes what a coder
  can newly select. Reverted only for rows still holding the value this
  migration set, so a later admin edit is not undone.
- 16: WHO_2022_VA_2026's ICD-10 mapping for the three-character codes
  V10-V82 and V87 (74 codes) moves from Other transport (vas_12_02) to
  Road traffic (vas_12_01), by WHO's own V01-V99 chapter note (unspecified
  traffic/nontraffic is assumed traffic for V10-V82 and V87, nontraffic for
  V83-V86). V01-V09, V83-V86, V88, V89 stay Other transport. Re-buckets
  historical records only; nobody is re-coded. Mirrors fad35e5c4b79: moves
  a row only while it still holds the 2026 workbook value (vas_12_02,
  match_type transport_non_road), so an admin edit survives and a rerun is
  a no-op.
- 17: the same idea for WHO_2022_VA_2026's ICD-11 rows PA22-PA29, PA2E,
  PA2F, PA2Y and PA2Z (12 codes): from the PA-split default Other transport
  (vas_12_02, match_type split) to Road traffic (vas_12_01). Supersedes
  owner decision 3 for these 12 codes only; PA20, PA21 and PA2A-PA2D stay
  Other transport.
- vocabulary: `mas_icd_search_terms` rows for "stillbirth" (both ICD-11
  timings), "fresh stillbirth"/"intrapartum stillbirth" (P95, KD3B.1) and
  "macerated stillbirth"/"antepartum stillbirth" (P95, KD3B.0). Deactivates
  the retired (stillbirth, icd11, KD3B) seed row, only while it is still
  active and seed-sourced -- an admin who re-sourced it is left alone.
  Mirrors fdb562cccac4's capture-table style so downgrade is exact.

Decision 18 (ICD-11 KD3B/KD3B.Z coding-selectability) is deliberately NOT
here: the ICD-11 coding-selectability policy is a dev-only draft
(`docs/icd-causegrp-mappings/migration-artifacts/who-2022-icd11-policy-draft-2026-09-24/`),
applied through `flask icd11 policy-import` on a database that has already
adopted that draft, not through a migration that would run everywhere.

The ICD-10 and ICD-11 code lists are embedded rather than read from
docs/icd-causegrp-mappings/.../WHO_2022_VA_2026_owner_decisions_overrides.csv
or .../who_2022_va_icd11_owner_decisions.csv (the layer an admin reset or a
regenerate applies), because docs/ is not in the image and a later edit of
those files must not change what this migration did. Tests keep the two
equal. Same reasoning for the vocabulary seed CSV
(resource/icd_search_vocabulary_seed.csv), which also carries these rows.

Downgrade reverses exactly what upgrade changed and leaves everything else
(including any admin edit) alone; a rerun of upgrade is a no-op.

After upgrading, refresh the COD bucket report snapshot so historic
V10-V82/V87 (and PA2x) deaths report as Road traffic:
`docker compose exec -T minerva_app_service uv run --no-sync flask analytics
refresh-submission-mv` -- the snapshot MV joins bucket rows live by
icd_code/icd_classification, so no MV SQL change is needed.
"""

import logging
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "a5f7c3d92b18"
down_revision = "fdb562cccac4"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

SCHEME_CODE = "WHO_2022_VA_2026"
DECISION_MATCH_TYPE = "owner_decision"

# --- Decision 15: ICD-10 three-character V01-V89 and Y85 not selectable ---

V_Y85_NOT_SELECTABLE_CODES = tuple(
    f"V{number:02d}" for number in range(1, 90) if number not in (7, 8)
) + ("Y85",)

# --- Decision 16: ICD-10 V10-V82 and V87 -> Road traffic ---

ICD10_ROAD_TRAFFIC_CODES = tuple(f"V{number:02d}" for number in range(10, 83)) + ("V87",)
ICD10_OLD_NODE = "vas_12_02"
ICD10_OLD_MATCH_TYPE = "transport_non_road"
ICD10_OLD_NOTE = (
    "Distinction vs VAs-12.01 depends on decimal-level transport codes and whether "
    "death was a road traffic accident.Requires detailed external-cause coding and "
    "road-traffic context."
)
ICD10_NEW_NODE = "vas_12_01"
ICD10_NEW_NOTE = (
    "Owner decision 16 (2026-09-25): WHO's ICD-10 V01-V99 chapter note assumes traffic "
    "for unspecified vehicle accidents V10-V82 and V87 (nontraffic for V83-V86), so this "
    "three-character code goes to Road traffic. Re-buckets historical records only; "
    "nobody is re-coded."
)

# --- Decision 17: ICD-11 PA22-PA29, PA2E, PA2F, PA2Y, PA2Z -> Road traffic ---

ICD11_ROAD_TRAFFIC_CODES = (
    tuple(f"PA2{digit}" for digit in "23456789") + ("PA2E", "PA2F", "PA2Y", "PA2Z")
)
ICD11_OLD_NODE = "vas_12_02"
ICD11_OLD_MATCH_TYPE = "split"
ICD11_OLD_NOTE = "ICD-11 2026-01 range PA00-PA5Z"
ICD11_NEW_NODE = "vas_12_01"
ICD11_NEW_NOTE = (
    "Owner decision 17 (2026-09-25): WHO's ICD-10 traffic assumption for unspecified "
    "V10-V82/V87 applied by analogy to ICD-11 unknown-whether-traffic codes -> Road "
    "traffic. Supersedes decision 3 for these codes."
)

SELECT_ROWS = sa.text(
    "SELECT m.mapping_id, m.icd_code, n.node_code, m.match_type FROM map_icd_cod_buckets m "
    "JOIN mas_cod_bucket_nodes n ON n.node_id = m.node_id "
    "WHERE m.scheme_id = :scheme AND m.icd_classification = :cls AND m.age_scope IS NULL "
    "AND upper(m.icd_code) IN :codes"
).bindparams(sa.bindparam("codes", expanding=True))
UPDATE_ROW = sa.text(
    "UPDATE map_icd_cod_buckets SET node_id = :node_id, match_type = :match_type, "
    "mapping_note = :mapping_note, updated_at = :now WHERE mapping_id = :mapping_id"
)


def _repoint(
    bind, *, classification, codes, old_node, old_match_type, old_note, new_node, new_note, to_decision
):
    """Move rows between the workbook/generated value and the owner decision.

    Mirrors fad35e5c4b79's ``_apply``: touches a row only while it still
    holds the source value, so an admin edit (or a value from a different
    decision) is left alone and counted.
    """
    scheme_id = bind.execute(
        sa.text("SELECT scheme_id FROM mas_cod_bucket_schemes WHERE scheme_code = :code"),
        {"code": SCHEME_CODE},
    ).scalar()
    if scheme_id is None:
        log.info("%s does not exist; no %s owner decision applied.", SCHEME_CODE, classification)
        return 0, 0
    nodes = dict(
        bind.execute(
            sa.text(
                "SELECT node_code, node_id FROM mas_cod_bucket_nodes "
                "WHERE scheme_id = :scheme AND node_type = 'field' AND age_scope IS NULL"
            ),
            {"scheme": scheme_id},
        ).all()
    )
    if to_decision:
        source, target_node, target_match, target_note = (
            (old_node, old_match_type), new_node, DECISION_MATCH_TYPE, new_note,
        )
    else:
        source, target_node, target_match, target_note = (
            (new_node, DECISION_MATCH_TYPE), old_node, old_match_type, old_note,
        )
    if target_node not in nodes:
        log.info("%s has no node %s; %s rows left.", SCHEME_CODE, target_node, len(codes))
        return 0, len(codes)
    now = datetime.now(UTC)
    updates = []
    left = 0
    for row in bind.execute(SELECT_ROWS, {"scheme": scheme_id, "cls": classification, "codes": list(codes)}):
        if (row.node_code, row.match_type) != source:
            left += (row.node_code, row.match_type) != (target_node, target_match)
            continue
        updates.append(
            {
                "mapping_id": row.mapping_id,
                "node_id": nodes[target_node],
                "match_type": target_match,
                "mapping_note": target_note,
                "now": now,
            }
        )
    if updates:
        bind.execute(UPDATE_ROW, updates)
        bind.execute(
            sa.text(
                "UPDATE mas_cod_bucket_schemes SET mapping_version = COALESCE(mapping_version, 0) + 1, "
                "updated_at = :now WHERE scheme_id = :scheme"
            ),
            {"scheme": scheme_id, "now": now},
        )
    return len(updates), left


def _set_selectability(codes, *, to_selectable: bool) -> None:
    bind = op.get_bind()
    was_selectable = not to_selectable
    result = bind.execute(
        sa.text(
            "UPDATE mas_icd10_2019_2 SET is_coding_selectable = :to_selectable, updated_at = now() "
            "WHERE semantic_level = 'three_character' AND code IN :codes "
            "AND is_coding_selectable = :was_selectable"
        ).bindparams(sa.bindparam("codes", expanding=True)),
        {"codes": list(codes), "to_selectable": to_selectable, "was_selectable": was_selectable},
    )
    log.info(
        "Decision 15: %s ICD-10 three-character rows set is_coding_selectable=%s.",
        result.rowcount, to_selectable,
    )


def _normalize(text: str) -> str:
    """Minimal reimplementation of icd_search_vocabulary_service.normalize_term
    for the plain ASCII terms this migration inserts. A migration must not
    import application code (tests/migrations/test_no_app_imports_in_migrations.py).
    """
    return " ".join(text.lower().split())


VOCAB_TABLE = "mas_icd_search_terms"
VOCAB_INSERTED_TABLE = "_mig_a5f7c3d92b18_vocab_inserted"
VOCAB_DEACTIVATED_TABLE = "_mig_a5f7c3d92b18_vocab_deactivated"

# (term, icd_classification, icd_code, note, sort_order)
VOCAB_ROWS = (
    ("stillbirth", "icd11", "KD3B.1", "common term", 1),
    ("stillbirth", "icd11", "KD3B.0", "common term", 2),
    ("fresh stillbirth", "icd10", "P95", "ICD-10 cannot distinguish fresh from macerated", None),
    ("fresh stillbirth", "icd11", "KD3B.1", "intrapartum fetal death", None),
    ("intrapartum stillbirth", "icd10", "P95", "ICD-10 cannot distinguish fresh from macerated", None),
    ("intrapartum stillbirth", "icd11", "KD3B.1", "intrapartum fetal death", None),
    ("macerated stillbirth", "icd10", "P95", "ICD-10 cannot distinguish fresh from macerated", None),
    ("macerated stillbirth", "icd11", "KD3B.0", "antepartum fetal death", None),
    ("antepartum stillbirth", "icd10", "P95", "ICD-10 cannot distinguish fresh from macerated", None),
    ("antepartum stillbirth", "icd11", "KD3B.0", "antepartum fetal death", None),
)
VOCAB_DEAD_KEY = ("stillbirth", "icd11", "KD3B")
VOCAB_DEFAULT_SORT_ORDER = 100


def _insert_vocab(bind) -> int:
    bind.execute(sa.text(f"CREATE TABLE IF NOT EXISTS {VOCAB_INSERTED_TABLE} (term_id uuid PRIMARY KEY)"))
    insert = sa.text(
        f"INSERT INTO {VOCAB_TABLE} (term_id, term, term_normalized, icd_classification, "
        "icd_code, source, note, sort_order, is_active, created_at, updated_at) "
        "VALUES (:term_id, :term, :term_normalized, :icd_classification, "
        ":icd_code, 'seed_used_cod', :note, :sort_order, true, :now, :now)"
    )
    capture = sa.text(f"INSERT INTO {VOCAB_INSERTED_TABLE} (term_id) VALUES (:term_id)")
    now = datetime.now(UTC)
    inserted = 0
    for term, classification, icd_code, note, sort_order in VOCAB_ROWS:
        term_normalized = _normalize(term)
        exists = bind.execute(
            sa.text(
                f"SELECT exists (SELECT 1 FROM {VOCAB_TABLE} WHERE term_normalized = :term_normalized "
                "AND icd_classification = :icd_classification AND icd_code = :icd_code)"
            ),
            {"term_normalized": term_normalized, "icd_classification": classification, "icd_code": icd_code},
        ).scalar()
        if exists:
            continue
        term_id = uuid.uuid4()
        bind.execute(
            insert,
            {
                "term_id": str(term_id),
                "term": term,
                "term_normalized": term_normalized,
                "icd_classification": classification,
                "icd_code": icd_code,
                "note": note,
                "sort_order": sort_order if sort_order is not None else VOCAB_DEFAULT_SORT_ORDER,
                "now": now,
            },
        )
        bind.execute(capture, {"term_id": str(term_id)})
        inserted += 1
    return inserted


def _deactivate_vocab(bind) -> int:
    bind.execute(sa.text(f"CREATE TABLE IF NOT EXISTS {VOCAB_DEACTIVATED_TABLE} (term_id uuid PRIMARY KEY)"))
    term_normalized, classification, icd_code = VOCAB_DEAD_KEY
    dead_rows = bind.execute(
        sa.text(
            f"SELECT term_id FROM {VOCAB_TABLE} WHERE term_normalized = :term_normalized "
            "AND icd_classification = :icd_classification AND icd_code = :icd_code "
            "AND is_active = true AND source = 'seed_used_cod'"
        ),
        {"term_normalized": _normalize(term_normalized), "icd_classification": classification, "icd_code": icd_code},
    ).mappings().all()
    for row in dead_rows:
        bind.execute(
            sa.text(f"UPDATE {VOCAB_TABLE} SET is_active = false WHERE term_id = :term_id"),
            {"term_id": str(row["term_id"])},
        )
        bind.execute(
            sa.text(f"INSERT INTO {VOCAB_DEACTIVATED_TABLE} (term_id) VALUES (:term_id)"),
            {"term_id": str(row["term_id"])},
        )
    return len(dead_rows)


def upgrade() -> None:
    bind = op.get_bind()

    _set_selectability(V_Y85_NOT_SELECTABLE_CODES, to_selectable=False)

    changed_16, left_16 = _repoint(
        bind, classification="icd10", codes=ICD10_ROAD_TRAFFIC_CODES,
        old_node=ICD10_OLD_NODE, old_match_type=ICD10_OLD_MATCH_TYPE, old_note=ICD10_OLD_NOTE,
        new_node=ICD10_NEW_NODE, new_note=ICD10_NEW_NOTE, to_decision=True,
    )
    changed_17, left_17 = _repoint(
        bind, classification="icd11", codes=ICD11_ROAD_TRAFFIC_CODES,
        old_node=ICD11_OLD_NODE, old_match_type=ICD11_OLD_MATCH_TYPE, old_note=ICD11_OLD_NOTE,
        new_node=ICD11_NEW_NODE, new_note=ICD11_NEW_NOTE, to_decision=True,
    )
    log.info(
        "Decision 16: %s ICD-10 rows moved to Road traffic, %s left. "
        "Decision 17: %s ICD-11 rows moved to Road traffic, %s left.",
        changed_16, left_16, changed_17, left_17,
    )

    inserted = _insert_vocab(bind)
    deactivated = _deactivate_vocab(bind)
    log.info("Stillbirth vocabulary: %s rows inserted, %s retired row deactivated.", inserted, deactivated)


def downgrade() -> None:
    bind = op.get_bind()

    reactivated = bind.execute(
        sa.text(
            f"UPDATE {VOCAB_TABLE} SET is_active = true WHERE term_id IN "
            f"(SELECT term_id FROM {VOCAB_DEACTIVATED_TABLE})"
        )
    ).rowcount
    bind.execute(sa.text(f"DROP TABLE {VOCAB_DEACTIVATED_TABLE}"))

    removed = bind.execute(
        sa.text(
            f"DELETE FROM {VOCAB_TABLE} WHERE term_id IN (SELECT term_id FROM {VOCAB_INSERTED_TABLE})"
        )
    ).rowcount
    bind.execute(sa.text(f"DROP TABLE {VOCAB_INSERTED_TABLE}"))
    log.info("Stillbirth vocabulary reverted: %s reactivated, %s removed.", reactivated, removed)

    changed_17, _ = _repoint(
        bind, classification="icd11", codes=ICD11_ROAD_TRAFFIC_CODES,
        old_node=ICD11_OLD_NODE, old_match_type=ICD11_OLD_MATCH_TYPE, old_note=ICD11_OLD_NOTE,
        new_node=ICD11_NEW_NODE, new_note=ICD11_NEW_NOTE, to_decision=False,
    )
    changed_16, _ = _repoint(
        bind, classification="icd10", codes=ICD10_ROAD_TRAFFIC_CODES,
        old_node=ICD10_OLD_NODE, old_match_type=ICD10_OLD_MATCH_TYPE, old_note=ICD10_OLD_NOTE,
        new_node=ICD10_NEW_NODE, new_note=ICD10_NEW_NOTE, to_decision=False,
    )
    log.info("Decision 16/17 reverted: %s ICD-10 rows, %s ICD-11 rows.", changed_16, changed_17)

    _set_selectability(V_Y85_NOT_SELECTABLE_CODES, to_selectable=True)
