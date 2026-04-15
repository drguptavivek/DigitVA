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
| `Id10342` | Delivery: Normal vaginal, without forceps or vacuum |
| `Id10343` | Delivery: Vaginal, with forceps or vacuum |
| `Id10344` | Delivery: Caesarean section |
| `Id10331` | Deliver or try to deliver an abnormally positioned baby |
| `Id10330` | Placenta completely delivered |
| `Id10328` | Excessive bleeding during labour or delivery |
| `Id10322_b` | Foul smelling vaginal discharge after delivery/abortion |
| `Id10329_a` | Excessive bleeding after delivery |

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10332` | `adult_3_16a` custom hour mapping feeding `adult_3_16 -> a3_16 -> s133` | `s133` | retained as labor-duration signal and thresholded at the symptom layer |
| `Id10328` | `adult_3_14 -> a3_14` | `s131` | retained as excessive bleeding during labor or delivery |
| `Id10337`, `Id10342`, `Id10343`, `Id10344`, `Id10331`, `Id10330`, `Id10322_b`, `Id10329_a` | no direct first-class adult WHO-to-symptom mapping from this displayed block | none | not retained as their own tariff-applied features in the current adult adapter |

## Current-State Summary

Only two displayed delivery questions clearly survive into adult SmartVA scoring:

- labor duration `s133`
- excessive bleeding during labor or delivery `s131`

The rest of the visible delivery block does not show a direct first-class symptom path in the current adult WHO adapter.

## Important Caveat

The current maternal delivery implementation is split across visible WHO 2022 fields and older hidden maternal fields.

Some downstream maternal-delivery symptoms still exist in SmartVA, but they are not fed one-to-one from the displayed WHO 2022 delivery block. In particular:

- visible mode-of-delivery fields `Id10342`, `Id10343`, `Id10344` do not feed adult maternal tariff features here
- visible post-delivery bleeding field `Id10329_a` does not visibly map to `s136` in this fork
- visible foul-smelling discharge field `Id10322_b` does not visibly map to `s137` in this fork

So the safe current-state reading is that this displayed subcategory is only partly retained.

## Code Map

- [Maternal Antenatal](maternal-antenatal.md)
- [Maternal Periods Delivery Abortion](maternal-periods-delivery-abortion.md)
