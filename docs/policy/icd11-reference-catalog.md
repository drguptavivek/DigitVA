---
title: ICD-11 Reference Catalog Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-26
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
`docs/policy/who-2022-icd11-coding-allowability.md`. A draft policy
generated from WHO's annex (`flask icd11 policy-draft`) is frozen in
`docs/icd-causegrp-mappings/migration-artifacts/who-2022-icd11-policy-draft-2026-09-24/`
for owner review; as of 2026-09-24 it is imported into the dev database only
(owner-approved, for review in the admin ICD-11 browser), and no migration
reads it.

Policy fields are editable only on `class_kind = "category"` rows; chapters
and blocks are structural hierarchy rows with no coding policy.

## Curation Path

ICD-11 policy is curated either in the admin ICD-11 browser panel
(`/admin/panels/icd11-browser`) or through the CLI. Both read and write the
same policy JSON format (`export_icd11_mms_policy_json` /
`import_icd11_mms_policy_json` in `app/services/icd11_mms_service.py`):

```bash
flask icd11 policy-export --release 2026-01 --output policy.json
flask icd11 policy-import policy.json --release 2026-01
```

The panel mirrors the ICD-10 browser: Miller-column panes, one per
hierarchy level (ICD-11 nests deeper than ICD-10's four fixed columns, so
the panes scroll horizontally), with a breadcrumb, status dots
(category selectable = green; not selectable but a direct child is = amber;
otherwise red), child counters, coding/sex/age filters, search, and a node
detail pane with an editable policy form on category rows. Its endpoints
are admin-only, under `/admin/api/icd11/mms/` with an optional
`release=YYYY-MM` argument; state changes require `X-CSRFToken`:

- `GET children`, `GET node`, `GET search`, `GET policy-options`
- `PATCH node/policy?linearization_uri=...` — one category's
  `is_coding_selectable`, `sex_selectable`, `age_group_selectable`,
  `restriction_note`, and optionally `policy_status`
- `GET policy-export` (JSON), `GET policy-export.xlsx` (every active
  category with its policy)
- `POST policy-import` (multipart `file`; `dry_run=1` returns the counts
  without writing). The panel always previews first and applies only after
  the admin confirms.

Policy writes and applied imports are logged with the acting user id and
the new values (not the restriction note text).

## Public Read-Only Help Browser

The canonical anonymous ICD-11 browser is `/help/icd11-codes`. It reuses the
admin browser's variable-depth Miller-column hierarchy, breadcrumb, search,
status indicators, and node detail layout in read-only mode. The browser uses
the configured current release and keeps the existing public catalogue scope
(chapter X remains excluded).

Public users may filter by coding selectability, sex, age group, policy review,
and mapping origin; search by code or title; and follow a node's full hierarchy
path. A node detail may show coding selectability, sex, age group, policy
status, restriction note, VA cause, and the shared plain-language origin badge
and reason. Structural ancestors remain visible when filters match a category,
and child counts reflect the visible filtered hierarchy. Public responses use a
whitelist of display and navigation fields; they must not expose database IDs,
source paths, foundation URIs, raw mapping notes, or policy-edit metadata.

The existing `/help/va-code-mappings/unmapped` and its CSV URL remain working
aliases for compatibility. The CSV retains its current public columns and
appends sex and age group. Filtered exports must use the same filters as the
browser and exclude internal mapping notes.

Every public browser and data endpoint is GET-only and rate-limited to 60
requests per minute. Public HTML and JavaScript must not render policy import,
export, or edit controls, include admin API URLs, or call mutation endpoints.
The `origin=digitva` query remains a hidden compatibility alias for its
existing origin group, not a visible filter choice.

Policy JSON format rules:

- Each item is keyed by `linearization_uri`; `code`, `title`,
  `class_kind`, `chapter_no` are informational.
- Listed categories take the item's `is_coding_selectable`,
  `sex_selectable`, `age_group_selectable` and `restriction_note` (absent
  means null). Every active category not listed is reset to not selectable
  with no sex/age/note.
- `policy_status` (`unreviewed` | `reviewed`) is set only when the item
  carries it and is left unchanged otherwise, including on reset rows. It is
  informational: the coding search reads only the selectable/sex/age fields.
- The export carries `restriction_note` and `policy_status`, so an export
  imports back without loss.

Allowed values match the ICD-10 catalog: `sex_selectable` in
`both | female | male`, `age_group_selectable` in
`all | neonate | infant | child | adult`, null for either when unset.

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
