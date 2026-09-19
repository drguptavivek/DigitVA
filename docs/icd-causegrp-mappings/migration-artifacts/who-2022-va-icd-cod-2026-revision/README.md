---
title: WHO 2022 VA ICD And COD 2026 Revision Migration Artifacts
doc_type: migration-artifact
status: active
owner: engineering
last_updated: 2026-09-19
---

# WHO 2022 VA ICD And COD 2026 Revision Migration Artifacts

This folder contains the fixed inputs for the 2026-09-18 adoption of the WHO
2026 manual for physician reviewers' Annex 1 Table A1 ICD-10 ranges. It
supersedes nothing under `who-2022-va-icd-cod-2026-04-27/`: that folder's
artifacts remain the source for the live `WHO_2022_VA` scheme, unchanged.
This folder is the source for a new, coexisting `WHO_2022_VA_2026` scheme and
a regenerated global ICD-10 coding-selectability policy.

See `.tasks/who-2026-annex-icd10-icd11-review.md` (Resolution section,
2026-09-18) for the full decision record, and
`docs/policy/who-2022-icd10-coding-allowability.md` ("2026 Annex Adjustments")
for the policy rules these artifacts implement.

Files:

- `who_2022_icd10_2019_2_policy_reviewed.json`
  - global ICD-10 coding-selectability policy, 2488 items
  - built from `who-2022-va-icd-cod-2026-04-27/who_2022_icd10_2019_2_policy_reviewed.json`
    (2380 items) plus 108 additive items: `G43`-`G47`, `K72`/`K73`/`K75`/`K76`,
    13 detailed `K70.x`/`K71.x` codes excluding the `VAs-06.02` liver-cirrhosis
    carve-out (`K70.2`, `K70.3`, `K71.7`), `R00`-`R09` minus `R08` (does not
    exist), and `R11`-`R94` minus `R10` (reserved to a Gastrointestinal
    disorders bucket)
  - this is a global, table-wide replacement import: there is no per-scheme
    partition for `mas_icd10_2019_2`, so importing this file changes ICD-10
    coding-selectability for every project
- `WHO_2022_VA_Bucket_Mapping_document_derived_2026_revision.xlsx`
  - source workbook for the new `WHO_2022_VA_2026` COD bucket scheme
  - built from `who-2022-va-icd-cod-2026-04-27/WHO_2022_VA_Bucket_Mapping_document_derived.xlsx`
    (2380 rows) plus:
    - the 108 codes above, bucketed to `VAs-98`/`VAs-99` by default
    - `R95` moved from `VAs-99` ("Cause of death unknown") to `VAs-10.99`
      ("Other and unspecified perinatal cause of death"); selectability
      unchanged (infant-only, both sexes)
    - 34 rows carrying forward manual bucket overrides that already existed
      in the live `WHO_2022_VA` scheme (`mapping_version=3`) at the time this
      folder was built, recovered from that scheme's node hierarchy so this
      revision does not regress prior clinical curation. 7 of those overrides
      differ from what a blanket annex-range assignment would have produced
      (`G46`, `G47`, `K72`, `K73`, `K75`, `K76`, `R50`); 10
      (`I11`, `I46`, `I50`, `K64`, `K70`, `R10`, `U07`, `Y91`, `UU1`, `UU2`)
      exist only as bucket-mapping rows and are not ICD-10 coding-selectable
      today — that is unchanged here, only their existing bucket coverage was
      replicated

Fresh databases get both changes from migration `c5f2a8d1e9b3`
(`migrations/versions/c5f2a8d1e9b3_adopt_who_2026_annex_icd10_ranges.py`). It is
idempotent and additive: it marks the 108 codes selectable only where they are
not already selectable, and creates `WHO_2022_VA_2026` only if it does not
exist, so existing deployments keep any later admin edits. Its downgrade is a
deliberate no-op.

The commands below are the manual equivalent, and the way to re-apply the
artifacts as a full replacement (`policy-import` resets every code absent from
the JSON, so use it knowingly). Regeneration commands (inside `minerva_app_service`):

```
uv run flask icd10 policy-import --path=docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd-cod-2026-revision/who_2022_icd10_2019_2_policy_reviewed.json
uv run flask cod-buckets import-who-2022-va-2026
```

The migration should read from this folder only. Source/review workbooks
outside this folder may continue to evolve independently.
