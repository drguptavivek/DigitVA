---
title: Adult WHO To SmartVA Gap Audit
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Adult WHO To SmartVA Gap Audit

This document is an adult-only gap audit for the current `smart-va-pipeline`.

It is designed to answer one question quickly:

- when a visible WHO 2022 adult field exists in DigitVA, does the stock SmartVA WHO pipeline actually feed the linked adult intermediate field and final symptom, or does it fall back to defaults / no retained path?

Related docs:

- [SmartVA Symptom KB](README.md)
- [Trace Summary Matrix](trace-summary-matrix.md)
- [Chest Pain](chest-pain.md)
- [Headache](headache.md)
- [Mental Confusion](mental-confusion.md)
- [Stiff Neck](stiff-neck.md)
- [Swelling](swelling.md)
- [Duration Of Illness](duration-of-illness.md)

## Runtime Evidence Basis

The runtime status column below is based on actual generated SmartVA outputs inspected in these sample runs:

- `private/unsw01/smartva_offline/UNSW01KA0101/smartva_input.csv`
- `private/unsw01/smartva_offline/UNSW01KA0101/smartva_output/4-monitoring-and-quality/intermediate-files/adult-raw-data.csv`
- `private/unsw01/smartva_offline/UNSW01KA0101/smartva_output/4-monitoring-and-quality/intermediate-files/adult-symptom.csv`
- `private/icmr01/smartva_offline_postfix3/ICMR01PY0101/smartva_input.csv`
- `private/icmr01/smartva_offline_postfix3/ICMR01PY0101/smartva_output/4-monitoring-and-quality/intermediate-files/adult-raw-data.csv`
- `private/icmr01/smartva_offline_postfix3/ICMR01PY0101/smartva_output/4-monitoring-and-quality/intermediate-files/adult-symptom.csv`

## Adult Audit Table

| DigitVA WHO Field ID | DigitVA WHO Field Label | SmartVA WHO Field ID | SmartVA Symptom ID And Label | Runtime status | Current-state note |
|---|---|---|---|---|---|
| `Id10174` | Chest pain | `adult_2_43` | `s61` Pain in the chest in the month preceding death | upstream value used | explicit visible WHO mapping; symptom is live |
| `Id10178` | Chest pain lasted for in minutes | `adult_2_44` | `s62` Pain greater than 24 hours | upstream value transformed | explicit `who_prep` duration bucketing into `<30m`, `30m-24h`, `>24h` |
| `Id10179` | Chest pain lasted for in hours | `adult_2_44` | `s62` Pain greater than 24 hours | upstream value transformed | explicit `who_prep` duration bucketing |
| `Id10179_1` | Chest pain lasted for in days | `adult_2_44` | `s62` Pain greater than 24 hours | upstream value transformed | explicit `who_prep` duration bucketing |
| `Id10175` | Chest pain severe | `adult_2_45` | `s63` Pain during physical activity | default used / no visible WHO mapping | downstream adult field exists, but visible WHO 2022 mapping is not surfaced in this fork |
| `Id10176` | Days before death the chest pain remained | `adult_2_46` | `s64` family: `s64991` Pain located in chest, `s64992` Pain located in left arm | default used / no visible WHO mapping | downstream adult field exists, but visible WHO 2022 mapping is not surfaced in this fork |
| `Id10208` | Stiff or painful neck | `adult_2_72` | `s92` Stiff neck | upstream value used | explicit visible WHO mapping; symptom is live |
| `Id10209` | Duration of stiff or painful neck in days | `adult_2_73` | `s93` Stiff neck at least duration threshold | default used / no visible WHO mapping | downstream duration field exists, but visible WHO 2022 mapping is not surfaced |
| `Id10209_b` | Duration of stiff or painful neck in months | `adult_2_73` | `s93` Stiff neck at least duration threshold | default used / no visible WHO mapping | downstream duration field exists, but visible WHO 2022 mapping is not surfaced |
| `Id10247` | Puffiness of face | `adult_2_25` | `s42` Puffiness of the face | upstream value used | explicit visible WHO mapping; symptom is live |
| `Id10248_a` | Duration of puffiness of the face in days | `adult_2_26` | `s43` Puffiness of the face for at least duration threshold | upstream value transformed | explicit unit/value normalization into duration feature |
| `Id10248_b` | Duration of puffiness of the face in months | `adult_2_26` | `s43` Puffiness of the face for at least duration threshold | upstream value transformed | explicit unit/value normalization into duration feature |
| `Id10252` | General swelling of the body | `adult_2_27` | `s44` General puffiness all over body | upstream value used | explicit visible WHO mapping; symptom is live |
| `Id10249` | Swollen legs or feet | no visible adult WHO mapping | none from this visible block | no retained path surfaced | this displayed WHO 2022 field is not explicitly wired into the adult path |
| `Id10250` | Duration of swelling lasted in days | no visible adult WHO mapping | none from this visible block | no retained path surfaced | this displayed WHO 2022 field is not explicitly wired into the adult path |
| `Id10250_b` | Duration of swelling lasted in months | no visible adult WHO mapping | none from this visible block | no retained path surfaced | this displayed WHO 2022 field is not explicitly wired into the adult path |
| `Id10251` | Both feet swollen | no visible adult WHO mapping | none from this visible block | no retained path surfaced | this displayed WHO 2022 field is not explicitly wired into the adult path |
| `Id10207` | Severe headache | `adult_2_69` | `s89` Headaches | default used | raw WHO field is present in DigitVA input, but SmartVA WHO prep fills downstream field with default `No`; final symptom stays `0` |
| `Id10207` | Severe headache | `adult_2_70` | `s90` Headaches at least duration threshold | default used | downstream duration family exists, but no visible WHO 2022 mapping is surfaced; final symptom stays `0` |
| `Id10207` | Severe headache | `adult_2_71` | `s91` Rapid headache onset | default used | downstream onset family exists, but no visible WHO 2022 mapping is surfaced; final symptom stays `0` |
| `Id10212` | Mental confusion | `adult_2_78` | `s98` Experienced a period of confusion in the three months prior to death | default used | raw WHO field is present in DigitVA input, but SmartVA WHO prep fills downstream field with default `No`; final symptom stays `0` |
| `Id10213_a` | Duration of mental confusion in days | `adult_2_79` | `s99` Period of confusion for at least duration threshold | default used | raw WHO field is present in DigitVA input, but downstream duration field is defaulted; final symptom stays `0` |
| `Id10213` | Duration of mental confusion in months | `adult_2_79` | `s99` Period of confusion for at least duration threshold | default used | raw WHO field is present in DigitVA input, but downstream duration field is defaulted; final symptom stays `0` |
| `Id10212` | Mental confusion | `adult_2_80` | `s100` Sudden confusion | default used | downstream sudden-confusion field exists, but no visible WHO 2022 mapping is surfaced; final symptom stays `0` |
| `Id10120` | Duration of illness in days before death | `adult_2_1` | `s15` Ill longer than duration threshold | no visible adult WHO mapping | adult downstream duration field exists in SmartVA, but visible WHO 2022 mapping is not surfaced in this fork |
| `Id10121` | Duration of illness in months before death | `adult_2_1` | `s15` Ill longer than duration threshold | no visible adult WHO mapping | adult downstream duration field exists in SmartVA, but visible WHO 2022 mapping is not surfaced in this fork |
| `Id10122` | Duration of illness in years before death | `adult_2_1` | `s15` Ill longer than duration threshold | no visible adult WHO mapping | adult downstream duration field exists in SmartVA, but visible WHO 2022 mapping is not surfaced in this fork |

## Quick Read

For adult current-state behavior, the rows above fall into four groups.

### Explicitly Live

These visible WHO 2022 fields clearly survive into adult SmartVA:

- `Id10174 -> adult_2_43 -> s61`
- `Id10208 -> adult_2_72 -> s92`
- `Id10247 -> adult_2_25 -> s42`
- `Id10252 -> adult_2_27 -> s44`

### Explicitly Transformed

These visible WHO 2022 fields are used, but only after unit/duration conversion:

- `Id10178`, `Id10179`, `Id10179_1 -> adult_2_44 -> s62`
- `Id10248_a`, `Id10248_b -> adult_2_26 -> s43`

### Present In DigitVA Input But Defaulted By SmartVA WHO Prep

These visible WHO 2022 fields exist in raw `smartva_input.csv`, but the stock SmartVA WHO path does not turn them into live adult symptom signal in the sampled runs:

- `Id10207 -> adult_2_69 / adult_2_70 / adult_2_71 -> s89 / s90 / s91`
- `Id10212`, `Id10213_a`, `Id10213 -> adult_2_78 / adult_2_79 / adult_2_80 -> s98 / s99 / s100`

### No Visible Adult WHO Mapping Surfaced

These visible WHO 2022 fields do not show an explicit retained adult path in this fork:

- `Id10175`, `Id10176`
- `Id10209`, `Id10209_b`
- `Id10249`, `Id10250`, `Id10250_b`, `Id10251`
- `Id10120`, `Id10121`, `Id10122`

## Current-State Conclusion

For adult tracing, the important distinction is:

- some WHO 2022 fields are correctly used directly or after transformation
- some WHO 2022 fields are present in DigitVA raw input but the stock SmartVA WHO prep still collapses them to defaults
- some visible WHO 2022 fields do not show any explicit retained adult mapping at all

So the adult gap is not one single failure mode. It is a mix of:

1. explicit live mappings
2. explicit transformed mappings
3. default-filled downstream adult fields
4. no surfaced visible WHO 2022 mapping
