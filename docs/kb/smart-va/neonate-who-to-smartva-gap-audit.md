---
title: Neonate WHO To SmartVA Gap Audit
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Neonate WHO To SmartVA Gap Audit

This document is a neonate-only gap audit for the current `smart-va-pipeline`.

It highlights which visible neonatal WHO 2022 fields are:

- explicitly used
- transformed before symptom scoring
- present upstream but not retained into live neonatal symptom signal
- or not surfaced as visible retained neonatal mappings in this fork

Related docs:

- [SmartVA Symptom KB](README.md)
- [Trace Summary Matrix](trace-summary-matrix.md)
- [Neonatal Delivery](neonatal-delivery.md)
- [Neonatal Unresponsive](neonatal-unresponsive.md)
- [Health History Neonate](health-history-neonate.md)
- [Neonatal Baby Mother](neonatal-baby-mother.md)
- [Duration Of Illness](duration-of-illness.md)

## Runtime Evidence Basis

The runtime notes below were checked against:

- `private/unsw01/smartva_offline/UNSW01KA0101/smartva_input.csv`
- `private/unsw01/smartva_offline/UNSW01KA0101/smartva_output/4-monitoring-and-quality/intermediate-files/neonate-raw-data.csv`
- `private/unsw01/smartva_offline/UNSW01KA0101/smartva_output/4-monitoring-and-quality/intermediate-files/neonate-symptom.csv`

## Neonate Audit Table

| DigitVA WHO Field ID And Label | SmartVA WHO Field ID | SmartVA Symptom ID And Label | Runtime status | Current-state note |
|---|---|---|---|---|
| `Id10399` Mother had convulsions during last 3 months of pregnancy, labour or delivery | `child_2_1` | `s33` Complications: Mother had convulsions | upstream value used | retained through the one-hot neonatal complication family |
| `Id10396` Mother had high blood pressure during last 3 months of pregnancy, labour or delivery | `child_2_1` | `s34` Complications: Mother had hypertension | upstream value used | retained through the one-hot neonatal complication family; live in sampled run |
| `Id10401` Mother had severe anemia | `child_2_1` | `s35` Complications: Mother had anemia | upstream value used | retained through the one-hot neonatal complication family |
| `Id10397` Mother had diabetes mellitus | `child_2_1` | `s36` Complications: Mother had diabetes | upstream value used | retained through the one-hot neonatal complication family; live in sampled run |
| `Id10403` Baby's bottom, feet, arm or hand came out before the head | `child_2_1` | `s37` Complications: Child delivered non-headfirst | upstream value used | retained through the one-hot neonatal complication family; live in sampled run |
| `Id10405` Umbilical cord delivered first | `child_2_1` | `s38` Complications: Cord delivered first | upstream value used | retained through the one-hot neonatal complication family; live in sampled run |
| `Id10404` Umbilical cord wrapped more than once around neck | `child_2_1` | `s39` Complications: Cord around child's neck | upstream value used | explicit retained path; sampled run had no positive values |
| `Id10402` Mother had vaginal bleeding during last 3 months of pregnancy but before labour started | `child_2_1` | `s40` Complications: Excessive bleeding | upstream value used | retained through the one-hot neonatal complication family; live in sampled run |
| `Id10395` Mother had fever during labour | `child_2_1` | `s41` Complications: Fever during labor | upstream value used | retained through the one-hot neonatal complication family; live in sampled run |
| `Id10385` Colour of the liquor when the waters broke | `child_2_8` | `s51` family: `s51991` Water wasn't normal color | upstream value transformed | explicit recode exists; sampled run had values upstream but no positive `s51` output |
| `Id10382` Duration for labour and delivery | `child_2_10` | `s53` Labor and delivery took at least duration threshold | upstream value transformed | explicit amount/unit mapping; live in sampled run |
| `Id10281` Baby become unresponsive or unconscious | `child_3_33` | `s94` Became unresponsive or unconscious | upstream value used | explicit retained path; live in sampled run |
| `Id10282` Baby become unresponsive or unconscious within 24 hours after birth | no visible neonate WHO mapping | none from this visible block | no retained path surfaced | not mapped as a first-class neonatal input in this fork |
| `Id10283` Baby become unresponsive or unconscious more than 24 hours after birth | no visible neonate WHO mapping | none from this visible block | no retained path surfaced | not mapped as a first-class neonatal input in this fork |
| `Id10391` Mother received any vaccinations since reaching adulthood including during this pregnancy | `child_2_11` | `s54` Mother received any vaccinations during pregnancy | default used / no visible mapping | downstream neonatal vaccination symptom exists, but this visible WHO field does not feed it in the current adapter |
| `Id10393` Mother received tetanus toxoid (TT) vaccine | `child_2_11` | `s54` Mother received any vaccinations during pregnancy | default used / no visible mapping | downstream neonatal vaccination symptom exists, but this visible WHO field does not feed it in the current adapter |
| `Id10351` Age of baby since fatal illness started | `child_1_20` | `s28` At least duration threshold old when fatal illness started | helper-driven / sample blank | retained path depends on helper unit fields; sampled run had no live `s28` signal |
| `Id10120_1` Prepared illness duration in days | `child_1_21` | `s29` Illness lasted at least duration threshold | helper-driven / sample blank | explicit illness-duration path exists, but sampled run had no live `s29` signal |
| `Id10121` Duration of illness in months before death | `child_1_21` | `s29` Illness lasted at least duration threshold | helper-driven / sample blank | explicit illness-duration path exists, but sampled run had no live `s29` signal |
| `Id10122` Duration of illness in years before death | `child_1_21` | `s29` Illness lasted at least duration threshold | helper-driven / sample blank | explicit illness-duration path exists, but sampled run had no live `s29` signal |
| `Id10123` Deceased died suddenly | `child_3_49` | `s109` Appeared to be healthy and then just die suddenly | upstream value present but sample stayed zero | explicit WHO 2022 override exists, but sampled run had no positive `s109` output |

## Quick Read

### Explicitly Live

- `Id10396 -> child_2_1 -> s34`
- `Id10397 -> child_2_1 -> s36`
- `Id10403 -> child_2_1 -> s37`
- `Id10405 -> child_2_1 -> s38`
- `Id10402 -> child_2_1 -> s40`
- `Id10395 -> child_2_1 -> s41`
- `Id10382 -> child_2_10 -> s53`
- `Id10281 -> child_3_33 -> s94`

### Explicitly Transformed

- `Id10385 -> child_2_8 -> s51`
- `Id10382 -> child_2_10 -> s53`
- `Id10351 -> child_1_20 -> s28` helper-driven
- `Id10120_1`, `Id10121`, `Id10122 -> child_1_21 -> s29` helper-driven

### No Visible Retained Neonatal Mapping Surfaced

- `Id10282`, `Id10283`

### Downstream Symptom Exists But Visible WHO Field Does Not Feed It Here

- `Id10391`, `Id10393 -> child_2_11 -> s54`

## Current-State Conclusion

For neonates, the strongest gap pattern is different from adults.

The core complication and delivery subset is mostly live, but there are three recurring blind spots:

1. visible timing split fields like `Id10282` and `Id10283` are not retained
2. vaccination fields do not feed the downstream neonatal vaccination symptom
3. some helper-driven retained paths exist, but may be blank in a given run even though the mapping path itself is real
