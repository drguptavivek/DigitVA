---
title: ICD-11 in the Coding Screen — Form-Level Classification and Optional Step 1
doc_type: planning
status: in-progress
owner: engineering
last_updated: 2026-09-24
---

# ICD-11 in the Coding Screen — Form-Level Classification and Optional Step 1

## Requirement (as stated 2026-09-17)

1. A **form-level setting** chooses `ICD-10` or `ICD-11`. Coders see the
   matching code search in the coding screens (Step 1 immediate/antecedent
   COD, final conclusive COD, reviewer initial/final COD).
2. A **project-level setting** lets a project skip the pre-SmartVA human
   ICD grade (Step 1). When set, the coder goes straight to the page that
   shows the SmartVA summary and enters the final COD.
3. ICD-11 codes get the **same age and sex restriction policy** as ICD-10
   (`is_coding_selectable`, `sex_selectable`, `age_group_selectable`,
   `restriction_note`), enforced server-side on search and on save.

## Relationship to the existing ICD-11 plan

`docs/planning/icd11-self-hosted-api-and-ect-plan.md` proposes the WHO ICD
API container and the Embedded Coding Tool. This plan takes only its
**catalog** piece (`mas_icd11_mms` seeded from the frozen 2026-01 Simple
Tabulation export) and reuses the ICD-10 coding pattern already in the app:
local catalog table + policy flags + `/api/v1/...` search filtered by
submission age/sex + Select2 in the partials. No WHO container, no ECT, no
runtime WHO dependency. The container/ECT remain a later, optional upgrade.

## Current state (verified 2026-09-17)

- ICD-10 catalog: `mas_icd10_2019_2` (`app/models/mas_icd10_2019_2.py`) with
  policy columns; service `app/services/icd10_2019_2_service.py`; routes
  `app/routes/api/icd10.py`; admin browser/policy editor in `app/routes/admin.py`.
- Coding screen: `app/routes/va_form.py::renderpartial`, partials
  `vainitialasses.html` (Step 1) and `vafinalasses.html` (SmartVA summary +
  conclusive COD). Both hard-code the ICD-10 search URL, the WHO ICD-10
  browser link and the `WHO_2022_VA_CODES.pdf` modal. Entry is
  `va_formcategory_partials/_va_cod_assessment_panel.html`, which loads Step 1
  unless an initial assessment already exists.
- Reviewer track: `app/services/reviewer_coding_service.py`
  (`submit_reviewer_initial_cod`, `submit_reviewer_final_cod`); reviewer final
  COD currently **requires** a reviewer initial COD.
- COD values are stored as free text `"<CODE> <title>"` in
  `va_initial_assessments`, `va_final_assessments`,
  `va_reviewer_initial_assessments`, `va_reviewer_final_assessments`.
  Validation extracts the code with `^[A-Z]\d{2}(\.\d+)?`
  (`_CODING_VALUE_CODE_RE`); the analytics MV and bucket reporting use the
  same shape (`submission_analytics_mv.py` line ~245). ICD-11 codes
  (`1A00`, `BA00.1`, `2C25.Z`) do **not** match this regex, so they would
  silently yield `NULL` in `final_icd` and stay unbucketed.
- Workflow: `mark_coder_finalized` already allows `coding_in_progress ->
  coder_finalized`, and `va_final_assessments.source_initial_assessment_id`
  is nullable. Skipping Step 1 is workflow-compatible without state changes.
- Form settings today live on `map_project_site_odk` (one row per
  project-site ODK form, carries `form_type_id`, edited in the admin
  "Project Forms" panel). `mas_form_types` is the global form-type registry
  (`WHO_2022_VA`). Project settings live on `va_project_master` and are edited
  in the admin "Projects" panel via a JSON API.
- WHO ICD-11 target list for VA (65 causes with ICD-11 ranges):
  `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_cause_list_icd10_icd11.csv`.

## Decisions to confirm before implementation

> **D1 superseded (owner, 2026-09-24).** The classification is a project
> setting, `va_project_master.icd_classification` (`icd10` | `icd11` |
> `selectable`); the per-form column is deprecated. See
> docs/policy/va-form-project-configuration.md ("5. ICD classification").

| # | Question | Recommendation |
|---|---|---|
| D1 | What is "form level"? | `map_project_site_odk.icd_classification` (`icd10` \| `icd11`, default `icd10`), edited in the Project Forms panel. The same `WHO_2022_VA` form type can be ICD-10 in one project-site and ICD-11 in another. |
| D2 | Does "skip Step 1" also apply to the reviewer track? | Yes, one project setting `skip_initial_cod_assessment` governs both coder Step 1 and reviewer initial COD. **Resolved 2026-09-19:** confirmed as recommended; one project setting `skip_initial_cod_assessment` governs coder Step 1 and reviewer initial COD. |
| D3 | Source of ICD-11 allowability | Selectable set = expansion of the WHO 2026 annex ICD-11 ranges over `mas_icd11_mms` linearization order (stem codes only). Age/sex exceptions mirror the ICD-10 policy per VA cause (neonatal causes -> `neonate`, maternal -> `female`, etc.). Shipped as a generated policy JSON like ICD-10, editable per code in the admin panel. Needs clinical sign-off before production. **Resolved 2026-09-19:** confirmed on record in commit `d9ae3b1` (2026-09-17): the WHO 2026 annex ICD-11 ranges are the authoritative ICD-11 source; the ICD-10 route (WHO's ICD-11 to ICD-10 mapping tables, then the ICD-10 policy) is advisory only, a cross-check whose disagreements go to clinical review. The curated source is therefore the WHO 2026 annex cause list already in the repo, `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_cause_list_icd10_icd11.csv` (65 VA causes, each with its ICD-11 ranges). No per-code ICD-11 policy JSON exists on any branch (verified 2026-09-19: main, `origin/icd-11`, `claude/eloquent-gagarin-83c118`, `claude/kind-boyd-a06575`; the catalog migration seeds every row `unreviewed`, unselectable). The policy is produced by expanding those ranges over `mas_icd11_mms` linearization order (stem codes) with the same two rules already recorded for ICD-10: **a more specific code listed under one VA cause wins over a broader range it falls inside** (`docs/policy/who-2022-icd10-coding-allowability.md:173`), and **the 2026 annex mapping is its own scheme with its own JSON**, separate from the earlier mapping, exactly as `WHO_2022_VA_2026` was kept apart from `WHO_2022_VA` for ICD-10. Age/sex restrictions mirror the ICD-10 policy per VA cause. Exported in the CLI's policy JSON format as a draft the owner reviews, then checked in as `who_2022_icd11_mms_2026_01_policy_reviewed.json` under `docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd-cod-2026-revision/` next to the ICD-10 reviewed file. The reviewed file, not the generator, is authoritative. |
| D4 | Record-level classification stamp | Add nullable `icd_classification` to the four assessment tables (backfilled `icd10`). Records stay self-describing if a form's setting changes later. |
| D5 | Changing a form from ICD-10 to ICD-11 mid-project | Allowed. Existing records keep their stamp; new coding and recodes use the current form setting. Mixed classification within one project is reported per record. **Resolved 2026-09-19:** allowed as recommended; existing assessments keep their `icd_classification` stamp, new coding and recodes use the current setting, and reports show classification per record. |
| D6 | Bucket reporting for ICD-11 | Out of scope here. Until an ICD-11 bucket mapping exists, ICD-11-coded deaths show `final_icd = NULL` and are reported as unbucketed. Tracked as a follow-up. **Confirmed 2026-09-17:** when built, the WHO 2026 annex ICD-11 ranges are the authoritative source for ICD-11 to VA bucket assignment; translating through WHO's ICD-11 to ICD-10 mapping table is advisory only, a cross-check that routes disagreements to clinical review. **Resolved 2026-09-19:** already confirmed 2026-09-17, restated as closed; the ICD-11 to VA bucket mapping is a separate scheme JSON (the ICD-11 counterpart of `WHO_2022_VA_2026`), never merged into an ICD-10 scheme, with the specific-beats-range rule applied when building it. |

## Design

### 1. Catalog: `mas_icd11_mms` (additive migration)

Columns as in the infra plan §2: `release`, `linearization_uri` (unique per
release), `foundation_uri`, `code`, `block_id`, `title`, `class_kind`,
`depth_in_kind`, `chapter_no`, `is_residual`, `is_leaf`, `primary_tabulation`,
`coding_note`, `sort_order`, `parent_linearization_uri`, plus DigitVA policy
fields identical in name and semantics to `mas_icd10_2019_2`:
`is_coding_selectable`, `sex_selectable`, `age_group_selectable`,
`policy_status`, `restriction_note`, `is_active`, timestamps. Primary key
`(release, linearization_uri)`; index on `code`.

Importer `app/services/icd11_mms_service.py::import_icd11_mms_from_export`
reads the frozen tab-separated export in streaming fashion, idempotent
(upsert on key, missing rows -> `is_active=false`, never deleted). CLI
`flask icd11 import` and `flask icd11 policy-import/export`, mirroring
`app/commands/icd10.py`. Seeded in the migration from a checked-in generated
CSV, following `docs/policy/icd10-reference-catalog.md`.

### 2. Shared coding-value helpers

- `_CODING_VALUE_CODE_RE` becomes classification-aware: ICD-10 pattern as
  today; ICD-11 pattern `^\s*([0-9A-Z][A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,2})?)\b`.
- New `app/services/icd_coding_service.py` with
  `get_icd_classification_for_submission(va_sid)` (submission -> form ->
  `map_project_site_odk`), `validate_coding_value_for_submission(va_sid, value)`
  that dispatches to the ICD-10 or ICD-11 validator, and
  `search_coding_choices(va_sid, query)`. Age/sex context logic
  (`_coding_age_group_for_submission`, `_coding_sex_for_submission`,
  `_coding_policy_clause`) moves to this shared module and is used by both.
- Callers switch from `validate_icd10_2019_2_coding_value_for_submission` to
  the dispatcher: `va_form.py` (Step 1, final), `reviewer_coding_service.py`.

### 3. API and UI

- `GET /api/v1/icd11/coding/<va_sid>/search` (same auth and shape as the
  ICD-10 coding search) and a single `GET /api/v1/icd/coding/<va_sid>/search`
  that dispatches by classification. The partials call the dispatcher, so
  the templates need no per-classification URL.
- Partials render a `classification` variable: label text ("ICD-10" /
  "ICD-11"), browser link (`https://icd.who.int/browse10/2019/en` vs
  `https://icd.who.int/browse/2026-01/mms/en`), and the reference modal
  (`WHO_2022_VA_CODES.pdf` for ICD-10; for ICD-11 a generated
  `WHO_2022_VA_CODES_ICD11.pdf` from the annex CSV, or the WHO 2026 manual
  pages if the PDF is not ready). WHO attribution string shown for ICD-11.
- Admin: ICD-11 browser and policy editor panel cloned from the ICD-10 one.
  **Done (2026-09-21):** `/admin/panels/icd11-browser` now has the ICD-10
  panel's filters, status dots, counters, editable per-category policy
  (including `policy_status`), previewed JSON import, and JSON/XLSX export,
  sharing the CLI's policy JSON format. See
  docs/policy/icd11-reference-catalog.md "Curation Path".

### 4. Settings

- `map_project_site_odk.icd_classification` String(8) NOT NULL default
  `icd10`; exposed in the Project Forms panel and its API.
- `va_project_master.skip_initial_cod_assessment` Boolean NOT NULL default
  false; exposed in the Projects panel via `_serialize_project` and the
  update route, next to `coding_intake_mode`.

### 5. Skip Step 1 behaviour

- `_va_cod_assessment_panel.html`: when the project skips Step 1, load
  `vafinalasses` directly for active coding sessions.
- `vafinalasses.html` and the final-COD branch already tolerate a missing
  initial assessment; the "Step 1" block is hidden when skipped.
- Reviewer: `submit_reviewer_final_cod` waives the reviewer-initial
  requirement when the project skips Step 1; the reviewer panel hides the
  reviewer Step 1 form.
- Data-manager and reporting surfaces that show Step 1 columns show a blank.
- Policy doc `docs/policy/coding-workflow-state-machine.md` gains a section
  "Optional Step 1"; `coder_step1_saved` is simply never written for such
  projects.

### 6. Record stamp

`icd_classification` String(8) nullable on `va_initial_assessments`,
`va_final_assessments`, `va_reviewer_initial_assessments`,
`va_reviewer_final_assessments`; migration backfills `icd10`. Set on every
new save from the form setting. Exports (`data_management_service.py`,
`submission_analytics_mv.py`) expose it as a column.

## Migration and data-loss review

All changes are additive: one new table, two new setting columns with
defaults, four nullable stamp columns with a backfill. No rewrites of
existing COD text. Rollback = drop the added columns/table. Frozen WHO
export is read-only input.

## Verification

- Unit: ICD-11 importer on an excerpt; regex/code extraction for both
  classifications; policy clause for age/sex; dispatcher picks the right
  catalog per form.
- Route tests: ICD-11 coding search (auth, CSRF where applicable, age/sex
  filtering); Step 1 save rejects an ICD-10 code on an ICD-11 form and vice
  versa; final COD on a skip-Step-1 project moves
  `coding_in_progress -> coder_finalized` with `source_initial_assessment_id`
  null; reviewer final COD without reviewer initial on such a project.
- Admin API tests for both settings.
- Manual: coder on an ICD-11 form sees ICD-11 search and browser link; project
  with skip enabled lands on the SmartVA summary page first.

## Phases

1. **Done (2026-09-17).** Catalog table (`mas_icd11_mms`), importer
   (`app/services/icd11_mms_service.py`), CLI (`flask icd11 ...`), migration
   `b6edb1b7d01a` seeded from the checked-in generated CSV, read-only admin
   browser (`app/routes/admin_icd11.py`,
   `app/templates/admin/panels/icd11_browser.html`; no coding-screen UI
   change). See docs/policy/icd11-reference-catalog.md. The browser became
   the policy editor (ICD-10 panel parity) on 2026-09-21; see section 3.
2. **Partially done (2026-09-17).** `map_project_site_odk.icd_classification`
   (migration `f4b8dd6e3568`, decision D1 implemented as recommended) is
   wired into the Project Forms admin panel/API, defaulting to `icd10`.
   Decision D4 (record-level `icd_classification` stamp on the four
   assessment tables) is implemented in spirit as a shared, classification-
   aware helper module (`app/services/icd_coding_value.py`:
   `ICD10_CODE_RE`/`ICD11_CODE_RE`/`extract_icd_code`/
   `get_icd_classification_for_submission`), but the stamp columns
   themselves are **not yet added** to `va_initial_assessments`,
   `va_final_assessments`, `va_reviewer_initial_assessments`, or
   `va_reviewer_final_assessments` — deferred to when phase 3 actually
   writes ICD-11 values into those tables. D1 and D4 are implemented as
   recommended above, pending the lead's confirmation.
3. Shared dispatcher, ICD-11 search API, partial rendering by classification,
   validation in coder and reviewer paths.
4. Skip Step 1 (coder, reviewer, panel, policy doc).
5. Allowability policy JSON for ICD-11 (annex expansion + age/sex mirror),
   clinical sign-off, policy doc `docs/policy/who-2022-icd11-coding-allowability.md`.
6. Follow-ups (separate issues): ICD-11 bucket mapping, export columns,
   WHO container/ECT.

## References

- `docs/planning/icd11-self-hosted-api-and-ect-plan.md`
- `docs/policy/icd10-reference-catalog.md`
- `docs/policy/who-2022-icd10-coding-allowability.md`
- `docs/policy/coding-workflow-state-machine.md`
- `docs/policy/final-cod-authority.md`
- `docs/icd-causegrp-mappings/migration-artifacts/icd11-mms-2026-01-base-2026-09-16/README.md`
