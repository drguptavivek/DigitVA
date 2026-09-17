---
title: ICD-11 Reference Catalog Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-17
---

# ICD-11 Reference Catalog Policy

## Purpose

Define how DigitVA stores and refreshes its ICD-11 MMS hierarchy reference
catalog, mirroring `docs/policy/icd10-reference-catalog.md` for the ICD-11
release.

## Policy

1. DigitVA stores the ICD-11 MMS linearization hierarchy as master reference
   data in `mas_icd11_mms`, one row per `(release, linearization_uri)`.
2. The authoritative structure source for the current release (`2026-01`) is
   the checked-in, frozen WHO Simple Tabulation export under
   `docs/icd-causegrp-mappings/migration-artifacts/icd11-mms-2026-01-base-2026-09-16/`
   (`SimpleTabulation-ICD-11-MMS-en.txt`) and the generated hierarchy CSV
   derived from it (`resource/icd11_mms_2026_01_hierarchy.csv`).
3. Fresh schema creation for `mas_icd11_mms` must seed the table from the
   checked-in generated hierarchy CSV during migration.
4. The reference catalog stores only hierarchy and local policy fields needed
   for app behavior; DigitVA does not mirror all WHO descriptive metadata
   (e.g. `BrowserLink`, `Grouping1..5` are not stored).
5. Import must be idempotent, upserting on `(release, linearization_uri)`.
6. Re-running the import must:
   - update structural hierarchy fields for entities still present in the
     source release
   - insert newly introduced entities
   - mark missing entities inactive instead of deleting them
7. Import must not require a database reset or table truncate.
8. Existing local policy curation must be preserved by default on rerun.
9. Policy fields may be refreshed from source only through an explicit
   operator action (`--apply-policy-columns` on `flask icd11 import`, which
   resets them to unreviewed rather than reading policy from WHO — WHO's
   export carries no DigitVA policy data).
10. A release upgrade (e.g. `2026-01` to a later release) is a new frozen
    export folder plus a new `release` value inserted as new rows, never an
    in-place rewrite of a prior release's rows.

## Parsing Rules (frozen 2026-01 export)

- Rows are split strictly on `\r\n`; coding notes may contain bare embedded
  line feeds, so splitting on any `\n` would produce spurious fragment rows.
- Each row is then parsed as tab-delimited CSV (title cells are quoted).
- `Title` carries WHO's `- ` depth-indent prefix per level; the importer
  strips it.
- `Parent` gives the parent entity's Foundation URI (empty only for the 28
  chapters); the importer resolves it to a `parent_linearization_uri` via an
  in-memory foundation-URI-to-linearization-URI map built during the import
  pass.
- `Primary tabulation` is stored as-is; WHO's readme leaves its meaning
  undefined, so it is informational only and is not used for any DigitVA
  policy decision.

Full column semantics:
`docs/icd-causegrp-mappings/migration-artifacts/icd11-mms-2026-01-base-2026-09-16/README.md`.

## Local Policy Scope

DigitVA may curate coding behavior in the same table using fields identical
in name and semantics to `mas_icd10_2019_2`:

- `is_coding_selectable`
- `sex_selectable`
- `age_group_selectable`
- `policy_status`
- `restriction_note`

Unlike ICD-10, ICD-11 categories receive **no default selectable values** on
import — every category starts `is_coding_selectable = NULL`
(`policy_status = "unreviewed"`) until curated. The ICD-11 selectable set and
its age/sex exceptions are a pending clinical decision (D3 in
`docs/planning/icd11-coding-screen-integration-plan.md`), tracked as
`docs/policy/who-2022-icd11-coding-allowability.md` (not yet written).

Policy fields are editable only on `class_kind = "category"` rows; chapters
and blocks are structural hierarchy rows with no coding policy.

## Curation Path (phases 1-2)

Only the CLI curates ICD-11 policy for now:

```bash
flask icd11 policy-export --release 2026-01 --output policy.json
flask icd11 policy-import policy.json --release 2026-01
```

The admin ICD-11 browser panel (`/admin/panels/icd11-browser`) is read-only:
hierarchy browsing, node details, and search only. It does not yet expose an
in-panel policy editor the way the ICD-10 browser does — that is deferred
until the allowability policy (D3) is confirmed.

## Form-Level Classification

`map_project_site_odk.icd_classification` (`icd10` | `icd11`, default
`icd10`) selects which catalog a project-site's form uses. It is set in the
admin Project Forms panel and defaults to ICD-10 for backward compatibility.
As of phases 1-2 this is stored and exposed, but the coding-screen search and
save-time validation dispatch on it (phase 3 of
`docs/planning/icd11-coding-screen-integration-plan.md`) is not implemented
yet — coder-facing coding screens still always use ICD-10.

## Relationship to the ICD-10 Catalog

- ICD-11 lookup does not replace ICD-10 lookup; both catalogs coexist, and a
  form uses exactly one classification.
- `app/services/icd_coding_value.py` provides classification-aware code
  extraction (`ICD10_CODE_RE`, `ICD11_CODE_RE`, `extract_icd_code`) and the
  classification resolver
  (`get_icd_classification_for_submission`), shared by both catalogs.
- The legacy `va_icd_codes` catalog remains ICD-10-only and deprecated, per
  `docs/policy/icd10-reference-catalog.md`; it is never used for ICD-11.
