---
title: WHO 2022 to SmartVA Field Mapping
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-17
---

# WHO 2022 to SmartVA Field Mapping

This document maps WHO 2022 VA form fields to their corresponding SmartVA internal variable names. Understanding this mapping is essential for debugging SmartVA results and interpreting which form data influences cause-of-death predictions.

---

## Narrative and Keyword Fields

These fields provide narrative context and keyword selections that feed into SmartVA's tariff scoring algorithm.

| WHO Field | WHO Field Label | SmartVA Field Name | Notes |
|-----------|-----------------|-------------------|-------|
| Id10476 | Narration | `adult_7_c`, `child_6_c` | Free-text narrative; word extraction (English only) → `s9999*` variables |
| Id10477 | Narration keywords (Adult) | `adult_7_*` | One-hot encoded from select_multiple |
| Id10478 | Narration keywords (Child) | `child_6_*` | One-hot encoded from select_multiple |
| Id10479 | Narration keywords (Neonate) | `neonate_6_*` | One-hot encoded from select_multiple |

See [smartva-keyword-processing.md](smartva-keyword-processing.md) for details on how these are processed.

---

## Health Care Worker and Facility Fields

| WHO Field | WHO Field Label | SmartVA Field Name | Notes |
|-----------|-----------------|-------------------|-------|
| Id10436 | Comment by health care worker | `adult_6_3b`, `child_5_0b` | Text field |
| Id10444 | Health service utilization text | `adult_6_8`, `child_5_9` | Text field |

---

## Cause of Death Certificate Fields

These fields capture medical certification of cause of death, when available from health facilities.

| WHO Field | WHO Field Label | SmartVA Field Name | Notes |
|-----------|-----------------|-------------------|-------|
| Id10464 | Immediate cause of death | `adult_6_11`, `child_5_12` | From death certificate |
| Id10466 | First antecedent cause | `adult_6_12`, `child_5_13` | From death certificate |
| Id10468 | Second antecedent cause | `adult_6_13`, `child_5_14` | From death certificate |
| Id10470 | Third antecedent cause | `adult_6_14`, `child_5_15` | From death certificate |
| Id10472 | Contributing cause(s) | `adult_6_15`, `child_5_16` | From death certificate |

---

## Chronic Condition Fields (Adult)

These fields capture chronic conditions from the final illness history section.

| WHO Field | WHO Field Label | SmartVA Field Name | Condition |
|-----------|-----------------|-------------------|-----------|
| Id10125 | Chronic condition | `adult_1_1d` | Diabetes |
| Id10127 | Chronic condition | `adult_1_1n` | TB |
| Id10133 | Chronic condition | `adult_1_1i` | HIV/AIDS |
| Id10134 | Chronic condition | `adult_1_1g` | Heart disease |
| Id10135 | Chronic condition | `adult_1_1a` | Asthma |
| Id10136 | Chronic condition | `adult_1_1h` | High blood pressure |
| Id10137 | Chronic condition | `adult_1_1c` | Cancer |
| Id10138 | Chronic condition | `adult_1_1m` | Stroke |
| Id10141 | Chronic condition | `adult_1_1l` | Other |

---

## Age Group Prefixes

SmartVA uses different prefixes for different age groups:

| Age Group | Prefix | Example Fields |
|-----------|--------|----------------|
| Adult (12+ years) | `adult_` | `adult_7_3`, `adult_6_11` |
| Child (1-11 years) | `child_` | `child_6_3`, `child_5_12` |
| Neonate (<1 year) | `neonate_` | `neonate_6_1`, `neonate_5_1` |

---

## Processing Pipeline

```
WHO Form (ODK) → Field Extraction → PHMRC Variable Names → SmartVA Analysis
     ↓
Id10477="Fever"  →  adult_7_3=1     →  Tariff scoring for fever symptoms
```

### Key Files

| File | Purpose |
|------|---------|
| `vendor/smartva-analyze/src/smartva/data/who_data.py` | WHO field → PHMRC variable mapping |
| `vendor/smartva-analyze/src/smartva/data/word_conversions.py` | Free-text word → s9999* mapping |
| `app/utils/va_smartva/va_smartva_02_prepdata.py` | DigitVA data preparation for SmartVA |

---

## Related Documentation

- [smartva-keyword-processing.md](smartva-keyword-processing.md) — Narrative and keyword processing details
- [smartva-analysis.md](smartva-analysis.md) — Overall SmartVA integration
- [data-model.md](data-model.md) — Database schema for SmartVA results
