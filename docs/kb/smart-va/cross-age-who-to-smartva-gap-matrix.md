---
title: Cross Age WHO To SmartVA Gap Matrix
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Cross Age WHO To SmartVA Gap Matrix

This document summarizes the major current-state blind spots across adult, child, and neonate in one place.

It is not exhaustive. It is a scan-friendly matrix of the highest-value gaps found in the age-specific audit tables.

Related docs:

- [Adult WHO To SmartVA Gap Audit](adult-who-to-smartva-gap-audit.md)
- [Child WHO To SmartVA Gap Audit](child-who-to-smartva-gap-audit.md)
- [Neonate WHO To SmartVA Gap Audit](neonate-who-to-smartva-gap-audit.md)

## Cross-Age Gap Matrix

| Age group | DigitVA WHO Field ID | DigitVA WHO Field Label | SmartVA WHO Field ID | SmartVA Symptom ID | Gap type | Current-state summary |
|---|---|---|---|---|---|---|
| adult | `Id10207` | Severe headache | `adult_2_69`, `adult_2_70`, `adult_2_71` | `s89`, `s90`, `s91` | upstream present, downstream defaulted | visible WHO field exists in raw input, but stock WHO prep leaves downstream adult headache family at defaults and final symptoms at `0` |
| adult | `Id10212`, `Id10213_a`, `Id10213` | Mental confusion and duration | `adult_2_78`, `adult_2_79`, `adult_2_80` | `s98`, `s99`, `s100` | upstream present, downstream defaulted | visible WHO fields exist in raw input, but stock WHO prep leaves downstream confusion family at defaults and final symptoms at `0` |
| adult | `Id10175`, `Id10176` | Chest pain severe / chest pain remained | `adult_2_45`, `adult_2_46` | `s63`, `s64` | downstream-only field | downstream adult fields exist, but visible WHO 2022 mapping is not surfaced in this fork |
| adult | `Id10209`, `Id10209_b` | Stiff-neck duration | `adult_2_73` | `s93` | downstream-only field | downstream duration field exists, but visible WHO 2022 mapping is not surfaced |
| adult | `Id10249` to `Id10251` | Swollen legs or feet block | none surfaced | none from this visible block | visible WHO block not wired | visible swelling block is not explicitly wired into the adult path |
| adult | `Id10120` to `Id10122` | Duration of illness block | `adult_2_1` | `s15` | downstream-only field | adult downstream duration field exists, but visible WHO 2022 mapping is not surfaced |
| child | `Id10123` | Deceased died suddenly | `child_3_49` | none on child path | upstream present, not retained | field is present upstream but does not produce a retained child symptom output |
| child | `Id10249` to `Id10251` | Swollen legs or feet block | no visible child mapping | no surfaced retained child symptom | visible WHO block not wired | downstream child swelling family exists, but this visible WHO block is not explicitly wired |
| child | `Id10391`, `Id10393` | Maternal vaccination fields | `child_2_11` | none on child path | downstream-only / defaulted | downstream variable exists in prep, but no visible retained child path is surfaced |
| neonate | `Id10282`, `Id10283` | Unresponsive timing split | none surfaced | none from this visible block | visible WHO block not wired | not mapped as first-class neonatal inputs in this fork |
| neonate | `Id10391`, `Id10393` | Maternal vaccination fields | `child_2_11` | `s54` | downstream symptom exists but visible WHO fields do not feed it | neonatal vaccination symptom exists downstream, but visible vaccination fields do not map into it here |
| neonate | `Id10351` | Age of baby since fatal illness started | `child_1_20` | `s28` | helper-driven | retained path is real, but depends on helper unit fields outside the visible field itself |
| neonate | `Id10120_1`, `Id10121`, `Id10122` | Duration of illness block | `child_1_21` | `s29` | helper-driven | retained path is explicit, but depends on helper transformation and may be blank in a given run |

## Cross-Age Takeaways

The three age groups fail in different ways.

### Adult

Adult has the strongest `downstream family exists but WHO 2022 does not really feed it` pattern.

### Child

Child has fewer hard failures in the sampled core families, but still has visible blocks that are not wired into retained child symptoms.

### Neonate

Neonate keeps more visible complication and delivery signals than adult, but still has blind spots where visible WHO fields do not feed downstream neonatal symptoms.

## Best Use

Use this matrix as the one-glance shortlist of:

1. adult fields that look collected but do not generate live SmartVA symptom signal
2. child fields that are present upstream but not retained on the child path
3. neonatal visible fields that do not feed downstream neonatal symptoms even though related downstream variables exist
