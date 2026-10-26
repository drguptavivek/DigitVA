"""ICD-11 2026-01: chapter 22 not selectable, KD3B.Z selectable (digitva-kmm2).

Revision ID: b8d4f2a6c1e9
Revises: c3f9a1d7e2b4
Create Date: 2026-10-27 12:00:00.000000

Policy: docs/policy/who-2022-icd11-coding-allowability.md rule 3 ("Changed
2026-10-26") and docs/policy/icd11-code-selection-principles.md principles 7
and 11. On mas_icd11_mms release 2026-01 categories:

- every chapter 22 category (injury nature) becomes not selectable as the
  final underlying cause; its sex, age group and note are kept;
- KD3B.Z becomes selectable, with the restriction its chapter 19 siblings
  KD3B.0 and KD3B.1 carry (both sexes, neonate or infant); the parent KD3B
  stays excluded; its bucket mapping (vas_11_02) is not touched;
- a leading "Draft: " is stripped from restriction_note (the policy is
  signed off).

A row changes only while it still holds the value a7c3e9f1b5d2 shipped
(chapter 22 selectable, KD3B.Z not selectable, note starting "Draft: "), so
an admin edit survives and an already-migrated row is left alone. The frozen sign-off JSON
that a7c3e9f1b5d2 reads is deliberately not edited: that migration reads it on
downgrade too, and a fresh database reaches the same rows by running both.

Recovery: the old and new values of every changed row go to
``_mig_b8d4f2a6c1e9_icd11_policy`` (kept after the upgrade; dropped by the
downgrade). Downgrade restores the old values of exactly those rows, and only
while a row still holds the value this migration wrote. Coded finals
(va_final_assessments) are not touched.
"""

import logging

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b8d4f2a6c1e9"
down_revision = "c3f9a1d7e2b4"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

AUDIT = "_mig_b8d4f2a6c1e9_icd11_policy"
RELEASE = "2026-01"
DRAFT_PREFIX = "Draft: "
# KD3B.0 and KD3B.1 carry this note (without the prefix) in the signed-off file.
KD3B_Z_NOTE = "chapter 19 (KA-KD), neonates and infants"

_CHAPTER_22 = "m.chapter_no = '22' AND m.is_coding_selectable IS TRUE"
_KD3B_Z = "m.code = 'KD3B.Z' AND m.is_coding_selectable IS FALSE"
_DRAFT_NOTE = "left(m.restriction_note, 7) = :prefix"

# Old and new values of every row one of the three rules hits, computed once;
# the UPDATE and the downgrade both read this table.
_RECORD = sa.text(
    f"INSERT INTO {AUDIT} (id, code, old_selectable, new_selectable, old_sex, new_sex, "
    "old_age, new_age, old_note, new_note) "
    "SELECT m.id, m.code, m.is_coding_selectable, "
    f"CASE WHEN {_CHAPTER_22} THEN FALSE WHEN {_KD3B_Z} THEN TRUE "
    "ELSE m.is_coding_selectable END, "
    f"m.sex_selectable, CASE WHEN {_KD3B_Z} THEN coalesce(m.sex_selectable, 'both') "
    "ELSE m.sex_selectable END, "
    f"m.age_group_selectable, CASE WHEN {_KD3B_Z} "
    "THEN coalesce(m.age_group_selectable, 'neonate_infant') ELSE m.age_group_selectable END, "
    f"m.restriction_note, CASE WHEN {_DRAFT_NOTE} THEN substr(m.restriction_note, 8) "
    f"WHEN {_KD3B_Z} THEN coalesce(m.restriction_note, :kd3bz_note) "
    "ELSE m.restriction_note END "
    "FROM mas_icd11_mms m WHERE m.release = :release AND m.class_kind = 'category' "
    f"AND (({_CHAPTER_22}) OR ({_KD3B_Z}) OR {_DRAFT_NOTE})"
)
_APPLY = sa.text(
    "UPDATE mas_icd11_mms m SET is_coding_selectable = a.new_selectable, "
    "sex_selectable = a.new_sex, age_group_selectable = a.new_age, "
    f"restriction_note = a.new_note, updated_at = now() FROM {AUDIT} a WHERE m.id = a.id"
)
_REVERT = sa.text(
    "UPDATE mas_icd11_mms m SET is_coding_selectable = a.old_selectable, "
    "sex_selectable = a.old_sex, age_group_selectable = a.old_age, "
    f"restriction_note = a.old_note, updated_at = now() FROM {AUDIT} a WHERE m.id = a.id "
    "AND m.is_coding_selectable IS NOT DISTINCT FROM a.new_selectable "
    "AND m.sex_selectable IS NOT DISTINCT FROM a.new_sex "
    "AND m.age_group_selectable IS NOT DISTINCT FROM a.new_age "
    "AND m.restriction_note IS NOT DISTINCT FROM a.new_note"
)


def upgrade() -> None:
    op.create_table(
        AUDIT,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(16)),
        sa.Column("old_selectable", sa.Boolean()),
        sa.Column("new_selectable", sa.Boolean()),
        sa.Column("old_sex", sa.String(16)),
        sa.Column("new_sex", sa.String(16)),
        sa.Column("old_age", sa.String(32)),
        sa.Column("new_age", sa.String(32)),
        sa.Column("old_note", sa.Text()),
        sa.Column("new_note", sa.Text()),
    )
    bind = op.get_bind()
    recorded = bind.execute(
        _RECORD, {"release": RELEASE, "prefix": DRAFT_PREFIX, "kd3bz_note": KD3B_Z_NOTE}
    ).rowcount
    bind.execute(_APPLY)
    log.info("ICD-11 %s chapter 22 / KD3B.Z / draft-note change applied to %s rows.",
             RELEASE, recorded)


def downgrade() -> None:
    restored = op.get_bind().execute(_REVERT).rowcount
    log.info("ICD-11 %s chapter 22 / KD3B.Z / draft-note change reverted on %s rows.",
             RELEASE, restored)
    op.drop_table(AUDIT)
