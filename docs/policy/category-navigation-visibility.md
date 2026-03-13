---
title: Category Navigation Visibility Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-03-13
---

# Category Navigation Visibility Policy

## Purpose

This document defines the baseline policy for how the left category navigation in the
VA coding/review screen is expected to behave.

It describes current intended behavior, even where the implementation is still
hardcoded.

## Core Rule

For category-style panels, left-nav visibility is determined dynamically from the
submission's current data, form type, role-aware category config, and category render
rules. The UI must not depend on stored `va_submissions.va_category_list` for runtime
navigation decisions.

## Current Baseline

### Workflow panels in nav

Some left-nav items are workflow panels, not submission-data categories.

Current baseline:

- coder views append a final `COD Assessment` nav item
- this workflow item is always shown for coder flows
- it is ordered after the visible submission-data categories
- it is not derived from mapped field values
- it is the final workflow step for coder flows
- it may assemble evidence from submission-data categories before showing the COD form

### Standard categories

A standard category button is shown only when its category code exists in
the live visible category set computed from current submission data and form-type
config.

Examples:

- `vademographicdetails`
- `vaneonatalperioddetails`
- `vainjuriesdetails`
- `vahealthhistorydetails`
- `vageneralsymptoms`
- `varespiratorycardiacsymptoms`
- `vaabdominalsymptoms`
- `vaneurologicalsymptoms`
- `vaskinmucosalsymptoms`
- `vaneonatalfeedingsymptoms`
- `vamaternalsymptoms`
- `vahealthserviceutilisation`

### Interview details

`vainterviewdetails` is additionally role/view gated.

Current baseline:

- show only when `vainterviewdetails` is present in the live visible category set
- and only when `va_action == "vasitepi"`

### Narration and documents

`vanarrationanddocuments` is always shown in the left nav.

Current baseline:

- it is configured as always included
- it no longer contains the COD assessment workflow block

### Badge counts

`va_catcount` is a badge/count concern only.

Current baseline:

- badge counts may be shown next to nav items
- zero or missing badge counts must not, by themselves, hide a nav item

## How Availability Is Derived

Runtime category visibility is computed dynamically using category-level data
filtering.

Current baseline filtering rules:

- preprocessing must resolve the effective form type for the submission's `va_form_id`
  before loading category mappings
- `None` values do not count as content
- string values `dk` and `ref` do not count as content
- zero-valued age-group flags (`isNeonatal`, `isChild`, `isAdult`) do not count as content
- missing attachments do not count as content
- a category is included only if at least one field survives those filters
- except for categories configured with `always_include = true`, such as
  `vanarrationanddocuments`

## Ordering Rule

Previous/next category navigation must use the same live visible category set that
drives left-nav visibility.

## Change Control

Any future change to left-nav visibility must explicitly document:

- whether visibility is still stored on `va_category_list` or becomes render-time derived
- whether any categories remain special-cased
- whether role/view-based exceptions still exist
- whether new form types may define categories outside the current hardcoded set
