"""adopt WHO 2026 annex ICD-10 ranges

Data-only migration. Makes a fresh database match the state produced by
`flask icd10 policy-import` and `flask cod-buckets import-who-2022-va-2026`
from the 2026-revision migration artifacts:

* marks the 108 codes listed in the artifact policy JSON as coding-selectable
  in `mas_icd10_2019_2` (both sexes, all ages), only where they are not
  already selectable, so re-running never overwrites later admin edits;
* creates the coexisting `WHO_2022_VA_2026` COD bucket scheme, only if it does
  not exist, so re-running never replaces an existing scheme or its edits.

Revision ID: c5f2a8d1e9b3
Revises: a40c38e73af4
Create Date: 2026-09-19T10:00:00.000000
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from alembic import op
from openpyxl import load_workbook
import sqlalchemy as sa


revision = "c5f2a8d1e9b3"
down_revision = "a40c38e73af4"
branch_labels = None
depends_on = None


ARTIFACT_DIR = Path(
    "docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd-cod-2026-revision"
)
POLICY_PATH = ARTIFACT_DIR / "who_2022_icd10_2019_2_policy_reviewed.json"
WORKBOOK_PATH = ARTIFACT_DIR / "WHO_2022_VA_Bucket_Mapping_document_derived_2026_revision.xlsx"

SCHEME_CODE = "WHO_2022_VA_2026"
SCHEME_NAME = "WHO 2022 VA (2026 revision)"
SCHEME_DESCRIPTION = (
    "WHO 2022 verbal autopsy cause-of-death bucket mapping, adopting the WHO 2026 "
    "manual for physician reviewers' Annex 1 Table A1 ICD-10 ranges, imported from "
    "the generated ICD_Mapped workbook. Coexists with the WHO_2022_VA scheme."
)

NODE_TYPE_CATEGORY = "category"
NODE_TYPE_FIELD = "field"
CHUNK_SIZE = 500


def _artifact_path(relative_path: Path) -> Path:
    path = Path(__file__).resolve().parents[2] / relative_path
    if not path.exists():
        raise ValueError(f"Migration artifact not found: {path}")
    return path


def _normalize_label(value) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", str(value).strip())
    return normalized or None


def _normalize_icd_code(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    return normalized or None


def _slugify(value: str, *, fallback_prefix: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or fallback_prefix


def _reflect(bind, name: str) -> sa.Table:
    return sa.Table(name, sa.MetaData(), autoload_with=bind)


def _apply_selectable_codes(bind) -> None:
    with _artifact_path(POLICY_PATH).open(encoding="utf-8") as handle:
        added_codes = json.load(handle)["who_2026_annex_adoption"]["added_codes"]
    icd = _reflect(bind, "mas_icd10_2019_2")
    for start in range(0, len(added_codes), CHUNK_SIZE):
        chunk = added_codes[start : start + CHUNK_SIZE]
        bind.execute(
            icd.update()
            .where(
                icd.c.code.in_(chunk),
                sa.or_(
                    icd.c.is_coding_selectable.is_(None),
                    icd.c.is_coding_selectable.is_(False),
                ),
            )
            .values(
                is_coding_selectable=True,
                sex_selectable="both",
                age_group_selectable="all",
            )
        )


def _load_sheet_rows(workbook_path: Path, sheet_name: str):
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        rows = workbook[sheet_name].iter_rows(values_only=True)
        headers = [str(h).strip() if h is not None else "" for h in next(rows)]
        for row_number, row in enumerate(rows, start=2):
            yield row_number, dict(zip(headers, row, strict=False))
    finally:
        workbook.close()


def _create_scheme_if_missing(bind, now: datetime) -> None:
    schemes = _reflect(bind, "mas_cod_bucket_schemes")
    exists = bind.execute(
        sa.select(schemes.c.scheme_id).where(schemes.c.scheme_code == SCHEME_CODE)
    ).first()
    if exists is not None:
        return

    nodes = _reflect(bind, "mas_cod_bucket_nodes")
    mappings = _reflect(bind, "map_icd_cod_buckets")
    age_bands = _reflect(bind, "mas_cod_bucket_scheme_age_bands")

    scheme_id = uuid.uuid4()
    bind.execute(
        schemes.insert().values(
            scheme_id=scheme_id,
            scheme_code=SCHEME_CODE,
            scheme_name=SCHEME_NAME,
            scheme_description=SCHEME_DESCRIPTION,
            source_path=str(WORKBOOK_PATH),
            mapping_version=1,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )
    bind.execute(
        age_bands.insert().values(
            age_band_id=uuid.uuid4(),
            scheme_id=scheme_id,
            age_scope=None,
            age_label="All Ages",
            min_age_value=0,
            min_age_unit="days",
            max_age_value=120,
            max_age_unit="years",
            level_count=2,
            sort_order=1,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )

    def new_node(*, node_type, label, sort_order, parent_id=None, code_source=None):
        node_id = uuid.uuid4()
        bind.execute(
            nodes.insert().values(
                node_id=node_id,
                scheme_id=scheme_id,
                age_scope=None,
                node_type=node_type,
                parent_node_id=parent_id,
                node_code=_slugify(code_source or label, fallback_prefix=node_type),
                node_label=label,
                sort_order=sort_order,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        return node_id

    category_nodes: dict[str, uuid.UUID] = {}
    field_nodes: dict[tuple[str, str], uuid.UUID] = {}
    pending: list[dict] = []
    for row_number, payload in _load_sheet_rows(_artifact_path(WORKBOOK_PATH), "ICD_Mapped"):
        icd_code = _normalize_icd_code(payload.get("icd_code"))
        section = _normalize_label(payload.get("WHO_2022_VA_section"))
        va_code = _normalize_label(payload.get("WHO_2022_VA_code"))
        va_title = _normalize_label(payload.get("WHO_2022_VA_cause"))
        if not icd_code or not section or not va_code or not va_title:
            continue
        if section not in category_nodes:
            category_nodes[section] = new_node(
                node_type=NODE_TYPE_CATEGORY,
                label=section,
                sort_order=len(category_nodes) + 1,
            )
        field_key = (section, va_code)
        if field_key not in field_nodes:
            field_nodes[field_key] = new_node(
                node_type=NODE_TYPE_FIELD,
                label=va_title,
                sort_order=len(field_nodes) + 1,
                parent_id=category_nodes[section],
                code_source=va_code,
            )
        pending.append(
            dict(
                mapping_id=uuid.uuid4(),
                scheme_id=scheme_id,
                age_scope=None,
                icd_code=icd_code,
                node_id=field_nodes[field_key],
                source_sheet="ICD_Mapped",
                source_row_number=row_number,
                source_category=_normalize_label(payload.get("category")),
                match_type=_normalize_label(payload.get("WHO_2022_VA_match_type")),
                mapping_note=_normalize_label(payload.get("WHO_2022_VA_note")),
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
    for start in range(0, len(pending), CHUNK_SIZE):
        bind.execute(mappings.insert(), pending[start : start + CHUNK_SIZE])


def upgrade():
    bind = op.get_bind()
    _apply_selectable_codes(bind)
    _create_scheme_if_missing(bind, datetime.now(timezone.utc))


def downgrade():
    # Data-only adoption of reviewed policy. The selectable codes may have been
    # edited since, and the scheme may carry admin overrides, so no destructive
    # reverse is attempted; remove them deliberately through the admin tools.
    pass
