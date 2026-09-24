"""Apply the owner's ICD-10 decisions 10, 11 and 12 to WHO_2022_VA_2026.

Revision ID: fad35e5c4b79
Revises: dc762caa67dd
Create Date: 2026-09-24 18:30:00.000000

digitva-712.5. Policy: docs/policy/icd10-to-icd11-transition.md section 6.
WHO_2022_VA is not touched.

- 11: A80-A89 (viral CNS infections; the scheme has only the ten
  three-character rows) go from vas_01_99 to vas_01_07 Meningitis and
  encephalitis, matching ICD-11 1C80-1C8F.
- 12: the 65 "boarding or alighting" point codes whose WHO 10To11
  one-category target is an ICD-11 traffic code (PA0x) go from vas_12_02 to
  vas_12_01 Road traffic. V81.x and V82.x stay Other transport (13b); so do
  V15.3, V25.3 and V97.1, whose targets are not PA0x.
- 10: heart failure I50.0 and I50.9 go from vas_04_99 to vas_04_01 Acute
  cardiac, like I50 and I50.1 already, and like ICD-11 BD10/BD1Z.

The codes and values are embedded rather than read from
docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd-cod-2026-revision/WHO_2022_VA_2026_owner_decisions_overrides.csv
(the layer an admin reset applies), because docs/ is not in the image and a
later edit of that file must not change what this migration did. A test
keeps the two equal.

Upgrade changes a row only while it still holds the 2026 workbook value
(node and match type), so admin edits survive and a rerun is a no-op. Source
sheet, row and category are kept. Downgrade restores the workbook value for
rows that still hold the decision. mapping_version is bumped when a row
changed.
"""

import logging
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "fad35e5c4b79"
down_revision = "dc762caa67dd"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

SCHEME_CODE = "WHO_2022_VA_2026"
DECISION_MATCH_TYPE = "owner_decision"

BOARDING_ALIGHTING_CODES = (
    "V10.3", "V11.3", "V12.3", "V13.3", "V14.3", "V16.3", "V17.3", "V18.3",
    "V20.3", "V21.3", "V22.3", "V23.3", "V24.3", "V26.3", "V27.3", "V28.3",
    "V30.4", "V31.4", "V32.4", "V33.4", "V34.4", "V35.4", "V36.4", "V37.4", "V38.4",
    "V40.4", "V41.4", "V42.4", "V43.4", "V44.4", "V45.4", "V46.4", "V47.4", "V48.4",
    "V50.4", "V51.4", "V52.4", "V53.4", "V54.4", "V55.4", "V56.4", "V57.4", "V58.4",
    "V60.4", "V61.4", "V62.4", "V63.4", "V64.4", "V65.4", "V66.4", "V67.4", "V68.4",
    "V70.4", "V71.4", "V72.4", "V73.4", "V74.4", "V75.4", "V76.4", "V77.4", "V78.4",
    "V83.4", "V84.4", "V85.4", "V86.4",
)

# (codes, (workbook node, match type, note), (decision node, note))
DECISIONS = (
    (
        tuple(f"A{number}" for number in range(80, 90)),
        ("vas_01_99", "range", None),
        (
            "vas_01_07",
            "Owner decision 11 (2026-09-24): viral infections of the central nervous "
            "system go to Meningitis/encephalitis, matching ICD-11 1C80-1C8F (a DigitVA "
            "decision against WHO's ICD-10 column)",
        ),
    ),
    (
        BOARDING_ALIGHTING_CODES,
        (
            "vas_12_02",
            "transport_non_road",
            "Distinction vs VAs-12.01 depends on decimal-level transport codes and whether "
            "death was a road traffic accident.Requires detailed external-cause coding and "
            "road-traffic context.",
        ),
        (
            "vas_12_01",
            "Owner decision 12 (2026-09-24): person injured while boarding or alighting "
            "goes to Road traffic, matching WHO's ICD-10 to ICD-11 table (a PA0x traffic code)",
        ),
    ),
    (
        ("I50.0", "I50.9"),
        ("vas_04_99", "range", "Requires 4-character ICD in parts."),
        (
            "vas_04_01",
            "Owner decision 10 (2026-09-24): heart failure is Acute cardiac in both "
            "classifications (matches I50 override and WHO footnote c)",
        ),
    ),
)

SELECT_ROWS = sa.text(
    "SELECT m.mapping_id, m.icd_code, n.node_code, m.match_type FROM map_icd_cod_buckets m "
    "JOIN mas_cod_bucket_nodes n ON n.node_id = m.node_id "
    "WHERE m.scheme_id = :scheme AND m.icd_classification = 'icd10' AND m.age_scope IS NULL "
    "AND upper(m.icd_code) IN :codes"
).bindparams(sa.bindparam("codes", expanding=True))
UPDATE_ROW = sa.text(
    "UPDATE map_icd_cod_buckets SET node_id = :node_id, match_type = :match_type, "
    "mapping_note = :mapping_note, updated_at = :now WHERE mapping_id = :mapping_id"
)


def _apply(to_decision):
    """Move rows from the workbook value to the decision, or back."""
    bind = op.get_bind()
    scheme_id = bind.execute(
        sa.text("SELECT scheme_id FROM mas_cod_bucket_schemes WHERE scheme_code = :code"),
        {"code": SCHEME_CODE},
    ).scalar()
    if scheme_id is None:
        log.info("%s does not exist; no ICD-10 owner decisions applied.", SCHEME_CODE)
        return
    nodes = dict(
        bind.execute(
            sa.text(
                "SELECT node_code, node_id FROM mas_cod_bucket_nodes "
                "WHERE scheme_id = :scheme AND node_type = 'field' AND age_scope IS NULL"
            ),
            {"scheme": scheme_id},
        ).all()
    )
    now = datetime.now(UTC)
    updates = []
    left = 0
    for codes, (old_node, old_match_type, old_note), (new_node, new_note) in DECISIONS:
        if to_decision:
            source, target = (old_node, old_match_type), (new_node, DECISION_MATCH_TYPE, new_note)
        else:
            source, target = (new_node, DECISION_MATCH_TYPE), (old_node, old_match_type, old_note)
        if target[0] not in nodes:
            log.info("%s has no node %s; %s rows left.", SCHEME_CODE, target[0], len(codes))
            continue
        for row in bind.execute(SELECT_ROWS, {"scheme": scheme_id, "codes": list(codes)}):
            if (row.node_code, row.match_type) != source:
                left += (row.node_code, row.match_type) != target[:2]
                continue
            updates.append(
                {
                    "mapping_id": row.mapping_id,
                    "node_id": nodes[target[0]],
                    "match_type": target[1],
                    "mapping_note": target[2],
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
    log.info(
        "%s ICD-10 owner decisions %s: %s rows changed, %s admin-edited rows left.",
        SCHEME_CODE, "applied" if to_decision else "reverted", len(updates), left,
    )


def upgrade():
    _apply(to_decision=True)


def downgrade():
    _apply(to_decision=False)
