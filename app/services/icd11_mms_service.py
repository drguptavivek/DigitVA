"""ICD-11 MMS catalog: import, stats, browsing and policy helpers.

Mirrors ``app/services/icd10_2019_2_service.py`` conventions for the ICD-11
MMS linearization catalog (``mas_icd11_mms``), seeded from the frozen WHO
Simple Tabulation export. See docs/policy/icd11-reference-catalog.md and
docs/icd-causegrp-mappings/migration-artifacts/icd11-mms-2026-01-base-2026-09-16/README.md
for the source file's column semantics.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models import MasIcd11Mms
from app.services.icd10_2019_2_service import get_icd10_2019_2_coding_context

DEFAULT_ICD11_RELEASE = "2026-01"
DEFAULT_ICD11_MMS_EXPORT_PATH = Path(
    "docs/icd-causegrp-mappings/migration-artifacts/"
    "icd11-mms-2026-01-base-2026-09-16/SimpleTabulation-ICD-11-MMS-en.txt"
)
DEFAULT_ICD11_MMS_CSV_PATH = Path("resource/icd11_mms_2026_01_hierarchy.csv")
SOURCE_VERSION = "ICD-11-MMS-2026-01"

SEX_SELECTABLE_OPTIONS = ("both", "female", "male")
AGE_GROUP_SELECTABLE_OPTIONS = ("all", "neonate", "infant", "child", "adult")
POLICY_EDITABLE_CLASS_KINDS = frozenset({"category"})

_IMPORT_BATCH_SIZE = 1000
_CODING_MIN_QUERY_LEN = 2
_CODING_MAX_RESULTS = 30

# WHO's export header/row shape (see the frozen export's README.md).
_EXPECTED_HEADER_CELLS = 20
_EXPECTED_ROW_CELLS = 19
_COLUMNS = (
    "foundation_uri",
    "linearization_uri",
    "code",
    "block_id",
    "title",
    "class_kind",
    "depth_in_kind",
    "is_residual",
    "chapter_no",
    "browser_link",
    "is_leaf",
    "primary_tabulation",
    "grouping1",
    "grouping2",
    "grouping3",
    "grouping4",
    "grouping5",
    "coding_note",
    "parent",
)


@dataclass(frozen=True)
class Icd11MmsImportResult:
    inserted: int
    updated: int
    deactivated: int
    total_rows: int


@dataclass(frozen=True)
class Icd11MmsPolicyUpdate:
    is_coding_selectable: bool | None
    sex_selectable: str | None
    age_group_selectable: str | None
    restriction_note: str | None


@dataclass(frozen=True)
class Icd11MmsPolicyImportResult:
    total_items: int
    updated_items: int
    reset_items: int
    skipped_items: list[dict[str, str]]


def _optional_text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _parse_who_bool(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def _parse_optional_bool(value: str | None) -> bool | None:
    normalized = (value or "").strip().lower()
    if not normalized:
        return None
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def _strip_title_depth_prefix(title: str) -> str:
    """Strip WHO's ``- `` depth-indent prefix from a title cell."""
    stripped = title or ""
    while stripped.startswith("- "):
        stripped = stripped[2:]
    return stripped.strip()


_EMBEDDED_LF_PLACEHOLDER = "\x00LF\x00"


def _parse_tab_row(line: str) -> list[str]:
    """Parse one CRLF-delimited row with a tab-delimited CSV reader.

    Coding notes may carry bare (unquoted) embedded line feeds; since the
    row was already isolated by splitting on literal CRLF, any remaining
    ``\\n`` in ``line`` is such embedded data, not a row terminator. It is
    swapped for a placeholder so python's csv reader (which otherwise raises
    on a newline inside an unquoted field) can parse the row, then restored
    in each resulting cell.
    """
    safe_line = line.replace("\n", _EMBEDDED_LF_PLACEHOLDER)
    cells = next(csv.reader([safe_line], delimiter="\t"))
    return [cell.replace(_EMBEDDED_LF_PLACEHOLDER, "\n") for cell in cells]


def _iter_export_rows(export_path: Path):
    """Yield each data row of the frozen export as a dict of `_COLUMNS`.

    Splits strictly on CRLF (not any bare line feed), since coding notes
    contain unquoted embedded LFs; each row is then parsed with a
    tab-delimited CSV reader because title cells are quoted.
    """
    with export_path.open("rb") as handle:
        raw = handle.read()
    text = raw.decode("utf-8-sig")
    lines = text.split("\r\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if not lines:
        raise ValueError(f"ICD-11 export is empty: {export_path}")

    header_cells = _parse_tab_row(lines[0])
    if len(header_cells) != _EXPECTED_HEADER_CELLS:
        raise ValueError(
            f"ICD-11 export header has {len(header_cells)} cells, "
            f"expected {_EXPECTED_HEADER_CELLS}: {export_path}"
        )

    for line_no, line in enumerate(lines[1:], start=2):
        cells = _parse_tab_row(line)
        if len(cells) != _EXPECTED_ROW_CELLS:
            raise ValueError(
                f"ICD-11 export row {line_no} has {len(cells)} cells, "
                f"expected {_EXPECTED_ROW_CELLS}: {export_path}"
            )
        yield dict(zip(_COLUMNS, cells))


def _build_foundation_to_linearization_map(export_path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in _iter_export_rows(export_path):
        foundation_uri = _optional_text(row["foundation_uri"])
        if foundation_uri:
            mapping[foundation_uri] = row["linearization_uri"]
    return mapping


def import_icd11_mms_from_export(
    export_path: str | Path = DEFAULT_ICD11_MMS_EXPORT_PATH,
    *,
    release: str = DEFAULT_ICD11_RELEASE,
    apply_policy_columns: bool = False,
) -> Icd11MmsImportResult:
    """Stream-import the frozen WHO Simple Tabulation export.

    Idempotent upsert on ``(release, linearization_uri)``. Rows missing from
    the export are marked ``is_active=False`` and never deleted. Local
    policy columns are preserved on rerun unless ``apply_policy_columns``.
    """
    export_path = Path(export_path)
    if not export_path.exists():
        raise ValueError(f"ICD-11 export not found: {export_path}")

    foundation_to_linearization = _build_foundation_to_linearization_map(export_path)

    existing_rows = {
        row.linearization_uri: row
        for row in db.session.scalars(
            sa.select(MasIcd11Mms).where(MasIcd11Mms.release == release)
        ).all()
    }

    inserted = 0
    updated = 0
    seen_uris: set[str] = set()
    total_rows = 0
    pending = 0

    for sort_order, row in enumerate(_iter_export_rows(export_path), start=1):
        total_rows += 1
        linearization_uri = row["linearization_uri"].strip()
        seen_uris.add(linearization_uri)
        record = existing_rows.get(linearization_uri)
        is_new = record is None
        if is_new:
            record = MasIcd11Mms(release=release, linearization_uri=linearization_uri)
            db.session.add(record)
            existing_rows[linearization_uri] = record
            inserted += 1
        else:
            updated += 1

        parent_foundation_uri = _optional_text(row["parent"])

        record.foundation_uri = _optional_text(row["foundation_uri"])
        record.code = _optional_text(row["code"])
        record.block_id = _optional_text(row["block_id"])
        record.title = _strip_title_depth_prefix(row["title"])
        record.class_kind = row["class_kind"].strip()
        depth_raw = _optional_text(row["depth_in_kind"])
        record.depth_in_kind = int(depth_raw) if depth_raw is not None else None
        record.chapter_no = _optional_text(row["chapter_no"])
        record.is_residual = _parse_who_bool(row["is_residual"])
        record.is_leaf = _parse_who_bool(row["is_leaf"])
        primary_tabulation_raw = _optional_text(row["primary_tabulation"])
        record.primary_tabulation = (
            _parse_who_bool(primary_tabulation_raw) if primary_tabulation_raw is not None else None
        )
        record.coding_note = _optional_text(row["coding_note"])
        record.sort_order = sort_order
        record.parent_foundation_uri = parent_foundation_uri
        record.parent_linearization_uri = (
            foundation_to_linearization.get(parent_foundation_uri)
            if parent_foundation_uri
            else None
        )
        record.source_version = SOURCE_VERSION
        record.source_path = str(export_path)
        record.is_active = True

        if is_new or apply_policy_columns:
            record.is_coding_selectable = None
            record.sex_selectable = None
            record.age_group_selectable = None
            record.policy_status = "unreviewed"
            record.restriction_note = None

        pending += 1
        if pending >= _IMPORT_BATCH_SIZE:
            db.session.flush()
            pending = 0

    deactivated = 0
    for linearization_uri, record in existing_rows.items():
        if linearization_uri in seen_uris or not record.is_active:
            continue
        record.is_active = False
        deactivated += 1

    db.session.commit()
    return Icd11MmsImportResult(
        inserted=inserted,
        updated=updated,
        deactivated=deactivated,
        total_rows=total_rows,
    )


def generate_icd11_mms_seed_csv(
    export_path: str | Path = DEFAULT_ICD11_MMS_EXPORT_PATH,
    csv_path: str | Path = DEFAULT_ICD11_MMS_CSV_PATH,
) -> int:
    """Generate the checked-in seed CSV consumed by the seeding migration.

    Returns the number of rows written.
    """
    export_path = Path(export_path)
    csv_path = Path(csv_path)
    foundation_to_linearization = _build_foundation_to_linearization_map(export_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "linearization_uri",
        "foundation_uri",
        "code",
        "block_id",
        "title",
        "class_kind",
        "depth_in_kind",
        "chapter_no",
        "is_residual",
        "is_leaf",
        "primary_tabulation",
        "coding_note",
        "sort_order",
        "parent_foundation_uri",
        "parent_linearization_uri",
    ]
    row_count = 0
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for sort_order, row in enumerate(_iter_export_rows(export_path), start=1):
            parent_foundation_uri = _optional_text(row["parent"])
            primary_tabulation_raw = _optional_text(row["primary_tabulation"])
            writer.writerow(
                {
                    "linearization_uri": row["linearization_uri"].strip(),
                    "foundation_uri": _optional_text(row["foundation_uri"]) or "",
                    "code": _optional_text(row["code"]) or "",
                    "block_id": _optional_text(row["block_id"]) or "",
                    "title": _strip_title_depth_prefix(row["title"]),
                    "class_kind": row["class_kind"].strip(),
                    "depth_in_kind": _optional_text(row["depth_in_kind"]) or "",
                    "chapter_no": _optional_text(row["chapter_no"]) or "",
                    "is_residual": "true" if _parse_who_bool(row["is_residual"]) else "false",
                    "is_leaf": "true" if _parse_who_bool(row["is_leaf"]) else "false",
                    "primary_tabulation": (
                        ("true" if _parse_who_bool(primary_tabulation_raw) else "false")
                        if primary_tabulation_raw is not None
                        else ""
                    ),
                    "coding_note": _optional_text(row["coding_note"]) or "",
                    "sort_order": sort_order,
                    "parent_foundation_uri": parent_foundation_uri or "",
                    "parent_linearization_uri": (
                        foundation_to_linearization.get(parent_foundation_uri, "")
                        if parent_foundation_uri
                        else ""
                    ),
                }
            )
            row_count += 1
    return row_count


def get_icd11_mms_stats(release: str = DEFAULT_ICD11_RELEASE) -> dict[str, int]:
    rows = db.session.execute(
        sa.select(
            sa.func.count().label("total_rows"),
            sa.func.count().filter(MasIcd11Mms.is_active.is_(True)).label("active_rows"),
            sa.func.count().filter(MasIcd11Mms.class_kind == "chapter").label("chapters"),
            sa.func.count().filter(MasIcd11Mms.class_kind == "block").label("blocks"),
            sa.func.count().filter(MasIcd11Mms.class_kind == "category").label("categories"),
            sa.func.count().filter(MasIcd11Mms.is_residual.is_(True)).label("residual_rows"),
            sa.func.count().filter(MasIcd11Mms.is_leaf.is_(True)).label("leaf_rows"),
        ).where(MasIcd11Mms.release == release)
    ).mappings().one()
    return {key: int(value or 0) for key, value in rows.items()}


def _serialize_row(row: MasIcd11Mms, *, child_count: int | None = None) -> dict:
    return {
        "id": str(row.id),
        "release": row.release,
        "linearization_uri": row.linearization_uri,
        "foundation_uri": row.foundation_uri,
        "code": row.code,
        "block_id": row.block_id,
        "title": row.title,
        "class_kind": row.class_kind,
        "depth_in_kind": row.depth_in_kind,
        "chapter_no": row.chapter_no,
        "is_residual": row.is_residual,
        "is_leaf": row.is_leaf,
        "primary_tabulation": row.primary_tabulation,
        "coding_note": row.coding_note,
        "sort_order": row.sort_order,
        "parent_foundation_uri": row.parent_foundation_uri,
        "parent_linearization_uri": row.parent_linearization_uri,
        "child_count": child_count,
        "is_coding_selectable": row.is_coding_selectable,
        "sex_selectable": row.sex_selectable,
        "age_group_selectable": row.age_group_selectable,
        "policy_status": row.policy_status,
        "restriction_note": row.restriction_note,
        "is_policy_editable": row.class_kind in POLICY_EDITABLE_CLASS_KINDS,
        "is_active": row.is_active,
    }


def list_icd11_mms_children(
    parent_linearization_uri: str | None,
    release: str = DEFAULT_ICD11_RELEASE,
) -> list[dict]:
    child_count_sq = (
        sa.select(
            MasIcd11Mms.parent_linearization_uri.label("parent_linearization_uri"),
            sa.func.count().label("child_count"),
        )
        .where(MasIcd11Mms.release == release, MasIcd11Mms.is_active.is_(True))
        .group_by(MasIcd11Mms.parent_linearization_uri)
        .subquery()
    )
    query = (
        sa.select(MasIcd11Mms, child_count_sq.c.child_count)
        .outerjoin(
            child_count_sq,
            child_count_sq.c.parent_linearization_uri == MasIcd11Mms.linearization_uri,
        )
        .where(MasIcd11Mms.release == release, MasIcd11Mms.is_active.is_(True))
        .order_by(MasIcd11Mms.sort_order, MasIcd11Mms.linearization_uri)
    )
    if parent_linearization_uri is None:
        query = query.where(MasIcd11Mms.parent_linearization_uri.is_(None))
    else:
        query = query.where(
            MasIcd11Mms.parent_linearization_uri == parent_linearization_uri
        )

    rows = db.session.execute(query).all()
    return [
        _serialize_row(row, child_count=int(child_count or 0)) for row, child_count in rows
    ]


def get_icd11_mms_node_details(
    linearization_uri: str, release: str = DEFAULT_ICD11_RELEASE
) -> dict | None:
    row = db.session.scalar(
        sa.select(MasIcd11Mms).where(
            MasIcd11Mms.release == release,
            MasIcd11Mms.linearization_uri == linearization_uri,
        )
    )
    if row is None or not row.is_active:
        return None

    child_count = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(MasIcd11Mms)
        .where(
            MasIcd11Mms.release == release,
            MasIcd11Mms.parent_linearization_uri == linearization_uri,
            MasIcd11Mms.is_active.is_(True),
        )
    ) or 0

    ancestors: list[dict[str, str]] = []
    current_uri = row.parent_linearization_uri
    while current_uri:
        ancestor = db.session.scalar(
            sa.select(MasIcd11Mms).where(
                MasIcd11Mms.release == release,
                MasIcd11Mms.linearization_uri == current_uri,
            )
        )
        if ancestor is None or not ancestor.is_active:
            break
        ancestors.append(
            {
                "linearization_uri": ancestor.linearization_uri,
                "title": ancestor.title,
                "class_kind": ancestor.class_kind,
            }
        )
        current_uri = ancestor.parent_linearization_uri
    ancestors.reverse()

    payload = _serialize_row(row, child_count=int(child_count))
    payload["ancestors"] = ancestors
    return payload


def get_icd11_mms_policy_options() -> dict[str, list[str]]:
    return {
        "sex_selectable": list(SEX_SELECTABLE_OPTIONS),
        "age_group_selectable": list(AGE_GROUP_SELECTABLE_OPTIONS),
    }


def _validate_policy_update(
    *, is_coding_selectable, sex_selectable, age_group_selectable, restriction_note
) -> Icd11MmsPolicyUpdate:
    if is_coding_selectable not in (True, False, None):
        raise ValueError("is_coding_selectable must be true, false, or null.")
    if sex_selectable not in (*SEX_SELECTABLE_OPTIONS, None):
        raise ValueError("sex_selectable must be one of both, female, male, or null.")
    if age_group_selectable not in (*AGE_GROUP_SELECTABLE_OPTIONS, None):
        raise ValueError(
            "age_group_selectable must be one of all, neonate, infant, child, adult, or null."
        )
    if restriction_note is not None and not isinstance(restriction_note, str):
        raise ValueError("restriction_note must be a string or null.")
    return Icd11MmsPolicyUpdate(
        is_coding_selectable=is_coding_selectable,
        sex_selectable=sex_selectable,
        age_group_selectable=age_group_selectable,
        restriction_note=_optional_text(restriction_note or ""),
    )


def update_icd11_mms_policy(
    linearization_uri: str,
    *,
    release: str = DEFAULT_ICD11_RELEASE,
    is_coding_selectable,
    sex_selectable,
    age_group_selectable,
    restriction_note,
) -> dict:
    row = db.session.scalar(
        sa.select(MasIcd11Mms).where(
            MasIcd11Mms.release == release,
            MasIcd11Mms.linearization_uri == linearization_uri,
        )
    )
    if row is None or not row.is_active:
        raise LookupError(f"ICD-11 entity not found: {linearization_uri}")
    if row.class_kind not in POLICY_EDITABLE_CLASS_KINDS:
        raise ValueError("Policy fields are only editable for ICD-11 category entities.")

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
    return get_icd11_mms_node_details(linearization_uri, release) or _serialize_row(row)


def export_icd11_mms_policy_json(release: str = DEFAULT_ICD11_RELEASE) -> dict:
    rows = db.session.scalars(
        sa.select(MasIcd11Mms)
        .where(
            MasIcd11Mms.release == release,
            MasIcd11Mms.is_active.is_(True),
            MasIcd11Mms.class_kind.in_(tuple(POLICY_EDITABLE_CLASS_KINDS)),
            sa.or_(
                MasIcd11Mms.is_coding_selectable.is_not(None),
                MasIcd11Mms.sex_selectable.is_not(None),
                MasIcd11Mms.age_group_selectable.is_not(None),
            ),
        )
        .order_by(MasIcd11Mms.sort_order, MasIcd11Mms.linearization_uri)
    ).all()

    items = [
        {
            "linearization_uri": row.linearization_uri,
            "code": row.code,
            "title": row.title,
            "class_kind": row.class_kind,
            "chapter_no": row.chapter_no,
            "is_coding_selectable": row.is_coding_selectable,
            "sex_selectable": row.sex_selectable,
            "age_group_selectable": row.age_group_selectable,
        }
        for row in rows
    ]
    return {
        "release": release,
        "source_version": SOURCE_VERSION,
        "row_count": len(items),
        "items": items,
    }


def import_icd11_mms_policy_json(
    payload: str | bytes | dict, release: str = DEFAULT_ICD11_RELEASE
) -> Icd11MmsPolicyImportResult:
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

    seen_uris: set[str] = set()
    updates_by_uri: dict[str, Icd11MmsPolicyUpdate] = {}
    skipped_items: list[dict[str, str]] = []

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each policy import item must be an object.")
        linearization_uri = _optional_text(item.get("linearization_uri", ""))
        if not linearization_uri:
            raise ValueError("Each policy import item must include a linearization_uri.")
        if linearization_uri in seen_uris:
            skipped_items.append({"code": linearization_uri, "reason": "duplicate_code"})
            continue
        seen_uris.add(linearization_uri)
        try:
            updates_by_uri[linearization_uri] = _validate_policy_update(
                is_coding_selectable=item.get("is_coding_selectable"),
                sex_selectable=item.get("sex_selectable"),
                age_group_selectable=item.get("age_group_selectable"),
                restriction_note=item.get("restriction_note"),
            )
        except ValueError:
            skipped_items.append(
                {"code": linearization_uri, "reason": "invalid_policy_values"}
            )

    rows = db.session.scalars(
        sa.select(MasIcd11Mms).where(
            MasIcd11Mms.release == release,
            MasIcd11Mms.is_active.is_(True),
            MasIcd11Mms.class_kind.in_(tuple(POLICY_EDITABLE_CLASS_KINDS)),
        )
    ).all()
    row_map = {row.linearization_uri: row for row in rows}

    updated_items = 0
    imported_uris: set[str] = set()
    for linearization_uri, update in updates_by_uri.items():
        row = row_map.get(linearization_uri)
        if row is None:
            skipped_items.append(
                {"code": linearization_uri, "reason": "unknown_or_non_editable_code"}
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
        imported_uris.add(linearization_uri)

    reset_items = 0
    for row in rows:
        if row.linearization_uri in imported_uris:
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
    return Icd11MmsPolicyImportResult(
        total_items=len(items),
        updated_items=updated_items,
        reset_items=reset_items,
        skipped_items=skipped_items,
    )


def _normalize_query(raw_query: str) -> str:
    return " ".join((raw_query or "").strip().lower().split())


def _coding_policy_clause(*, age_group: str | None, sex: str | None):
    clause = MasIcd11Mms.is_coding_selectable.is_(True)
    if age_group:
        clause = sa.and_(
            clause,
            sa.or_(
                MasIcd11Mms.age_group_selectable == "all",
                MasIcd11Mms.age_group_selectable == age_group,
            ),
        )
    if sex:
        clause = sa.and_(
            clause,
            sa.or_(
                MasIcd11Mms.sex_selectable == "both",
                MasIcd11Mms.sex_selectable == sex,
            ),
        )
    return clause


def search_icd11_mms(
    query: str,
    va_sid: str | None = None,
    release: str = DEFAULT_ICD11_RELEASE,
    limit: int = _CODING_MAX_RESULTS,
) -> list[dict[str, str | bool | None]]:
    """Search selectable ICD-11 categories by code or title.

    When ``va_sid`` is given, results are filtered by that submission's age
    and sex policy, mirroring ``search_icd10_2019_2_coding_choices``.
    """
    normalized_query = _normalize_query(query)
    if len(normalized_query) < _CODING_MIN_QUERY_LEN:
        return []

    age_group: str | None = None
    sex: str | None = None
    if va_sid is not None:
        context = get_icd10_2019_2_coding_context(va_sid)
        if context is None:
            raise LookupError(f"Submission not found: {va_sid}")
        age_group = context["age_group"]
        sex = context["sex"]

    like_query = f"%{normalized_query}%"
    code_prefix = f"{normalized_query}%"
    lower_code = sa.func.lower(sa.func.coalesce(MasIcd11Mms.code, ""))
    lower_title = sa.func.lower(MasIcd11Mms.title)

    rank_expr = sa.case(
        (lower_code == normalized_query, 0),
        (lower_code.like(code_prefix), 1),
        (lower_title.like(code_prefix), 2),
        (lower_title.like(like_query), 3),
        else_=4,
    )

    filters = [
        MasIcd11Mms.release == release,
        MasIcd11Mms.is_active.is_(True),
        MasIcd11Mms.class_kind.in_(tuple(POLICY_EDITABLE_CLASS_KINDS)),
        sa.or_(lower_code.like(like_query), lower_title.like(like_query)),
    ]
    if va_sid is not None:
        filters.append(_coding_policy_clause(age_group=age_group, sex=sex))

    rows = db.session.scalars(
        sa.select(MasIcd11Mms)
        .where(*filters)
        .order_by(rank_expr, MasIcd11Mms.sort_order, MasIcd11Mms.linearization_uri)
        .limit(min(limit, _CODING_MAX_RESULTS))
    ).all()

    return [
        {
            "icd_code": row.code,
            "icd_to_display": f"{row.code} {row.title}" if row.code else row.title,
            "title": row.title,
            "linearization_uri": row.linearization_uri,
            "class_kind": row.class_kind,
        }
        for row in rows
    ]
