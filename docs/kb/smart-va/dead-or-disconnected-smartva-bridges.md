---
title: Dead Or Disconnected SmartVA Bridges
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Dead Or Disconnected SmartVA Bridges

This document isolates the main audit failure mode in the current `smart-va-pipeline`:

- the DigitVA WHO field is collected upstream
- a related SmartVA intermediate field and downstream `s*` symptom family exists
- but the stock WHO-to-SmartVA bridge is not live, or is only partially live

This is the highest-value blind-spot view because these fields can appear available to the interviewer and to DigitVA, while still failing to produce usable SmartVA symptom signal.

Related docs:

- [Adult WHO To SmartVA Gap Audit](adult-who-to-smartva-gap-audit.md)
- [Child WHO To SmartVA Gap Audit](child-who-to-smartva-gap-audit.md)
- [Neonate WHO To SmartVA Gap Audit](neonate-who-to-smartva-gap-audit.md)
- [Cross Age WHO To SmartVA Gap Matrix](cross-age-who-to-smartva-gap-matrix.md)

## Bridge Status Meanings

- `live`: WHO field is collected and the linked SmartVA path is actually fed
- `transformed-live`: WHO field is used after unit conversion, bucketing, thresholding, or one-hot expansion
- `disconnected-defaulted`: WHO field is collected, linked SmartVA family exists, but the stock WHO bridge leaves the downstream field at defaults
- `disconnected-unsurfaced`: linked downstream SmartVA family exists, but the visible WHO 2022 field-to-field bridge is not surfaced in this fork
- `not-retained`: field is present upstream, but does not produce a retained age-path symptom output

## Priority Dead-Bridge Shortlist

| Age group | DigitVA WHO Field ID | DigitVA WHO Field Label | SmartVA WHO Field ID | SmartVA Symptom ID | Bridge status | Why this matters |
|---|---|---|---|---|---|---|
| adult | `Id10207` | Severe headache | `adult_2_69`, `adult_2_70`, `adult_2_71` | `s89`, `s90`, `s91` | disconnected-defaulted | raw WHO field is present in `smartva_input.csv`, downstream adult headache family exists, but SmartVA WHO prep leaves the family at defaults and final symptoms at `0` |
| adult | `Id10212`, `Id10213_a`, `Id10213` | Mental confusion and duration | `adult_2_78`, `adult_2_79`, `adult_2_80` | `s98`, `s99`, `s100` | disconnected-defaulted | raw WHO fields are present in DigitVA input, downstream confusion family exists, but the bridge does not feed it and final symptoms stay `0` |
| adult | `Id10175`, `Id10176` | Chest pain severe / chest pain remained | `adult_2_45`, `adult_2_46` | `s63`, `s64` | disconnected-unsurfaced | downstream adult follow-up family exists, but the visible WHO 2022 bridge is not surfaced in this fork |
| adult | `Id10209`, `Id10209_b` | Stiff-neck duration | `adult_2_73` | `s93` | disconnected-unsurfaced | downstream adult duration field exists, but no visible WHO 2022 bridge is surfaced |
| adult | `Id10120`, `Id10121`, `Id10122` | Duration of illness block | `adult_2_1` | `s15` | disconnected-unsurfaced | adult duration symptom exists downstream, but the visible WHO 2022 duration bridge is not surfaced |
| child | `Id10391`, `Id10393` | Maternal vaccination fields | `child_2_11` | none on child path | disconnected-defaulted | downstream prep variable exists, but the visible WHO vaccination fields do not feed a retained child symptom path |
| child | `Id10249`, `Id10250`, `Id10250_b`, `Id10251` | Swollen legs or feet block | child swelling family exists downstream | `s145`, `s146` | disconnected-unsurfaced | the visible child WHO swelling block is not explicitly wired into the retained child swelling family |
| child | `Id10123` | Deceased died suddenly | `child_3_49` | none on child path | not-retained | field is present upstream, but does not produce a retained child `s*` output |
| neonate | `Id10391`, `Id10393` | Maternal vaccination fields | `child_2_11` | `s54` | disconnected-defaulted | downstream neonatal vaccination symptom exists, but the visible WHO fields do not feed it in the current adapter |
| neonate | `Id10282`, `Id10283` | Unresponsive timing split | no surfaced visible bridge | none from this visible block | disconnected-unsurfaced | visible neonatal timing split exists, but it is not retained as a first-class neonatal symptom path |

## Confirmed Adult Runtime Evidence

The strongest confirmed dead-bridge cases are adult headache and adult mental confusion.

Checked runtime files:

- `private/unsw01/smartva_offline/UNSW01KA0101/smartva_input.csv`
- `private/unsw01/smartva_offline/UNSW01KA0101/smartva_output/4-monitoring-and-quality/intermediate-files/adult-raw-data.csv`
- `private/unsw01/smartva_offline/UNSW01KA0101/smartva_output/4-monitoring-and-quality/intermediate-files/adult-symptom.csv`
- `private/icmr01/smartva_offline_postfix3/ICMR01PY0101/smartva_input.csv`
- `private/icmr01/smartva_offline_postfix3/ICMR01PY0101/smartva_output/4-monitoring-and-quality/intermediate-files/adult-raw-data.csv`
- `private/icmr01/smartva_offline_postfix3/ICMR01PY0101/smartva_output/4-monitoring-and-quality/intermediate-files/adult-symptom.csv`

For adult headache:

- raw WHO field `Id10207` is present upstream
- downstream adult family `adult_2_69`, `adult_2_70`, `adult_2_71` exists
- symptom family `s89`, `s90`, `s91` exists
- but `adult-raw-data.csv` shows defaults, not mapped values
- and `adult-symptom.csv` keeps `s89`, `s90`, `s91` at `0`

For adult mental confusion:

- raw WHO fields `Id10212`, `Id10213_a`, `Id10213` are present upstream
- downstream adult family `adult_2_78`, `adult_2_79`, `adult_2_80` exists
- symptom family `s98`, `s99`, `s100` exists
- but `adult-raw-data.csv` shows defaults, not mapped values
- and `adult-symptom.csv` keeps `s98`, `s99`, `s100` at `0`

## What This Means

The main SmartVA audit risk is not just missing downstream variables.

The higher-risk problem is when the whole chain appears available:

1. the WHO question is present in DigitVA
2. a corresponding SmartVA adult, child, or neonate family exists
3. but the WHO bridge is dead, defaulted, or not surfaced

That creates false confidence, because the questionnaire captures data that looks structurally compatible with SmartVA, while the current stock bridge still fails to turn it into live symptom signal.

## Best Use

Use this document as the shortest shortlist for:

1. identifying the highest-value WHO-to-SmartVA bridge blind spots
2. separating true missing data from stock adapter disconnects
3. prioritizing any future adapter fixes or documentation work
