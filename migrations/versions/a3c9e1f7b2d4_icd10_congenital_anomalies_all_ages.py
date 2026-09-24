"""Make ICD-10 congenital anomalies Q00-Q99 selectable at all ages.

Revision ID: a3c9e1f7b2d4
Revises: 33dea3ea3303
Create Date: 2026-09-24 21:00:00.000000

Owner decision (2026-09-24), docs/policy/icd10-to-icd11-transition.md
section 6: a congenital anomaly can cause death at any age. ICD-11 chapter
20 was drafted all ages, and the ICD-10 Q codes follow it so the two
classifications match. ICD-10 selectability is global, so this changes what
coders can select in every project.

Upgrade moves the selectable Q rows that are still neonate-only to all ages;
a rerun is a no-op and a row an admin set to anything else is left alone.
Downgrade puts the codes listed here back to neonate if they are still all
ages. The list is the 87 rows the reviewed WHO 2026 policy made neonate-only.
"""

import sqlalchemy as sa
from alembic import op

revision = "a3c9e1f7b2d4"
down_revision = "33dea3ea3303"
branch_labels = None
depends_on = None

Q_CODES = (
    "Q00", "Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q10", "Q11",
    "Q12", "Q13", "Q14", "Q15", "Q16", "Q17", "Q18", "Q20", "Q21", "Q22",
    "Q23", "Q24", "Q25", "Q26", "Q27", "Q28", "Q30", "Q31", "Q32", "Q33",
    "Q34", "Q35", "Q36", "Q37", "Q38", "Q39", "Q40", "Q41", "Q42", "Q43",
    "Q44", "Q45", "Q50", "Q51", "Q52", "Q53", "Q54", "Q55", "Q56", "Q60",
    "Q61", "Q62", "Q63", "Q64", "Q65", "Q66", "Q67", "Q68", "Q69", "Q70",
    "Q71", "Q72", "Q73", "Q74", "Q75", "Q76", "Q77", "Q78", "Q79", "Q80",
    "Q81", "Q82", "Q83", "Q84", "Q85", "Q86", "Q87", "Q89", "Q90", "Q91",
    "Q92", "Q93", "Q95", "Q96", "Q97", "Q98", "Q99",
)


def _set_age(from_age: str, to_age: str) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE mas_icd10_2019_2 SET age_group_selectable = :to_age, updated_at = now() "
            "WHERE code IN :codes AND is_coding_selectable IS TRUE "
            "AND age_group_selectable = :from_age"
        ).bindparams(sa.bindparam("codes", expanding=True)),
        {"codes": list(Q_CODES), "from_age": from_age, "to_age": to_age},
    )


def upgrade():
    _set_age("neonate", "all")


def downgrade():
    _set_age("all", "neonate")
