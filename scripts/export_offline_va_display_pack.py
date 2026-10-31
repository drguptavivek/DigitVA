"""Export the VA display pack for Collect Plus offline coding (pack schema 1).

Run in minerva_app_service against the seeded WHO_2022_VA field mapping. This
reads the mapping tables through the same services the server's coding
workspace uses, so the phone builds the server's category payload from the
draft's answers without a network call (docs/policy/doris-cod-workflow.md,
"Offline coding workspace"). tests/services/test_export_offline_va_display_pack.py
checks that the committed pack equals the database at head; the golden file of
scripts/export_offline_va_display_golden.py ties the phone's renders to the
server's.

Pack layout (schema 1). Every ordered collection is a JSON array, never an
object: JS orders integer-like keys first, which would break the app's hash.
  categories     coder nav in ``get_category_nav`` order, with the workflow item
                 (``vacodassessment``): code, label, nav_label, icon_name,
                 render_mode, display_order, always_include, is_default_start.
  datalevel      [[category, [[subcategory, [[field_id, label], ...]], ...]], ...]
                 from ``va_get_render_datalevel("vacode", ...)`` with every
                 coder-enabled DB category merged; visibility is decided per case.
  visibility     [[category, [field_id, ...]], ...] for every active category of the
                 form type, the field ids of the DB mapping (``get_fieldsitepi``) in its
                 order. The server decides which categories a case shows from this
                 mapping, not from the coder ``datalevel`` (they differ), so the phone
                 renders a category over these ids, with the same skip and attachment
                 rules, as ``get_visible_category_codes`` does.
  subcategories  [[category, [[subcategory, label, render_mode], ...]], ...] for
                 every subcategory of ``datalevel`` (render_mode "default" when unset).
  choices        [[field_id, [[value, label], ...]], ...] sorted by code point.
  flip_labels, info_labels    sorted labels.
  summary        fields (build_submission_summary order and label rule) and the
                 special fields shown as "label: value".
  catcount       the category-count rule: va_mapping_summary per category, the
                 flip labels (counted on "no") and the special ids (never counted).
  render         the constant lists of va_render_processcategorydata.
  workflow_panel the two categories the COD assessment panel appends.
  db_revision    alembic version_num the pack was cut at (null without one); not hashed.

``content_sha256`` is the sha256 (hex) of the UTF-8 bytes of the compact JSON
``json.dumps({"schema", "form_type_code", "categories", "datalevel",
"visibility", "subcategories", "choices", "flip_labels", "info_labels", "summary", "catcount",
"render", "workflow_panel"}, separators=(",", ":"), ensure_ascii=False)``, keys
in that order. The app recomputes it from the parsed file.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import sqlalchemy as sa

from app import create_app, db
from app.services.category_rendering_service import (
    clear_category_rendering_cache,
    get_category_rendering_service,
)
from app.services.field_mapping_service import get_mapping_service
from app.services.submission_summary_service import SPECIAL_VALUE_SUMMARY_FIELDS, summary_fields
from app.utils.va_mapping.va_mapping_04_summary import va_mapping_summary
from app.utils.va_mapping.va_mapping_05_summaryflip import va_mapping_summaryflip
from app.utils.va_preprocess.va_preprocess_02_summcatenotification import SPECIAL_SUMMARY_IDS
from app.utils.va_render import va_render_06_processcategorydata as render_module
from app.utils.va_routes.va_api_helpers import va_get_render_datalevel

ROOT = Path(__file__).resolve().parents[1]
FORM_TYPE_CODE = "WHO_2022_VA"
OUTPUT = ROOT / f"mobile/digitva-collect/assets/va-display-{FORM_TYPE_CODE}.json"
SCHEMA = 1
VA_ACTION = "vacode"
HASHED_FIELDS = (
    "schema", "form_type_code", "categories", "datalevel", "visibility", "subcategories", "choices",
    "flip_labels", "info_labels", "summary", "catcount", "render", "workflow_panel",
)
# The categories the COD assessment panel appends (case_content_service.get_section_data).
WORKFLOW_PANEL = {"attachments_category": "vanarrationanddocuments", "health_history_category": "vahealthhistorydetails"}


def compact_sha256(value: object) -> str:
    canonical = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_pack() -> dict:
    """The pack from the current database (needs an app context)."""
    # A second build in one process (tests) must not read another database's cached mapping.
    clear_category_rendering_cache()
    mapping = get_mapping_service()
    category_service = get_category_rendering_service()
    all_codes = [item.category_code for item in category_service.get_all_active_categories(FORM_TYPE_CODE)]
    field_mapping = mapping.get_fieldsitepi(FORM_TYPE_CODE)
    if not all_codes:
        raise ValueError(f"No active categories for {FORM_TYPE_CODE}: the field mapping is not loaded.")

    categories = [
        {
            "code": item.category_code,
            "label": item.display_label,
            "nav_label": item.nav_label,
            "icon_name": item.icon_name,
            "render_mode": item.render_mode,
            "display_order": item.display_order,
            "always_include": item.always_include,
            "is_default_start": item.is_default_start,
        }
        for item in category_service.get_category_nav(FORM_TYPE_CODE, VA_ACTION, all_codes)
    ]

    datalevel = va_get_render_datalevel(VA_ACTION, FORM_TYPE_CODE, all_codes)
    subcategories = []
    for category_code, sections in datalevel.items():
        labels = mapping.get_subcategory_labels(FORM_TYPE_CODE, category_code)
        render_modes = mapping.get_subcategory_render_modes(FORM_TYPE_CODE, category_code)
        subcategories.append([
            category_code,
            [[code, labels.get(code, code), render_modes.get(code, "default")] for code in sections],
        ])

    pack = {
        "schema": SCHEMA,
        "form_type_code": FORM_TYPE_CODE,
        "categories": categories,
        "datalevel": [
            [category_code, [[code, [[field_id, label] for field_id, label in fields.items()]] for code, fields in sections.items()]]
            for category_code, sections in datalevel.items()
        ],
        "visibility": [
            [code, [field_id for fields in field_mapping.get(code, {}).values() for field_id in fields]]
            for code in all_codes
        ],
        "subcategories": subcategories,
        # Sorted here, not by SQL ORDER BY, so the order (and the hash) never depends on the DB collation.
        "choices": [
            [field_id, sorted([value, label] for value, label in choices.items())]
            for field_id, choices in sorted(mapping.get_choices(FORM_TYPE_CODE).items())
        ],
        "flip_labels": sorted(set(mapping.get_flip_labels(FORM_TYPE_CODE))),
        "info_labels": sorted(set(mapping.get_info_labels(FORM_TYPE_CODE))),
        "summary": {
            "fields": [
                {"field_id": field_id, "label": label, "flip_color": flip_color}
                for field_id, label, flip_color in summary_fields(FORM_TYPE_CODE)
            ],
            "special_fields": sorted(SPECIAL_VALUE_SUMMARY_FIELDS),
        },
        "catcount": {
            "summary": [
                [category_code, [[field_id, label] for field_id, label in fields.items()]]
                for category_code, fields in va_mapping_summary.items()
            ],
            "flip": list(va_mapping_summaryflip),
            "special_fields": sorted(SPECIAL_SUMMARY_IDS),
        },
        "render": {
            "dates": list(render_module.va_dealwithdates),
            "datetimes": list(render_module.va_dealwithdatetimes),
            "zero_skip": list(render_module.va_zeroskipfields),
            "skip_values": list(render_module.va_skipvalues),
            "attachments": list(render_module.va_isattachment),
            "multiselect": list(render_module.va_multipleselect),
        },
        "workflow_panel": dict(WORKFLOW_PANEL),
    }
    # A create_all test database has no alembic_version: no revision to record.
    has_revision_table = db.session.scalar(sa.text("SELECT to_regclass('alembic_version') IS NOT NULL"))
    pack["db_revision"] = (
        db.session.scalar(sa.text("SELECT version_num FROM alembic_version LIMIT 1")) if has_revision_table else None
    )
    pack["content_sha256"] = compact_sha256({key: pack[key] for key in HASHED_FIELDS})
    return pack


def main() -> int:
    app = create_app()
    with app.app_context():
        pack = build_pack()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(pack, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{OUTPUT.relative_to(ROOT)}: {len(pack['categories'])} categories, {OUTPUT.stat().st_size} bytes, {pack['content_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
