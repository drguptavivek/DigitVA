# Offline coding workspace (digitva-9cll.22.8)

- Status: in progress
- Priority: P1
- Created: 2026-10-31
- Policy: `docs/policy/doris-cod-workflow.md` "Offline coding workspace"

## Goal

Collect Plus offline coding (`mobile/digitva-collect/src/nativeRoutes/offlineCoding.native.tsx`) mounts the shared
`src/workspace/CaseWorkspaceScreen.tsx` (as `src/nativeRoutes/plusWorkspace.tsx` does online) with a local `WorkspaceApi`,
so the coder reviews the case as on the web. Nothing leaves the phone.

## Pieces

1. **Display pack** (backend): `scripts/export_offline_va_display_pack.py` writes
   `mobile/digitva-collect/assets/va-display-WHO_2022_VA.json`; drift test `tests/services/test_export_offline_va_display_pack.py`
   (pattern: `scripts/export_offline_va_definitions.py` and its test).
2. **Golden renders** (backend): `scripts/export_offline_va_display_golden.py` writes
   `mobile/digitva-collect/__tests__/fixtures/va-display-golden.json` from committed synthetic inputs through the server's
   real render functions; the same pytest asserts the committed file equals a regeneration.
3. **Server array fix** (backend): `app/utils/va_render/va_render_06_processcategorydata.py` labels a list answer as it labels
   the space-joined string (Collect submits multi-selects as arrays and they reach `payload_data` unchanged).
4. **Phone producer and route** (mobile): `src/workspace/localCategories.ts` (pure: pack + answers -> nav, counts, default,
   `CategoryPayload`), local `WorkspaceApi` in the offline route, local media, Jest parity against the golden file.

## Pack schema (`digitva.va-display-pack`, schema 1)

Every ordered collection is a JSON array (never rely on object key order: JS puts integer-like keys first).

```
{
  "schema": 1,
  "form_type_code": "WHO_2022_VA",
  "categories": [ {"code","label","nav_label","icon_name","render_mode","display_order","always_include","is_default_start"} ],
        // coder role (va_action "vacode"), MasCategoryDisplayConfig + WORKFLOW_NAV_ITEMS, in get_category_nav order
  "datalevel": [ ["<category>", [ ["<subcategory>", [ ["<field_id>", "<label>"], ... ]], ... ]], ... ],
        // va_get_render_datalevel("vacode", ...) with every coder-enabled DB category merged (visibility is decided per case)
  "visibility": [ ["<category>", ["<field_id>", ...]], ... ],
        // get_fieldsitepi's field ids per active category: get_visible_category_codes renders over the DB mapping, not
        // the coder datalevel (e.g. Id10233-Id10236 are coder-only); visible = always_include or a non-empty render here
  "subcategories": [ ["<category>", [ ["<subcategory>", "<label>", "<render_mode>"], ... ]], ... ],
        // get_subcategory_labels / get_subcategory_render_modes ("default" when unset), for every category in datalevel
  "choices": [ ["<field_id>", [ ["<value>", "<label>"], ... ]], ... ],
  "flip_labels": [ ... ], "info_labels": [ ... ],                     // sorted
  "summary": { "fields": [ {"field_id","label","flip_color"} ],       // build_submission_summary order and label rule
               "special_fields": [ ... ] },                           // SPECIAL_VALUE_SUMMARY_FIELDS, sorted
  "catcount": { "summary": [ ["<category>", [ ["<field_id>", "<label>"], ... ]], ... ],   // va_mapping_summary
                "flip": [ ... ], "special_fields": [ ... ] },          // va_mapping_summaryflip; the excluded ids
  "render": { "dates": [], "datetimes": [], "zero_skip": [], "skip_values": [], "attachments": [], "multiselect": [] },
  "workflow_panel": { "attachments_category": "vanarrationanddocuments", "health_history_category": "vahealthhistorydetails" },
  "db_revision": "<alembic version_num or null>",                     // not hashed
  "content_sha256": "<hex>"
}
```

`content_sha256` = sha256 of the UTF-8 compact JSON (`separators=(",", ":")`, `ensure_ascii=False`) of every top-level key
except `db_revision` and `content_sha256`, in the order above. The app recomputes it from the parsed file.

## Golden schema

```
{
  "pack_sha256": "<the pack's content_sha256>",
  "cases": [ {
    "name": "<case name>",
    "data": { <device-shaped answers: flat Id-keyed, arrays for multi-selects, numbers as numbers,
              attachment fields as "who-va-attachment:<uuid>"> },
    "visible_category_codes": [ ... ],
    "categories": [ {"code","label","nav_label","icon_name","count","attachment_count","render_mode"} ],   // workspace nav
    "default_category": "<code>",
    "summary_items": [ ... ],
    "category_payloads": [ {"code","label","render_mode","summary_items","subcategories","blocked_by": []} ]  // every nav code
  } ]
}
```

Renders use the answers after `strip_irrelevant_answers` (as at submit). An attachment field that holds a reference
renders as the string `digitva-local-attachment:<field_id>` (the server's URL step is replaced; the phone emits the same
string and resolves it through `renderMedia`). No PII: synthetic answers only.

## Out of scope here

`.22.3` native CategoryPanel visual parity, `.22.4` offline NQA/SA saving (set `narrative_qa_enabled` /
`social_autopsy_enabled` per the owner rule; payloads stay null), `.22.5` not-codeable/remark, `.22.6` SmartVA sex code.
