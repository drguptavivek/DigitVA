---
title: ICD-10 Browser Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-26
---

# ICD-10 Browser Policy

## Purpose

Define the backend contract for the ICD-10 2019 browser built on
`mas_icd10_2019_2`.

The administration console exposes the browser under
`/admin/panels/icd10-browser`, backed by admin JSON routes under
`/admin/api/icd10/2019-2/*`.

## Policy

1. The ICD browser reads hierarchy data from `mas_icd10_2019_2`.
2. The browser must use lazy hierarchy expansion rather than loading the full
   tree in one response.
3. Browser reads expose:
   - one node's details
   - the direct children of a requested node
   - allowed vocabulary options for local policy fields
   - a JSON export of curated code-policy rows
   - an XLSX export of editable code-policy rows with COD manual override status
4. Policy edits must update only local policy fields and must not rewrite ICD
   hierarchy structure fields loaded from source.
5. Policy-edit responses must return the updated node payload so the browser can
   refresh in place.
6. In the admin browser UI, turning on `is_coding_selectable` must prefill
   `sex_selectable=both` and `age_group_selectable=all` before save. Admins may
   still override those defaults before submitting.
7. The policy export must include only `three_character` and `detailed_code`
   rows where at least one of `is_coding_selectable`, `sex_selectable`, or
   `age_group_selectable` is set.
8. The policy export payload must expose:
   - `code`
   - `title`
   - `semantic_level`
   - lineage fields needed to place the code in hierarchy
   - `is_coding_selectable`
   - `sex_selectable`
   - `age_group_selectable`
9. The XLSX policy export must expose active `three_character` and
   `detailed_code` rows with coding allowed status, age coding policy, sex
   coding policy, policy status, restriction note, and whether the ICD code has
   any COD bucket manual override mappings.
10. The policy import must be overwrite-style:
    - imported code rows are updated from the file
    - all other editable ICD code rows are reset to `is_coding_selectable=false`
    - all other editable ICD code rows are reset to `sex_selectable=NULL`
    - all other editable ICD code rows are reset to `age_group_selectable=NULL`
11. The policy import response must include:
    - `total_items`
    - `updated_items`
    - `reset_items`
    - `failed_codes`, with each failed code and the reason it was not imported
12. Browser status indicators must distinguish inherited selectability:
    - green: the row itself is selectable, or all direct three-character
      children in a structural block are selectable
    - yellow: a three-character row is not selectable itself but has at least
      one selectable detailed child; structural blocks containing such rows
      must also remain navigable under the active filter
    - red: neither the row nor any relevant child row is selectable
13. The admin ICD browser page must show a read-only list of reporting-only
    legacy ICD normalization aliases used by COD bucket reporting so operators
    can see how selected historical finalized ICD values are bucketed against
    the ICD-10 2019 master.

## Access Policy

1. `data_manager` and `admin` may browse the ICD hierarchy.
2. Only `admin` may edit ICD local policy fields.
3. `data_manager` and `admin` may use the API export endpoint.
4. Only `admin` may use the admin-panel export endpoint.

## Local Policy Field Semantics

Current browser-editable policy fields are:

- `is_coding_selectable`
- `sex_selectable`
- `age_group_selectable`
- `restriction_note`

Applicability rule:

- `chapter` and `block` rows are structural only and must not allow local policy
  edits
- `three_character` and `detailed_code` rows may carry local policy fields

Current vocabulary constraints are:

- `sex_selectable`: `both`, `female`, `male`
- `age_group_selectable`: `all`, `neonate`, `infant`, `child`, `adult`

`NULL` remains valid for optional fields where no curation has been applied.

## Public Help Browser

The Help centre exposes the same hierarchy-pane interaction at
`/help/icd10-codes`. It reads the active ICD-10 rows and `WHO_2022_VA_2026`
mapping state as a public, anonymous, read-only reference.

- The page, its hierarchy data routes, search, and CSV accept GET requests and
  are limited to 60 requests per minute.
- It lazily loads Chapters, Blocks, 3-Character Codes, and Detailed Codes using
  public read-only routes. Blocks load as complete children; the hierarchy is
  not paginated.
- Search results open the selected code's full hierarchy path.
- Filters cover coding selectability, sex, age group, policy review, and VA
  mapping origin. The `digitva` origin value remains a supported inbound alias.
- The selected-node details show coding selectability, sex and age limits,
  policy review, restriction note, VA cause, and the plain-language origin
  badge and reason.
- Public routes return curated fields only. They do not proxy admin APIs and do
  not expose policy edit/import/export controls, reporting aliases, raw mapping
  notes, or mutation endpoints.
- The CSV includes the displayed catalogue and public mapping fields, omits
  internal mapping notes, and escapes spreadsheet formula values.
