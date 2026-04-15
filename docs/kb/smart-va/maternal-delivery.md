---
title: SmartVA Maternal Delivery Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Maternal Delivery

This document traces the `Maternal Symptoms / delivery` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Maternal Antenatal](maternal-antenatal.md)
- [Maternal Periods Delivery Abortion](maternal-periods-delivery-abortion.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10337` | Location of delivery |
| `Id10332` | Hours in labour |
| `Id10342` | Delivery: normal vaginal, without forceps or vacuum |
| `Id10343` | Delivery: vaginal, with forceps or vacuum |
| `Id10344` | Delivery: Caesarean section |
| `Id10331` | Deliver or try to deliver an abnormally positioned baby |
| `Id10330` | Placenta completely delivered |
| `Id10328` | Excessive bleeding during labour or delivery |
| `Id10322_b` | Foul smelling vaginal discharge after delivery/abortion |
| `Id10329_a` | Excessive bleeding after delivery |

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10332` | `RENAME_QUESTIONS -> adult_3_16a`, then `UNIT_IF_AMOUNT -> adult_3_16 -> a3_16` | `s133` | explicit visible WHO mapping for labor duration |
| `Id10328` | `adult_3_14 -> a3_14` | `s131` | explicit visible WHO mapping for excessive bleeding during labor or delivery |
| hidden older source `Id10336` | `adult_3_17 -> a3_17` | `s134` | downstream maternal-delivery feature retained from an older hidden source, not from a visible field in this displayed subcategory |
| hidden older source `Id10315` | `adult_3_18 -> a3_18` | `s135` | downstream maternal-delivery feature retained from an older hidden source |
| hidden older source `Id10329` | `adult_3_19 -> a3_19` | `s136` | downstream post-delivery bleeding feature retained from an older hidden source |
| downstream maternal feature `adult_3_20 -> a3_20` | `s137` | `s137` | bad-smelling-discharge symptom exists downstream, but no visible WHO 2022 source is surfaced for it in this fork |
| `Id10342`, `Id10343`, `Id10344` | no adult maternal mapping from this displayed block | none on the adult path | these visible mode-of-delivery fields are not the current source of adult maternal retention here |
| `Id10331`, `Id10330`, `Id10337`, `Id10322_b`, `Id10329_a` | no direct first-class adult WHO-to-symptom mapping from this displayed block | none from these visible fields | not visibly retained as first-class adult SmartVA inputs |

## Cross-Path Clarification

The visible maternal delivery block is not the only place where delivery-type information appears in the codebase.

- `Id10342`, `Id10343`, and `Id10344` are used by `who_prep.map_neonate_delivery_type()` to build neonatal `child_2_17`
- they do not feed the adult maternal delivery symptom family in the current adult path

So the same visible WHO fields matter for the neonatal model, but not for adult maternal tariff features here.

## Current-State Summary

Visible WHO 2022 delivery fields that clearly survive on the adult maternal path:

- `Id10332 -> s133`
- `Id10328 -> s131`

Adult maternal-delivery symptoms that still exist downstream but are fed by hidden older sources instead of the visible WHO 2022 block:

- `s134` from `Id10336`
- `s135` from `Id10315`
- `s136` from `Id10329`
- `s137` from an untraced `adult_3_20` source not surfaced as a visible WHO 2022 field in this fork

So the displayed WHO 2022 delivery subcategory is only partly retained on the adult maternal SmartVA path, and the remaining maternal-delivery features still depend on older hidden fields.

## Code Map

- [Maternal Antenatal](maternal-antenatal.md)
- [Maternal Periods Delivery Abortion](maternal-periods-delivery-abortion.md)
