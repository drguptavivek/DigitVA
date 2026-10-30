---
title: VA Cause Definitions
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-30
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
- The ICD-11 DORIS screens (digitva-wy34) do the same: the DORIS editor
  (`_doris_certificate_editor.html`: certificate lines and the Step 2 final
  cause) and the masked Step 2 picker (`_masked_doris_final_cod.html`) each
  have a "VA Definitions" button that opens the modal, and the picked or
  confirmed ICD-11 code opens the floating panel with
  `classification=icd11`. Each include gets its own modal id (derived from the
  editor or form id) so two modals can share one page.
- Expo: the cause details (i) sheet shows the VA cause code, title and
  definition for the code through the app's API client
  (`getVaDefinitionForIcd`, `classification=icd11`). A 404 shows no VA cause; a
  failed lookup is silent. The definition is shown as plain text: tags are
  dropped and the common entities decoded, never injected as HTML.
- `GET /api/v1/va-definitions/for-icd?code=&classification=` (same roles as
  above; classification is inferred from the code shape when omitted) returns
  `{icd_code, classification, va_code, title, definition_html, source}` or
  404 when no mapping resolves. ICD-11 also returns `bucket_code`,
  `bucket_label`, `bucket_section` and `has_definition`. A bucket without a
  definition has `definition_html` `""` and `title` set to the bucket label;
  its `va_code` is the `VAs-` code of a `vas_*` node, else the node code.
- An ICD code reaches a VA cause through the COD bucket mappings: ICD-10 in
  scheme `WHO_2022_VA`, ICD-11 in `WHO_2022_VA_2026` (`icd_classification =
  'icd11'`), fixed in `VA_DEFINITION_SCHEMES`. A bucket node `vas_01_02` is VA
  cause `VAs-01.02`; nodes that are not `vas_*` causes, and `vas_09_99`
  (not in the WHO table), have no definition. The exact code is tried first,
  then its three-character category (ICD-10) or its ancestors in
  `mas_icd11_mms` (ICD-11). For ICD-11 this walk is replaced by the bucket
  rule in the next section.

## VA cause bucket for the selected ICD-11 code (owner, 2026-10-30, digitva-to74)

- **One rule with analytics.** The VA cause an ICD-11 code shows while it is
  being coded is the bucket the COD snapshot gives it
  (`_who_2026_bucket_sql`, [ICD-11 COD Bucket Schemes](icd11-cod-bucket-schemes.md),
  "Which mapping rows resolve"). That means the `WHO_2022_VA_2026` `icd11`
  rows in the all-ages scope (`age_scope IS NULL`, the scheme's only band),
  exact code first, then the nearest mapped ancestor. A post-coordinated value
  resolves by its primary stem. The walk stops at the nearest mapped node,
  whether or not that node has a definition: it never skips past it to an
  ancestor's VA cause. The snapshot, the server lookup and the offline pack
  share one SQL implementation. A test checks that all three give the same
  result for every catalogue code.
- **What shows.** Under the selected underlying cause, on the web DORIS
  screens and in Collect Plus, before and after Process: the bucket's section
  (parent node label) and `VA cause: <node label> (<VAs code, else node
  code>)`. The WHO definition follows when the node has one in
  `mas_va_cause_definitions`. Nodes without one (`vas_98`, `vas_09_99`,
  `other_gastrointestinal_diseases`) show the label and section only; no text
  is invented. A code with no bucket on its chain shows `VA cause: not
  mapped`, because it reports as `unmapped` in analytics. It is information
  only: an unmapped ICD-11 code is never blocked from selection, Process,
  save or submission, online or offline (owner, 2026-10-30), and the line is
  not a warning to confirm.
- **Fully offline in Collect Plus.** The app always reads the bucket from its
  bundled pack (`assets/va-definitions-WHO_2022_VA_2026.json`), in every mode,
  online included. The one exception is an online `/` cluster: only the
  server knows WHO's causing condition, so it asks the server and falls back
  to the pack's first stem. Offline, the engine supplies it. The pack records
  its content hash and the migration revision it was cut at.
  `tests/services/test_export_offline_va_definitions.py` fails when the
  committed pack differs from the database. That check needs a database with
  the ICD-11 catalogue loaded, such as dev at head, and skips on a `create_all`
  test database; regenerate and check the pack with every mapping or
  definition change. A mapping edited on a
  server after a build shows in the app only after the next pack and build.
  The browser uses the server lookup.
- **Display only.** The source ICD-11 code stays the record of truth. The
  bucket changes no stored value, provenance or selectability.
- **Scope.** Shown for ICD-11 (DORIS) coding only, in the scheme fixed in
  `VA_DEFINITION_SCHEMES`. Projects have no bucket-scheme column. ICD-10
  coding keeps the `WHO_2022_VA` lookup above, unchanged.

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
