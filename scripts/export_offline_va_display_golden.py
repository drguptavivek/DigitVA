"""Export the golden renders that tie Collect Plus offline coding to the server (display pack schema 1).

Run in minerva_app_service against the seeded WHO_2022_VA field mapping. Each
case of ``tests/fixtures/va_display_golden_inputs.json`` is a synthetic,
device-shaped answer set (flat field-id keys, ``string[]`` for multi-selects,
numbers as numbers, ``YYYY-MM-DD`` dates, ISO datetimes, attachments as
``who-va-attachment:<uuid>``; no personal data). It is run through the server's
real functions, in the order the coding workspace uses them:

  1. ``strip_irrelevant_answers``: the answers the server stores on submission.
  2. ``get_visible_category_codes``, ``get_category_nav``, the category counts
     of ``va_preprocess_summcatenotification``, ``_count_attachments_per_category``
     and ``get_default_category_code``: the workspace nav.
  3. ``build_section`` and ``category_subcategories``: each nav category's
     payload, as ``GET /api/v1/va/<sid>/categories/<code>`` serves it.

Only the steps that need a stored submission are replaced: an attachment field
that holds a reference is present, and renders as
``digitva-local-attachment:<field_id>`` (the phone emits the same string and
resolves it through ``renderMedia``). ``data`` in the output is the input, before
step 1; the phone strips its own answers the same way.

Output layout (mobile/digitva-collect/__tests__/fixtures/va-display-golden.json):
  pack_sha256  the ``content_sha256`` of the display pack the renders were built with.
  cases        name, data, visible_category_codes, categories (code, label,
               nav_label, icon_name, count, attachment_count, render_mode),
               default_category, summary_items and category_payloads (code,
               label, render_mode, summary_items, subcategories, blocked_by) for
               every nav code.

tests/services/test_export_offline_va_display_pack.py checks that the committed
file equals a regeneration.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from app import create_app
from app.routes.api.va_case import _category_counts, category_subcategories
from app.services.case_content_service import build_section
from app.services.category_rendering_service import (
    get_category_rendering_service,
    get_visible_category_codes,
)
from app.services.coding_service import _count_attachments_per_category
from app.services.web_form_relevance_service import strip_irrelevant_answers
from app.utils.va_preprocess.va_preprocess_02_summcatenotification import (
    va_preprocess_summcatenotification,
)
from app.utils.va_render import va_render_06_processcategorydata as render_module
from scripts.export_offline_va_display_pack import FORM_TYPE_CODE, VA_ACTION, build_pack

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "tests/fixtures/va_display_golden_inputs.json"
OUTPUT = ROOT / "mobile/digitva-collect/__tests__/fixtures/va-display-golden.json"
# Not a stored form: form type resolution falls back to the default, WHO_2022_VA.
FORM_ID = "GOLDEN_FORM"
# What the instrument's today() reads; fixed so the regeneration is reproducible.
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
LOCAL_ATTACHMENT = "digitva-local-attachment:{field_id}"


def _render_case(data: dict) -> dict:
    """One golden case's renders from the device-shaped *data* (needs an app context)."""
    stripped, _removed = strip_irrelevant_answers(data, now=NOW)

    field_by_reference = {}
    for field_id in render_module.va_isattachment:
        reference = stripped.get(field_id)
        if reference:
            if reference in field_by_reference:
                raise ValueError(f"Attachment reference {reference!r} is used by two fields.")
            field_by_reference[reference] = field_id

    def local_attachment(_va_sid, _va_form_id, reference):
        return LOCAL_ATTACHMENT.format(field_id=field_by_reference[reference])

    category_service = get_category_rendering_service()
    with (
        mock.patch.object(render_module, "_prefetch_attachment_urls", lambda _va_sid: None),
        mock.patch.object(render_module, "_resolve_attachment_url", local_attachment),
        # Visibility checks ask the attachment store; a reference is present.
        mock.patch.object(render_module.attachment_service, "is_attachment_present_for_form", lambda _form, reference: bool(reference)),
    ):
        visible = get_visible_category_codes(stripped, FORM_ID)
        nav = category_service.get_category_nav(FORM_TYPE_CODE, VA_ACTION, visible)
        _summary, catcount = va_preprocess_summcatenotification(stripped)
        counts = _category_counts(catcount, nav)
        attachment_counts = _count_attachments_per_category(FORM_TYPE_CODE, stripped, FORM_ID)
        payloads = []
        for item in nav:
            section = build_section(
                stripped, FORM_ID, FORM_TYPE_CODE, VA_ACTION, item.category_code, item, visible, va_sid="golden"
            )
            payloads.append({
                "code": item.category_code,
                "label": item.display_label,
                "render_mode": item.render_mode,
                "summary_items": section["summary_items"],
                "subcategories": category_subcategories(section, item, FORM_TYPE_CODE, item.category_code),
                "blocked_by": [],
            })
        summary_items = payloads[0]["summary_items"]

    return {
        "visible_category_codes": visible,
        "categories": [
            {
                "code": item.category_code,
                "label": item.display_label,
                "nav_label": item.nav_label,
                "icon_name": item.icon_name,
                "count": counts[item.category_code],
                "attachment_count": attachment_counts.get(item.category_code, 0),
                "render_mode": item.render_mode,
            }
            for item in nav
        ],
        "default_category": category_service.get_default_category_code(FORM_TYPE_CODE, VA_ACTION, visible),
        "summary_items": summary_items,
        "category_payloads": payloads,
    }


def build_golden() -> dict:
    """The golden document from the committed inputs and the current database (needs an app context)."""
    cases = json.loads(INPUTS.read_text(encoding="utf-8"))["cases"]
    pack = build_pack()
    return {
        "pack_sha256": pack["content_sha256"],
        "cases": [{"name": case["name"], "data": case["data"], **_render_case(case["data"])} for case in cases],
    }


def dump_golden(golden: dict) -> str:
    return json.dumps(golden, indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    app = create_app()
    with app.app_context():
        golden = build_golden()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(dump_golden(golden), encoding="utf-8")
    print(f"{OUTPUT.relative_to(ROOT)}: {len(golden['cases'])} cases, {OUTPUT.stat().st_size} bytes, pack {golden['pack_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
