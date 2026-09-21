---
title: VA Cause Definitions
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-21
---

# VA Cause Definitions

Baseline for the WHO verbal autopsy cause codes, titles and definitions that
coders and reviewers consult while assigning causes of death.

## Source

- The WHO table in `docs/kb/WHO_VA_2022_Docs/va_definitions.html` (manual for
  physician reviewers). Only cause codes are definitions: the 62
  `VAs-NN.NN` codes and `VAs-99` (Cause of death unknown), 63 in all. Section
  headings (`VAs-01` ... `VAs-12`, "Non-communicable diseases") are groups,
  not codes, and are not stored; neither is `VAs-98` (Other and unspecified
  non-communicable disease), which the owner treats as a group, nor the
  group-level note under `VAs-12`.
- Stored in `mas_va_cause_definitions`, one row per cause code, listed in
  `va_code` order: `title`, `definition_html`, `is_active`, `source`,
  `updated_by`.
- `docs/` is not shipped in the image, so the parsed table is frozen in
  `resource/va_cause_definitions_who_2022.json`
  (`flask va-definitions generate-seed-json`). Migration `fba41e2f1f9d` and
  `flask seed run` load that file; both skip codes that already exist.
- `flask va-definitions import [PATH] [--force]` refreshes from the HTML.
  It upserts by `va_code`, never deletes or deactivates, and leaves a row an
  admin has edited (`updated_by` set) untouched unless `--force`, which
  overwrites it and clears `updated_by`.

## Who may read and edit

- Read: any user with a coder, coding tester, reviewer or admin role, through
  `GET /api/v1/va-definitions?q=` (active rows only, flat, in code order), the
  "VA Definitions" modal beside the cause selects, and the help page
  `/help/va-definitions`. `q` matches code, title and definition text,
  case-insensitively.
- Edit: global admins only, in the admin panel "VA Definitions"
  (`/admin/panels/va-definitions`): edit title and definition, activate or
  deactivate (confirmed in-page), add a new code (`VAs-NN.NN` or `VAs-99`).
  Codes are not renamed or deleted; deactivate instead.

## Definition for the selected ICD code

- On the coding screens (Step 1 immediate and antecedent, Step 2 conclusive,
  and the reviewer's selects), picking an ICD code shows the definition of the
  VA cause it maps to in a floating panel at the bottom right
  (`app/static/js/va_definition_panel.js`). It has no backdrop and takes no
  focus; closing it hides it until the next selection; no match shows nothing.
- `GET /api/v1/va-definitions/for-icd?code=&classification=` (same roles as
  above; classification is inferred from the code shape when omitted) returns
  `{icd_code, classification, va_code, title, definition_html}` or 404.
- An ICD code reaches a VA cause through the COD bucket mappings: ICD-10 in
  scheme `WHO_2022_VA`, ICD-11 in `WHO_2022_VA_2026` (`icd_classification =
  'icd11'`), fixed in `VA_DEFINITION_SCHEMES`. A bucket node `vas_01_02` is VA
  cause `VAs-01.02`; nodes that are not `vas_*` causes, and `vas_09_99`
  (not in the WHO table), have no definition. The exact code is tried first,
  then its three-character category (ICD-10) or its ancestors in
  `mas_icd11_mms` (ICD-11).

## Rich text

- Definitions are edited as formatted text in the shared editor
  `app/static/js/rich_text_editor.js` (Quill 2.0.3, vendored in
  `app/static/vendor/quill/`). One toolbar for every rich-text field: bold,
  italic, bullet list, numbered list, outdent, indent. Indent is saved as
  nested lists.
- The server sanitizes with `app/utils/rich_text.py::sanitize_rich_text`
  (nh3) on every admin write and on import. Allowed tags: `p`, `br`, `ul`,
  `ol`, `li`, `strong`, `b`, `em`, `i`. No attributes, links, styles or
  classes survive; `script` and `style` lose their content. The source's
  `NOTE` paragraphs are stored as italic paragraphs. A save returns the
  stored HTML and the editor reloads it, so the admin sees what was kept.
- The coder modal and help page insert the stored HTML as-is; code and
  title are always inserted as text.

## Audit

- Every admin write sets `updated_by` and `updated_at` and is written to the
  application log (`va definition created|updated`, code, changed fields,
  user id), as for other admin master-data edits such as ICD policy. No
  definition text is logged.
- Writes are JSON `POST`/`PATCH` under `/admin/api/va-definitions`, carrying
  the `X-CSRFToken` header.
