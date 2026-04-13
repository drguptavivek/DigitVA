---
title: SmartVA Neonatal Delivery Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Neonatal Delivery

This document traces the neonatal delivery block `Id10369`, `Id10382` through `Id10385`, `Id10387` through `Id10389`, and `Id10403` through `Id10405` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Neonatal Fetal Movement](neonatal-fetal-movement.md)
- [Neonatal Period General](neonatal-period-general.md)

## WHO Question Group

| WHO field | Label |
|---|---|
| `Id10369` | Complications during labour or delivery |
| `Id10382` | Duration for labour and delivery |
| `Id10383` | Baby born 24 hours or more after the water broke |
| `Id10384` | Liquor foul smelling |
| `Id10385` | Colour of the liquor when the waters broke |
| `Id10387` | Delivery: normal vaginal, without forceps or vacuum |
| `Id10388` | Delivery: vaginal, with forceps or vacuum |
| `Id10389` | Delivery: Caesarean section |
| `Id10403` | Baby's bottom, feet, arm or hand came out before the head |
| `Id10404` | Umbilical cord wrapped more than once around neck |
| `Id10405` | Umbilical cord delivered first |

## Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10403` | `child_2_1 -> complications5 -> c2_01_5` | `s37` | retained as `Complications: Child delivered non-headfirst` |
| `Id10405` | `child_2_1 -> complications6 -> c2_01_6` | `s38` | retained as `Complications: Cord delivered first` |
| `Id10404` | `child_2_1 -> complications7 -> c2_01_7` | `s39` | retained as `Complications: Cord around child's neck` |
| `Id10385` | `child_2_8 -> c2_08a` | `s51 -> s51991` | transformed into the non-normal-liquor-color feature |
| `Id10382` | `child_2_10a -> child_2_10 -> c2_10` | `s53` | transformed into the prolonged labor-and-delivery threshold feature |
| `Id10384` | likely `child_2_9 -> c2_09` | `s52` | downstream foul-smelling-liquor feature exists, but the exact WHO adapter line is less explicit in this fork |
| `Id10387` / `Id10388` / `Id10389` | likely `child_2_17 -> c2_17` | `s58991 / s58992 / s58994` | delivery mode survives downstream, but the exact visible WHO adapter lines are less explicit here |
| `Id10369` | likely expands into the `child_2_1` complications family | `s33` through `s43` | the complication family clearly exists downstream, but this exact WHO field is not shown as a single direct map in the visible adapter tables |
| `Id10383` | likely `child_2_7 -> c2_07` | `s50991` | downstream water-broke-early feature exists, but the exact visible WHO adapter line is less explicit here |

## Current-State Summary

This delivery block is partly explicit and partly adapter-shaped.

Clearly retained in the visible WHO adapter:

- non-headfirst delivery: `s37`
- cord first: `s38`
- cord around neck: `s39`
- non-normal liquor color: `s51991`
- prolonged labor and delivery: `s53`

Clearly present downstream, but less explicit in the visible WHO adapter tables:

- foul-smelling liquor: `s52`
- delivery mode: `s58991`, `s58992`, `s58994`
- broader delivery complications family: `s33` through `s43`
- water-broke-early feature: `s50991`

## Important Caveat

This is one of the more compressed WHO-to-SmartVA areas for neonates.

Several WHO delivery questions do not survive as raw questionnaire detail. Instead they are narrowed into:

1. one-hot complication features
2. thresholded duration or timing features
3. reduced delivery-mode categories

So the current pipeline keeps the high-value delivery signals, but not the full delivery detail from the WHO form.
