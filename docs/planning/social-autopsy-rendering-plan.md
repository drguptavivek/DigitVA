---
title: "Plan: Form-Type-Aware Rendering & Social Autopsy Category"
doc_type: planning
status: draft
owner: vivekgupta
last_updated: 2026-03-12
---

# Plan: Form-Type-Aware Rendering & Social Autopsy Category

## Background & Problem Statement

The coder UI renders VA form submissions through a category-by-category panel system.
Currently this system is hardcoded around a single form type (`WHO_2022_VA`).

A new form type `WHO_2022_VA_SOCIAL` has been created in the admin field mapping panel,
with all standard categories **plus** a new `social_autopsy` category (display_order 15).
The immediate goal is to have coders see a static Social Autopsy panel when working on
`WHO_2022_VA_SOCIAL` form submissions.

This phase is intentionally limited:

- no project-level toggle yet
- no DB-driven category-list generation yet
- no attempt to make category/nav behavior configurable yet
- no migration/backfill work yet, because no SOCIAL forms have been mapped or synced

---

## How the Current Rendering Pipeline Works

### Question / Field Order Within a Category

Field order is fully database-driven via `MasFieldDisplayConfig.display_order` (integer).

The `FieldMappingService._build_fieldsitepi()` builds the nested dict consumed by the renderer:

```
{ category_code → { subcategory_code → { field_id → short_label } } }
```

- **Category order**: `MasCategoryOrder.display_order`
- **Field order within subcategory**: `MasFieldDisplayConfig.display_order` (ascending)
- **Subcategory order within category**: `MasSubcategoryOrder.display_order`
- **Coder vs Site-PI level**: `va_mapping_fieldcoder` (a static Python dict in
  `app/utils/va_mapping/va_mapping_02_fieldcoder.py`) is used during coding/review.
  The DB service `get_fieldsitepi()` is used for site-PI views. There is no
  `show_to_coder` flag in `MasFieldDisplayConfig` yet.

### Data Filtering ("Hide if no relevant data")

At **sync time**, `va_preprocess_categoriestodisplay()` decides which categories to include
in each submission's `va_category_list` (stored on `va_submissions`):

1. Iterates a **hardcoded** 13-category list (`va_renderforall`)
2. For each category, calls `va_render_processcategorydata()` using the **old static mapping**
   (`va_mapping_fieldsitepi` from `app/utils/va_mapping/va_mapping_01_fieldsitepi.py`)
3. `va_render_processcategorydata` skips values that are: `dk`, `ref`, `None`, blank,
   zero-skip fields at 0, and missing attachments
4. If the result dict is empty (all answers were DK/NA/blank) → category is **excluded**
5. `vanarrationanddocuments` is **always appended** regardless of data
6. Result stored as `va_submissions.va_category_list`

At **render time** (`va_renderpartial`):

1. Reads mapping from `FieldMappingService` but **hardcodes `form_type_code = "WHO_2022_VA"`**
2. Calls `va_render_processcategorydata()` again to build the display data
3. The same skip/filter logic applies — empty subcategories are omitted from the display

At **left nav time** (`va_coding.html`):

1. Each nav button is wrapped in `{% if "category_code" in catlist %}`
2. Nav entries are **hardcoded** in the template — no dynamic generation
3. `vanarrationanddocuments` has **no guard** — always shown

### Current Gaps for `social_autopsy`

| Layer | Gap |
|---|---|
| `va_renderpartial` | Hardcoded `form_type_code = "WHO_2022_VA"` — SOCIAL mappings never loaded |
| `va_mapping_fieldcoder` | Static Python dict — no `social_autopsy` entries |
| `va_coding.html` left nav | Hardcoded nav items — no `social_autopsy` entry |
| Template | `va_formcategory_partials/social_autopsy.html` does not exist |
| `va_preprocess_03` | Hardcoded 13-category list + old static mapping — category-list generation still ignores `social_autopsy` |

For this phase, the preprocessing gap is acceptable because there are currently no synced
SOCIAL submissions. We can render the category statically for SOCIAL forms first and
address category-list generation later.

---

## Design Decisions

### D1 — What controls whether Social Autopsy appears?

**Decision: Form type only for Phase 1.**

If a submission belongs to `WHO_2022_VA_SOCIAL`, the UI should render a static
`social_autopsy` category. No project-level enable/disable flag is introduced yet.

Rationale: this is the smallest change that proves the form-type-aware render path
without broadening scope into admin configuration.

### D2 — How should the category list be built?

**Decision: Leave preprocessing unchanged for Phase 1.**

`va_preprocess_categoriestodisplay()` remains hardcoded for now. We are not making
category-list generation DB-driven in this phase, and we are not using
`mas_category_order` as the effective source of truth for coder navigation yet.

Rationale: there are no synced SOCIAL submissions yet, so there is no immediate data
migration or stale-category-list problem to solve.

### D3 — How should the render pipeline resolve the form type?

**Decision: Look up the actual form type in `va_renderpartial`.**

`va_submission.va_form_id → VaForms.form_type_id → MasFormTypes.form_type_code`.
Use this code for all `FieldMappingService` calls. Fall back to `WHO_2022_VA` if
`form_type_id` is NULL.

This phase assumes future SOCIAL forms are registered with `form_type_id` set correctly.

### D4 — What about `va_mapping_fieldcoder` (coder-level field filter)?

**Decision: Extend `va_mapping_fieldcoder` to include social autopsy fields
OR add a `show_to_coder` boolean to `MasFieldDisplayConfig` and derive the coder mapping
from the DB service.**

This is the largest decision. Option A (extend static dict) is lower risk for existing
categories but does not scale. Option B (DB-driven coder mapping) is the clean target
state but requires a migration and admin UI changes.

**Recommendation: Option A for this iteration** — add `social_autopsy` to
`va_mapping_fieldcoder` manually, since there's no `show_to_coder` column yet.
Defer DB-driven coder mapping to a separate refactor.

### D5 — Left nav in `va_coding.html`

**Decision: Add a single static `social_autopsy` nav entry** for SOCIAL forms.

Do not make nav generation dynamic in this phase. Add one hardcoded entry and guard it
using form type, not project settings.

### D6 — `va_forms.form_type_id` linkage

**Decision: Do not add backfill work in Phase 1.**

Because no SOCIAL forms have been mapped or synced yet, this phase only depends on
future SOCIAL form registrations carrying the correct `form_type_id`.

---

## Ordered Implementation Steps

### Step 1 — Form-type-aware `va_renderpartial`

Replace `_form_type_code = "WHO_2022_VA"` with a lookup:

```python
_form = db.session.get(VaForms, va_submission.va_form_id)
_form_type_code = "WHO_2022_VA"
if _form and _form.form_type_id:
    _ft = db.session.get(MasFormTypes, _form.form_type_id)
    if _ft:
        _form_type_code = _ft.form_type_code
```

Add `VaForms` and `MasFormTypes` to imports if not present.

**Risk**: Low. Existing non-SOCIAL submissions keep falling back to `WHO_2022_VA`.

### Step 2 — Add `social_autopsy` to `va_mapping_fieldcoder`

Add a `social_autopsy` key to the static dict with the field IDs and coder labels
matching what was configured in the admin field mapping panel.

This is the only step that requires knowing the actual field IDs in the social autopsy
ODK form. Pull them from `mas_field_display_config` for `WHO_2022_VA_SOCIAL`.

**Risk**: Low. Additive change to a static dict. No existing behaviour affected.

### Step 3 — Create `va_formcategory_partials/social_autopsy.html`

Generic category template with:
- Card header "Social Autopsy"
- Loop over subcategories in `category_data`
- Same flip/info badge logic as other category templates
- Previous/Next navigation footer (same as others)

**Risk**: None. New file.

### Step 4 — Add `social_autopsy` to `va_renderforall` in `va_api.py`

Add `"social_autopsy"` to the `va_renderforall` list so `va_renderpartial` routes it
to the standard rendering path.

**Risk**: Low. Only affects requests where `va_partial == "social_autopsy"`.

### Step 5 — Left nav entry in `va_coding.html`

Add a hardcoded `social_autopsy` nav button for SOCIAL forms. Because
`va_category_list` is not being changed in this phase, the nav guard should not rely on
`"social_autopsy" in catlist` alone.

Guard the nav entry using resolved form type in template context, for example:

```html
{% if form_type_code == "WHO_2022_VA_SOCIAL" %}
```

`va_calltoaction` in `va_cta.py` must pass the submission's resolved `form_type_code`
into the template context.

**Risk**: Low. Purely additive.

---

## Deferred Follow-up Work

The following items are explicitly out of scope for this phase and should be handled in
a later plan or phase:

- make coder field visibility DB-driven (`show_to_coder` or equivalent)
- use `mas_category_order` to drive coder category lists/navigation
- add project-level `social_autopsy_enabled`
- add migration/backfill strategy for existing forms and submissions once SOCIAL forms
  are actually mapped and synced

---

## Open Questions Before Implementation

1. **D4 confirmed?** — Should we add `social_autopsy` fields to `va_mapping_fieldcoder`
   (static dict, immediate) or add a `show_to_coder` DB column (clean, requires more work)?

2. **D6 timing** — Should the `form_type_id` backfill be in the same migration as
   `social_autopsy_enabled`, or separate?

3. **Re-preprocess existing submissions?** — After Step 3 ships, existing SOCIAL
   submissions will have old `va_category_list` values (without `social_autopsy`).
   Do we want a one-time re-preprocessing job to rebuild them, or just let it happen
   on next sync?

4. **`vanarrationanddocuments` special-casing** — Should this remain always-included,
   or should future form types be able to exclude it via `mas_category_order`?

---

## Dependencies

```
Step 1 (migration: social_autopsy_enabled)
Step 2 (backfill form_type_id)
    └── Step 3 (DB-driven preprocess)   [can work without Step 2 via fallback]
    └── Step 4 (form-type-aware render) [can work without Step 2 via fallback]
Step 5 (va_mapping_fieldcoder)          [independent]
Step 6 (social_autopsy.html template)   [independent]
Step 7 (va_renderforall in va_api.py)   [independent]
Step 1 + Step 4 + Step 7 + Step 6
    └── Step 8 (left nav)               [needs all of the above]
```

---

## Files Affected

| File | Change |
|---|---|
| `migrations/versions/<new>.py` | Add `social_autopsy_enabled` to `va_project_master`; optionally backfill `form_type_id` |
| `app/models/va_project_master.py` | Add `social_autopsy_enabled` column |
| `app/routes/admin.py` | Serialize + PUT endpoint for `social_autopsy_enabled` |
| `app/templates/admin/panels/projects.html` | Toggle button (same pattern as NQA) |
| `app/utils/va_preprocess/va_preprocess_03_categoriestodisplay.py` | Replace hardcoded list with DB-driven lookup |
| `app/routes/va_api.py` | Resolve form type dynamically; add `social_autopsy` to `va_renderforall` |
| `app/routes/va_cta.py` | Pass `social_autopsy_enabled` to `va_coding.html` context |
| `app/utils/va_mapping/va_mapping_02_fieldcoder.py` | Add `social_autopsy` fields |
| `app/templates/va_formcategory_partials/social_autopsy.html` | New template |
| `app/templates/va_frontpages/va_coding.html` | Add `social_autopsy` nav entry |
