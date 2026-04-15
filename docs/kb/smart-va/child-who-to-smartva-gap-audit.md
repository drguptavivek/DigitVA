---
title: Child WHO To SmartVA Gap Audit
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Child WHO To SmartVA Gap Audit

This document is a child-only gap audit for the current `smart-va-pipeline`.

It highlights which visible child WHO 2022 fields are:

- explicitly used
- transformed before symptom scoring
- present upstream but not retained on the child path
- or not surfaced as visible retained child mappings in this fork

Related docs:

- [SmartVA Symptom KB](README.md)
- [Trace Summary Matrix](trace-summary-matrix.md)
- [Fever](fever.md)
- [Breathing Difficulty](breathing-difficulty.md)
- [Stiff Neck](stiff-neck.md)
- [Swelling](swelling.md)
- [Duration Of Illness](duration-of-illness.md)

## Runtime Evidence Basis

The runtime notes below were checked against:

- `private/unsw01/smartva_offline/UNSW01KA0101/smartva_input.csv`
- `private/unsw01/smartva_offline/UNSW01KA0101/smartva_output/4-monitoring-and-quality/intermediate-files/child-raw-data.csv`
- `private/unsw01/smartva_offline/UNSW01KA0101/smartva_output/4-monitoring-and-quality/intermediate-files/child-symptom.csv`

## Child Audit Table

| DigitVA WHO Field ID And Label | SmartVA WHO Field ID | SmartVA Symptom ID And Label | Runtime status | Current-state note |
|---|---|---|---|---|
| `Id10147` Fever | `child_4_1` | `s110` Fever | upstream value used | explicit visible WHO mapping; symptom is live |
| `Id10148_b` Duration of fever in days | `child_4_2` | `s111` Fever for at least duration threshold | upstream value transformed | explicit duration conversion via `DURATION_CONVERSIONS` |
| `Id10148_c` Duration of fever in months | `child_4_2` | `s111` Fever for at least duration threshold | upstream value transformed | explicit duration conversion via `DURATION_CONVERSIONS` |
| `Id10153` Cough | `child_4_12` | `s121` Cough | upstream value used | explicit visible WHO mapping |
| `Id10154_a` Duration of cough in days | `child_4_13` | `s122` Cough for at least duration threshold | upstream value transformed | explicit duration conversion via `DURATION_CONVERSIONS` |
| `Id10154_b` Duration of cough in months | `child_4_13` | `s122` Cough for at least duration threshold | upstream value transformed | explicit duration conversion via `DURATION_CONVERSIONS` |
| `Id10159` Difficulty breathing | `child_4_16` | `s125` Difficulty breathing | upstream value used | explicit visible WHO mapping; symptom is live |
| `Id10208` Stiff or painful neck | `child_4_28` | `s136` Stiff neck | upstream value used | explicit visible WHO mapping; sampled run happened to be all `No` |
| `Id10120_1` Prepared illness duration in days | `child_1_21` | `s29` Illness lasted at least duration threshold | upstream value transformed | child duration path is explicit through `who_prep.map_child_illness_duration()` |
| `Id10121` Duration of illness in months before death | `child_1_21` | `s29` Illness lasted at least duration threshold | upstream value transformed | child duration path is explicit |
| `Id10122` Duration of illness in years before death | `child_1_21` | `s29` Illness lasted at least duration threshold | upstream value transformed | child duration path is explicit |
| `Id10123` Deceased died suddenly | `child_3_49` | none on child symptom path | upstream value present but not retained | the field is populated upstream, but the child symptom file does not expose a retained child `s*` output for it |
| `Id10249` Swollen legs or feet | no visible child WHO mapping | downstream family `s145` Swollen legs or feet, `s146` Swelling for at least duration threshold | no visible retained path surfaced | downstream child swelling family exists, but this visible WHO block is not explicitly wired in this fork |
| `Id10250` Duration of swelling lasted in days | no visible child WHO mapping | downstream family `s145` Swollen legs or feet, `s146` Swelling for at least duration threshold | no visible retained path surfaced | downstream child swelling family exists, but this visible WHO block is not explicitly wired in this fork |
| `Id10250_b` Duration of swelling lasted in months | no visible child WHO mapping | downstream family `s145` Swollen legs or feet, `s146` Swelling for at least duration threshold | no visible retained path surfaced | downstream child swelling family exists, but this visible WHO block is not explicitly wired in this fork |
| `Id10251` Both feet swollen | no visible child WHO mapping | downstream family `s145` Swollen legs or feet, `s146` Swelling for at least duration threshold | no visible retained path surfaced | downstream child swelling family exists, but this visible WHO block is not explicitly wired in this fork |
| `Id10391` Mother received any vaccinations since reaching adulthood including during this pregnancy | `child_2_11` | none on child symptom path | default / no visible mapping | the downstream variable exists in child/neonate prep, but no visible retained child path is surfaced from this WHO field |
| `Id10393` Mother received tetanus toxoid (TT) vaccine | `child_2_11` | none on child symptom path | default / no visible mapping | no visible retained child path is surfaced from this WHO field |

## Quick Read

### Explicitly Live

- `Id10147 -> child_4_1 -> s110`
- `Id10153 -> child_4_12 -> s121`
- `Id10159 -> child_4_16 -> s125`
- `Id10208 -> child_4_28 -> s136`

### Explicitly Transformed

- `Id10148_b`, `Id10148_c -> child_4_2 -> s111`
- `Id10154_a`, `Id10154_b -> child_4_13 -> s122`
- `Id10120_1`, `Id10121`, `Id10122 -> child_1_21 -> s29`

### Present Upstream But Not Retained On The Child Symptom Path

- `Id10123 -> child_3_49`

### No Visible Retained Child Mapping Surfaced

- `Id10249` to `Id10251`
- `Id10391`, `Id10393`

## Current-State Conclusion

The child path is in better shape than the adult gap cases for the sampled core symptom families.

The main child blind spots in this audit are:

1. visible swelling fields that do not show an explicit retained child mapping
2. maternal-vaccination fields that do not show a retained child path
3. `Id10123`, which is present upstream but not carried into a retained child symptom output
