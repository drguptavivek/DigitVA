---
title: WHO 2022 ICD Assignability Audit
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-27
---

# WHO 2022 ICD Assignability Audit

## Purpose

Define the review baseline for deciding which ICD-10 codes should be assignable
in DigitVA when coding WHO 2022 verbal autopsy forms.

## Baseline

DigitVA uses the ICD codes listed in the WHO 2022 VA form crosswalk as the
starting source of truth for assignable ICD-10 codes.

This source is represented in:

- `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/WHO_2022_VA_Crosswalk.xlsx`
- `docs/icd-causegrp-mappings/generated/who_2022_icd10_2019_2_policy.json`
- `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/WHO_2022_VA_Bucket_Mapping.xlsx`

The generated policy includes WHO-listed three-character ICD codes and the
WHO-listed dotted detailed ICD codes that are needed for categories such as
COVID-19, maternal causes, circulatory causes, liver disease, and transport
injury footnote logic.

## CMEA10 Comparison

The CMEA10 mapping workbook is a reporting taxonomy, not the primary source of
truth for coder ICD assignability.

However, blank CMEA10 mappings are useful audit signals. A blank CMEA10 bucket
means the ICD code is present in the CMEA10 source list but is not assigned to a
CMEA10 reporting bucket.

DigitVA compares the WHO 2022 assignable ICD set against blank CMEA10 rows to
identify codes that may need review.

The audit artifact is:

- `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/CMEA10_Blank_WHO_2022_Assignable_Audit.xlsx`
- reviewed decisions:
  `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/CMEA10_Blank_WHO_2022_Assignable_Audit- decision.xlsx`

This workbook lists CMEA10 blank ICD rows that are still assignable under the
WHO 2022 ICD policy and provides review columns for:

- proposed action
- final decision
- reviewer notes

## Review Principle

Many ICD-10 codes listed in broad WHO 2022 residual ranges are technically
included by the source crosswalk but have an extremely low likelihood of being a
valid underlying cause of death in verbal autopsy coding.

Examples include conditions such as:

- dental caries
- cataract
- minor eye and ear disorders
- other low-fatality local conditions

These should be reviewed for possible non-assignability even when they are
included in broad WHO residual ranges such as `VAs-98`.

Other blank CMEA10 rows may instead represent probable CMEA10 omissions rather
than low-fatality ICD codes. Examples requiring clinical or mapping review may
include conditions such as peritonitis, cholecystitis, sepsis-related codes, and
acute inflammatory cardiac conditions.

## Decision Categories

Audit decisions should use these categories:

- `Disable WHO coding` — the ICD code should be removed from the assignable WHO
  2022 coding list because it is not plausible as an underlying cause of death
  for VA coding.
- `Add CMEA10 bucket` — the ICD code should remain assignable for WHO 2022 VA,
  and the CMEA10 reporting workbook should be updated to classify it.
- `Clinical review` — the code needs domain review before either disabling WHO
  coding or adding a CMEA10 bucket.

## Implementation Rule

Do not automatically disable codes only because CMEA10 leaves them blank.

The reviewed audit workbook must be the input for any policy update. After
review:

1. Codes marked `Disable WHO coding` should be removed from or disabled in the
   generated WHO 2022 ICD policy.
2. Codes marked `Add CMEA10 bucket` should be assigned a CMEA10 bucket in the
   CMEA10 source mapping and then re-imported.
3. Codes marked `Clinical review` should remain unchanged until a final
   decision is recorded.

This preserves the WHO 2022 crosswalk as the initial source of truth while
allowing DigitVA to apply a clinically reviewed assignability policy for
low-fatality ICD codes.

The COD bucket mapping workbook is not changed by this disable review. It
remains a WHO 2022 document-derived reporting mapping; disabled ICD codes are
excluded from coder assignability through the reviewed ICD policy instead.
