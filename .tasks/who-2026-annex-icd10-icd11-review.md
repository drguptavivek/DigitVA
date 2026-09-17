# Review WHO 2026 Annex 1 ICD-10 changes and ICD-11 correspondences

- **Status:** pending
- **Priority:** medium
- **Created:** 2026-09-16
- **Goal:** Decide whether the ICD-10 coding allowability policy and the coder-facing VA codes PDF should be regenerated from the 2026 WHO annex, and whether ICD-11 support is wanted.
- **Plan:** [`docs/planning/icd11-self-hosted-api-and-ect-plan.md`](../docs/planning/icd11-self-hosted-api-and-ect-plan.md) (self-hosted WHO ICD API container plus Embedded Coding Tool; branch `icd-11`)
- **Reference doc:** [`docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who-2022-va-cause-list-icd10-icd11.md`](../docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who-2022-va-cause-list-icd10-icd11.md)

## Context

The 2026 WHO manual for physician reviewers (Annex 1, Table A1) publishes the
WHO 2022 VA cause list with both ICD-10 and ICD-11 codes. Its ICD-10 column
differs from the earlier extract used in this repo in four places (VAs-98,
VAs-10.99, VAs-99, VAs-12.99). The largest change is VAs-99, which now covers
R00-R09, R11-R94 and R96-R99 instead of R95-R99 only.

The app's ICD-10 coding allowability policy was generated from the earlier
crosswalk workbook and has not been re-derived from the 2026 annex. The app has
no ICD-11 catalog, and nothing in the app reads the new reference files.

## References

- `docs/policy/who-2022-icd10-coding-allowability.md`
- `docs/policy/icd10-reference-catalog.md`
- `docs/icd-causegrp-mappings/migration-artifacts/README.md`
- `app/static/WHO_2022_VA_CODES.pdf` (coder-facing extract, ICD-10 only)
- `docs/kb/WHO_VA_2022_Docs/2026 - pcva_manual-for-physician-reviewers.pdf`

## Expected Scope

1. Compare the reviewed policy JSON with the 2026 annex ICD-10 ranges and list
   the codes whose selectability or WHO bucket would change.
2. Decide with the clinical lead whether to adopt the 2026 ranges. If yes,
   update the policy doc first, then regenerate the policy JSON and bucket
   mapping through the existing generator rather than by hand.
3. Replace or supplement `app/static/WHO_2022_VA_CODES.pdf` with a version that
   carries the 2026 ranges and, if wanted, the ICD-11 column.
4. ICD-11 support is planned in `docs/planning/icd11-self-hosted-api-and-ect-plan.md`:
   self-hosted `whoicd/icd-api` container, `mas_icd11_mms` master with a
   migration plan, Embedded Coding Tool in the coder panels behind an
   authenticated same-origin proxy, and expansion of the annex ranges into
   VA bucket rows. The WHO Simple Tabulation exports (2026-01 and 2025-01
   releases, a development snapshot, and WHO's change list between the two
   releases) are frozen under
   `docs/icd-causegrp-mappings/migration-artifacts/icd11-mms-*/`; the catalog
   is seeded from the release export, not from the API. WHO's ICD-10 to
   ICD-11 mapping tables and ICD-11 mortality tabulation list for the same
   release are frozen beside them for bucket cross-checks and reporting.
   Start with the staging spike in that plan.
