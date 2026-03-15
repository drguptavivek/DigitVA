---
title: SmartVA Keyword and Free-Text Processing
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-16
---

# SmartVA Keyword and Free-Text Processing

This document explains how SmartVA extracts diagnostic signals from narrative text and keyword selections in the WHO 2022 VA form. Understanding this processing is essential for interpreting results, especially in multilingual deployments.

---

## Overview

SmartVA has two mechanisms for extracting cause-related information from narrative responses:

| Mechanism | WHO 2022 Fields | Processing | Language Dependent |
|-----------|-----------------|------------|-------------------|
| **Free-text word extraction** | Id10476 (narrative text) | Stem → Map to s9999* | **Yes (English only)** |
| **Keyword one-hot encoding** | Id10477, Id10478, Id10479 | Choice → Binary variable | **No** |

Both mechanisms contribute symptom features that feed into the tariff-based cause scoring algorithm.

---

## WHO 2022 Narrative Fields

### Field Definitions

| Field ID | Field Name | Type | Description |
|----------|------------|------|-------------|
| `Id10476` | Narrative | Text | Open-ended verbal autopsy narrative |
| `Id10477` | Adult Keywords | select_multiple | Cause-related keywords for adults |
| `Id10478` | Child Keywords | select_multiple | Cause-related keywords for children |
| `Id10479` | Neonate Keywords | select_multiple | Cause-related keywords for neonates |

### Processing Flow

```
Id10476 (text)     →  Word extraction  →  s9999* variables
                         (English only)

Id10477 (choices)  →  One-hot encoding →  adult_7_* variables
Id10478 (choices)  →  One-hot encoding →  child_6_* variables
Id10479 (choices)  →  One-hot encoding →  neonate_6_* variables
```

---

## Free-Text Word Extraction

### Source Files

| File | Purpose |
|------|---------|
| `vendor/smartva-analyze/src/smartva/data/word_conversions.py` | Word → variable mappings |
| `vendor/smartva-analyze/src/smartva/data/common_data.py` | `WORD_SUBS` misspelling corrections |
| `vendor/smartva-analyze/src/smartva/pre_symptom_prep.py` | Word extraction logic |
| `vendor/smartva-analyze/src/smartva/common_prep.py` | Free-text preprocessing |

### Processing Pipeline

1. **Normalize text** (`common_prep.py:293-310`)
   ```python
   # Lowercase, remove non-alphabetic characters
   words = re.sub('[^a-z ]', '', row[variable].lower()).split(' ')
   ```

2. **Apply word substitutions** (`WORD_SUBS` dictionary)
   - Corrects common misspellings
   - Normalizes variants to canonical forms

3. **Stem words** (Porter2 stemmer)
   ```python
   stem("fever")     → "fever"
   stem("fevers")    → "fever"
   stem("diabetes")  → "diabet"
   stem("diabetic")  → "diabet"
   ```

4. **Map to symptom variables** (`word_conversions.py`)
   ```python
   ADULT_WORDS_TO_VARS = {
       'fever': 's999969',
       'cancer': 's999927',
       'stroke': 's9999146',
       'suicide': 's9999148',
       # ... 172 total mappings
   }
   ```

5. **Set binary flags**
   ```python
   row['s999969'] = 1  # if "fever" found in narrative
   ```

### Word Substitutions (`common_data.py:451-557`)

The `WORD_SUBS` dictionary maps misspellings and variants to canonical forms:

| Input Word | Mapped To | Reason |
|------------|-----------|--------|
| `abdominal` | `abdomen` | Variant normalization |
| `bleeding` | `blood` | Variant normalization |
| `heart attack` | `ami` | Acute myocardial infarction |
| `aids` | `hiv` | Synonym |
| `burned`, `burnt`, `burning` | `fire` | Tense normalization |
| `pnuemonia` | `pneumonia` | Common misspelling |
| `poisonous` | `poison` | Form normalization |
| `tuberculosis` | `tb` | Abbreviation |

### Adult Word Mappings (`word_conversions.py:1-173`)

172 English word stems map to `s9999*` variables:

| Word Stem | Variable | Word Stem | Variable |
|-----------|----------|-----------|----------|
| `arrest` | `s99999` | `kidney` | `s999999` |
| `abdomen` | `s99991` | `cancer` | `s999927` |
| `asthma` | `s999911` | `fever` | `s999969` |
| `bite` | `s999917` | `stroke` | `s9999146` |
| `blood` | `s999919` | `suicide` | `s9999148` |

### Child Word Mappings (`word_conversions.py:175-225`)

55 word stems for child analysis:

| Word Stem | Variable |
|-----------|----------|
| `fever` | `s999919` |
| `diarrhea` | `s999916` |
| `pneumonia` | `s999933` |
| `malaria` | `s999930` |
| `drown` | `s999917` |

### Neonate Word Mappings (`word_conversions.py:227-265`)

38 word stems for neonate analysis:

| Word Stem | Variable |
|-----------|----------|
| `asphyxia` | `s99993` |
| `sepsi` | `s999932` |
| `preterm` | `s999930` |
| `stillbirth` | `s999933` |

---

## Keyword One-Hot Encoding

### Source File

`vendor/smartva-analyze/src/smartva/data/who_data.py:391-420`

### Processing Logic

The `ONE_HOT_FROM_MULTISELECT` dictionary maps (WHO field, choice value) pairs to binary PHMRC-style variables:

```python
ONE_HOT_FROM_MULTISELECT = {
    'adult_7_1': ('Id10477', 'Chronic_kidney_disease'),
    'adult_7_2': ('Id10477', 'Dialysis'),
    # ...
}
```

When processing:
```python
# If Id10477 contains "Fever" in its space-separated value list
row['adult_7_3'] = 1  # else 0
```

### Adult Keywords (Id10477 → adult_7_*)

| Variable | Choice Value | Description |
|----------|--------------|-------------|
| `adult_7_1` | `Chronic_kidney_disease` | Chronic kidney disease |
| `adult_7_2` | `Dialysis` | Dialysis treatment |
| `adult_7_3` | `Fever` | Fever |
| `adult_7_4` | `Heart_attack` | Heart attack |
| `adult_7_5` | `Heart_problem` | Heart problem |
| `adult_7_6` | `Jaundice` | Jaundice |
| `adult_7_7` | `Liver_failure` | Liver failure |
| `adult_7_8` | `Malaria` | Malaria |
| `adult_7_9` | `Pneumonia` | Pneumonia |
| `adult_7_10` | `Renal_kidney_failure` | Renal/kidney failure |
| `adult_7_11` | `Suicide` | Suicide |

### Child Keywords (Id10478 → child_6_*)

| Variable | Choice Value | Description |
|----------|--------------|-------------|
| `child_6_1` | `abdomen` | Abdomen issues |
| `child_6_2` | `cancer` | Cancer |
| `child_6_3` | `dehydration` | Dehydration |
| `child_6_4` | `dengue` | Dengue |
| `child_6_5` | `diarrhea` | Diarrhea |
| `child_6_6` | `fever` | Fever |
| `child_6_7` | `heart_problem` | Heart problem |
| `child_6_8` | `jaundice` | Jaundice |
| `child_6_9` | `pneumonia` | Pneumonia |
| `child_6_10` | `rash` | Rash |

### Neonate Keywords (Id10479 → neonate_6_*)

| Variable | Choice Value | Description |
|----------|--------------|-------------|
| `neonate_6_1` | `asphyxia` | Asphyxia |
| `neonate_6_2` | `incubator` | Incubator care |
| `neonate_6_3` | `lung_problem` | Lung problem |
| `neonate_6_4` | `pneumonia` | Pneumonia |
| `neonate_6_5` | `preterm_delivery` | Preterm delivery |
| `neonate_6_6` | `respiratory_distress` | Respiratory distress |

---

## Language Handling

### Free-Text Processing (Id10476)

**English only.** The word extraction pipeline:

1. Relies on English word stems in `ADULT_WORDS_TO_VARS`
2. Uses English-specific Porter2 stemmer
3. Applies English misspelling corrections in `WORD_SUBS`

| Language | Processing Result | s9999* Variables |
|----------|-------------------|------------------|
| English | Words extracted, stemmed, mapped | Set correctly |
| Hindi | No word matches | **None set** |
| Kannada | No word matches | **None set** |
| Malayalam | No word matches | **None set** |
| Spanish | No word matches | **None set** |

**Example:**

```
English:  "Patient had fever and cough for 2 weeks"
          → s999969=1 (fever), s999946=1 (cough)

Hindi:    "रोगी को दो सप्ताह से बुखार और खांसी थी"
          → No s9999* variables set
```

### Keyword Processing (Id10477-10479)

**Language independent.** ODK stores choice values, not display labels:

| Display Language | Label Shown | Stored Value | Processing |
|------------------|-------------|--------------|------------|
| English | "Fever" | `Fever` | `adult_7_3=1` |
| Hindi | "बुखार" | `Fever` | `adult_7_3=1` |
| Kannada | "ಜ್ವರ" | `Fever` | `adult_7_3=1` |
| Malayalam | "പനി" | `Fever` | `adult_7_3=1` |

This means keyword selections work correctly regardless of the language used during data collection.

---

## Context Problem: Negation and Qualifiers

### The Fundamental Issue

SmartVA's word extraction is **context-blind**. It detects word presence but does not understand:

- **Negation**: "no fever", "denied fever", "never had fever"
- **Qualifiers**: "possible fever", "rule out fever"
- **Temporal context**: "fever 5 years ago (unrelated)"
- **Family history**: "father had fever"

### Examples of Misclassification

| Narrative Text | SmartVA Interpretation | Correct Interpretation |
|----------------|------------------------|------------------------|
| "no fever" | `s999969=1` (fever present) | Fever absent |
| "denied chest pain" | `s999935=1` (chest pain) | Chest pain absent |
| "rule out cancer" | `s999927=1` (cancer) | Cancer suspected, not confirmed |
| "family history of stroke" | `s9999146=1` (stroke) | Not the decedent's stroke |
| "fever 10 years ago, resolved" | `s999969=1` (fever) | Unrelated to death |

### Why This Matters

The tariff scoring algorithm adds points for symptom endorsements. A false positive (word detected but symptom absent) can:

1. **Inflate scores** for causes that include that symptom
2. **Dilute the signal** from genuinely present symptoms
3. **Mislead coders** who see keyword flags in the UI

### Mitigation Strategies

1. **Keyword fields are safer**: The select_multiple fields (Id10477-10479) require active selection, avoiding negation issues.

2. **Coders should read full narrative**: Free-text flags are hints, not definitive. The actual narrative may contain negations.

3. **Training emphasis**: Coder training should emphasize that SmartVA keywords are presence-detected, not context-aware.

4. **Future improvement options**:
   - Negation detection (NLP preprocessing)
   - Require keyword confirmation in structured field
   - Use `--freetext=False` to disable problematic extraction

---

## Configuration: `--freetext` Flag

### Effect on Analysis

The `--freetext` CLI flag controls whether free-text variables are included in tariff scoring:

```bash
smartva --freetext=True   # Include s9999* variables (default)
smartva --freetext=False  # Exclude s9999* variables
```

### In DigitVA

| Form Field | Default | Config Location |
|------------|---------|-----------------|
| `form_smartvafreetext` | `"True"` | `va_forms` table |

Passed to SmartVA binary in `va_smartva_03_runsmartva.py`:

```python
cmd = [
    va_smartva_binary,
    "--freetext", va_form.form_smartvafreetext,  # "True" or "False"
    # ...
]
```

### When to Disable Free-Text

Consider `--freetext=False` if:

1. **Non-English narratives**: 0% of s9999* variables will be set anyway
2. **Negation-heavy narratives**: Context problems outweigh benefits
3. **Inconsistent narrative quality**: Reduces noise in scoring

### Impact Assessment

| Setting | English Narratives | Non-English Narratives |
|---------|-------------------|----------------------|
| `freetext=True` | Extra features from text | No effect (words not matched) |
| `freetext=False` | Lose text features | No change |

---

## Multilingual Deployment Recommendations

### Current Setup Assessment

With mixed-language data (English, Hindi, Kannada, Malayalam):

| Feature | English VAs | Hindi/Kannada/Malayalam VAs |
|---------|-------------|----------------------------|
| Structured questions | ✅ Full contribution | ✅ Full contribution |
| Keyword fields (Id10477-79) | ✅ Full contribution | ✅ Full contribution |
| Free-text extraction | ✅ Extra features | ❌ No contribution |

### Recommendations

1. **Keep `freetext=True`**: No harm for non-English; benefit for English submissions

2. **Emphasize keyword fields in training**: Ensure coders use Id10477-10479 selections rather than relying on narrative text

3. **Document language limitations**: Coders should understand that non-English narratives do not contribute to SmartVA scoring

4. **Consider structured alternatives**: If critical diagnostic information is being lost, add more structured questions to the ODK form

### Future Enhancement Options

To enable non-English free-text processing:

1. **Add language-specific word mappings** to `word_conversions.py`:
   ```python
   HINDI_WORDS_TO_VARS = {
       'बुखार': 's999969',  # fever
       'कैंसर': 's999927',  # cancer
       # ...
   }
   ```

2. **Add language-specific substitutions** to `WORD_SUBS`

3. **Detect language** and route to appropriate mapping

4. **Requires linguistic expertise** and validation testing

---

## Summary Table

| Aspect | Id10476 (Text) | Id10477-10479 (Keywords) |
|--------|----------------|--------------------------|
| **Type** | Free text | select_multiple |
| **Processing** | Word extraction | One-hot encoding |
| **Language dependent** | Yes (English only) | No |
| **Context aware** | No (negation problem) | N/A (explicit selection) |
| **Variables produced** | s9999* (172 for adult) | adult_7_*, child_6_*, neonate_6_* |
| **Reliability** | Medium (context issues) | High |
| **Recommendation** | Use as hint, verify in narrative | Trust as structured data |

---

## Related Documentation

- [`smartva-analysis.md`](smartva-analysis.md) — Overall SmartVA integration in DigitVA
- [`data-model.md`](data-model.md) — `va_smartva_results` table schema
- [`odk-sync.md`](odk-sync.md) — How SmartVA is triggered during sync
