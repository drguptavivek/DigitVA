"""Withdraw ICD-10 symptom and sign codes R00-R94 (except R50, R54) from coding.

Revision ID: 1f037b4717e4
Revises: a7d3e9c5b2f1
Create Date: 2026-11-25 12:00:00.000000

Owner decision 2026-11-25, digitva-82l9. Policy:
docs/policy/who-2022-icd10-coding-allowability.md, "Symptom and sign codes
are withdrawn from coding". Every mas_icd10_2019_2 row in an R00-R94
three-character family -- the three-character code and any detailed subcode
an admin enabled, R10 included -- becomes not coding-selectable, so coding
search stops offering it and a save refuses it (both go through
``coding_policy_clause``). R50 and R54 and their subcodes, and R95-R99, are
not touched.

COD bucket rows (map_icd_cod_buckets) in every scheme are not touched, so a
death already coded with a withdrawn code keeps its bucket; saved final
assessments keep their code. Re-coding them is a separate decision.

Only the flag (and updated_at) changes, as owner decision 15 (a5f7c3d92b18)
did for V01-V89/Y85. Unlike decision 15, downgrade cannot simply re-enable
every listed row that is false: most detailed R subcodes were never
selectable. So upgrade records each row it changed in a capture table
(prior value is always true, so the code is enough), and downgrade re-enables
only captured rows still false, leaving a later admin edit alone. A rerun of
upgrade is a no-op.

The family list is embedded (generated once from the catalogue, 85 families:
the R00-R94 three-character codes that exist, minus R50 and R54), not read
from docs/, which is not in the image. Re-importing the released 2026 ICD-10
policy JSON
(docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd-cod-2026-revision/who_2022_icd10_2019_2_policy_reviewed.json)
would re-enable these codes and undo this decision.
"""

import logging

import sqlalchemy as sa
from alembic import op

revision = "1f037b4717e4"
down_revision = "a7d3e9c5b2f1"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

WITHDRAWN_FAMILIES = (
    "R00", "R01", "R02", "R03", "R04", "R05", "R06", "R07", "R09", "R10",
    "R11", "R12", "R13", "R14", "R15", "R16", "R17", "R18", "R19", "R20",
    "R21", "R22", "R23", "R25", "R26", "R27", "R29", "R30", "R31", "R32",
    "R33", "R34", "R35", "R36", "R39", "R40", "R41", "R42", "R43", "R44",
    "R45", "R46", "R47", "R48", "R49", "R51", "R52", "R53", "R55", "R56",
    "R57", "R58", "R59", "R60", "R61", "R62", "R63", "R64", "R65", "R68",
    "R69", "R70", "R71", "R72", "R73", "R74", "R75", "R76", "R77", "R78",
    "R79", "R80", "R81", "R82", "R83", "R84", "R85", "R86", "R87", "R89",
    "R90", "R91", "R92", "R93", "R94",
)

CAPTURE_TABLE = "_mig_1f037b4717e4_withdrawn"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(f"CREATE TABLE IF NOT EXISTS {CAPTURE_TABLE} (code varchar(16) PRIMARY KEY)"))
    withdrawn = bind.execute(
        sa.text(
            "WITH changed AS ("
            "UPDATE mas_icd10_2019_2 SET is_coding_selectable = false, updated_at = now() "
            "WHERE three_character_code IN :families AND is_coding_selectable IS TRUE "
            "RETURNING code) "
            f"INSERT INTO {CAPTURE_TABLE} (code) SELECT code FROM changed ON CONFLICT DO NOTHING"
        ).bindparams(sa.bindparam("families", expanding=True)),
        {"families": list(WITHDRAWN_FAMILIES)},
    ).rowcount
    log.info("digitva-82l9: %s ICD-10 R00-R94 rows set is_coding_selectable=false.", withdrawn)


def downgrade() -> None:
    bind = op.get_bind()
    restored = bind.execute(
        sa.text(
            "UPDATE mas_icd10_2019_2 SET is_coding_selectable = true, updated_at = now() "
            f"WHERE code IN (SELECT code FROM {CAPTURE_TABLE}) AND is_coding_selectable IS FALSE"
        )
    ).rowcount
    bind.execute(sa.text(f"DROP TABLE {CAPTURE_TABLE}"))
    log.info("digitva-82l9 reverted: %s ICD-10 R00-R94 rows set is_coding_selectable=true.", restored)
