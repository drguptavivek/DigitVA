---
title: SmartVA Agentic Tracing Instructions
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# SmartVA Agentic Tracing Instructions

This document defines the working method for tracing `WHO_2022_VA_SOCIAL` form content into the current `smart-va-pipeline`.

Use it whenever you are checking one WHO category or subcategory at a time and producing or updating documents in [`docs/kb/smart-va`](README.md).

## Goal

For each WHO form subcategory, answer the current-state question:

`Which displayed WHO fields survive into the smart-va-pipeline, how are they transformed, and where do they land by symptom and tariff stage?`

The target path is:

1. WHO category / subcategory
2. WHO fields shown in DigitVA
3. PHMRC-style or SmartVA prep variables
4. pre-symptom conversions
5. symptom-stage variables such as `s15`, `s61`, `s109`
6. tariff-applied or tariff-gating behavior

## Scope Rules

- Use the term `smart-va-pipeline`, not `vendor`.
- Describe the current implementation only.
- Do not turn the document into a bug hunt unless the mapping is clearly broken and that fact materially changes the trace.
- Prefer exact current-state statements over idealized behavior.
- When the UI block does not map one-to-one to SmartVA, say that explicitly.
- When fields are merged across subcategories, document the cross-subcategory merge.
- When a field is operational only, say that it is gating, metadata, or output-only rather than symptom or tariff data.

## Starting Point

Always begin from the DB-backed inventory doc:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)

Use it to determine:

- the exact category and subcategory name
- the exact field ids in the displayed block
- whether an existing KB page already covers the block

## Source Of Truth Order

Use sources in this order.

1. DB-backed field display config and the inventory doc
2. `app/utils/va_mapping/va_mapping_01_fieldsitepi.py`
3. `app/utils/va_mapping/va_mapping_02_fieldcoder.py`
4. `vendor/smartva-analyze/src/smartva/data/who_data.py`
5. `vendor/smartva-analyze/src/smartva/who_prep.py`
6. age-group-specific pre-symptom files
   - `adult_pre_symptom_data.py`
   - `child_pre_symptom_data.py`
   - `neonate_pre_symptom_data.py`
7. age-group-specific symptom files
   - `adult_symptom_data.py`
   - `child_symptom_data.py`
   - `neonate_symptom_data.py`
8. age-group-specific tariff files
   - `adult_tariff_data.py`
   - `child_tariff_data.py`
   - `neonate_tariff_data.py`
9. shared pipeline files when needed
   - `common_prep.py`
   - `pre_symptom_prep.py`
   - `tariff_prep.py`
   - `word_conversions.py`
   - `output_prep.py`

## Core Tracing Workflow

For each subcategory, do this in order.

### 1. Confirm displayed WHO fields

List the exact field ids and short labels in the subcategory.

Questions to answer:

- what fields does the UI actually show in this block?
- are there related helper fields in the uncategorized bucket that matter for the pipeline?
- are any displayed fields just derived UI fields?

### 2. Find WHO-to-prep mappings

Check `who_data.py` first.

Look for:

- direct yes/no mappings
- one-hot or multiselect mappings
- WHO 2022 override mappings
- duration conversions
- custom mappings that fold multiple fields into one PHMRC-style variable

Questions to answer:

- which displayed WHO fields map directly?
- which map through multiselect or one-hot conversion?
- which displayed fields do not appear in the adapter at all?
- does this block pull in fields from another subcategory?

### 3. Follow age-group-specific prep variables

Check the relevant pre-symptom file.

Look for:

- variable renames like `child_2_1 -> c2_01_1`
- binary conversions
- duration conversions
- fallback handling
- default-fill behavior when relevant

Questions to answer:

- what intermediate variable names are created?
- is the block handled differently in adult, child, and neonate?
- does the block exist in one age group but not the others?

### 4. Follow into symptom-stage variables

Check the relevant symptom file.

Look for:

- `VAR_CONVERSION_MAP`
- generated or bucketed variables
- duration cutoffs
- injury gating or special binary expansion
- age and sex conditioning

Questions to answer:

- which `s...` variables are produced?
- are they retained, transformed, collapsed, or ignored?
- are some variables used only as gates or thresholds rather than direct labeled symptoms?

### 5. Confirm tariff-stage meaning

Check the relevant tariff file.

Look for:

- symptom descriptions
- short-form or HCE drop lists
- injury or duration gate behavior
- special age restrictions

Questions to answer:

- is the symptom actually tariff-applied or only an internal gate?
- what human-readable description does the tariff layer give it?
- is the variable excluded in some modes?

### 6. Write the current-state interpretation

Every doc should clearly say:

- what is retained
- what is transformed
- what is collapsed
- what is ignored
- what caveat matters most for reading the block correctly

## Required Output Structure For Each Subcategory Doc

Use this structure unless there is a strong reason not to.

1. YAML front matter
2. title
3. short summary sentence naming the category/subcategory
4. `Related docs`
5. `WHO Subcategory Fields`
6. `Forward Trace`
7. age-group-specific or branch-specific summary sections when needed
8. `Current-State Summary`
9. `Important Caveat` when needed
10. `Code Map`

## Doc-Writing Rules For This Folder

- Keep one KB page per WHO symptom family or subcategory trace.
- Use repo-relative links only.
- Keep YAML front matter complete and refresh `last_updated` on every material update.
- Use the exact category and subcategory names from the inventory doc in the opening summary sentence.
- Prefer updating an existing KB page when the subcategory is already substantially covered there.
- Create a new KB page only when the existing symptom pages do not already cover the displayed WHO block cleanly.
- Keep the interpretation current-state only. Do not mix in redesign suggestions.

## Completion Checklist For Each Subcategory Pass

When one subcategory pass is complete:

1. update or create the KB page
2. add or verify the relative link in [SmartVA Symptom KB](README.md)
3. update the row in [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
4. note any follow-up gap in `.tasks/` only if the trace is materially incomplete
5. verify that the page clearly distinguishes retained, transformed, collapsed, ignored, and gating behavior

## Classification Language

Use these terms consistently.

- `retained`: the WHO concept survives as its own downstream feature
- `transformed`: the value is bucketed, thresholded, or recoded
- `collapsed`: multiple WHO inputs converge to one downstream feature
- `ignored`: no first-class downstream feature is visible in the current pipeline
- `gating`: the variable controls whether a record or feature family proceeds, but is not itself a tariff symptom
- `output metadata only`: used in outputs, not scoring

## Things To Watch For

### Cross-subcategory merges

Some downstream feature families combine fields that live in different UI subcategories.

When that happens:

- say it directly
- do not pretend the visible subcategory is self-contained

### Age-group splits

The same WHO block may behave differently across:

- adult
- child
- neonate

Do not write one unified statement if the code is actually split.

### WHO 2022 overrides

The current pipeline contains explicit WHO 2022 overrides.

Check for those before concluding that an older mapping still applies.

### Derived or helper fields

Some displayed fields are not what the pipeline actually reads.

Examples:

- prepared duration helper fields
- normalized age fields
- multiselect expansion helpers

Document when the pipeline depends on helper fields instead of the visible field alone.

## When To Reuse An Existing Doc

If a subcategory is already substantially covered by an existing doc:

- update the existing doc instead of duplicating it
- only create a new doc when the subcategory has a distinct displayed block or distinct trace path

Examples:

- `Neonatal Period Details / physical_abnormalities` is different from `Neonatal Feeding Symptoms / physical_abnormalality`
- a symptom family already documented may still need updates if the inventory shows additional displayed WHO fields that were missed

## Inventory Update Rule

After finishing a subcategory doc:

1. update [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
2. change that subcategory row from `pending` to the new doc link
3. update [SmartVA Symptom KB](README.md)
4. update the local task tracker in `.tasks/` if this pass is being tracked there

## Documentation Standard

Every new or materially updated doc under `docs/` must include:

- `title`
- `doc_type`
- `status`
- `owner`
- `last_updated`

Keep paths repo-relative in the document body.

## Minimum Quality Bar

Before finishing a subcategory pass, confirm:

- the WHO field list matches the inventory
- the downstream variables are age-group-correct
- the summary does not overstate certainty where the adapter is partial
- cross-subcategory merges are called out
- the inventory and README link to the new doc

## Practical End Condition

A subcategory trace is complete when a future engineer can answer all of these without re-reading the whole codebase:

- Which displayed WHO fields matter?
- Which do not?
- What do they become downstream?
- Are they symptom features, tariff features, gates, or metadata?
- Is the mapping one-to-one, transformed, or merged with another block?
