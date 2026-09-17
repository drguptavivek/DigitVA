# ICD-11 in the coding screen

- Status: parked (2026-09-17) until the organization model phases land; decisions D1–D6 recommended, not yet confirmed
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

Phase 1 catalog + importer + migration; Phase 2 settings + record stamp;
Phase 3 dispatcher + ICD-11 search + partials; Phase 4 skip Step 1;
Phase 5 ICD-11 allowability policy JSON with clinical sign-off.
Follow-ups: ICD-11 bucket mapping, export columns, WHO container/ECT.
