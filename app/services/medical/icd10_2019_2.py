from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from decimal import Decimal

import sqlalchemy as sa

from app import db
from app.models import MasIcd1020192, VaSubmissions

DEFAULT_ICD10_2019_2_CSV_PATH = Path(
    "docs/icd-causegrp-mappings/generated/icd10_2019_hierarchy.csv"
)
SOURCE_VERSION = "ICD-10-2019"
SEX_SELECTABLE_OPTIONS = ("both", "female", "male")
AGE_GROUP_SELECTABLE_OPTIONS = ("all", "adult", "child", "neonate")
POLICY_EDITABLE_LEVELS = frozenset({"three_character", "detailed_code"})
_THREE_CHARACTER_STUZ_EXCEPTION_RE = re.compile(r"^[STUZ]\d{2}$")
_CODING_ICD_MIN_QUERY_LEN = 2
_CODING_ICD_MAX_RESULTS = 30
_DAYS_PER_YEAR = Decimal("365.25")


@dataclass(frozen=True)
class Icd1020192ImportResult:
    inserted: int
    updated: int
    deactivated: int
    total_rows: int


@dataclass(frozen=True)
class Icd1020192PolicyUpdate:
    is_coding_selectable: bool | None
    sex_selectable: str | None
    age_group_selectable: str | None
    restriction_note: str | None


@dataclass(frozen=True)
class Icd1020192PolicyImportResult:
    total_items: int
    updated_items: int
    reset_items: int
    skipped_items: list[dict[str, str]]


def _parse_bool(value: str) -> bool | None:
    normalized = (value or "").strip().lower()
    if not normalized:
        return None
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def _optional_text(value: str) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _is_default_selectable_three_character(code: str, semantic_level: str) -> bool:
    if semantic_level != "three_character":
        return False
    normalized_code = (code or "").strip().upper()
    return not _THREE_CHARACTER_STUZ_EXCEPTION_RE.match(normalized_code)


def _serialize_row(row: MasIcd1020192, *, child_count: int | None = None) -> dict:
    return {
        "code": row.code,
        "title": row.title,
        "node_type": row.node_type,
        "semantic_level": row.semantic_level,
        "sort_order": row.sort_order,
        "parent_code": row.parent_code,
        "chapter_code": row.chapter_code,
        "chapter_title": row.chapter_title,
        "block_code": row.block_code,
        "block_title": row.block_title,
        "three_character_code": row.three_character_code,
        "three_character_title": row.three_character_title,
        "has_children": row.has_children,
        "child_count": child_count,
        "is_leaf": row.is_leaf,
        "is_three_character_code": row.is_three_character_code,
        "is_detailed_code": row.is_detailed_code,
        "is_coding_selectable": row.is_coding_selectable,
        "sex_selectable": row.sex_selectable,
        "age_group_selectable": row.age_group_selectable,
        "restriction_note": row.restriction_note,
        "is_policy_editable": row.semantic_level in POLICY_EDITABLE_LEVELS,
        "is_active": row.is_active,
    }


def _normalize_query(raw_query: str) -> str:
    return " ".join((raw_query or "").strip().lower().split())


def _coding_age_group_for_submission(submission: VaSubmissions | None) -> str | None:
    if submission is None:
        return None
    normalized_days = submission.va_deceased_age_normalized_days
    if normalized_days is not None:
        if normalized_days <= Decimal("28"):
            return "neonate"
        if normalized_days < (Decimal("15") * _DAYS_PER_YEAR):
            return "child"
        return "adult"

    legacy_age = submission.va_deceased_age
    if legacy_age is None:
        return None
    if legacy_age < 15:
        return "child"
    return "adult"


def _coding_sex_for_submission(submission: VaSubmissions | None) -> str | None:
    if submission is None:
        return None
    normalized = (submission.va_deceased_gender or "").strip().lower()
    if normalized in {"male", "female"}:
        return normalized
    return None


def _coding_policy_clause(model, *, age_group: str | None, sex: str | None):
    clause = model.is_coding_selectable.is_(True)
    if age_group:
        clause = sa.and_(
            clause,
            sa.or_(
                model.age_group_selectable == "all",
                model.age_group_selectable == age_group,
            ),
        )
    if sex:
        clause = sa.and_(
            clause,
            sa.or_(
                model.sex_selectable == "both",
                model.sex_selectable == sex,
            ),
        )
    return clause


def _apply_code_filters(query, model, *, coding_filter: str, sex_filter: str, age_filter: str):
    if coding_filter == "active":
        query = query.where(model.is_coding_selectable.is_(True))
    elif coding_filter == "disabled":
        query = query.where(
            sa.or_(model.is_coding_selectable.is_(False), model.is_coding_selectable.is_(None))
        )
    if sex_filter != "any":
        query = query.where(model.sex_selectable == sex_filter)
    if age_filter != "any":
        query = query.where(model.age_group_selectable == age_filter)
    return query


def _code_filter_clause(
    model,
    *,
    coding_filter: str,
    sex_filter: str,
    age_filter: str,
):
    clause = sa.true()
    if coding_filter == "active":
        clause = sa.and_(clause, model.is_coding_selectable.is_(True))
    elif coding_filter == "disabled":
        clause = sa.and_(
            clause,
            sa.or_(model.is_coding_selectable.is_(False), model.is_coding_selectable.is_(None)),
        )
    if sex_filter != "any":
        clause = sa.and_(clause, model.sex_selectable == sex_filter)
    if age_filter != "any":
        clause = sa.and_(clause, model.age_group_selectable == age_filter)
    return clause


def _status_indicator_for_row(
    row: MasIcd1020192,
    *,
    direct_three_character_total: int | None = None,
    direct_three_character_selectable: int | None = None,
) -> str | None:
    if row.semantic_level in {"three_character", "detailed_code"}:
        return "green" if row.is_coding_selectable else "red"
    if row.semantic_level == "block":
        total = int(direct_three_character_total or 0)
        selectable = int(direct_three_character_selectable or 0)
        if total <= 0 or selectable <= 0:
            return "red"
        if selectable >= total:
            return "green"
        return "yellow"
    return None


def _validate_policy_update(
    *,
    is_coding_selectable,
    sex_selectable,
    age_group_selectable,
    restriction_note,
) -> Icd1020192PolicyUpdate:
    if is_coding_selectable not in (True, False, None):
        raise ValueError("is_coding_selectable must be true, false, or null.")
    if sex_selectable not in (*SEX_SELECTABLE_OPTIONS, None):
        raise ValueError("sex_selectable must be one of both, female, male, or null.")
    if age_group_selectable not in (*AGE_GROUP_SELECTABLE_OPTIONS, None):
        raise ValueError("age_group_selectable must be one of all, adult, child, neonate, or null.")
    if restriction_note is not None and not isinstance(restriction_note, str):
        raise ValueError("restriction_note must be a string or null.")
    return Icd1020192PolicyUpdate(
        is_coding_selectable=is_coding_selectable,
        sex_selectable=sex_selectable,
        age_group_selectable=age_group_selectable,
        restriction_note=_optional_text(restriction_note or ""),
    )


def _load_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise ValueError(f"ICD CSV not found: {csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise ValueError(f"ICD CSV is empty: {csv_path}")

    seen_codes: set[str] = set()
    for row in rows:
        code = (row.get("code") or "").strip()
        if not code:
            raise ValueError("ICD CSV contains a row with empty code")
        if code in seen_codes:
            raise ValueError(f"ICD CSV contains duplicate code: {code}")
        seen_codes.add(code)

    return rows


def import_icd10_2019_2_from_csv(
    csv_path: str | Path = DEFAULT_ICD10_2019_2_CSV_PATH,
    *,
    apply_policy_columns: bool = False,
) -> Icd1020192ImportResult:
    csv_path = Path(csv_path)
    rows = _load_csv_rows(csv_path)
    existing_rows = {
        row.code: row
        for row in db.session.scalars(
            sa.select(MasIcd1020192)
        ).all()
    }

    inserted = 0
    updated = 0
    seen_codes: set[str] = set()

    for sort_order, row in enumerate(rows, start=1):
        code = row["code"].strip()
        seen_codes.add(code)
        record = existing_rows.get(code)
        is_new = record is None
        if is_new:
            record = MasIcd1020192(code=code)
            db.session.add(record)
            inserted += 1
        else:
            updated += 1

        record.title = row["title"].strip()
        record.node_type = row["node_type"].strip()
        record.semantic_level = row["semantic_level"].strip()
        record.sort_order = sort_order
        record.parent_code = _optional_text(row.get("parent_code", ""))
        record.chapter_code = _optional_text(row.get("chapter_code", ""))
        record.chapter_title = _optional_text(row.get("chapter_title", ""))
        record.block_code = _optional_text(row.get("block_code", ""))
        record.block_title = _optional_text(row.get("block_title", ""))
        record.three_character_code = _optional_text(row.get("three_character_code", ""))
        record.three_character_title = _optional_text(row.get("three_character_title", ""))
        record.has_children = bool(_parse_bool(row.get("has_children", "")))
        record.is_leaf = bool(_parse_bool(row.get("is_leaf", "")))
        record.is_three_character_code = bool(
            _parse_bool(row.get("is_three_character_code", ""))
        )
        record.is_detailed_code = bool(_parse_bool(row.get("is_detailed_code", "")))
        record.source_version = SOURCE_VERSION
        record.source_path = str(csv_path)
        record.is_active = True

        if is_new or apply_policy_columns:
            record.is_coding_selectable = _parse_bool(row.get("is_coding_selectable", ""))
            record.sex_selectable = _optional_text(row.get("sex_selectable", ""))
            record.age_group_selectable = _optional_text(row.get("age_group_selectable", ""))
            record.policy_status = row.get("policy_status", "").strip() or "unreviewed"
            record.restriction_note = _optional_text(row.get("restriction_note", ""))

        if (
            is_new
            and _is_default_selectable_three_character(
                code=record.code,
                semantic_level=record.semantic_level,
            )
        ):
            if record.is_coding_selectable is None:
                record.is_coding_selectable = True
            if record.sex_selectable is None:
                record.sex_selectable = "both"
            if record.age_group_selectable is None:
                record.age_group_selectable = "all"

    deactivated = 0
    for code, record in existing_rows.items():
        if code in seen_codes or not record.is_active:
            continue
        record.is_active = False
        deactivated += 1

    db.session.commit()
    return Icd1020192ImportResult(
        inserted=inserted,
        updated=updated,
        deactivated=deactivated,
        total_rows=len(rows),
    )


def get_icd10_2019_2_stats() -> dict[str, int]:
    rows = db.session.execute(
        sa.select(
            sa.func.count().label("total_rows"),
            sa.func.count().filter(MasIcd1020192.is_active.is_(True)).label("active_rows"),
            sa.func.count().filter(MasIcd1020192.semantic_level == "chapter").label("chapters"),
            sa.func.count().filter(MasIcd1020192.semantic_level == "block").label("blocks"),
            sa.func.count()
            .filter(MasIcd1020192.semantic_level == "three_character")
            .label("three_character_rows"),
            sa.func.count()
            .filter(MasIcd1020192.semantic_level == "detailed_code")
            .label("detailed_rows"),
        )
    ).mappings().one()
    return {key: int(value or 0) for key, value in rows.items()}


def list_icd10_2019_2_children(
    parent_code: str | None = None,
    *,
    coding_filter: str = "any",
    sex_filter: str = "any",
    age_filter: str = "any",
) -> list[dict]:
    child_count_sq = (
        sa.select(
            MasIcd1020192.parent_code.label("parent_code"),
            sa.func.count().label("child_count"),
        )
        .where(MasIcd1020192.is_active.is_(True))
        .group_by(MasIcd1020192.parent_code)
        .subquery()
    )
    block_status_sq = (
        sa.select(
            MasIcd1020192.parent_code.label("block_code"),
            sa.func.count().label("direct_three_character_total"),
            sa.func.count()
            .filter(MasIcd1020192.is_coding_selectable.is_(True))
            .label("direct_three_character_selectable"),
        )
        .where(
            MasIcd1020192.is_active.is_(True),
            MasIcd1020192.semantic_level == "three_character",
        )
        .group_by(MasIcd1020192.parent_code)
        .subquery()
    )
    filtered_three_character_sq = _apply_code_filters(
        sa.select(
            MasIcd1020192.code,
            MasIcd1020192.parent_code,
        ).where(
            MasIcd1020192.is_active.is_(True),
            MasIcd1020192.semantic_level == "three_character",
        ),
        MasIcd1020192,
        coding_filter=coding_filter,
        sex_filter=sex_filter,
        age_filter=age_filter,
    ).subquery()
    chapter_filtered_child_count_sq = (
        sa.select(
            MasIcd1020192.parent_code.label("chapter_code"),
            sa.func.count(sa.distinct(MasIcd1020192.code)).label("filtered_child_count"),
        )
        .join(
            filtered_three_character_sq,
            filtered_three_character_sq.c.parent_code == MasIcd1020192.code,
        )
        .where(
            MasIcd1020192.is_active.is_(True),
            MasIcd1020192.semantic_level == "block",
        )
        .group_by(MasIcd1020192.parent_code)
        .subquery()
    )
    block_filtered_child_count_sq = (
        sa.select(
            filtered_three_character_sq.c.parent_code.label("block_code"),
            sa.func.count().label("filtered_child_count"),
        )
        .group_by(filtered_three_character_sq.c.parent_code)
        .subquery()
    )
    filtered_detailed_sq = _apply_code_filters(
        sa.select(
            MasIcd1020192.code,
            MasIcd1020192.parent_code,
        ).where(
            MasIcd1020192.is_active.is_(True),
            MasIcd1020192.semantic_level == "detailed_code",
        ),
        MasIcd1020192,
        coding_filter=coding_filter,
        sex_filter=sex_filter,
        age_filter=age_filter,
    ).subquery()
    three_character_filtered_child_count_sq = (
        sa.select(
            filtered_detailed_sq.c.parent_code.label("three_character_code"),
            sa.func.count().label("filtered_child_count"),
        )
        .group_by(filtered_detailed_sq.c.parent_code)
        .subquery()
    )

    query = (
        sa.select(
            MasIcd1020192,
            child_count_sq.c.child_count,
            block_status_sq.c.direct_three_character_total,
            block_status_sq.c.direct_three_character_selectable,
            chapter_filtered_child_count_sq.c.filtered_child_count.label(
                "chapter_filtered_child_count"
            ),
            block_filtered_child_count_sq.c.filtered_child_count.label(
                "block_filtered_child_count"
            ),
            three_character_filtered_child_count_sq.c.filtered_child_count.label(
                "three_character_filtered_child_count"
            ),
        )
        .outerjoin(child_count_sq, child_count_sq.c.parent_code == MasIcd1020192.code)
        .outerjoin(block_status_sq, block_status_sq.c.block_code == MasIcd1020192.code)
        .outerjoin(
            chapter_filtered_child_count_sq,
            chapter_filtered_child_count_sq.c.chapter_code == MasIcd1020192.code,
        )
        .outerjoin(
            block_filtered_child_count_sq,
            block_filtered_child_count_sq.c.block_code == MasIcd1020192.code,
        )
        .outerjoin(
            three_character_filtered_child_count_sq,
            three_character_filtered_child_count_sq.c.three_character_code
            == MasIcd1020192.code,
        )
        .where(MasIcd1020192.is_active.is_(True))
        .order_by(MasIcd1020192.sort_order, MasIcd1020192.code)
    )
    if parent_code is None:
        query = query.where(MasIcd1020192.parent_code.is_(None))
    else:
        query = query.where(MasIcd1020192.parent_code == parent_code)
        parent = db.session.get(MasIcd1020192, parent_code)
        if parent is not None:
            if parent.semantic_level == "block":
                query = query.where(
                    sa.or_(
                        MasIcd1020192.semantic_level == "block",
                        _code_filter_clause(
                            MasIcd1020192,
                            coding_filter=coding_filter,
                            sex_filter=sex_filter,
                            age_filter=age_filter,
                        ),
                    )
                )
            elif parent.semantic_level == "three_character":
                query = _apply_code_filters(
                    query,
                    MasIcd1020192,
                    coding_filter=coding_filter,
                    sex_filter=sex_filter,
                    age_filter=age_filter,
                )

    rows = db.session.execute(query).all()
    payload = []
    for (
        row,
        child_count,
        direct_total,
        direct_selectable,
        chapter_filtered_child_count,
        block_filtered_child_count,
        three_character_filtered_child_count,
    ) in rows:
        effective_child_count = int(child_count or 0)
        if parent_code is None:
            effective_child_count = int(chapter_filtered_child_count or 0)
        elif row.semantic_level == "block":
            effective_child_count = int(block_filtered_child_count or 0)
        elif row.semantic_level == "three_character":
            effective_child_count = int(three_character_filtered_child_count or 0)
        item = _serialize_row(row, child_count=effective_child_count)
        item["status_indicator"] = _status_indicator_for_row(
            row,
            direct_three_character_total=direct_total,
            direct_three_character_selectable=direct_selectable,
        )
        payload.append(item)
    return payload


def get_icd10_2019_2_node_details(code: str) -> dict | None:
    child_count = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(MasIcd1020192)
        .where(
            MasIcd1020192.parent_code == code,
            MasIcd1020192.is_active.is_(True),
        )
    ) or 0
    row = db.session.get(MasIcd1020192, code)
    if row is None or not row.is_active:
        return None

    ancestors: list[dict[str, str]] = []
    current_code = row.parent_code
    while current_code:
        ancestor = db.session.get(MasIcd1020192, current_code)
        if ancestor is None or not ancestor.is_active:
            break
        ancestors.append(
            {
                "code": ancestor.code,
                "title": ancestor.title,
                "semantic_level": ancestor.semantic_level,
            }
        )
        current_code = ancestor.parent_code
    ancestors.reverse()

    payload = _serialize_row(row, child_count=int(child_count))
    payload["status_indicator"] = _status_indicator_for_row(row)
    payload["ancestors"] = ancestors
    return payload


def get_icd10_2019_2_policy_options() -> dict[str, list[str]]:
    return {
        "sex_selectable": list(SEX_SELECTABLE_OPTIONS),
        "age_group_selectable": list(AGE_GROUP_SELECTABLE_OPTIONS),
    }


def update_icd10_2019_2_policy(
    code: str,
    *,
    is_coding_selectable,
    sex_selectable,
    age_group_selectable,
    restriction_note,
) -> dict:
    row = db.session.get(MasIcd1020192, code)
    if row is None or not row.is_active:
        raise LookupError(f"ICD code not found: {code}")
    if row.semantic_level not in POLICY_EDITABLE_LEVELS:
        raise ValueError(
            "Policy fields are only editable for three-character and detailed ICD codes."
        )

    update = _validate_policy_update(
        is_coding_selectable=is_coding_selectable,
        sex_selectable=sex_selectable,
        age_group_selectable=age_group_selectable,
        restriction_note=restriction_note,
    )
    row.is_coding_selectable = update.is_coding_selectable
    row.sex_selectable = update.sex_selectable
    row.age_group_selectable = update.age_group_selectable
    row.restriction_note = update.restriction_note
    db.session.commit()
    return get_icd10_2019_2_node_details(code) or _serialize_row(row)


def export_icd10_2019_2_policy_json() -> dict:
    rows = db.session.scalars(
        sa.select(MasIcd1020192)
        .where(
            MasIcd1020192.is_active.is_(True),
            MasIcd1020192.semantic_level.in_(tuple(POLICY_EDITABLE_LEVELS)),
            sa.or_(
                MasIcd1020192.is_coding_selectable.is_not(None),
                MasIcd1020192.sex_selectable.is_not(None),
                MasIcd1020192.age_group_selectable.is_not(None),
            ),
        )
        .order_by(MasIcd1020192.sort_order, MasIcd1020192.code)
    ).all()

    items = [
        {
            "code": row.code,
            "title": row.title,
            "semantic_level": row.semantic_level,
            "chapter_code": row.chapter_code,
            "chapter_title": row.chapter_title,
            "block_code": row.block_code,
            "block_title": row.block_title,
            "three_character_code": row.three_character_code,
            "three_character_title": row.three_character_title,
            "is_coding_selectable": row.is_coding_selectable,
            "sex_selectable": row.sex_selectable,
            "age_group_selectable": row.age_group_selectable,
        }
        for row in rows
    ]
    return {
        "source_version": SOURCE_VERSION,
        "row_count": len(items),
        "items": items,
    }


def get_icd10_2019_2_coding_context(va_sid: str) -> dict | None:
    submission = db.session.get(VaSubmissions, va_sid)
    if submission is None:
        return None
    return {
        "va_sid": submission.va_sid,
        "age_group": _coding_age_group_for_submission(submission),
        "sex": _coding_sex_for_submission(submission),
    }


def search_icd10_2019_2_coding_choices(va_sid: str, query: str) -> list[dict[str, str | bool | None]]:
    normalized_query = _normalize_query(query)
    if len(normalized_query) < _CODING_ICD_MIN_QUERY_LEN:
        return []

    context = get_icd10_2019_2_coding_context(va_sid)
    if context is None:
        raise LookupError(f"Submission not found: {va_sid}")

    like_query = f"%{normalized_query}%"
    code_prefix = f"{normalized_query}%"
    lower_code = sa.func.lower(MasIcd1020192.code)
    lower_title = sa.func.lower(MasIcd1020192.title)
    display_expr = sa.func.concat(MasIcd1020192.code, sa.literal(" "), MasIcd1020192.title)

    rank_expr = sa.case(
        (lower_code == normalized_query, 0),
        (lower_code.like(code_prefix), 1),
        (lower_title.like(code_prefix), 2),
        (lower_title.like(like_query), 3),
        else_=4,
    )

    rows = db.session.scalars(
        sa.select(MasIcd1020192)
        .where(
            MasIcd1020192.is_active.is_(True),
            MasIcd1020192.semantic_level.in_(tuple(POLICY_EDITABLE_LEVELS)),
            _coding_policy_clause(
                MasIcd1020192,
                age_group=context["age_group"],
                sex=context["sex"],
            ),
            sa.or_(
                lower_code.like(like_query),
                lower_title.like(like_query),
                sa.func.lower(display_expr).like(like_query),
            ),
        )
        .order_by(rank_expr, MasIcd1020192.sort_order, MasIcd1020192.code)
        .limit(_CODING_ICD_MAX_RESULTS)
    ).all()

    return [
        {
            "icd_code": row.code,
            "icd_to_display": f"{row.code} {row.title}",
            "title": row.title,
            "semantic_level": row.semantic_level,
            "is_detailed_code": row.is_detailed_code,
            "three_character_code": row.three_character_code,
        }
        for row in rows
    ]


def list_icd10_2019_2_coding_detailed_children(
    va_sid: str, parent_code: str
) -> list[dict[str, str | bool | None]]:
    context = get_icd10_2019_2_coding_context(va_sid)
    if context is None:
        raise LookupError(f"Submission not found: {va_sid}")

    rows = db.session.scalars(
        sa.select(MasIcd1020192)
        .where(
            MasIcd1020192.is_active.is_(True),
            MasIcd1020192.parent_code == parent_code,
            MasIcd1020192.semantic_level == "detailed_code",
            _coding_policy_clause(
                MasIcd1020192,
                age_group=context["age_group"],
                sex=context["sex"],
            ),
        )
        .order_by(MasIcd1020192.sort_order, MasIcd1020192.code)
    ).all()

    return [
        {
            "icd_code": row.code,
            "icd_to_display": f"{row.code} {row.title}",
            "title": row.title,
            "semantic_level": row.semantic_level,
            "is_detailed_code": row.is_detailed_code,
            "three_character_code": row.three_character_code,
        }
        for row in rows
    ]


def import_icd10_2019_2_policy_json(payload: str | bytes | dict) -> Icd1020192PolicyImportResult:
    if isinstance(payload, (str, bytes)):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("Policy import file is not valid JSON.") from exc
    elif isinstance(payload, dict):
        data = payload
    else:
        raise ValueError("Policy import payload must be JSON.")

    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("Policy import JSON must include an items array.")

    seen_codes: set[str] = set()
    updates_by_code: dict[str, Icd1020192PolicyUpdate] = {}
    skipped_items: list[dict[str, str]] = []

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each policy import item must be an object.")
        code = _optional_text(item.get("code", ""))
        if not code:
            raise ValueError("Each policy import item must include a code.")
        if code in seen_codes:
            skipped_items.append(
                {
                    "code": code,
                    "reason": "duplicate_code",
                }
            )
            continue
        seen_codes.add(code)
        try:
            updates_by_code[code] = _validate_policy_update(
                is_coding_selectable=item.get("is_coding_selectable"),
                sex_selectable=item.get("sex_selectable"),
                age_group_selectable=item.get("age_group_selectable"),
                restriction_note=item.get("restriction_note"),
            )
        except ValueError:
            skipped_items.append(
                {
                    "code": code,
                    "reason": "invalid_policy_values",
                }
            )

    rows = db.session.scalars(
        sa.select(MasIcd1020192).where(
            MasIcd1020192.is_active.is_(True),
            MasIcd1020192.semantic_level.in_(tuple(POLICY_EDITABLE_LEVELS)),
        )
    ).all()
    row_map = {row.code: row for row in rows}

    updated_items = 0
    imported_codes: set[str] = set()
    for code, update in updates_by_code.items():
        row = row_map.get(code)
        if row is None:
            skipped_items.append(
                {
                    "code": code,
                    "reason": "unknown_or_non_editable_code",
                }
            )
            continue

        changed = False
        if row.is_coding_selectable != update.is_coding_selectable:
            row.is_coding_selectable = update.is_coding_selectable
            changed = True
        if row.sex_selectable != update.sex_selectable:
            row.sex_selectable = update.sex_selectable
            changed = True
        if row.age_group_selectable != update.age_group_selectable:
            row.age_group_selectable = update.age_group_selectable
            changed = True
        if row.restriction_note != update.restriction_note:
            row.restriction_note = update.restriction_note
            changed = True
        if changed:
            updated_items += 1
        imported_codes.add(code)

    reset_items = 0
    for row in rows:
        if row.code in imported_codes:
            continue
        changed = False
        if row.is_coding_selectable is not False:
            row.is_coding_selectable = False
            changed = True
        if row.sex_selectable is not None:
            row.sex_selectable = None
            changed = True
        if row.age_group_selectable is not None:
            row.age_group_selectable = None
            changed = True
        if row.restriction_note is not None:
            row.restriction_note = None
            changed = True
        if changed:
            reset_items += 1

    db.session.commit()
    return Icd1020192PolicyImportResult(
        total_items=len(items),
        updated_items=updated_items,
        reset_items=reset_items,
        skipped_items=skipped_items,
    )
