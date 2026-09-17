# ICD-11 in the coding screen

- Status: in progress (2026-09-17) — phases 1–2 implemented (catalog, importer,
  CLI, migration, read-only admin browser, `icd_classification` setting,
  classification-aware code regex/helper); phases 3–6 not started. Decisions
  D1 and D4 implemented as recommended; D2, D3, D5, D6 still pending the
  lead's confirmation.
- Priority: high
- Created: 2026-09-17

## Goal

Form-level ICD-10/ICD-11 classification, project-level option to skip the
pre-SmartVA Step 1 human ICD grade, and ICD-11 age/sex allowability policy
mirroring ICD-10.

## Context

Plan: `docs/planning/icd11-coding-screen-integration-plan.md` (phases 1–6,
decisions table). Reuses the ICD-10 local-catalog pattern; no WHO container.

## References

- `app/routes/va_form.py` (Step 1 / final COD branches)
- `app/services/icd10_2019_2_service.py`, `app/routes/api/icd10.py`
- `app/services/reviewer_coding_service.py`
- `app/models/map_project_site_odk.py`, `app/models/va_project_master.py`
- `app/templates/va_form_partials/vainitialasses.html`, `vafinalasses.html`
- `app/templates/va_formcategory_partials/_va_cod_assessment_panel.html`

## Expected Scope

Phase 1 catalog + importer + migration — **done**: `mas_icd11_mms`
(`app/models/mas_icd11_mms.py`), importer/service
(`app/services/icd11_mms_service.py`), migration `b6edb1b7d01a`, seed CSV
(`resource/icd11_mms_2026_01_hierarchy.csv`), CLI (`app/commands/icd11.py`),
read-only admin browser (`app/routes/admin_icd11.py`,
`app/templates/admin/panels/icd11_browser.html`).

Phase 2 settings + record stamp — **partially done**: `icd_classification`
on `map_project_site_odk` (migration `f4b8dd6e3568`) is done, wired into the
admin Project Forms panel/API, and
`app/services/icd_coding_value.py::get_icd_classification_for_submission`
resolves it per submission. Classification-aware code regex
(`ICD10_CODE_RE`/`ICD11_CODE_RE`/`extract_icd_code`) is done and
`icd10_2019_2_service.py` uses it. Still open from phase 2: the
`icd_classification` stamp on the four assessment tables
(`va_initial_assessments` etc.) and `va_project_master.skip_initial_cod_assessment`
are not implemented (they belong to phase 2/4 per the plan's design section
but were not required by this session's scope).

Phase 3 dispatcher + ICD-11 search API + partials; Phase 4 skip Step 1;
Phase 5 ICD-11 allowability policy JSON with clinical sign-off — **not
started**. Coder-facing coding screens still always use ICD-10 regardless of
`icd_classification`.

Follow-ups: ICD-11 bucket mapping, export columns, WHO container/ECT.
