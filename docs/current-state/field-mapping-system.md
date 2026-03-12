---
title: Field Mapping System
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-12
---

# Field Mapping System

The field mapping system controls how ODK submission data is displayed in DigitVA:
labels, category groupings, choice translations, flip colours, info flags, and PII
handling. All configuration is stored in the database under the `mas_*` table family
and managed through the admin UI at `/admin/?panel=/admin/panels/field-mapping`.

---

## Data Model

Five tables form the core of the system. All are scoped to a `form_type_id` so
multiple form types can coexist independently.

```
mas_form_types
  └─► mas_category_order          (display groupings)
  └─► mas_subcategory_order       (sub-groupings within categories)
  └─► mas_field_display_config    (per-field labels and flags)
  └─► mas_choice_mappings         (choice value → label translations)
```

### `mas_form_types`

Registry of supported VA form types.

| Column | Type | Notes |
|--------|------|-------|
| `form_type_id` | UUID PK | |
| `form_type_code` | VARCHAR(32) UNIQUE | Uppercase, e.g. `WHO_2022_VA` |
| `form_type_name` | VARCHAR(128) | Human-readable display name |
| `form_type_description` | TEXT | Optional free text |
| `base_template_path` | VARCHAR(256) | Optional path to base XLSForm |
| `mapping_version` | INTEGER | Incremented on major remaps |
| `is_active` | BOOLEAN | Soft-delete flag |
| `created_at` / `updated_at` | TIMESTAMP | UTC |

### `mas_category_order`

Controls the display order of categories within a form type.

| Column | Type | Notes |
|--------|------|-------|
| `category_order_id` | UUID PK | |
| `form_type_id` | UUID FK | |
| `category_code` | VARCHAR(64) | e.g. `A`, `B`, `Demographics` |
| `category_name` | VARCHAR(128) | Display label |
| `display_order` | INTEGER | Ascending sort |
| `is_active` | BOOLEAN | |

Unique constraint: `(form_type_id, category_code)`.

### `mas_subcategory_order`

Controls the display order of sub-categories within a category.

| Column | Type | Notes |
|--------|------|-------|
| `subcategory_order_id` | UUID PK | |
| `form_type_id` | UUID FK | |
| `category_code` | VARCHAR(64) | Parent category |
| `subcategory_code` | VARCHAR(64) | e.g. `A1`, `A2` |
| `subcategory_name` | VARCHAR(128) | Display label |
| `display_order` | INTEGER | |
| `is_active` | BOOLEAN | |

Unique constraint: `(form_type_id, category_code, subcategory_code)`.

### `mas_field_display_config`

One row per field per form type. Controls every display aspect of a field.

| Column | Type | Notes |
|--------|------|-------|
| `config_id` | UUID PK | |
| `form_type_id` | UUID FK | |
| `field_id` | VARCHAR(64) | ODK variable name, e.g. `Id10007` |
| `category_code` | VARCHAR(64) | Display category assignment |
| `subcategory_code` | VARCHAR(64) | Display sub-category assignment |
| `odk_label` | TEXT | Synced from XLSForm `survey` sheet |
| `short_label` | VARCHAR(256) | Concise label for coding screens |
| `full_label` | TEXT | Expanded label for detail views |
| `summary_label` | VARCHAR(256) | Label in the case summary panel |
| `field_type` | VARCHAR(32) | `select_one`, `integer`, `text`, etc. |
| `age_group` | VARCHAR(16) | `neonate`, `child`, `adult`, or blank |
| `flip_color` | BOOLEAN | Invert colour coding in the UI |
| `is_info` | BOOLEAN | Informational only — not coded |
| `summary_include` | BOOLEAN | Include in case summary panel |
| `is_pii` | BOOLEAN | Field contains PII |
| `pii_type` | VARCHAR(32) | `name`, `dob`, `address`, etc. |
| `display_order` | NUMERIC(10,2) | Order within sub-category; decimal values allowed for rapid inserts |
| `is_active` | BOOLEAN | |
| `is_custom` | BOOLEAN | True for app-added fields not in ODK |
| `created_at` / `updated_at` | TIMESTAMP | UTC |

Unique constraint: `(form_type_id, field_id)`.

### `mas_choice_mappings`

One row per field-choice combination. Translates ODK coded values to human-readable labels.

| Column | Type | Notes |
|--------|------|-------|
| `choice_id` | UUID PK | |
| `form_type_id` | UUID FK | |
| `field_id` | VARCHAR(64) | ODK variable name |
| `choice_value` | VARCHAR(128) | Coded value as stored in submission |
| `choice_label` | VARCHAR(256) | Display label |
| `display_order` | INTEGER | Ascending sort |
| `is_active` | BOOLEAN | |
| `synced_at` | TIMESTAMP | Last synced from ODK Central |

Unique constraint: `(form_type_id, field_id, choice_value)`.

---

## Admin UI

The Field Mapping panel lives at `/admin/?panel=/admin/panels/field-mapping`
and is restricted to admin users.

---

### Form Type Management

The panel header shows a count of registered form types and two action buttons:
**Import** and **New Form Type**.

Each registered form type is shown as a card with:
- Code, name, and description
- Stats: category count, field count, choice count
- Action buttons: Fields · Sync ODK · Duplicate · Export

#### Create a blank form type

**New Form Type** button → modal:

| Field | Validation |
|-------|-----------|
| Form Type Code | Uppercase, `[A-Z0-9_]`, max 32 chars, must be unique |
| Form Type Name | Free text, max 128 chars, required |
| Description | Optional free text |

Route: `POST /admin/api/form-types`
Body: `{ "form_type_code": "...", "form_type_name": "...", "description": "..." }`
Response `201`: `{ "form_type_code": "...", "form_type_name": "..." }`
Response `409`: `{ "error": "Form type already exists: ..." }`

#### Duplicate an existing form type

**Duplicate** button on any card → same modal (labelled for duplicate, shows source info banner).

Route: `POST /admin/api/form-types/<source_code>/duplicate`
Body: `{ "new_code": "...", "new_name": "...", "description": "..." }`

The service copies all child records under a new `form_type_id` with fresh UUIDs:
- All `MasCategoryOrder` rows
- All `MasSubcategoryOrder` rows
- All `MasFieldDisplayConfig` rows (labels, flags, PII settings, ODK labels)
- All `MasChoiceMappings` rows

The duplicate is fully independent. Changes to it do not affect the source.

#### Export a form type

**Export** button on any card → browser downloads `form_type_<code>.json`.

Route: `GET /admin/api/form-types/<code>/export`
Response: JSON file attachment.

Export bundle format:

```json
{
  "schema_version": 1,
  "exported_at": "2026-03-10T12:00:00+00:00",
  "form_type": {
    "form_type_code": "WHO_2022_VA",
    "form_type_name": "WHO 2022 VA",
    "form_type_description": "...",
    "base_template_path": null,
    "mapping_version": 1
  },
  "categories": [
    { "category_code": "A", "category_name": "Identification", "display_order": 1, "is_active": true }
  ],
  "subcategories": [
    { "category_code": "A", "subcategory_code": "A1", "subcategory_name": "...", "display_order": 1, "is_active": true }
  ],
  "fields": [
    {
      "field_id": "Id10007", "category_code": "A", "subcategory_code": "A1",
      "odk_label": "Date of Interview", "short_label": "Interview Date",
      "full_label": null, "summary_label": null,
      "field_type": "date", "age_group": null,
      "flip_color": false, "is_info": false, "summary_include": true,
      "is_pii": false, "pii_type": null,
      "display_order": 1, "is_active": true, "is_custom": false
    }
  ],
  "choices": [
    { "field_id": "Id10019", "choice_value": "1", "choice_label": "Male", "display_order": 1, "is_active": true }
  ]
}
```

The file is safe to commit to version control and share between environments.

#### Import a form type

**Import** button in the panel header → modal with file picker.

On file selection a preview strip shows the embedded code, name, and record counts.

Route: `POST /admin/api/form-types/import` (multipart, `enctype="multipart/form-data"`)

Form fields:

| Field | Notes |
|-------|-------|
| `file` | Required. The `.json` export file. Max 10 MB. |
| `override_code` | Optional. Use a different form type code on import. |
| `override_name` | Optional. Use a different form type name on import. |
| `override_description` | Optional. Override description. |

If the code in the file already exists in the database the import fails with a `409` conflict.
Use the **"Import with a different code / name"** toggle to resolve this.

Response `201`:
```json
{
  "form_type_code": "WHO_2022_VA_COPY",
  "form_type_name": "WHO 2022 VA Copy",
  "categories_created": 14,
  "subcategories_created": 42,
  "fields_created": 410,
  "choices_created": 1203
}
```

Import **always creates** a new form type. It does not update or merge into an existing one.

---

### Field Management

**Fields** button on any card → opens the field list sub-panel below the cards.

Route: `GET /admin/panels/field-mapping/fields?form_type=<code>`

The table shows all fields for the selected form type:

| Column | Description |
|--------|-------------|
| Field ID | ODK variable name — read-only |
| ODK Label | Synced from XLSForm (read-only reference) |
| Short Label | App display label for coding screens |
| Category / Sub | Display grouping |
| Type | ODK field type |
| Flip | Colour inversion flag |
| Info | Informational-only flag |
| Summary | Included in case summary |
| PII | Contains personally identifiable information |
| Source | `ODK` (synced) or `App` (custom) |

#### Editing a field

Pencil icon on any row → edit modal (`GET /admin/panels/field-mapping/field/<code>/<field_id>`).

Editable fields in the modal:

| Field | Notes |
|-------|-------|
| **Short Label** | Coding screen display label |
| **Full Label** | Expanded label for detail/tooltip views |
| **Summary Label** | Label in the case summary panel |
| **Category** | Select from registered categories |
| **Sub-category** | Select from registered sub-categories |
| **Age Group** | `neonate` / `child` / `adult` / blank |
| **Field Type** | Override the ODK-sourced type |
| **Flip Color** | Toggle |
| **Is Info** | Toggle |
| **Summary Include** | Toggle |
| **Is PII** | Toggle |
| **PII Type** | Free text when Is PII is checked |

ODK Label and Field ID are shown read-only for reference. Hover tooltips on each
label explain the field's purpose in the app.

On submit → `POST /admin/panels/field-mapping/field/<code>/<field_id>`

On success the table row updates in-place via HTMX (`outerHTML` swap) and the modal closes.
No full-page reload is needed.

---

### ODK Sync

**Sync ODK** button on any card → opens the sync sub-panel.

Route: `GET /admin/panels/field-mapping/sync?form_type=<code>`

#### Selecting the ODK source

Three cascading dropdowns load progressively:

1. **ODK Connection** — active connections from `MasOdkConnections`; auto-selects if only one
2. **ODK Project** — loaded from `GET /admin/api/odk-connections/<id>/odk-projects`
3. **ODK Form** — loaded from `GET /admin/api/odk-connections/<id>/odk-projects/<pid>/forms`

**Preview Changes** and **Run Sync** buttons are disabled until a form is selected.

#### Preview changes (dry run)

Route: `POST /admin/panels/field-mapping/sync/preview`
Body: `{ "form_type_code", "connection_id", "odk_project_id", "odk_form_id" }`

Downloads the XLSForm XLSX and computes a diff without writing to the database.

Response shows three change lists:

| Key | Meaning |
|-----|---------|
| `label_changes` | Fields whose ODK label would be updated; `[{field_id, current_label, new_label}]` |
| `new_choices` | Choices in ODK not yet in DB; `[{field_id, value, label}]` |
| `updated_choices` | Existing choices with changed labels; `[{field_id, value, old_label, new_label}]` |

If no changes are pending, a "Database is already up to date" message is shown.

#### Running a sync

Route: `POST /admin/panels/field-mapping/sync`
Body: same as preview.

The sync service:

1. Downloads the XLSForm XLSX from ODK Central via pyODK
2. Parses the **`survey`** sheet: reads `name`, `type`, and the first `label*` column
3. Parses the **`choices`** sheet: reads `list_name`, `name`, and the first `label*` column
4. Joins choices to fields on `list_name` extracted from type strings like `select_one <list_name>`
5. For each field in `MasFieldDisplayConfig`: updates `odk_label` if changed
6. For each choice from the XLSForm: upserts into `MasChoiceMappings`
   - New → insert
   - Changed label → update
   - Unchanged → skip (not counted as updated)
   - Absent from XLSForm → **left untouched** (sync is additive only)

Result table:

| Stat | Description |
|------|-------------|
| `fields_processed` | Count of ODK fields matched in `MasFieldDisplayConfig` |
| `labels_updated` | Count of `odk_label` values changed |
| `choices_added` | New choice rows inserted |
| `choices_updated` | Existing choice labels changed |

**Why sync is additive-only:** The WHO VA XLSForm is a universal template covering all
deployment sites. A site-specific ODK project only contains choices for that site.
Deactivating choices absent from one site's form would silently remove choices needed
by other sites. Choices seeded from `resource/mapping/mapping_choices.xlsx` are the
canonical source; ODK sync augments them.

#### Label column discovery

XLSForm label columns vary by form: `label`, `label::English (en)`, `label::English`,
etc. The sync service picks the first column whose name starts with `label`.

---

## Field Mapping Service (Runtime)

At runtime, the `FieldMappingService` (singleton) serves field and choice data to
rendering code. It caches queries per form type.

```python
from app.services.field_mapping_service import get_mapping_service

svc = get_mapping_service()
config = svc.get_field_config(form_type_id, field_id)   # MasFieldDisplayConfig | None
choices = svc.get_choices(form_type_id, field_id)       # list[MasChoiceMappings]
label = svc.get_choice_label(form_type_id, field_id, value)  # str | None
```

The cache is invalidated after any field edit via `svc.clear_cache()`.

Ordering behavior in `get_fieldsitepi(form_type_code)`:

- categories are ordered by `MasCategoryOrder.display_order`
- subcategories within a category are ordered by `MasSubcategoryOrder.display_order`
- fields within a subcategory are ordered by `MasFieldDisplayConfig.display_order`

If a field-bearing subcategory does not yet have a `MasSubcategoryOrder` row, it still
renders after the explicitly ordered subcategories for that category.

---

## FormTypeService (Admin)

The `FormTypeService` singleton handles all admin operations.

```python
from app.services.form_type_service import get_form_type_service

svc = get_form_type_service()

# Register a blank form type
ft = svc.register_form_type("MY_FORM", "My Form", description="...")

# List all active form types
types = svc.list_form_types()

# Stats for one form type
stats = svc.get_form_type_stats("WHO_2022_VA")
# {"form_type_code", "form_type_name", "form_count", "category_count", "field_count", "choice_count"}

# Duplicate (copies all categories, subcategories, fields, choices)
new_ft = svc.duplicate_form_type("WHO_2022_VA", "WHO_2022_VA_V2", "WHO 2022 VA v2")

# Export to dict (JSON-serializable)
data = svc.export_form_type("WHO_2022_VA")

# Import from dict
new_ft, stats = svc.import_form_type(data, override_code="NEW_CODE", override_name="New Name")

# Soft-delete (raises ValueError if forms are still linked)
svc.deactivate_form_type("OLD_FORM")
```

---

## Field Display Flags Reference

| Flag | Column | Effect in coding screen |
|------|--------|------------------------|
| **Flip Color** | `flip_color` | Inverts the colour coding so "No" appears positive and "Yes" negative |
| **Is Info** | `is_info` | Field is shown for reference only; it is not included in VA coding |
| **Summary Include** | `summary_include` | Field appears in the case summary panel alongside the VA result |
| **Is PII** | `is_pii` | Field contains personally identifiable information — masked in non-PII views |

Labels hierarchy (first non-null wins for display):

```
short_label  →  full_label  →  odk_label  →  field_id
```

---

## API Reference

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/admin/panels/field-mapping` | Main panel (HTMX partial) |
| `GET` | `/admin/panels/field-mapping/fields?form_type=<code>` | Field list sub-panel |
| `GET` | `/admin/panels/field-mapping/field/<code>/<field_id>` | Field edit modal |
| `POST` | `/admin/panels/field-mapping/field/<code>/<field_id>` | Save field edits |
| `GET` | `/admin/panels/field-mapping/sync?form_type=<code>` | Sync sub-panel |
| `POST` | `/admin/panels/field-mapping/sync/preview` | Dry-run sync diff |
| `POST` | `/admin/panels/field-mapping/sync` | Run sync |
| `POST` | `/admin/api/form-types` | Create blank form type |
| `POST` | `/admin/api/form-types/<code>/duplicate` | Duplicate form type |
| `GET` | `/admin/api/form-types/<code>/export` | Download JSON bundle |
| `POST` | `/admin/api/form-types/import` | Import from JSON bundle |

All state-changing routes require `X-CSRFToken` header and admin role.

---

## Related Files

| Path | Purpose |
|------|---------|
| [`app/models/va_field_mapping.py`](../../app/models/va_field_mapping.py) | SQLAlchemy models for all `mas_*` tables |
| [`app/services/form_type_service.py`](../../app/services/form_type_service.py) | CRUD, duplicate, export, import |
| [`app/services/odk_schema_sync_service.py`](../../app/services/odk_schema_sync_service.py) | XLSForm parsing and DB upsert |
| [`app/services/field_mapping_service.py`](../../app/services/field_mapping_service.py) | Runtime rendering cache |
| [`app/routes/admin.py`](../../app/routes/admin.py) | All admin routes (~line 1089 onward) |
| [`app/templates/admin/panels/field_mapping.html`](../../app/templates/admin/panels/field_mapping.html) | Main panel — cards, import/export modals |
| [`app/templates/admin/panels/field_mapping_fields.html`](../../app/templates/admin/panels/field_mapping_fields.html) | Field list sub-panel |
| [`app/templates/admin/panels/field_mapping_field_edit.html`](../../app/templates/admin/panels/field_mapping_field_edit.html) | Field edit modal |
| [`app/templates/admin/panels/field_mapping_field_row.html`](../../app/templates/admin/panels/field_mapping_field_row.html) | Table row partial (returned on save) |
| [`app/templates/admin/panels/field_mapping_sync.html`](../../app/templates/admin/panels/field_mapping_sync.html) | ODK sync sub-panel |
| [`tests/services/test_odk_schema_sync.py`](../../tests/services/test_odk_schema_sync.py) | 10 unit tests for sync service |
| [`resource/mapping/mapping_labels.xlsx`](../../resource/mapping/mapping_labels.xlsx) | Source field definitions (seed data) |
| [`resource/mapping/mapping_choices.xlsx`](../../resource/mapping/mapping_choices.xlsx) | Source choice definitions (seed data) |

### Related Documentation
- [Data Model](data-model.md)
- [ODK Sync](odk-sync.md)
- [Admin and Setup](admin-and-setup.md)
