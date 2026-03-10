---
title: Field Mapping System
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-10
---

# Field Mapping System

## Summary

The field mapping system controls how ODK submission data is:
- Displayed in the UI (labels, groupings, formatting)
- Processed for summaries and categorization
- Rendered with choice value translations
- Styled with flip colors and info flags

**Current State**: Multi-form-type system fully implemented and operational.
The database-backed field mapping supports multiple named form types, each with
independent categories, subcategories, fields, and choice mappings. An admin UI
allows managing form types, editing field display configuration, syncing labels
and choices from ODK Central XLSForms, and exporting/importing form type
definitions as portable JSON bundles.

---

## Current State

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ODK Central                                 │
│  ┌──────────────────┐                                               │
│  │ WHO VA Form 2022 │ ──► submissions.csv.zip                       │
│  └──────────────────┘                                               │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      DigitVA Sync Process                           │
│  1. Download ZIP                                                    │
│  2. Extract CSV + attachments                                       │
│  3. Store ALL fields in va_submissions.va_data (JSONB)              │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────┐
│                    Mapping Configuration                           │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ mapping_labels.xlsx (single file for ALL forms)             │   │
│  │ ├── category         → vainterviewdetails, vademographic... │   │
│  │ ├── sub_category     → va_interviewer, interview...         │   │
│  │ ├── name             → Id10010, Id10010a...                 │   │
│  │ ├── short_label      → Display text                         │   │
│  │ ├── flip_color       → "flip" for alternating row colors    │   │
│  │ ├── is_info          → "info" for header rows               │   │
│  │ ├── summary_include  → Include in summary view              │   │
│  │ └── type             → text, integer, select_one...         │   │
│  └─────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ mapping_choices.xlsx (single file for ALL forms)            │   │
│  │ ├── category         → Field ID (Id10010b)                  │   │
│  │ ├── name             → Choice value (female, male)          │   │
│  │ └── short_label      → Display text (Female, Male)          │   │
│  └─────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Generated Python Modules                         │
│  va_mapping_01_fieldsitepi.py  → Field labels by category          │
│  va_mapping_02_fieldcoder.py   → Coder-specific field labels       │
│  va_mapping_03_choice.py       → Choice value translations         │
│  va_mapping_04_summary.py      → Summary field selection           │
│  va_mapping_05_summaryflip.py  → Summary flip colors               │
│  va_mapping_06_info.py         → Info field flags                  │
│  va_mapping_07_flip.py         → Flip color flags                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Render Process                                 │
│  va_render_processcategorydata():                                   │
│    for field_id, label in MAPPING.items():  # Only mapped fields    │
│        if field_id in submission_data:                              │
│            process_and_display()                                    │
│                                                                     │
│  ⚠️  Unmapped fields are STORED but NOT DISPLAYED                   │
└──────────────────────────────────────────────────────────────────── ┘
```

### Excel File Structure

#### mapping_labels.xlsx (427 rows)

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `category` | string | Main grouping | `vainterviewdetails` |
| `sub_category` | string | Sub-grouping | `va_interviewer` |
| `sub-parts` | string | Further subdivision | (mostly empty) |
| `permission` | string | Access control | `pm` |
| `flip_color` | string | UI styling flag | `flip` |
| `is_info` | string | Informational header | `info` |
| `summary_include` | string | Include in summary | (flag) |
| `is_pii` | string | **PII flag** - marks sensitive data | `pii` |
| `name` | string | **ODK field ID** | `Id10010` |
| `agegroup` | string | Age relevance | `ALL` |
| `short_label` | string | Display label | `(Id10010) Name of VA interviewer` |
| `summary_label` | string | Summary view label | |
| `coder_value` | string | Coding-related | |
| `coder_positive` | string | Positive coding value | |
| `coder_negative` | string | Negative coding value | |
| `label` | string | Full label text | `(Id10010) [Name of VA interviewer]` |
| `type` | string | Field type | `text`, `select_one` |
| `relevant` | string | Relevance condition | |

#### mapping_choices.xlsx (1199 rows)

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `category` | string | Field ID | `Id10010b` |
| `name` | string | Choice value | `female` |
| `short_label` | string | Display text | `Female` |

### Categories (Current Form)

```
vainterviewdetails
├── va_interviewer
├── interview
├── va_respondent
└── va_deceased

vademographicdetails
├── general
├── neonatal
├── child
└── adult

vaneonatalperioddetails
vainjuriesdetails
vahealthhistorydetails
vageneralsymptoms
varespiratorycardiacsymptoms
vaabdominalsymptoms
vaneurologicalsymptoms
vaskinmucosalsymptoms
vaneonatalfeedingsymptoms
vamaternalsymptoms
vahealthserviceutilisation
vanarrationanddocuments
```

### Current Limitations

| Limitation | Impact |
|------------|--------|
| **Single Excel for WHO_2022 only** | Cannot support Ballabgarh_VA, SMART_VA forms |
| **No form_type in va_forms** | System doesn't know which template to use |
| Hardcoded field IDs (Id1xxxx) | Ballabgarh/SMART may use different ID schemes |
| No versioning | Cannot handle form schema evolution |
| Manual regeneration | Mapping changes require running Python functions |
| No validation | Unknown fields silently ignored |
| **Category order hardcoded** | Order defined in Python, not configurable |
| **No explicit sort_order** | Sub-category/field order is implicit from Excel row order |

### Current Excel Templates (Form-Type-Specific)

| File | Form Type | Description |
|------|-----------|-------------|
| `mapping_labels.xlsx` | **WHO_2022_VA only** | Field display config for WHO VA Tool 2022 |
| `mapping_choices.xlsx` | **WHO_2022_VA only** | Choice mappings for WHO VA Tool 2022 |

**Note**: These templates are ONLY for WHO_2022_VA form. They will NOT work for:
- **Ballabgarh_VA** (different field structure, different ID scheme)
- **SMART_VA** (different field structure, different ID scheme)

### Ordering Mechanism (Current)

| Level | How Ordered | Source |
|-------|-------------|--------|
| **Category** | Hardcoded list | `va_preprocess_03_categoriestodisplay.py` |
| **Sub-category** | Dict insertion order | Generated from Excel row order |
| **Field within sub-category** | Dict insertion order | Generated from Excel row order |

The generated Python mapping preserves the Excel row order:

```python
# va_mapping_01_fieldsitepi.py (generated)
va_mapping_fieldsitepi = {
    "vainterviewdetails": {              # ← Category
        "va_interviewer": {              # ← Sub-category (order from Excel)
            "Id10010": "...",            # ← Field (order from Excel)
            "Id10010a": "...",
            "Id10010b": "...",
        },
        "interview": { ... },            # ← Next sub-category (Excel row order)
    },
}
```

The render function uses `OrderedDict` and iterates in insertion order:

```python
# va_render_06_processcategorydata.py
for va_subcat, va_fieldmap in va_datalevel.get(va_partial).items():  # Sub-cat order
    for va_fieldid, va_label in va_fieldmap.items():                  # Field order
        ...
```

---

## What Happens to New ODK Fields

### During Sync

```python
# ALL fields from ODK are stored
va_data = {
    "Id10010": "John",
    "Id10010a": "35",
    "new_field_1": "some value",     # ← Stored in DB
    "new_field_2": "another value",  # ← Stored in DB
}
# Saved to va_submissions.va_data (JSONB)
```

### During Display

```python
# Only MAPPED fields are displayed
for field_id, label in mapping.items():  # Iterates mapping, not data
    if field_id in va_data:
        display(va_data[field_id])

# new_field_1 and new_field_2 are NEVER displayed
# They exist in DB but are invisible in UI
```

### Summary Table

| Aspect | New Field Status |
|--------|-----------------|
| Stored in database | ✅ Yes (`va_data` JSONB) |
| Data preserved | ✅ Yes (never lost) |
| Visible in coding UI | ❌ No |
| Visible in review UI | ❌ No |
| Included in summaries | ❌ No |
| Available in raw export | ✅ Yes |

---

## Desired State

### Goals

1. **Multi-form-type support**: WHO_2022_VA, Ballabgarh_VA, SMART_VA each have their own templates
2. **Project → Form Type mapping**: Each project specifies which form type(s) it uses
3. **Form-type-specific base templates**: Each form type has its own starting configuration
4. **Backward compatibility**: Existing WHO VA form continues to work
5. **Schema versioning**: Handle form schema evolution over time
6. **Admin UI**: Manage mappings without editing Excel files
7. **Validation**: Warn when ODK fields are not mapped

### Supported Form Types

| Form Type Code | Description | Status |
|----------------|-------------|--------|
| `WHO_2022_VA` | WHO VA Tool 2022 | ✅ Current - has Excel templates |
| `BALLABGARH_VA` | Ballabgarh VA Form | 🔜 Coming soon - needs template |
| `SMART_VA` | SMART VA Form | 🔜 Coming soon - needs template |

### Project → Form Type Mapping

```
┌─────────────────────────────────────────────────────────────────────┐
│                    va_forms (Database)                               │
│                                                                      │
│  form_id    │ project_id │ odk_form_id        │ form_type_id        │
│  ──────────────────────────────────────────────────────────────────│
│  UNSW01NC01 │ UNSW01     │ NC01_DS_WHOVA2022   │ UUID → WHO_2022_VA  │
│  UNSW01KA01 │ UNSW01     │ KA01_DS_WHOVA2022   │ UUID → WHO_2022_VA  │
│  ICMR01NC02 │ ICMR01     │ NC02_TVA_WHOVA2022  │ UUID → WHO_2022_VA  │
│  BALL01     │ BALLABH    │ BALL_VA_2024        │ UUID → BALLABGARH   │
│  SMART01    │ SMART      │ SMART_VA_2024       │ UUID → SMART_VA     │
└─────────────────────────────────────────────────────────────────────┘
```

### Form-Type-Specific Base Templates

```
resource/
├── mapping/
│   ├── form_types/
│   │   ├── WHO_2022_VA/
│   │   │   ├── mapping_labels.xlsx      # Current file (renamed)
│   │   │   └── mapping_choices.xlsx     # Current file (renamed)
│   │   │
│   │   ├── BALLABGARH_VA/
│   │   │   ├── mapping_labels.xlsx      # NEW - needs to be created
│   │   │   └── mapping_choices.xlsx     # NEW - needs to be created
│   │   │
│   │   └── SMART_VA/
│   │       ├── mapping_labels.xlsx      # NEW - needs to be created
│   │       └── mapping_choices.xlsx     # NEW - needs to be created
```

---

## PII (Personally Identifiable Information) Handling

### PII Fields in WHO VA Form

Based on WHO VA Tool 2022, the following fields contain PII:

| Field ID | Field Name | PII Type |
|----------|------------|----------|
| `Id10010` | Name of VA interviewer | Name |
| `Id10010c` | ID of VA interviewer | Identifier |
| `Id10007` | Name of the respondent | Name |
| `Id10017` | Deceased's name | Name |
| `Id10018` | Deceased's surname | Name |
| `Id10061` | Father name | Name |
| `Id10062` | Mother name | Name |
| `Id10057` | Place of death (detailed) | Location |
| `Id10055` | Usual residence | Location |
| `deviceid` | Device ID | Identifier |
| `unique_id` | Unique identifier | Identifier |

### PII Marking in Base Template

```excel
# mapping_labels.xlsx
| name     | short_label              | is_pii | category              |
|----------|--------------------------|--------|----------------------|
| Id10010  | Name of VA interviewer   | pii    | vainterviewdetails   |
| Id10017  | Name                     | pii    | vademographicdetails |
| Id10018  | Surname                  | pii    | vademographicdetails |
| Id10061  | Father name              | pii    | vademographicdetails |
| Id10062  | Mother name              | pii    | vademographicdetails |
```

### PII Display Rules

| User Role | PII Field Display |
|-----------|-------------------|
| Coder | **MASKED** - Shows `****` or truncated |
| Site PI | **MASKED** - Partial access if needed |
| Project PI | **VISIBLE** - Full access |
| Admin | **VISIBLE** - Full access |
| API Export | **MASKED** by default, `?include_pii=true` for authorized |

### PII Masking Implementation

```python
# In display rendering
def render_field_value(field_id, value, user_role, field_config):
    if field_config.get('is_pii') and user_role not in ['admin', 'project_pi']:
        return mask_pii(value, field_config.get('pii_type', 'name'))
    return value

def mask_pii(value, pii_type):
    """Mask PII based on type."""
    if not value:
        return value

    if pii_type == 'name':
        # Show first letter only: "John" -> "J***"
        return value[0] + '*' * (len(value) - 1) if len(value) > 1 else '*'
    elif pii_type == 'location':
        # Show city/region only, hide specific address
        return value.split(',')[0] if ',' in value else '****'
    elif pii_type == 'identifier':
        # Show last 4 chars: "ID123456" -> "****3456"
        return '****' + value[-4:] if len(value) > 4 else '****'
    else:
        return '****'
```

### Database Schema for PII

```sql
-- Add to mas_field_display_config
ALTER TABLE mas_field_display_config
ADD COLUMN is_pii BOOLEAN DEFAULT FALSE,
ADD COLUMN pii_type VARCHAR(32);  -- 'name', 'location', 'identifier', 'date'

-- PII access logging (audit trail)
CREATE TABLE mas_pii_access_log (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES va_users(user_id),
    field_id VARCHAR(64) NOT NULL,
    submission_id VARCHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,  -- 'view', 'export'
    accessed_at TIMESTAMP DEFAULT NOW()
);
```

### Export Rules

```python
def export_submissions(form_id, user, include_pii=False):
    """Export submissions with PII handling."""
    fields = get_field_display_config(form_id)
    pii_fields = {f.field_id for f in fields if f.is_pii}

    submissions = get_submissions(form_id)

    if not include_pii or user.role not in ['admin', 'project_pi']:
        # Mask PII fields
        for sub in submissions:
            for field_id in pii_fields:
                if field_id in sub.data:
                    sub.data[field_id] = '****'

    return submissions
```

---

## Edge Cases

### Scenario 1: Multiple ODK Forms Per Project

**Problem**: A project may have multiple ODK forms with different field sets:
- WHO VA Form 2022 and WHO VA Form 2024
- Different forms for different sites
- Pilot forms vs production forms

**Solution**:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Project: UNSW01                                   │
│                                                                      │
│  ODK Forms Linked:                                                   │
│  ├── NC01_DS_WHOVA2022 (281 fields)                                 │
│  ├── NC01_TVA_WHOVA2022 (281 fields)                                │
│  └── NC01_PILOT_2024 (295 fields) ← NEW VERSION                     │
│                                                                      │
│  Schema Comparison Tool:                                             │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Field              │ 2022 Form │ 2024 Form │ Status         │    │
│  │ ─────────────────────────────────────────────────────────── │    │
│  │ Id10010            │    ✅     │    ✅     │ Common         │    │
│  │ Id10010a           │    ✅     │    ✅     │ Common         │    │
│  │ Id10490            │    ❌     │    ✅     │ NEW in 2024    │    │
│  │ Id10491            │    ❌     │    ✅     │ NEW in 2024    │    │
│  │ Id10099            │    ✅     │    ❌     │ REMOVED in 2024│    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  Actions:                                                            │
│  [Use 2022 Schema] [Use 2024 Schema] [Merge Schemas]               │
└─────────────────────────────────────────────────────────────────────┘
```

**Implementation**:

```python
def compare_form_schemas(form_id_1, form_id_2):
    """Compare two ODK form schemas and return differences."""
    schema_1 = get_odk_form_schema(form_id_1)
    schema_2 = get_odk_form_schema(form_id_2)

    fields_1 = {f['name'] for f in schema_1}
    fields_2 = {f['name'] for f in schema_2}

    return {
        'common': fields_1 & fields_2,
        'only_in_1': fields_1 - fields_2,  # Removed in new version
        'only_in_2': fields_2 - fields_1,  # New in new version
        'choice_diffs': compare_choices(schema_1, schema_2),
    }
```

### Scenario 2: Form Updates During Data Collection

**Problem**: ODK form gets updated mid-collection with new fields:
- Existing submissions have old schema (281 fields)
- New submissions have new schema (295 fields)
- Need to add mappings for new fields WITHOUT losing existing mappings

**Solution**:

```
┌─────────────────────────────────────────────────────────────────────┐
│              Form Schema Change Detection                            │
│                                                                      │
│  Current mapped fields: 281                                         │
│  ODK form now has: 295 fields                                       │
│                                                                      │
│  ⚠️  14 NEW fields detected in ODK form (not yet mapped)           │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ NEW Field    │ Type     │ Current Status    │ Action        │    │
│  │ ─────────────────────────────────────────────────────────── │    │
│  │ Id10490      │ string   │ Not mapped        │ [Assign]      │    │
│  │ Id10491      │ select1  │ Not mapped        │ [Assign]      │    │
│  │ Id10492      │ integer  │ Not mapped        │ [Assign]      │    │
│  │ ...          │          │                   │               │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  [Auto-assign to 'New Fields' category] [Assign individually]      │
│  [Ignore for now] [Export list]                                     │
│                                                                      │
│  ✅ Existing 281 mappings PRESERVED                                 │
└─────────────────────────────────────────────────────────────────────┘
```

**Implementation**:

```python
def detect_schema_changes(form_type_id, odk_form_id):
    """
    Detect new fields in ODK form that aren't mapped.
    Returns new fields for assignment - NEVER modifies existing mappings.
    """
    # Get current mappings (preserved)
    current_mappings = FieldDisplayConfig.query.filter_by(
        form_type_id=form_type_id
    ).all()
    mapped_field_ids = {m.field_id for m in current_mappings}

    # Get ODK form schema
    odk_schema = fetch_odk_form_schema(odk_form_id)
    odk_field_ids = {f['name'] for f in odk_schema}

    # Find new fields
    new_fields = odk_field_ids - mapped_field_ids
    removed_fields = mapped_field_ids - odk_field_ids

    return {
        'new_fields': new_fields,        # Need assignment
        'removed_fields': removed_fields, # No longer in form
        'existing_mappings_preserved': len(mapped_field_ids),
    }


def assign_new_field(form_type_id, field_id, category, sub_category, **kwargs):
    """
    Assign a new field to a category WITHOUT affecting existing mappings.
    """
    # Check if already mapped (safety check)
    existing = FieldDisplayConfig.query.filter_by(
        form_type_id=form_type_id,
        field_id=field_id
    ).first()

    if existing:
        raise ValueError(f"Field {field_id} already mapped - use update instead")

    # Create new mapping
    mapping = FieldDisplayConfig.create(
        form_type_id=form_type_id,
        field_id=field_id,
        category=category,
        sub_category=sub_category,
        **kwargs
    )
    return mapping
```

### Data Model for Schema Versioning

```sql
-- Track form schema versions
CREATE TABLE mas_form_schema_versions (
    schema_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_type_id UUID NOT NULL REFERENCES mas_form_types(form_type_id),
    schema_version INTEGER NOT NULL,
    odk_form_id VARCHAR(64),           -- Which ODK form this schema came from
    field_count INTEGER,               -- Number of fields in this version
    schema_hash VARCHAR(64),           -- Hash of field names for quick comparison
    detected_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE(form_type_id, schema_version)
);

-- Track which schema version submissions belong to
ALTER TABLE va_submissions
ADD COLUMN schema_version_id UUID REFERENCES mas_form_schema_versions(schema_version_id);
```

### Mapping Resolution Rule

```
┌─────────────────────────────────────────────────────────────────────┐
│                    FOR EACH PROJECT                                  │
│                                                                      │
│   1. DETERMINE form_type from va_forms.form_type_id                │
│                                                                      │
│   2. IF project has NO custom mapping:                               │
│      └── Apply BASE TEMPLATE for that form_type                     │
│          ├── WHO_2022_VA → resource/mapping/form_types/WHO_2022_VA/ │
│          ├── BALLABGARH_VA → resource/.../BALLABGARH_VA/           │
│          └── SMART_VA → resource/.../SMART_VA/                      │
│                                                                      │
│   3. IF project HAS custom mapping:                                  │
│      └── Apply PROJECT-SPECIFIC MAPPING (from database)             │
│          └── Uses customized categories, labels, order             │
│          └── Preserves all previous customizations                  │
└─────────────────────────────────────────────────────────────────────┘
```

### Workflow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    BASE TEMPLATE (mapping_labels.xlsx)               │
│                                                                      │
│  Purpose: Starting point for ALL new projects                        │
│                                                                      │
│  Contains:                                                           │
│  - All known field IDs (Id10010, Id10010a, etc.)                    │
│  - Category assignments (vainterviewdetails, etc.)                  │
│  - Sub-category assignments (va_interviewer, etc.)                  │
│  - Short labels, flip colors, info flags, summary flags             │
│  - Category/sub-category display order (implicit in row order)      │
│                                                                      │
│  Status: ✅ Already exists - 427 rows, 14 categories                │
│                                                                      │
│  Usage: Copied ONCE when project first gets custom mapping          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ First time project needs customization
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│              PROJECT-SPECIFIC MAPPING (Database)                     │
│                                                                      │
│  Creation: COPY base template → project_id specific rows            │
│                                                                      │
│  Customization (preserves existing, allows changes):                │
│     - Move fields between categories/sub-categories                  │
│     - Edit short labels                                              │
│     - Change flip colors, info flags                                 │
│     - Adjust display order (sort_order)                              │
│                                                                      │
│  New ODK fields (additive only, never deletes):                     │
│     - System shows unmapped ODK fields                               │
│     - User assigns category/sub-category                             │
│     - User sets display options                                      │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ During sync
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    AUTO-SYNC FROM ODK                                │
│                                                                      │
│  Choices: ✅ Auto-synced from ODK form XLSX                         │
│  Field types: ✅ Auto-synced from ODK form XLSX                     │
│  Display config: ❌ Manual (from base template + customization)     │
│                                                                      │
│  NEW fields detected: Shown in admin for assignment                 │
│  EXISTING mappings: NEVER auto-deleted, always preserved            │
└─────────────────────────────────────────────────────────────────────┘
```

### Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ODK Central                                  │
│  ┌──────────────────┐  ┌──────────────────┐                        │
│  │ WHO VA Form 2022 │  │ Neonatal VA Form │  ...more forms         │
│  └──────────────────┘  └──────────────────┘                        │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      DigitVA Sync Process                           │
│  (unchanged - stores ALL fields in va_data JSONB)                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 NEW: Form Type Registry (Database)                  │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ mas_form_types                                               │   │
│  │ ├── form_type_id: UUID (PK)                                 │   │
│  │ ├── form_type_code: VARCHAR (who_va_2022, neonatal_va)      │   │
│  │ ├── form_type_name: VARCHAR                                 │   │
│  │ ├── form_type_description: TEXT                             │   │
│  │ ├── mapping_version: INTEGER                                │   │
│  │ └── is_active: BOOLEAN                                      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ va_forms (modified)                                          │   │
│  │ ... existing columns ...                                     │   │
│  │ + form_type_id: UUID (FK → mas_form_types)                  │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│              NEW: Form Type Mapping Tables (Database)               │
│                                                                      │
│  mas_field_mappings                                                 │
│  ├── mapping_id: UUID (PK)                                         │
│  ├── form_type_id: UUID (FK)                                       │
│  ├── field_id: VARCHAR (Id10010, neo_001, etc.)                   │
│  ├── category: VARCHAR                                             │
│  ├── sub_category: VARCHAR                                         │
│  ├── short_label: VARCHAR                                          │
│  ├── full_label: TEXT                                              │
│  ├── field_type: VARCHAR                                           │
│  ├── flip_color: BOOLEAN                                           │
│  ├── is_info: BOOLEAN                                              │
│  ├── summary_include: BOOLEAN                                      │
│  ├── sort_order: INTEGER                                           │
│  └── is_active: BOOLEAN                                            │
│                                                                      │
│  mas_choice_mappings                                                │
│  ├── choice_id: UUID (PK)                                          │
│  ├── form_type_id: UUID (FK)                                       │
│  ├── field_id: VARCHAR                                             │
│  ├── choice_value: VARCHAR                                         │
│  ├── choice_label: VARCHAR                                         │
│  └── sort_order: INTEGER                                           │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Modified Render Process                          │
│                                                                      │
│  def get_mapping_for_form(form_id):                                 │
│      form = VaForms.query.get(form_id)                             │
│      form_type = form.form_type                                    │
│      return load_mapping_from_db(form_type_id)                     │
│                                                                      │
│  # Now each form uses its own mapping!                             │
└─────────────────────────────────────────────────────────────────────┘
```

### Database Schema Changes

```sql
-- NEW: Form type registry
CREATE TABLE mas_form_types (
    form_type_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_type_code VARCHAR(32) UNIQUE NOT NULL,
    form_type_name VARCHAR(128) NOT NULL,
    form_type_description TEXT,
    mapping_version INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- NEW: Category display order per form type
CREATE TABLE mas_category_order (
    category_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_type_id UUID NOT NULL REFERENCES mas_form_types(form_type_id),
    category_code VARCHAR(64) NOT NULL,
    category_name VARCHAR(128),
    display_order INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE(form_type_id, category_code)
);

-- NEW: Sub-category display order per form type
CREATE TABLE mas_subcategory_order (
    subcategory_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_type_id UUID NOT NULL REFERENCES mas_form_types(form_type_id),
    category_code VARCHAR(64) NOT NULL,
    subcategory_code VARCHAR(64) NOT NULL,
    subcategory_name VARCHAR(128),
    display_order INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE(form_type_id, category_code, subcategory_code)
);

-- NEW: Field display configuration per form type
CREATE TABLE mas_field_display_config (
    config_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_type_id UUID NOT NULL REFERENCES mas_form_types(form_type_id),
    field_id VARCHAR(64) NOT NULL,
    category_code VARCHAR(64),
    subcategory_code VARCHAR(64),
    short_label VARCHAR(256),
    full_label TEXT,
    field_type VARCHAR(32),
    flip_color BOOLEAN DEFAULT FALSE,
    is_info BOOLEAN DEFAULT FALSE,
    summary_include BOOLEAN DEFAULT FALSE,
    is_pii BOOLEAN DEFAULT FALSE,
    pii_type VARCHAR(32),
    display_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE(form_type_id, field_id)
);

-- NEW: Choice mappings per form type (AUTO-SYNCED from ODK)
CREATE TABLE mas_choice_mappings (
    choice_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_type_id UUID NOT NULL REFERENCES mas_form_types(form_type_id),
    field_id VARCHAR(64) NOT NULL,
    choice_value VARCHAR(128) NOT NULL,
    choice_label VARCHAR(256) NOT NULL,
    display_order INTEGER DEFAULT 0,
    UNIQUE(form_type_id, field_id, choice_value)
);

-- MODIFY: Add form_type to va_forms
ALTER TABLE va_forms
ADD COLUMN form_type_id UUID REFERENCES mas_form_types(form_type_id);

-- Indexes for performance
CREATE INDEX idx_category_order_form_type ON mas_category_order(form_type_id);
CREATE INDEX idx_subcategory_order_form_type ON mas_subcategory_order(form_type_id);
CREATE INDEX idx_field_display_config_form_type ON mas_field_display_config(form_type_id);
CREATE INDEX idx_choice_mappings_form_type ON mas_choice_mappings(form_type_id);
```

### Migration Path

#### Phase 1: Database Setup (Low Risk)

1. Create `mas_form_types` table
2. Create `mas_field_mappings` table
3. Create `mas_choice_mappings` table
4. Add `form_type_id` to `va_forms` (nullable initially)

#### Phase 2: Data Migration (Medium Risk)

1. Create "WHO VA 2022" form type record
2. Migrate data from Excel to database:
   ```python
   def migrate_excel_to_db():
       form_type = FormType.create(code='who_va_2022', name='WHO VA Tool 2022')

       # Migrate field mappings
       df = pd.read_excel('mapping_labels.xlsx')
       for _, row in df.iterrows():
           FieldMapping.create(
               form_type_id=form_type.id,
               field_id=row['name'],
               category=row['category'],
               sub_category=row['sub_category'],
               short_label=row['short_label'],
               # ... other fields
           )

       # Migrate choice mappings
       df = pd.read_excel('mapping_choices.xlsx')
       for _, row in df.iterrows():
           ChoiceMapping.create(
               form_type_id=form_type.id,
               field_id=row['category'],
               choice_value=row['name'],
               choice_label=row['short_label'],
           )
   ```

3. Link existing forms to WHO VA 2022 type
4. Update render code to read from DB (with Excel fallback)

#### Phase 3: New Form Type (Low Risk)

1. Create new form type (e.g., "Neonatal VA")
2. Create field mappings for new form type
3. Create choice mappings for new form type
4. Link new ODK forms to the new form type

#### Phase 4: Admin UI (Future)

1. Build admin interface for managing form types
2. Build CRUD for field mappings
3. Build CRUD for choice mappings
4. Add import/export functionality

### Backward Compatibility

During migration, the system will:

1. **Check DB first**: Try to load mapping from database
2. **Fall back to Excel**: If no DB mapping, use existing Excel files
3. **Log warnings**: Alert when using fallback

```python
def get_field_mapping(form_type_id):
    # Try database first
    db_mapping = FieldMapping.query.filter_by(form_type_id=form_type_id).all()
    if db_mapping:
        return db_mapping

    # Fall back to Excel (legacy)
    logger.warning(f"Using legacy Excel mapping for form_type={form_type_id}")
    return load_from_excel()
```

### File Structure (Proposed)

```
resource/
├── mapping/
│   ├── legacy/                    # Moved during migration
│   │   ├── mapping_labels.xlsx
│   │   └── mapping_choices.xlsx
│   │
│   └── form_types/               # NEW: Form-specific mappings
│       ├── who_va_2022/
│       │   ├── fields.xlsx       # Optional: for import/export
│       │   └── choices.xlsx
│       │
│       └── neonatal_va/
│           ├── fields.xlsx
│           └── choices.xlsx
```

---

## Auto-Sync from ODK Central Form Schema

### Verification Results (2026-03-10)

**Comparison of ODK form vs mapping_choices.xlsx:**

| Metric | Value |
|--------|-------|
| ODK select fields (Id*) | 281 |
| Our mapped fields (Id*) | 281 |
| Common fields | 281 |
| **Exact matches** | **272 (97%)** |
| Differing | 9 (3%) |

**Conclusion**: Our `mapping_choices.xlsx` matches ODK form **97%**. The 9 differing fields are minor issues:
- Trailing spaces (`spouse ` vs `spouse`)
- Extra legacy options (`dk`, `less`, `more`, `ref`)

**We CAN auto-sync choices from ODK Central with high confidence.**

### ODK Central API Capabilities

ODK Central provides API endpoints to retrieve form schema information directly:

| Endpoint | Purpose | Returns |
|----------|---------|---------|
| `GET /projects/{id}/forms/{formId}.xml` | Form XML definition | XForm XML |
| `GET /projects/{id}/forms/{formId}.xlsx` | Original XLSForm | Binary XLSX |
| `GET /projects/{id}/forms/{formId}/fields` | **Form schema as JSON** | Structured field definitions |

### Form Fields API (Recommended)

The `/fields` endpoint returns structured JSON with everything we need:

```json
[
  {
    "name": "Id10010",
    "type": "string",
    "path": "/Id10010",
    "binary": false
  },
  {
    "name": "Id10010b",
    "type": "select1",
    "path": "/Id10010b",
    "binary": false,
    "selectChoices": [
      {"name": "female", "value": "female"},
      {"name": "male", "value": "male"},
      {"name": "undetermined", "value": "undetermined"}
    ]
  },
  {
    "name": "Id10012",
    "type": "date",
    "path": "/Id10012",
    "binary": false
  }
]
```

### Key Insight: What We Can Automate vs What We Can't

| Aspect | Source | Can Automate? |
|--------|--------|---------------|
| **Field names** | ODK form schema | ✅ Yes |
| **Field types** | ODK form schema | ✅ Yes |
| **Choice values** | ODK form schema | ✅ Yes |
| **Choice labels** | ODK form schema | ✅ Yes (language-specific) |
| **Category grouping** | NOT in ODK | ❌ No - requires DigitVA config |
| **Sub-category grouping** | NOT in ODK | ❌ No - requires DigitVA config |
| **Short labels** | NOT in ODK | ❌ No - requires DigitVA config |
| **Flip color flags** | NOT in ODK | ❌ No - requires DigitVA config |
| **Info flags** | NOT in ODK | ❌ No - requires DigitVA config |
| **Summary inclusion** | NOT in ODK | ❌ No - requires DigitVA config |

### Proposed Hybrid Approach

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ODK Central Form Schema API                       │
│  GET /projects/{id}/forms/{formId}/fields                           │
│  ├── field names                                                    │
│  ├── field types                                                    │
│  └── choice values + labels                                         │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Auto-Sync Service (NEW)                            │
│                                                                      │
│  def sync_form_schema(form):                                        │
│      client = va_odk_clientsetup(form.project_id)                   │
│      response = client.get(                                         │
│          f"projects/{form.odk_project_id}/forms/{form.odk_form_id}/fields"│
│      )                                                              │
│      fields = response.json()                                       │
│                                                                      │
│      for field in fields:                                           │
│          # Store/update field definition                            │
│          FormField.upsert(                                          │
│              form_type_id=form.form_type_id,                        │
│              field_id=field['name'],                                │
│              field_type=field['type'],                              │
│          )                                                          │
│                                                                      │
│          # Store/update choices for select fields                   │
│          if 'selectChoices' in field:                               │
│              for choice in field['selectChoices']:                  │
│                  FormChoice.upsert(                                 │
│                      form_type_id=form.form_type_id,                │
│                      field_id=field['name'],                        │
│                      choice_value=choice['value'],                  │
│                      choice_label=choice['name'],                   │
│                  )                                                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│              DigitVA-Specific Configuration (DB)                    │
│                                                                      │
│  mas_field_display_config                                           │
│  ├── form_type_id                                                   │
│  ├── field_id                                                       │
│  ├── category          ← DigitVA-specific grouping                  │
│  ├── sub_category      ← DigitVA-specific subgrouping               │
│  ├── short_label       ← Custom display label                       │
│  ├── flip_color        ← UI styling flag                            │
│  ├── is_info           ← Header row flag                            │
│  ├── summary_include   ← Summary view flag                          │
│  └── sort_order        ← Display order                              │
└─────────────────────────────────────────────────────────────────────┘
```

### Benefits of Hybrid Approach

| Benefit | Description |
|---------|-------------|
| **No manual choice sync** | Choices auto-synced from ODK when form updates |
| **Form version tracking** | Detect when ODK form schema changes |
| **Validation** | Warn if ODK has fields not in display config |
| **Multi-language support** | ODK stores labels per language |
| **Single source of truth** | ODK form is authoritative for field structure |
| **Flexibility preserved** | DigitVA-specific display config remains manual |

### Implementation: Auto-Sync Choices

```python
# app/services/va_form_schema/va_form_schema_01_sync.py

def sync_form_choices(form):
    """
    Sync choice options from ODK Central form schema.
    Run this after form creation and periodically to detect schema changes.
    """
    client = va_odk_clientsetup(form.project_id)

    # Get form fields from ODK Central
    response = client.get(
        f"projects/{form.odk_project_id}/forms/{form.odk_form_id}/fields"
    )
    fields = response.json()

    synced_count = 0
    for field in fields:
        if field.get('type', '').startswith('select'):
            # This is a select field - sync its choices
            for choice in field.get('selectChoices', []):
                ChoiceMapping.upsert(
                    form_type_id=form.form_type_id,
                    field_id=field['name'],
                    choice_value=choice['value'],
                    choice_label=choice['name'],
                )
                synced_count += 1

    # Log unmapped fields (fields in ODK but not in display config)
    unmapped = find_unmapped_fields(form, fields)
    if unmapped:
        logger.warning(f"Unmapped fields in {form.form_id}: {unmapped}")

    return synced_count


def find_unmapped_fields(form, odk_fields):
    """Find fields in ODK that have no display configuration."""
    odk_field_names = {f['name'] for f in odk_fields}
    configured = set(
        FieldDisplayConfig.query
        .filter_by(form_type_id=form.form_type_id)
        .values('field_id')
    )
    return odk_field_names - configured
```

### API Endpoint for Manual Trigger

```python
# app/routes/admin.py

@admin.route('/forms/<form_id>/sync-schema', methods=['POST'])
@login_required
def sync_form_schema(form_id):
    """Manually trigger form schema sync from ODK Central."""
    form = VaForms.query.get_or_404(form_id)

    try:
        count = sync_form_choices(form)
        flash(f"Synced {count} choice options from ODK Central.", "success")
    except Exception as e:
        flash(f"Failed to sync: {e}", "danger")

    return redirect(url_for('admin.forms'))
```

### What Gets Eliminated

| Current (Manual) | New (Automated) |
|------------------|-----------------|
| `mapping_choices.xlsx` maintenance | Auto-sync from ODK API |
| Manual choice updates when form changes | Detect + sync on schedule |
| Risk of mismatch | Always in sync with ODK |
| 1199 rows to maintain | Zero manual rows |

### What Remains Manual

| Configuration | Why Manual |
|--------------|------------|
| Category grouping | DigitVA-specific, not in ODK |
| Sub-category grouping | DigitVA-specific, not in ODK |
| Short labels | Custom display text |
| Flip colors | UI styling preference |
| Info flags | UI behavior preference |
| Summary inclusion | Business logic |

---

## Admin UI — Form Type Management

The Field Mapping panel is accessible at `/admin/?panel=/admin/panels/field-mapping`
(admin role required). It shows a card for each registered form type.

### Form Type Card

Each card displays:
- **Form Type Code** — short uppercase identifier (e.g. `WHO_2022_VA`)
- **Form Type Name** — human-readable name
- **Description** — optional free text
- **Stats** — count of categories, fields, and choices

Card footer actions:

| Button | Behaviour |
|--------|-----------|
| **Fields** | Opens the field list sub-panel for this form type |
| **Sync ODK** | Opens the ODK sync sub-panel (choose connection → project → form) |
| **Duplicate** | Opens a modal to copy the entire form type under a new code |
| **Export** | Downloads a `form_type_<code>.json` bundle (direct link) |

### Creating a New Form Type

Click **New Form Type** in the panel header. A modal prompts for:

| Field | Rules |
|-------|-------|
| **Form Type Code** | Uppercase, letters/digits/underscores, max 32 chars |
| **Form Type Name** | Free text, max 128 chars |
| **Description** | Optional free text |

On submit → `POST /admin/api/form-types` → creates a blank `MasFormTypes` row.
The panel reloads to show the new card.

### Duplicating a Form Type

Click **Duplicate** on any card. Provide a new code and name.

On submit → `POST /admin/api/form-types/<source_code>/duplicate`

The service copies:
- All `MasCategoryOrder` rows (new UUIDs, same codes/names/order)
- All `MasSubcategoryOrder` rows
- All `MasFieldDisplayConfig` rows (all labels, PII flags, display settings)
- All `MasChoiceMappings` rows

The duplicated form type is independent — changes to it do not affect the source.

### Exporting a Form Type

Click **Export** on any card → browser downloads `form_type_<code>.json`.

The file is a self-contained JSON bundle:

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
  "categories": [ { "category_code": "A", "category_name": "...", "display_order": 1, "is_active": true } ],
  "subcategories": [ { "category_code": "A", "subcategory_code": "A1", ... } ],
  "fields": [ { "field_id": "Id10007", "short_label": "...", "odk_label": "...", ... } ],
  "choices": [ { "field_id": "Id10007", "choice_value": "1", "choice_label": "Yes", ... } ]
}
```

Route: `GET /admin/api/form-types/<code>/export`
The file is safe to commit to version control and share between environments.

### Importing a Form Type

Click **Import** in the panel header. A modal prompts for a `.json` export file.

On file selection, a preview strip shows the embedded code/name/counts before committing.

If the code already exists in this database, the import will fail with a conflict error.
Use the **"Import with a different code / name"** toggle to override the code, name,
and description before submitting.

On submit → `POST /admin/api/form-types/import` (multipart form, file + optional override fields)

The response includes creation stats:

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

Import always creates a new form type. It does **not** update or merge into an existing one.

---

## Admin UI — Field Management

Click **Fields** on any form type card to open the field list sub-panel.

### Field List

Displays all fields for the selected form type in a table:

| Column | Source |
|--------|--------|
| Field ID | ODK variable name (read-only) |
| ODK Label | Synced from XLSForm `survey` sheet |
| Short Label | App-level display label for coding screens |
| Category / Sub-category | Display grouping |
| Type | `select_one`, `integer`, `text`, etc. |
| Flip | Inverts colour coding in the UI |
| Info | Marks field as informational (no coding) |
| Summary | Include in the case summary panel |
| PII | Field contains personally identifiable information |
| Source | `ODK` (from sync) or `App` (custom) |

Route: `GET /admin/panels/field-mapping/fields?form_type=<code>`

### Editing a Field

Click the pencil icon on any row to open the edit modal. Editable fields:

| Field | Notes |
|-------|-------|
| **Short Label** | Display label in coding screen |
| **Full Label** | Expanded label (tooltips, detail views) |
| **Summary Label** | Label used in the summary panel |
| **Category** | Assigns the field to a display category |
| **Sub-category** | Assigns the field to a display sub-category |
| **Age Group** | `neonate`, `child`, `adult`, or blank |
| **Field Type** | Override the ODK field type |
| **Flip Color** | Toggle colour inversion |
| **Is Info** | Toggle informational flag |
| **Summary Include** | Toggle summary inclusion |
| **Is PII** | Toggle PII flag |
| **PII Type** | Type of PII (name, dob, address, etc.) |

The modal also shows **ODK Label** and **Field ID** as read-only reference.

Hover tooltips on each label explain the field's purpose.

On submit → `POST /admin/panels/field-mapping/field/<form_type_code>/<field_id>`
On success the table row updates in-place (HTMX `outerHTML` swap) and the modal closes.

---

## Admin UI — ODK Sync

Click **Sync ODK** on any form type card to open the sync sub-panel.

### Selecting the ODK Source

Three cascading dropdowns:

1. **ODK Connection** — lists active connections from `MasOdkConnections`
   (auto-selects if only one active connection)
2. **ODK Project** — populated via `GET /admin/api/odk-connections/<id>/odk-projects`
3. **ODK Form** — populated via `GET /admin/api/odk-connections/<id>/odk-projects/<pid>/forms`

Both **Preview Changes** and **Run Sync** buttons are disabled until a form is selected.

### Preview Changes

Click **Preview Changes** → `POST /admin/panels/field-mapping/sync/preview`

Runs a dry-run (no DB writes). Shows colour-coded tables:

| Colour | Meaning |
|--------|---------|
| Blue | Field ODK label updates |
| Green | New choices to be added |
| Yellow | Existing choices with changed labels |

### Running a Sync

Click **Run Sync** → `POST /admin/panels/field-mapping/sync`

The sync service:
1. Downloads the XLSForm XLSX from ODK Central via pyODK
2. Parses the **`survey`** sheet: reads `name`, `type`, `label*` columns
3. Parses the **`choices`** sheet: reads `list_name`, `name`, `label*` columns
4. Joins on `list_name` extracted from `type` strings like `select_one <list_name>`
5. For each field in the DB (`MasFieldDisplayConfig`): updates `odk_label` if changed
6. For each choice in the XLSForm: upserts into `MasChoiceMappings`
   - New choices are inserted
   - Existing choices with changed labels are updated
   - **No choices are deactivated** (sync is additive only — see below)

**Result table** shows: fields processed, ODK labels updated, choices added, choices updated.

### Why Sync is Additive-Only

The WHO VA XLSForm is a universal template covering all deployment sites (India, Australia,
Thailand, etc.). A site-specific ODK project only contains the choices relevant to that
site. Deactivating against one site's form would silently remove choices used by other
sites. Choices seeded from `resource/mapping/mapping_choices.xlsx` are the canonical
source; ODK sync only augments them.

### Label Column Discovery

XLSForm label columns vary by form (`label`, `label::English (en)`, `label::English`, etc.).
The sync service picks the first column whose name starts with `label`.

---

## Implementation Checklist

### Phase 0: ODK Schema Sync
- [x] Add `OdkSchemaSyncService` with `sync_form_choices` and `detect_schema_changes`
- [x] Add `preview_sync` (dry-run mode)
- [x] Switch from `/fields` API to XLSX as primary source
- [x] Parse both `survey` and `choices` sheets
- [x] Additive-only sync (no deactivation)
- [x] `odk_label` stored in `MasFieldDisplayConfig`
- [x] Admin UI with cascading Connection → Project → Form selectors
- [x] Preview Changes before committing

### Phase 1: Database Setup
- [x] Migration for `mas_form_types`
- [x] Migration for `mas_category_order`
- [x] Migration for `mas_subcategory_order`
- [x] Migration for `mas_field_display_config` (includes `is_pii`, `pii_type`, `odk_label`)
- [x] Migration for `mas_choice_mappings`
- [x] Migration for `mas_pii_access_log`
- [x] `form_type_id` column on `va_forms`
- [x] SQLAlchemy models

### Phase 2: Data Migration
- [x] WHO VA 2022 form type registered
- [x] Display config migrated from Excel via `Who2022VaMigrator`
- [x] Choices populated from `mapping_choices.xlsx`
- [x] Existing forms linked to form type

### Phase 3: PII Handling
- [x] PII flags on fields (`is_pii`, `pii_type`)
- [ ] PII masking in display render functions
- [ ] Role-based PII access control
- [ ] PII access logging (`mas_pii_access_log`)
- [ ] `include_pii` parameter for exports

### Phase 4: New Form Support
- [x] Create new form type via admin UI (blank or duplicate)
- [x] Export / import form type bundles (JSON)
- [x] ODK sync per form type
- [ ] Render pipeline using form-type-specific mappings for non-WHO forms

### Phase 5: Admin UI
- [x] Form type management page (create, duplicate, export, import)
- [x] Field display config edit interface (modal, inline row update)
- [x] PII field marking in field editor
- [x] ODK sync UI per form type (cascading selectors, preview, run)
- [ ] Unmapped fields warning dashboard
- [ ] Celery task for periodic sync

---

## Related Files

### Services
- [`app/services/form_type_service.py`](../../app/services/form_type_service.py) — CRUD, duplicate, export, import
- [`app/services/odk_schema_sync_service.py`](../../app/services/odk_schema_sync_service.py) — ODK XLSForm sync
- [`app/services/field_mapping_service.py`](../../app/services/field_mapping_service.py) — runtime rendering service

### Routes
- [`app/routes/admin.py`](../../app/routes/admin.py) — all field mapping admin routes (lines ~1089–1360)

### Templates
- [`app/templates/admin/panels/field_mapping.html`](../../app/templates/admin/panels/field_mapping.html) — main panel (form cards, import/export modals)
- [`app/templates/admin/panels/field_mapping_field_edit.html`](../../app/templates/admin/panels/field_mapping_field_edit.html) — field edit modal
- [`app/templates/admin/panels/field_mapping_field_row.html`](../../app/templates/admin/panels/field_mapping_field_row.html) — table row partial (returned on save)
- [`app/templates/admin/panels/field_mapping_fields.html`](../../app/templates/admin/panels/field_mapping_fields.html) — field list sub-panel
- [`app/templates/admin/panels/field_mapping_sync.html`](../../app/templates/admin/panels/field_mapping_sync.html) — ODK sync sub-panel

### Models
- [`app/models/va_field_mapping.py`](../../app/models/va_field_mapping.py) — all field mapping models

### Tests
- [`tests/services/test_odk_schema_sync.py`](../../tests/services/test_odk_schema_sync.py) — 10 tests covering sync service

### Seed / Migration Data
- [`resource/mapping/mapping_labels.xlsx`](../../resource/mapping/mapping_labels.xlsx) — source field definitions
- [`resource/mapping/mapping_choices.xlsx`](../../resource/mapping/mapping_choices.xlsx) — source choice definitions

### Related Documentation
- [ODK Sync](odk-sync.md) — how submissions are downloaded
- [Data Model](data-model.md) — database schema
- [Admin and Setup](admin-and-setup.md) — admin panel overview
- [Architecture Overview](architecture-overview.md) - System architecture
