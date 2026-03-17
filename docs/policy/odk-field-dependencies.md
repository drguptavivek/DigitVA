---
title: ODK Field Dependencies — Application Logic Based on ODK Form Fields
doc_type: policy
status: active
owner: engineering
last_updated: 2026-03-17
---

# ODK Field Dependencies — Application Logic Based on ODK Form Fields

## Purpose

This document captures all ODK form fields that the DigitVA application depends on for business logic. When creating new ODK forms or modifying existing ones, these field names and values MUST be preserved to ensure correct application behavior.

**Critical for:** New form creation, form migration, field renaming, choice value changes.

---

## 1. Consent Capture — `Id10013`

| Property | Value |
|----------|-------|
| **Field Name** | `Id10013` |
| **Location in ODK** | `respondent_backgr.Id10013` (nested in group) |
| **Flattened Name** | `Id10013` (after OData normalization) |
| **DB Column** | `va_submissions.va_consent` |

### Expected Values

| Value | Behavior |
|-------|----------|
| `yes` | Submission is **imported** and stored locally |
| `no` | Submission is **imported** and stored locally |
| `telephonic_consent` | Submission is **imported** and stored locally |
| (any other) | Submission is **imported** and stored locally |
| `null` / missing | Submission is **imported** and stored locally as blank consent |

### Code Reference

Consent is normalized and persisted during sync; it is no longer an ingest-time
filter.

### Impact

- Consent remains available for workflow and UI decisions, but it does not
  exclude a row from local sync
- Coverage comparison and dashboard counts should treat consented and
  non-consented rows as part of the synced ODK population
- Data managers can review ODK status and sync health without losing visibility
  into consent=`no` or consent-missing rows

---

## 2. Deceased Gender — `Id10019`

| Property | Value |
|----------|-------|
| **Field Name** | `Id10019` |
| **Location in ODK** | `respondent_backgr.Id10019` |
| **Flattened Name** | `Id10019` |
| **DB Column** | `va_submissions.va_deceased_gender` |

### Expected Values

- `male`
- `female`
- `dont_know`
- `na` (not applicable)

### Code Reference

```python
# app/services/va_data_sync/va_data_sync_01_odkcentral.py:110
va_submission_gender = va_submission.get("Id10019")
```

### Usage

- Displayed in submission lists
- Passed to SmartVA for analysis
- Used in demographic summaries

---

## 3. Deceased Age — `finalAgeInYears`

| Property | Value |
|----------|-------|
| **Field Name** | `finalAgeInYears` |
| **Location in ODK** | Computed field in form |
| **Flattened Name** | `finalAgeInYears` |
| **DB Column** | `va_submissions.va_deceased_age` |

### Expected Values

- Integer (0-120+)
- `nan` (handled gracefully)

### Code Reference

```python
# app/services/va_data_sync/va_data_sync_01_odkcentral.py:105-109
_raw_age = va_submission.get("finalAgeInYears")
try:
    va_submission_age = int(_raw_age) if _raw_age else 0
except (ValueError, TypeError):
    va_submission_age = 0  # Handles NaN, None, invalid values
```

### Edge Cases

- `NaN` string from OData → converted to `0`
- `None` / missing → converted to `0`
- Invalid values → converted to `0`

---

## 4. Unique Identifier — `unique_id`

| Property | Value |
|----------|-------|
| **Field Name** | `unique_id` |
| **Location in ODK** | Top-level field |
| **Flattened Name** | `unique_id` |
| **DB Column** | `va_submissions.va_uniqueid_real`, `va_uniqueid_masked` |

### Derived Field: `unique_id2`

Computed from `unique_id` + `start` timestamp:

```python
# app/utils/va_odk/va_odk_06_fetchsubmissions.py:217-232
out["unique_id2"] = (
    str(out["unique_id"]).rsplit("_", 1)[0]
    + "_"
    + start_dt.strftime("%H%M%S")
    + f"{int(start_dt.microsecond / 1000):03}"
)
```

### Usage

- Masked display identifier for privacy
- Search and filtering in UI

---

## 5. Narration Language — `narr_language` / `language`

| Property | Value |
|----------|-------|
| **Primary Field** | `narr_language` |
| **Fallback Field** | `language` |
| **DB Column** | `va_submissions.va_narration_language` |
| **Normalization** | Raw ODK values mapped to canonical codes via `map_language_aliases` |
| **Canonical List** | `mas_languages` table |

### Language Normalization

Raw ODK values (e.g., `"Bengali"`, `"bn"`, `"bangla"`) are normalized to canonical
codes (e.g., `"bangla"`) at sync time using the `map_language_aliases` lookup table.
Unknown values pass through unchanged and are stored as-is.

### Code Reference

```python
# app/services/va_data_sync/va_data_sync_01_odkcentral.py
_raw_lang = (
    va_submission.get("narr_language")
    if va_submission.get("narr_language")
    else va_submission.get("language")
)
va_submission_narrlang = _normalize_language(_raw_lang)
```

### Canonical Languages

| Code | Display Name | Common Aliases |
|------|-------------|----------------|
| `bangla` | Bangla | bengali, bn |
| `english` | English | en, eng |
| `hindi` | Hindi | hi, hin |
| `kannada` | Kannada | kn, kan |
| `malayalam` | Malayalam | ml, mal |
| `marathi` | Marathi | mr, mar |
| `tamil` | Tamil | ta, tam |
| `telugu` | Telugu | te, tel |
| `gujarati` | Gujarati | gu, guj |
| `odia` | Odia | or, ori, oriya |
| `punjabi` | Punjabi | pa, pan |
| `assamese` | Assamese | as, asm |
| `urdu` | Urdu | ur, urd |

### Adding New Languages or Aliases

Add rows to `mas_languages` and `map_language_aliases` via admin or migration.
The sync alias cache reloads at the start of each sync run.

---

## 6. OData System Fields (Auto-generated)

These fields come from ODK Central's `__system` metadata and are always present.

| OData Field | Flattened Name | DB Column | Purpose |
|-------------|----------------|-----------|---------|
| `__id` | `KEY` | Used in `sid` computation | ODK submission UUID |
| `__system/submissionDate` | `SubmissionDate` | `va_submissions.va_submission_date` | When submitted to ODK |
| `__system/updatedAt` | `updatedAt` | `va_submissions.va_odk_updatedat` | Last edit timestamp |
| `__system/submitterName` | `SubmitterName` | `va_submissions.va_data_collector` | Data collector name |
| `__system/reviewState` | `ReviewState` | `va_submissions.va_odk_reviewstate` | ODK review state |
| `meta/instanceName` | `instanceName` | `va_submissions.va_instance_name` | Display name in ODK |

### Code Reference

```python
# app/utils/va_odk/va_odk_06_fetchsubmissions.py:200-206
out["KEY"] = instance_id
out["SubmissionDate"] = system.get("submissionDate")
out["updatedAt"] = system.get("updatedAt")
out["SubmitterName"] = system.get("submitterName")
out["ReviewState"] = system.get("reviewState")
out["instanceName"] = meta.get("instanceName")
```

---

## 7. Submission ID — `sid` (Computed)

| Property | Value |
|----------|-------|
| **Format** | `{KEY}-{form_id.lower()}` |
| **Example** | `uuid:abc123-icmr01mp0101` |
| **DB Column** | `va_submissions.va_sid` (PRIMARY KEY) |

### Code Reference

```python
# app/utils/va_odk/va_odk_06_fetchsubmissions.py:213
out["sid"] = f"{instance_id}-{form_id.lower()}"
```

### Impact

- This is the primary key for all submission records
- Used in all foreign key relationships (allocations, assessments, reviews, notes)
- MUST be deterministic — same ODK submission always produces same `sid`

---

## 8. SmartVA Input Fields

The following fields are required for SmartVA analysis. If missing or invalid, SmartVA may fail or produce incorrect results.

### Age Computation Fields

| Field | Purpose |
|-------|---------|
| `ageInDays` | Age in days (neonates) |
| `ageInDays2` | Secondary age in days |
| `ageInYears` | Age in years |
| `ageInYearsRemain` | Remaining years |
| `ageInMonths` | Age in months |
| `ageInMonthsRemain` | Remaining months |

### Code Reference

```python
# app/utils/va_smartva/va_smartva_02_prepdata.py:45-52
nan_check_columns = [
    "ageInDays", "ageInDays2", "ageInYears", "ageInYearsRemain",
    "ageInMonths", "ageInMonthsRemain",
]
```

### NaN Handling

SmartVA cannot process `NaN` values. The app converts OData `NaN` strings to Python `None` before writing to CSV.

---

## 9. Fields Excluded from SmartVA

The following field prefixes are **dropped** from SmartVA input to prevent processing errors:

| Prefix | Reason |
|--------|--------|
| `sa01` - `sa19` | Social autopsy modules (not used by SmartVA) |
| `sa_`, `sa_note`, `sa_tu` | Social autopsy notes and training |
| `survey_block` | Survey metadata |
| `telephonic_consent` | Consent tracking (non-standard) |

### Code Reference

```python
# app/utils/va_smartva/va_smartva_02_prepdata.py:10-14
_SMARTVA_DROP_PREFIXES = ("sa01", "sa02", ..., "survey_block", "telephonic_consent")
```

---

## 10. Form Instance Fields

| Field | Purpose |
|-------|---------|
| `form_def` | Form ID (computed, e.g., `ICMR01MP0101`) |
| `start` | Submission start timestamp (used for `unique_id2` derivation) |
| `KEY` | ODK instance ID |

---

## Summary: Required Fields Checklist

When creating a new ODK form for DigitVA, ensure it contains:

### Mandatory for Sync

| Field | Location | Expected Values |
|-------|----------|-----------------|
| `Id10013` | `respondent_backgr` | `"yes"` (to be synced) |
| `Id10019` | `respondent_backgr` | `"male"`, `"female"`, `"dont_know"`, `"na"` |
| `finalAgeInYears` | (computed) | Integer or `nan` |
| `unique_id` | (top-level) | Any string |

### Mandatory for SmartVA

| Field | Purpose |
|-------|---------|
| All WHO VA 2022 standard fields | Cause of death analysis |
| `ageInYears`, `ageInMonths`, `ageInDays` | Age computation |
| `Id10019` | Sex/gender |

### Auto-provided by ODK Central

| Field | Source |
|-------|--------|
| `__id` | ODK Central |
| `__system/submissionDate` | ODK Central |
| `__system/updatedAt` | ODK Central |
| `__system/submitterName` | ODK Central |
| `__system/reviewState` | ODK Central |
| `meta/instanceName` | ODK form meta |

---

## Migration Notes

### Changing Field Names

1. **Update sync code** — `va_data_sync_01_odkcentral.py`
2. **Update mapping files** — `resource/mapping/*.xlsx`
3. **Update preprocessing** — `va_preprocess_*.py`
4. **Update SmartVA prep** — `va_smartva_02_prepdata.py`
5. **Test with sample data** before deploying

### Adding New Consent Values

Current logic: any non-null, non-`"no"` value is accepted. No code change needed
for new consent values — they are imported automatically.

### Adding New Languages

Add rows to `mas_languages` and `map_language_aliases` tables. The sync alias
cache reloads at the start of each sync run. New languages can also be added
via the seed command or a migration.

---

## Related Documents

- [`odk-sync.md`](../current-state/odk-sync.md) — Sync implementation details
- [`data-model.md`](../current-state/data-model.md) — Database schema
- [`workflow-and-permissions.md`](../current-state/workflow-and-permissions.md) — Workflow logic
