---
title: SmartVA Neonatal Delivery Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
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
| `Id10403` | `REVERSE_ONE_HOT_MULTISELECT -> child_2_1 -> complications5 -> c2_01_5` | `s37` | retained as `child delivered not head first` |
| `Id10405` | `REVERSE_ONE_HOT_MULTISELECT -> child_2_1 -> complications6 -> c2_01_6` | `s38` | retained as `cord first` |
| `Id10404` | `REVERSE_ONE_HOT_MULTISELECT -> child_2_1 -> complications7 -> c2_01_7` | `s39` | retained as `cord around child's neck` |
| `Id10385` | `RECODE_QUESTIONS -> child_2_8 -> c2_08a` | `s51 -> s51991` | explicit visible WHO mapping for non-normal liquor color |
| `Id10382` | `RENAME_QUESTIONS -> child_2_10a`, then `UNIT_IF_AMOUNT -> child_2_10 -> c2_10` | `s53` | explicit visible WHO mapping for prolonged labor-and-delivery threshold |
| `Id10384` | downstream `child_2_9 -> c2_09` exists | `s52` | foul-smelling-liquor feature exists downstream, but no visible WHO 2022 source mapping is surfaced in this fork |
| `Id10383` | downstream `child_2_7 -> c2_07` exists | `s50 -> s50991` | water-broke-early feature exists downstream, but no visible WHO 2022 source mapping is surfaced in this fork |
| `Id10387`, `Id10388`, `Id10389` | no visible mapping to `child_2_17` from this displayed block | none from these visible fields | not the current source of delivery-mode retention |
| `Id10342`, `Id10343`, `Id10344` from the maternal delivery block | `who_prep.map_neonate_delivery_type() -> child_2_17 -> c2_17` | `s58991`, `s58992`, `s58994` | current delivery-mode retention comes from these fields instead |
| `Id10369` | no visible direct mapping | none from this aggregate field | the retained complication family is built from specific yes/no delivery/maternal fields instead of this aggregate prompt |

## Current-State Summary

The visible neonatal delivery block splits into three categories.

Explicitly wired from visible WHO 2022 fields:

- `Id10403 -> s37`
- `Id10405 -> s38`
- `Id10404 -> s39`
- `Id10385 -> s51991`
- `Id10382 -> s53`

Present downstream but not visibly fed by the displayed block in this fork:

- `s52` foul-smelling liquor
- `s50` / `s50991` baby born one day or more after waters broke
- delivery mode `s58991`, `s58992`, `s58994`

Not retained from the displayed aggregate field:

- `Id10369`

So the delivery block is now fully characterized: some visible WHO fields are explicit, while other neonatal-delivery symptoms are currently fed by older or separate source fields, not by the visible `Id10383` to `Id10389` block.
