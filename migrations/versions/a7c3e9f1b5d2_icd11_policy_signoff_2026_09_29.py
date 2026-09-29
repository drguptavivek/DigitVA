"""Ship the signed-off ICD-11 coding-selectability policy (release 2026-01).

Revision ID: a7c3e9f1b5d2
Revises: d3a9c5e1f7b2
Create Date: 2026-09-29 15:00:00.000000

digitva-dus.3. Policy: docs/policy/who-2022-icd11-coding-allowability.md. The
owner signed off the draft on 2026-09-29. Until now only the dev database
held it (``flask icd11 policy-import``); every other database had all
mas_icd11_mms rows at is_coding_selectable NULL, so ICD-11 coding was
impossible there.

Semantics mirror the importer's full replacement for active categories: an
item in the frozen file gets is_coding_selectable true plus its sex, age
group and note; every other active category becomes not selectable with no
sex, age group or note. Unlike the importer, the migration also marks the
row policy_status 'reviewed' (ICD-10 precedent: d6e7f8a9b0c1), because the
policy is now signed off.

A row is touched only while it is still never reviewed (all five policy
fields NULL, policy_status 'unreviewed'), so an admin edit or a row already
imported on dev survives and a rerun is a no-op. Downgrade resets a row to
that state only while it still holds the migrated values.

The data is a frozen copy under resource/ (docs/ is not in the image and a
later regeneration of the draft must not change what this migration did; a
test keeps the copy byte-equal to the docs artifact). Regenerating the
policy after this point needs a new migration.
"""

import json
import logging
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "a7c3e9f1b5d2"
down_revision = "d3a9c5e1f7b2"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

RELEASE = "2026-01"
POLICY_PATH = Path("resource/icd11_mms_2026_01_policy_signoff_2026_09_29.json")

_NEVER_REVIEWED = (
    "m.is_coding_selectable IS NULL AND m.sex_selectable IS NULL "
    "AND m.age_group_selectable IS NULL AND m.restriction_note IS NULL "
    "AND m.policy_status = 'unreviewed'"
)
_ACTIVE_CATEGORY = "m.release = :release AND m.is_active IS TRUE AND m.class_kind = 'category'"

_ARRAYS = (
    sa.bindparam("uris", type_=sa.ARRAY(sa.Text())),
    sa.bindparam("sex", type_=sa.ARRAY(sa.Text())),
    sa.bindparam("age", type_=sa.ARRAY(sa.Text())),
    sa.bindparam("note", type_=sa.ARRAY(sa.Text())),
)
_FROM_ITEMS = (
    "FROM unnest(CAST(:uris AS text[]), CAST(:sex AS text[]), CAST(:age AS text[]), "
    "CAST(:note AS text[])) AS v(uri, sex, age, note)"
)

# Listed items -> migrated values.
_APPLY_LISTED = sa.text(
    "UPDATE mas_icd11_mms m SET is_coding_selectable = TRUE, sex_selectable = v.sex, "
    "age_group_selectable = v.age, restriction_note = v.note, policy_status = 'reviewed', "
    "updated_at = now() " + _FROM_ITEMS + " "
    f"WHERE m.linearization_uri = v.uri AND {_ACTIVE_CATEGORY} AND {_NEVER_REVIEWED}"
).bindparams(*_ARRAYS)
# Every other active category -> not selectable.
_APPLY_REST = sa.text(
    "UPDATE mas_icd11_mms m SET is_coding_selectable = FALSE, policy_status = 'reviewed', "
    f"updated_at = now() WHERE {_ACTIVE_CATEGORY} AND {_NEVER_REVIEWED} "
    "AND NOT (m.linearization_uri = ANY(CAST(:uris AS text[])))"
).bindparams(sa.bindparam("uris", type_=sa.ARRAY(sa.Text())))

_RESET = (
    "is_coding_selectable = NULL, sex_selectable = NULL, age_group_selectable = NULL, "
    "restriction_note = NULL, policy_status = 'unreviewed', updated_at = now()"
)
_REVERT_LISTED = sa.text(
    f"UPDATE mas_icd11_mms m SET {_RESET} " + _FROM_ITEMS + " "
    f"WHERE m.linearization_uri = v.uri AND {_ACTIVE_CATEGORY} "
    "AND m.policy_status = 'reviewed' AND m.is_coding_selectable IS TRUE "
    "AND m.sex_selectable IS NOT DISTINCT FROM v.sex "
    "AND m.age_group_selectable IS NOT DISTINCT FROM v.age "
    "AND m.restriction_note IS NOT DISTINCT FROM v.note"
).bindparams(*_ARRAYS)
_REVERT_REST = sa.text(
    f"UPDATE mas_icd11_mms m SET {_RESET} WHERE {_ACTIVE_CATEGORY} "
    "AND m.policy_status = 'reviewed' AND m.is_coding_selectable IS FALSE "
    "AND m.sex_selectable IS NULL AND m.age_group_selectable IS NULL "
    "AND m.restriction_note IS NULL "
    "AND NOT (m.linearization_uri = ANY(CAST(:uris AS text[])))"
).bindparams(sa.bindparam("uris", type_=sa.ARRAY(sa.Text())))


def _load_arrays() -> dict:
    path = Path(__file__).resolve().parents[2] / POLICY_PATH
    if not path.exists():
        raise ValueError(f"ICD-11 policy sign-off JSON not found: {path}")
    items = json.loads(path.read_text(encoding="utf-8"))["items"]
    if not all(item["is_coding_selectable"] is True for item in items):
        raise ValueError("Frozen ICD-11 policy must list only selectable items.")
    # Same normalisation as the importer: empty note -> NULL.
    return {
        "uris": [i["linearization_uri"] for i in items],
        "sex": [i["sex_selectable"] for i in items],
        "age": [i["age_group_selectable"] for i in items],
        "note": [(i["restriction_note"] or "").strip() or None for i in items],
    }


def _has_release(bind) -> bool:
    return bool(
        bind.execute(
            sa.text("SELECT 1 FROM mas_icd11_mms WHERE release = :release LIMIT 1"),
            {"release": RELEASE},
        ).scalar()
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_release(bind):
        log.info("mas_icd11_mms release %s absent; policy sign-off not applied.", RELEASE)
        return
    arrays = _load_arrays()
    # One statement per group, not per row: 16k listed + ~21k other rows.
    listed = bind.execute(_APPLY_LISTED, {"release": RELEASE, **arrays}).rowcount
    rest = bind.execute(_APPLY_REST, {"release": RELEASE, "uris": arrays["uris"]}).rowcount
    log.info(
        "ICD-11 policy sign-off applied: %s selectable, %s not selectable "
        "(%s items in file).", listed, rest, len(arrays["uris"]),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_release(bind):
        return
    arrays = _load_arrays()
    listed = bind.execute(_REVERT_LISTED, {"release": RELEASE, **arrays}).rowcount
    rest = bind.execute(_REVERT_REST, {"release": RELEASE, "uris": arrays["uris"]}).rowcount
    log.info("ICD-11 policy sign-off reverted: %s selectable, %s not selectable rows reset.",
             listed, rest)
