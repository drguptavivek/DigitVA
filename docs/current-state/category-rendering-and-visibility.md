---
title: Category Rendering And Visibility
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-13
---

# Category Rendering And Visibility

## Purpose

This document maps the current category rendering path used by the coding and site PI
UI:

- which route serves each category
- which partial renders it
- which mapping source is used
- which fields matter for category presence
- which conditions must be met for the category to appear in the left nav

This is a current-state description of the running code, not a target-state design.

## Shared Render Pipeline

All category panels are served by [`app/routes/va_api.py`](../../app/routes/va_api.py)
through:

- `/<va_action>/<va_actiontype>/<va_sid>/<va_partial>`

Current route behavior:

- the render path now resolves form type from `va_submissions.va_form_id ->
  va_forms.form_type_id -> mas_form_types.form_type_code`
- category eligibility and previous/next traversal now come from
  `CategoryRenderingService`, which reads ordered role visibility from
  `mas_category_display_config`
- if `form_type_id` is not populated, the runtime falls back to the legacy
  `va_forms.form_type` value when it matches a registered active form type
- if neither link is available, the runtime falls back to the default form type
  `WHO_2022_VA`
- coder and reviewer views still start from the static coder mapping in
  [`app/utils/va_mapping/va_mapping_02_fieldcoder.py`](../../app/utils/va_mapping/va_mapping_02_fieldcoder.py)
  but now bridge in DB-backed categories that are visible in category config and
  missing from the static dict
- site PI view uses DB-backed site-PI mappings from
  [`app/services/field_mapping_service.py`](../../app/services/field_mapping_service.py)
  via `get_fieldsitepi()`
- category partial selection now branches by `mas_category_display_config.render_mode`
  for categories visible to the current role:
  - `table_sections` -> generic renderer in
    [`category_table_sections.html`](../../app/templates/va_formcategory_partials/category_table_sections.html)
  - `health_history_summary` -> generic renderer in
    [`category_health_history_summary.html`](../../app/templates/va_formcategory_partials/category_health_history_summary.html)
  - `attachments` -> hybrid renderer in
    [`category_attachments.html`](../../app/templates/va_formcategory_partials/category_attachments.html)
    using generic submission-data sections plus explicit workflow/result panels

Common filtering happens in
[`app/utils/va_render/va_render_06_processcategorydata.py`](../../app/utils/va_render/va_render_06_processcategorydata.py).

A mapped field contributes to rendered category content only if:

- the field exists in `va_submission.va_data`
- the value is not `None`
- the value is not string `dk`
- the value is not string `ref`
- if the field is one of `isNeonatal`, `isChild`, `isAdult`, the value is not `0`
- if the field is an attachment, the referenced file exists on disk

Additional render-time transforms:

- some fields are date-normalized
- some fields are datetime-normalized
- choice-coded fields are label-mapped
- some multi-select fields are expanded to mapped choice labels
- attachment fields are converted to media URLs
- `table_sections` categories now render subcategory sections generically from ordered
  DB config and reuse the same flip/info badge rules as the legacy static partials
- `health_history_summary` now renders positive diagnoses, absent diagnoses, and
  non-binary leftovers generically from category data instead of using a category-
  specific template
- `attachments` now renders narration/audio/images and document galleries generically
  from category data, while still appending explicit SmartVA / QA / COD workflow UI
- in `attachments`, file type detection is automatic by file extension
- image carousel behavior is now controlled by subcategory-level
  `MasSubcategoryOrder.render_mode`, currently seeded as `media_gallery` for
  `medical_documents` and `death_documents`
- attachment images now open in an in-page lightbox with close, zoom, and pan support
- `social_autopsy` in `table_sections` mode now also appends an app-owned Social
  Autopsy analysis form for coder coding flows
- coder/reviewer rendering uses a bridge path so DB-only categories such as
  `social_autopsy` do not render empty while the field-level coder config remains
  partially static

## Left Nav Visibility

The left nav is rendered by
[`app/templates/va_frontpages/va_coding.html`](../../app/templates/va_frontpages/va_coding.html).

Current visibility rules:

- the coding-page left nav is now rendered from `CategoryRenderingService`
- a category must be role-visible in `mas_category_display_config`
- a category must either:
  - be present in `va_submissions.va_category_list`, or
  - have `always_include = true` in `mas_category_display_config`
- this means `vainterviewdetails` is now site-PI-only because the category config
  marks it hidden for coder and reviewer
- `vanarrationanddocuments` is always shown because its category config sets
  `always_include = true`

`va_category_list` is built during preprocess in
[`app/utils/va_preprocess/va_preprocess_03_categoriestodisplay.py`](../../app/utils/va_preprocess/va_preprocess_03_categoriestodisplay.py).

Current preprocess rule:

- preprocess now resolves the effective form type from `va_form_id` using the same
  runtime form-type fallback chain
- preprocess now loads category field mappings and choice mappings from the DB-backed
  field mapping service for that form type
- a category is included if `va_render_processcategorydata(...)` returns at least one
  surviving mapped field
- `vanarrationanddocuments` is appended unconditionally

Important current limitation:

- left-nav visibility is stored at preprocess time
- actual panel content is recalculated again at render time
- if mappings or data filters change after sync, the nav and the panel can drift

Current UI behavior:

- the initial HTMX-loaded category now comes from the visible nav order:
  - preferred `is_default_start = true` category if visible
  - otherwise the first visible category by `display_order`

## Category Inventory

For each category below, "important fields" means the mapped field groups that
currently determine whether the category can produce any content. In practice, a
category appears when at least one of its mapped fields survives the shared filtering
rules above.

### `vainterviewdetails`

- Nav label: `Interview Details`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/vainterviewdetails`
- Partial:
  [`app/templates/va_formcategory_partials/vainterviewdetails.html`](../../app/templates/va_formcategory_partials/vainterviewdetails.html)
- Mapping source:
  - site PI: DB-backed `get_fieldsitepi()`
  - coder/reviewer: not reachable through normal nav because coder mapping has no
    `vainterviewdetails` entry and the left nav hides it unless `va_action ==
    "vasitepi"`
- Partial sections:
  - `interview`
  - `va_interviewer`
  - `va_respondent`
- Important mapped fields:
  - `va_interviewer`: `Id10010`, `Id10010a`, `Id10010b`, `Id10010c`
  - `interview`: `language`, `Id10012`, `Id10013`, `Id10011`, `Id10481`
  - `va_respondent`: `Id10007`, `Id10007a`, `Id10007b`, `Id10008`, `Id10009`
- Conditions to appear in left nav:
  - `vainterviewdetails` must be present in `va_category_list`
  - `va_action` must be `vasitepi`
- Effective trigger rule:
  - any surviving field in `va_interviewer`, `interview`, or `va_respondent`

### `vademographicdetails`

- Nav label: `Demographic / Risk Factors`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/vademographicdetails`
- Partial:
  [`app/templates/va_formcategory_partials/vademographicdetails.html`](../../app/templates/va_formcategory_partials/vademographicdetails.html)
- Partial sections:
  - `general`
  - `risk_factors`
- Important mapped fields:
  - `general`: `Site`, `unique_id`, `site_individual_id`, `Id10017`, `Id10018`,
    `Id10021`, `Id10023`, `isNeonatal`, `isChild`, `isAdult`, `Id10019`,
    `Id10058`
  - `risk_factors`: `Id10411`, `Id10413`, `Id10413_d`, `Id10413_a`, `Id10413_b`,
    `Id10414`, `Id10414_d`, `Id10414_a`, `Id10414_b`, `Id10487`
- Conditions to appear in left nav:
  - `vademographicdetails` must be present in `va_category_list`
- Effective trigger rule:
  - any surviving field in `general` or `risk_factors`
- Important nuance:
  - `isNeonatal`, `isChild`, and `isAdult` only count when their stored value is
    truthy (`1`, `1.0`)

### `vaneonatalperioddetails`

- Nav label: `Neonatal Period`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/vaneonatalperioddetails`
- Partial:
  [`app/templates/va_formcategory_partials/vaneonatalperioddetails.html`](../../app/templates/va_formcategory_partials/vaneonatalperioddetails.html)
- Partial sections:
  - `general`
  - `delivery`
  - `stillbirth`
  - `birth_weight`
  - `symptoms`
  - `physical_abnormalities`
  - `baby_mother`
- Important mapped fields:
  - `general`: `Id10354`, `Id10367`
  - `delivery`: `Id10387`, `Id10388`, `Id10389`, `Id10369`
  - `stillbirth`: `Id10104`, `Id10105`, `Id10110`, `Id10114`
  - `birth_weight`: `Id10366_check`, `Id10366`, `Id10363`, `Id10365`
  - `symptoms`: `Id10406`, `Id10284`, `Id10286`, `Id10287`
  - `physical_abnormalities`: `Id10370`, `Id10371`, `Id10372`, `Id10373`
  - `baby_mother`: `Id10391`, `Id10393`, `Id10395`, `Id10396`
- Conditions to appear in left nav:
  - `vaneonatalperioddetails` must be present in `va_category_list`
- Effective trigger rule:
  - any surviving field in any neonatal-period subcategory

### `vainjuriesdetails`

- Nav label: `Injuries`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/vainjuriesdetails`
- Partial:
  [`app/templates/va_formcategory_partials/vainjuriesdetails.html`](../../app/templates/va_formcategory_partials/vainjuriesdetails.html)
- Partial sections:
  - `default`
- Important mapped fields:
  - `Id10077`, `Id10077_a`, `Id10079`, `Id10082`, `Id10083`, `Id10084`,
    `Id10085`, `Id10089`, `Id10098`, `Id10099`, `Id10100`
- Conditions to appear in left nav:
  - `vainjuriesdetails` must be present in `va_category_list`
- Effective trigger rule:
  - any surviving field in the `default` injury field group

### `vahealthhistorydetails`

- Nav label: `Disease/Co-morbidity`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/vahealthhistorydetails`
- Partial:
  [`app/templates/va_formcategory_partials/vahealthhistorydetails.html`](../../app/templates/va_formcategory_partials/vahealthhistorydetails.html)
- Partial sections:
  - `medical_history`
  - `neonate`
- Important mapped fields:
  - `neonate`: `Id10351`, `Id10408`
  - `medical_history`: `Id10125`, `Id10126`, `Id10127`, `Id10128`, `Id10482`,
    `Id10132`, `Id10133`, `Id10134`, `Id10135`, `Id10137`
- Conditions to appear in left nav:
  - `vahealthhistorydetails` must be present in `va_category_list`
- Effective trigger rule:
  - any surviving field in `medical_history` or `neonate`
- Important partial behavior:
  - the partial groups many `medical_history` yes/no values into positive vs negative
    diagnosis summaries before rendering the detailed tables
  - in the admin Categories browser, `vahealthhistorydetails / medical_history` should
    be treated as a special subcategory because assigning a field there opts it into this
    summary behavior, not a plain query/response section

### `social_autopsy`

- Nav label: `Social Autopsy`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/social_autopsy`
- Partial:
  [`app/templates/va_formcategory_partials/category_table_sections.html`](../../app/templates/va_formcategory_partials/category_table_sections.html)
  with
  [`app/templates/va_formcategory_partials/_social_autopsy_analysis_form.html`](../../app/templates/va_formcategory_partials/_social_autopsy_analysis_form.html)
- Partial sections:
  - DB-configured Social Autopsy subcategories and fields
  - app-owned `Social Autopsy Analysis` form appended after the mapped sections
- Important mapped fields:
  - all fields assigned to category `social_autopsy` for the active form type
- Conditions to appear in left nav:
  - `social_autopsy` must be visible for the current role and have surviving mapped
    field data
- Important partial behavior:
  - the mapped Social Autopsy submission fields render through the generic
    `table_sections` pipeline
  - in coder coding flows, the category then appends the app-owned Social Autopsy
    analysis form
  - in the admin Categories browser, `social_autopsy` should be treated as a special
    category because it mixes dynamic submission rendering with an explicit workflow form

### `vageneralsymptoms`

- Nav label: `General Symptoms`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/vageneralsymptoms`
- Partial:
  [`app/templates/va_formcategory_partials/vageneralsymptoms.html`](../../app/templates/va_formcategory_partials/vageneralsymptoms.html)
- Partial sections:
  - `duration_of_illness`
  - `fever`
  - `skin_rash`
  - `yellow_discoloration`
  - `nutrition`
  - `puffiness`
  - `swelling`
- Important mapped fields:
  - `duration_of_illness`: `Id10123`, `Id10121`, `Id10122`, `Id10120`
  - `fever`: `Id10147`, `Id10148`, `Id10149`, `Id10150`
  - `skin_rash`: `Id10233`, `Id10234`, `Id10235`, `Id10236`
  - `yellow_discoloration`: `Id10265`, `Id10266`, `Id10267`
  - `nutrition`: `Id10268`, `Id10269`, `Id10252`, `Id10485`
  - `puffiness`: `Id10247`, `Id10248`
  - `swelling`: `Id10249`, `Id10250`, `Id10251`
- Conditions to appear in left nav:
  - `vageneralsymptoms` must be present in `va_category_list`
- Effective trigger rule:
  - any surviving field in any general-symptom subcategory

### `varespiratorycardiacsymptoms`

- Nav label: `Respiratory / Cardiac`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/varespiratorycardiacsymptoms`
- Partial:
  [`app/templates/va_formcategory_partials/varespiratorycardiacsymptoms.html`](../../app/templates/va_formcategory_partials/varespiratorycardiacsymptoms.html)
- Partial sections:
  - `cough`
  - `breathlessness`
  - `fast_breathing`
  - `breathing_pattern`
  - `chest_pain`
- Important mapped fields:
  - `cough`: `Id10153`, `Id10154`, `Id10155`, `Id10157`
  - `breathlessness`: `Id10159`, `Id10161`, `Id10162`, `Id10171`
  - `fast_breathing`: `Id10166`, `Id10167`
  - `breathing_pattern`: `Id10172`, `Id10173_nc`, `Id10173_a`
  - `chest_pain`: `Id10174`, `Id10175`, `Id10176`, `Id10179`
- Conditions to appear in left nav:
  - `varespiratorycardiacsymptoms` must be present in `va_category_list`
- Effective trigger rule:
  - any surviving field in any respiratory/cardiac subcategory

### `vaabdominalsymptoms`

- Nav label: `Abdominal`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/vaabdominalsymptoms`
- Partial:
  [`app/templates/va_formcategory_partials/vaabdominalsymptoms.html`](../../app/templates/va_formcategory_partials/vaabdominalsymptoms.html)
- Partial sections:
  - `diarrhoea`
  - `vomit`
  - `abdominal_pain`
  - `protuding_abdomen`
  - `mass_abdomen`
  - `urine_issues`
- Important mapped fields:
  - `diarrhoea`: `Id10181`, `Id10182`, `Id10183`, `Id10185`
  - `bleeding`: `Id10186`
  - `vomit`: `Id10188`, `Id10190_a`, `Id10189`, `Id10191`
  - `abdominal_pain`: `Id10194`, `Id10195`, `Id10196`, `Id10199`
  - `protuding_abdomen`: `Id10200`, `Id10201`, `Id10202`, `Id10203`
  - `mass_abdomen`: `Id10204`, `Id10205`, `Id10206`
  - `urine_issues`: `Id10223`, `Id10226`, `Id10224`
- Conditions to appear in left nav:
  - `vaabdominalsymptoms` must be present in `va_category_list`
- Effective trigger rule:
  - any surviving field in any abdominal subcategory
- Important partial nuance:
  - the mapping includes `bleeding`, but the current partial has no dedicated
    `bleeding` section, so that field group can influence category presence without
    being visibly rendered as its own table

### `vaneurologicalsymptoms`

- Nav label: `Neurological`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/vaneurologicalsymptoms`
- Partial:
  [`app/templates/va_formcategory_partials/vaneurologicalsymptoms.html`](../../app/templates/va_formcategory_partials/vaneurologicalsymptoms.html)
- Partial sections:
  - `headache`
  - `smell_taste`
  - `mental_confusion`
  - `unconcious`
  - `paralyses`
  - `stiff_painful_neck`
  - `convulsions`
  - `swallowing`
- Important mapped fields:
  - `headache`: `Id10207`
  - `smell_taste`: `Id10486`
  - `mental_confusion`: `Id10212`, `Id10213_a`, `Id10213`
  - `unconcious`: `Id10214`, `Id10216_b`, `Id10216`, `Id10217`
  - `paralyses`: `Id10258`, `Id10259`, `Id10260`
  - `stiff_painful_neck`: `Id10208`, `Id10209_b`, `Id10209`
  - `convulsions`: `Id10220`, `Id10222`, `Id10275`, `Id10276`
  - `swallowing`: `Id10261`, `Id10262_b`, `Id10262`, `Id10262_c`
- Conditions to appear in left nav:
  - `vaneurologicalsymptoms` must be present in `va_category_list`
- Effective trigger rule:
  - any surviving field in any neurological subcategory

### `vaskinmucosalsymptoms`

- Nav label: `Skin / Mucosal / Others`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/vaskinmucosalsymptoms`
- Partial:
  [`app/templates/va_formcategory_partials/vaskinmucosalsymptoms.html`](../../app/templates/va_formcategory_partials/vaskinmucosalsymptoms.html)
- Partial sections:
  - `ulcers`
  - `skin_rash`
  - `lumps`
  - `others`
- Important mapped fields:
  - `ulcers`: `Id10230`, `Id10231`, `Id10232_b`, `Id10232`
  - `skin_rash`: `Id10233`, `Id10234`, `Id10235`, `Id10236`
  - `lumps`: `Id10254`, `Id10255`, `Id10256`, `Id10257`
  - `others`: `Id10237`, `Id10238`, `Id10239`, `Id10240`
- Conditions to appear in left nav:
  - `vaskinmucosalsymptoms` must be present in `va_category_list`
- Effective trigger rule:
  - any surviving field in any skin/mucosal subcategory

### `vaneonatalfeedingsymptoms`

- Nav label: `Neonatal Specific`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/vaneonatalfeedingsymptoms`
- Partial:
  [`app/templates/va_formcategory_partials/vaneonatalfeedingsymptoms.html`](../../app/templates/va_formcategory_partials/vaneonatalfeedingsymptoms.html)
- Partial sections:
  - `feeding`
  - `physical_abnormalality`
  - `unresponsive`
- Important mapped fields:
  - `feeding`: `Id10271`, `Id10272`, `Id10273`, `Id10274_c`
  - `physical_abnormalality`: `Id10277`, `Id10278`, `Id10279`
  - `unresponsive`: `Id10281`, `Id10282`, `Id10283`
- Conditions to appear in left nav:
  - `vaneonatalfeedingsymptoms` must be present in `va_category_list`
- Effective trigger rule:
  - any surviving field in any neonatal-specific subcategory

### `vamaternalsymptoms`

- Nav label: `Maternal`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/vamaternalsymptoms`
- Partial:
  [`app/templates/va_formcategory_partials/vamaternalsymptoms.html`](../../app/templates/va_formcategory_partials/vamaternalsymptoms.html)
- Partial sections:
  - `general`
  - `pld_tr`
  - `antenatal`
  - `delivery`
- Important mapped fields:
  - `general`: `Id10296`, `Id10299`, `Id10300`, `Id10301`
  - `pld_tr`: `Id10302`, `Id10303`, `Id10305`, `Id10312`
  - `antenatal`: `Id10319`, `Id10317`, `Id10309`, `Id10320`
  - `delivery`: `Id10337`, `Id10332`, `Id10342`, `Id10343`
- Conditions to appear in left nav:
  - `vamaternalsymptoms` must be present in `va_category_list`
- Effective trigger rule:
  - any surviving field in any maternal subcategory

### `vahealthserviceutilisation`

- Nav label: `Health Service Utilization`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/vahealthserviceutilisation`
- Partial:
  [`app/templates/va_formcategory_partials/vahealthserviceutilisation.html`](../../app/templates/va_formcategory_partials/vahealthserviceutilisation.html)
- Partial sections:
  - `treatment`
  - `hcw_cod`
  - `mother_related`
- Important mapped fields:
  - `treatment`: `Id10418`, `Id10419`, `Id10420`, `Id10421`
  - `hcw_cod`: `Id10435`, `Id10436`
  - `mother_related`: `Id10446`
- Conditions to appear in left nav:
  - `vahealthserviceutilisation` must be present in `va_category_list`
- Effective trigger rule:
  - any surviving field in `treatment`, `hcw_cod`, or `mother_related`

### `vanarrationanddocuments`

- Nav label: `Narration / Documents / COD`
- Route: `/<va_action>/<va_actiontype>/<va_sid>/vanarrationanddocuments`
- Partial:
  [`app/templates/va_formcategory_partials/vanarrationanddocuments.html`](../../app/templates/va_formcategory_partials/vanarrationanddocuments.html)
- Partial sections:
  - `narration`
  - `death_registeration`
  - `medical_certs`
  - `medical_documents`
  - `death_documents`
  - `iv_final`
- Important mapped fields:
  - `narration`: `narr_language`, `Id10476_audio`, `imagenarr`, `Id10476`
  - `death_registeration`: `Id10070`, `Id10071`, `Id10072`
  - `medical_certs`: `Id10462`, `Id10463`, `Id10464`, `Id10465`
  - `medical_documents`: `md_im1` to `md_im30`
  - `death_documents`: `ds_im1` to `ds_im5`
  - `iv_final`: `comment`
- Conditions to appear in left nav:
  - none beyond being on the coding page; this category is always shown
- Effective trigger rule for actual content:
  - any surviving field in the narration/documents mapping will render content
  - attachment-backed sections only render if the referenced file exists on disk
- Important mapping nuance:
  - site PI mapping includes `death_registeration`
  - coder static mapping omits `death_registeration`
- Important partial behavior:
  - the active runtime path now uses
    [`category_attachments.html`](../../app/templates/va_formcategory_partials/category_attachments.html),
    not the legacy category-specific partial above
  - audio fields render as players
  - narration image opens in the shared attachments lightbox
  - `medical_documents` and `death_documents` are seeded with subcategory
    `render_mode = media_gallery`, which drives their carousel rendering
  - in coding mode with NQA enabled, `Narrative Quality Assessment` appears
    immediately before `Symptoms on VA Interview`

## Current Gaps And Mismatches

- `vaabdominalsymptoms` mapping contains `bleeding`, but the partial does not render a
  dedicated `bleeding` section
- `vanarrationanddocuments` has a subcategory mismatch between site-PI and coder
  mappings: `death_registeration` exists only in the site-PI mapping
- coder/reviewer category rendering still depends on the static
  `va_mapping_02_fieldcoder.py` dict even though site-PI and preprocess category mapping
  are now form-type aware
- left-nav visibility is derived from stored preprocess output, while panel content is
  recalculated at request time
