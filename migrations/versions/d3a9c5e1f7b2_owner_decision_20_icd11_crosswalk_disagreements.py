"""Owner decision 20 (ICD-11 crosswalk disagreements) for WHO_2022_VA_2026.

Revision ID: d3a9c5e1f7b2
Revises: b1f4d8a6c9e2
Create Date: 2026-09-29 12:00:00.000000

digitva-712.6. Policy: docs/policy/icd10-to-icd11-transition.md section 6
(decision 20). Seven ICD-11 rows of WHO_2022_VA_2026 change bucket:

- 1D64 (MERS): Haemorrhagic fever (vas_01_11) -> Acute respiratory
  infection (vas_01_02); the ICD-10 crosswalk (J12.9) agrees.
- PA92: Accidental drowning (vas_12_04) -> Accidental fall (vas_12_03);
  the title excludes drowning and ICD-10 W16 is in W00-W19.
- PA08, PA0A, PA0B, PA0C, PA0D: Road traffic (vas_12_01) -> Other
  transport (vas_12_02), by decisions 13b and 16 (streetcar/rail and
  V83-V86 are nontraffic; PA2A-PA2D are Other transport under decision 17).

Four more decided codes (1C8C, 8B22.40, KD3B.1, PA15) already sit in the
decided bucket, so their node is unchanged. Fresh seeds label them
owner_decision, but existing databases still hold the generated match_type
(range or split), and the public mapping page shows provenance from
match_type; so they are stamped owner_decision with the decision note too.

The code list is embedded rather than read from
docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_icd11_owner_decisions.csv
because docs/ is not in the image and a later edit of that file must not
change what this migration did. Tests keep the two equal.

A row changes only while it still holds the generated value (node, match_type),
so an admin edit survives and a rerun is a no-op. Downgrade restores the
generated value only for rows still holding the decision value. The
mapping_version bump happens only when a row changed.
"""

import logging
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "d3a9c5e1f7b2"
down_revision = "b1f4d8a6c9e2"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

SCHEME_CODE = "WHO_2022_VA_2026"
DECISION_MATCH_TYPE = "owner_decision"

_NOTE_1D64 = (
    "Owner decision 20 (2026-09-29): MERS is a respiratory infection -> Acute "
    "respiratory infection; the ICD-10 crosswalk (J12.9) agrees"
)
_NOTE_PA92 = (
    "Owner decision 20 (2026-09-29): Injury other than drowning following fall into "
    "water -> Accidental fall; the title excludes drowning and ICD-10 W16 is in W00-W19"
)
_NOTE_PA08 = (
    "Owner decision 20 (2026-09-29): Streetcar or tram occupant -> Other transport: "
    "decision 13b (rail and streetcar are not road traffic)"
)
_NOTE_PA0X = (
    "Owner decision 20 (2026-09-29): {} -> Other transport: decision 16 (ICD-10 "
    "V83-V86 are nontraffic; ICD-11 PA2A-PA2D are Other transport under decision 17)"
)

_NOTE_1C8C = (
    "Owner decision 20 (2026-09-29): Venezuelan equine encephalitis -> "
    "Meningitis/encephalitis, matching ICD-11 1C80-1C8F and decision 11"
)
_NOTE_8B22 = (
    "Owner decision 20 (2026-09-29): Arteriovenous malformation of cerebral vessels "
    "-> Stroke, as the ICD-11 range 8B00-8B23"
)
_NOTE_KD3B1 = (
    "Owner decision 20 (2026-09-29): Intrapartum fetal death -> Fresh stillbirth "
    "(unlike ICD-10 P95, which is one code)"
)
_NOTE_PA15 = (
    "Owner decision 20 (2026-09-29): Nontraffic bus or coach occupant -> Other "
    "transport: ICD-11 says explicitly nontraffic (ICD-10 V79); decisions 16 and 17 "
    "cover only codes unspecified as to traffic"
)

# code -> (old_node, old_match_type, old_note, new_node, new_note)
CHANGES = {
    "1D64": ("vas_01_11", "range", "ICD-11 2026-01 range 1D60-1D6Z", "vas_01_02", _NOTE_1D64),
    "PA92": ("vas_12_04", "range", "ICD-11 2026-01 range PA90-PA9Z", "vas_12_03", _NOTE_PA92),
    "PA08": ("vas_12_01", "split", "ICD-11 2026-01 range PA00-PA5Z", "vas_12_02", _NOTE_PA08),
    "PA0A": ("vas_12_01", "split", "ICD-11 2026-01 range PA00-PA5Z", "vas_12_02",
             _NOTE_PA0X.format("Agricultural special vehicle")),
    "PA0B": ("vas_12_01", "split", "ICD-11 2026-01 range PA00-PA5Z", "vas_12_02",
             _NOTE_PA0X.format("Industrial-premises special vehicle")),
    "PA0C": ("vas_12_01", "split", "ICD-11 2026-01 range PA00-PA5Z", "vas_12_02",
             _NOTE_PA0X.format("Construction special vehicle")),
    "PA0D": ("vas_12_01", "split", "ICD-11 2026-01 range PA00-PA5Z", "vas_12_02",
             _NOTE_PA0X.format("All-terrain vehicle")),
    # node unchanged: only match_type and note are stamped
    "1C8C": ("vas_01_07", "range", "ICD-11 2026-01 range 1C80-1C8F", "vas_01_07", _NOTE_1C8C),
    "8B22.40": ("vas_04_02", "range", "ICD-11 2026-01 range 8B00-8B23", "vas_04_02", _NOTE_8B22),
    "KD3B.1": ("vas_11_01", "range", "ICD-11 2026-01 range KD3B.1", "vas_11_01", _NOTE_KD3B1),
    "PA15": ("vas_12_02", "split", "ICD-11 2026-01 range PA00-PA5Z", "vas_12_02", _NOTE_PA15),
}

SELECT_ROWS = sa.text(
    "SELECT m.mapping_id, m.icd_code, n.node_code, m.match_type FROM map_icd_cod_buckets m "
    "JOIN mas_cod_bucket_nodes n ON n.node_id = m.node_id "
    "WHERE m.scheme_id = :scheme AND m.icd_classification = 'icd11' AND m.age_scope IS NULL "
    "AND upper(m.icd_code) IN :codes"
).bindparams(sa.bindparam("codes", expanding=True))
UPDATE_ROW = sa.text(
    "UPDATE map_icd_cod_buckets SET node_id = :node_id, match_type = :match_type, "
    "mapping_note = :mapping_note, updated_at = :now WHERE mapping_id = :mapping_id"
)


def _repoint(to_decision: bool) -> int:
    bind = op.get_bind()
    scheme_id = bind.execute(
        sa.text("SELECT scheme_id FROM mas_cod_bucket_schemes WHERE scheme_code = :code"),
        {"code": SCHEME_CODE},
    ).scalar()
    if scheme_id is None:
        log.info("%s does not exist; owner decision 20 not applied.", SCHEME_CODE)
        return 0
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
    for row in bind.execute(SELECT_ROWS, {"scheme": scheme_id, "codes": list(CHANGES)}):
        old_node, old_match, old_note, new_node, new_note = CHANGES[row.icd_code.upper()]
        if to_decision:
            source, target = (old_node, old_match), (new_node, DECISION_MATCH_TYPE, new_note)
        else:
            source, target = (new_node, DECISION_MATCH_TYPE), (old_node, old_match, old_note)
        if (row.node_code, row.match_type) != source or target[0] not in nodes:
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
    log.info("Owner decision 20 %s: %s of %s ICD-11 rows changed.",
             "applied" if to_decision else "reverted", len(updates), len(CHANGES))
    return len(updates)


def upgrade() -> None:
    _repoint(to_decision=True)


def downgrade() -> None:
    _repoint(to_decision=False)
