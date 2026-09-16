# Review WHO 2026 Annex 1 ICD-10 changes and ICD-11 correspondences

- **Status:** pending
- **Priority:** medium
- **Created:** 2026-09-16
- **Goal:** Decide whether the ICD-10 coding allowability policy and the coder-facing VA codes PDF should be regenerated from the 2026 WHO annex, and whether ICD-11 support is wanted.
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
4. Scope ICD-11 separately: it needs an ICD-11 MMS code master (WHO ICD API), a
   `mas_icd11_*` table with a migration plan, and expansion of the annex ranges
   into selectable codes.
