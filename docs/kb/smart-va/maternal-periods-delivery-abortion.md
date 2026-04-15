---
title: SmartVA Maternal Periods Delivery Abortion Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Maternal Periods Delivery Abortion

This document traces the WHO maternal timing block `Id10302`, `Id10303`, `Id10305`, `Id10306`, `Id10308`, `Id10310`, `Id10312`, `Id10314`, `Id10333`, and `Id10334` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Medical History](medical-history.md)

## WHO Question Group

| WHO field | Label |
|---|---|
| `Id10302` | Period overdue (at time of death) |
| `Id10303` | Duration of period been overdue in weeks (at time of death) |
| `Id10305` | Pregnant and not yet in labour at the time of death |
| `Id10306` | Died within 6 weeks after delivering a baby |
| `Id10308` | Died in less than 1 year after delivery, abortion or miscarriage |
| `Id10310` | Confirmation: 12 months prior to her death, the woman was not pregnant, she did not have a delivery and she also did not have an abortion or miscarriage |
| `Id10312` | Died during labour or delivery |
| `Id10314` | Died within 24 hours after delivering a baby |
| `Id10333` | An attempt to terminate the pregnancy |
| `Id10334` | Pregnancy that ended in an abortion or miscarriage within 6 weeks before death |

## Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10302` | `adult_3_7 -> a3_07` | `s124` | retained as `Period overdue at time of death` |
| `Id10303` | `adult_3_8a -> a3_08b`, with `UNIT_IF_AMOUNT` filling `adult_3_8 -> a3_08a` | `s125` | transformed into the overdue-period-duration threshold feature |
| `Id10305` | `adult_3_10 -> a3_10` | `s127` | retained as `Pregnant at the time of death` |
| `Id10334` | `adult_3_12 -> a3_12` | `s129` | retained as `Died during an abortion` via the WHO 2022 override |
| `Id10312` | `adult_3_15 -> a3_15` | `s132` | retained as `Died during labor or delivery` |
| `Id10306` | no explicit WHO-to-PHMRC mapping surfaced for this exact field in the current adapter | related downstream `s135` exists | the downstream childbirth-timing concept exists, but this exact WHO field is not shown as the visible incoming adapter key here |
| `Id10314` | no explicit WHO-to-PHMRC mapping surfaced for this exact field in the current adapter | related downstream `s135` exists | the visible adapter uses a different incoming WHO field for the childbirth-within-6-weeks concept |
| `Id10308` | no explicit WHO-to-PHMRC mapping surfaced in the current adapter | none | not exposed as its own first-class tariff feature |
| `Id10310` | no explicit WHO-to-PHMRC mapping surfaced in the current adapter | none | confirmation logic does not appear as its own first-class tariff feature |
| `Id10333` | no explicit WHO-to-PHMRC mapping surfaced in the current adapter | none | not exposed as its own first-class tariff feature |

## Current-State Summary

The current maternal timing family clearly retains these first-class SmartVA features:

- `s124` period overdue at death
- `s125` period overdue duration, thresholded
- `s127` pregnant at death
- `s129` died during abortion
- `s132` died during labor or delivery

The important narrowing is on duration:

- `Id10303` is not kept as raw weeks
- it is converted into the PHMRC-style unit/value pair `adult_3_8`
- then it becomes `s125`, which SmartVA treats as an overdue-period threshold feature

## Important Caveats

There are two current-state caveats in this block.

1. `Id10334` is explicitly wired through the WHO 2022 override:
   `adult_3_12` now uses `Id10334` instead of the older `Id10335`, and feeds `s129`.

2. Several WHO timing and confirmation questions in this block do not show one-to-one retained paths in the visible adapter tables:
   - `Id10306`
   - `Id10308`
   - `Id10310`
   - `Id10314`
   - `Id10333`

For those, the safe current-state reading is:

- the broader maternal concepts exist downstream in the adult symptom and tariff layers
- but these exact WHO 2022 fields are not exposed as distinct first-class tariff-applied features in this fork
