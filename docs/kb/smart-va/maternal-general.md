---
title: SmartVA Maternal General Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Maternal General

This document traces the `Maternal Symptoms / general` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Maternal Periods Delivery Abortion](maternal-periods-delivery-abortion.md)
- [Lumps](lumps.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10296` | Ever have a period or menstruate |
| `Id10299` | Menstrual period stop naturally because of menopause |
| `Id10300` | Vaginal bleeding after cessation of menstruation |
| `Id10301` | Excessive vaginal bleeding in the week prior to death |
| `Id10294` | Lump(s) / ulcer(s) in the breast |
| `Id10340` | Operation to remove uterus shortly before death |

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10294` | `adult_3_1` and `adult_3_2` via WHO 2022 special mapping | `s118` and `s119` | collapsed into two downstream breast symptoms: swelling/lump and ulcer(s) in the breast |
| `Id10299` | `adult_3_3 -> a3_03` | `s120` | retained as menopause history |
| `Id10300` | `adult_3_4 -> a3_04` | `s121` | retained as post-menopausal bleeding |
| `Id10301` | `adult_3_6 -> a3_06` | `s123` | retained as excessive vaginal bleeding in the week prior to death |
| `Id10296` | `adult_3_3a` only | none | visible in the WHO adapter, but no downstream symptom-stage retention is visible in this fork |
| `Id10340` | none | none | ignored before symptom and tariff stages |

## Current-State Summary

What clearly survives from this displayed subcategory:

- breast lump / swelling `s118`
- breast ulcer(s) `s119`
- menopause history `s120`
- post-menopausal bleeding `s121`
- excessive vaginal bleeding shortly before death `s123`

What does not survive as a first-class SmartVA symptom:

- `Id10296` as its own separate symptom
- `Id10340` hysterectomy / uterus-removal history

## Important Caveat

`Id10294` is a real collapse point in the current WHO adapter.

One displayed WHO field feeds two downstream SmartVA symptoms:

1. `s118` swelling or lump in the breast
2. `s119` ulcers (pits) in the breast

So the current pipeline does not preserve a one-field-to-one-symptom relationship here.

## Code Map

- [Maternal Periods Delivery Abortion](maternal-periods-delivery-abortion.md)
- [Lumps](lumps.md)
