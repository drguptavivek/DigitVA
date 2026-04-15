---
title: SmartVA Maternal Antenatal Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Maternal Antenatal

This document traces the `Maternal Symptoms / antenatal` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Maternal General](maternal-general.md)
- [Maternal Periods Delivery Abortion](maternal-periods-delivery-abortion.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10319` | Count of births, including stillbirths, before this pregnancy |
| `Id10317` | Count of babies she was pregnant with |
| `Id10309` | Pregnancy duration (in months) |
| `Id10320` | Any previous Caesarean section |
| `Id10321` | High blood pressure during pregnancy |
| `Id10323` | Convulsions during the last 3 months of pregnancy and/or after delivery |
| `Id10324` | Blurred vision during the last 3 months of pregnancy and/or after delivery |
| `Id10304` | Sharp abdominal pain in the first 3 months of pregnancy |
| `Id10304_a` | Fainted when had the sharp abdominal pain |
| `Id10322_a` | Foul smelling vaginal discharge during pregnancy |
| `Id10325` | Bleeding during pregnancy |
| `Id10329_b` | Excessive bleeding during or after abortion or miscarriage |
| `Id10327` | Vaginal bleeding during the last 3 months of pregnancy but before labour started |

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10304` | `adult_3_9 -> a3_09` | `s126` | retained as sharp abdominal pain shortly before death |
| `Id10309` | `adult_3_11a` custom month mapping feeding `adult_3_11 -> a3_11 -> s128` | `s128` | retained as pregnancy-duration signal, then thresholded at the symptom layer |
| `Id10325` | `adult_3_13 -> a3_13` | `s130` | retained as bleeding while pregnant |
| `Id10319`, `Id10317`, `Id10320`, `Id10321`, `Id10323`, `Id10324`, `Id10304_a`, `Id10322_a`, `Id10329_b`, `Id10327` | no direct first-class WHO-to-symptom mapping for this displayed block | none | not retained as their own tariff-applied features in the current adapter |

## Current-State Summary

Only three displayed antenatal questions clearly survive into adult SmartVA scoring:

- sharp abdominal pain `s126`
- pregnancy duration `s128`
- bleeding while pregnant `s130`

The rest of the displayed subcategory does not show a direct first-class symptom path in this fork.

## Important Caveat

This displayed WHO subcategory is richer than the current SmartVA adapter.

Several clinically important-looking questions are visible in the UI but do not map to standalone SmartVA symptoms here, including:

- prior Caesarean section
- high blood pressure during pregnancy
- convulsions during pregnancy
- blurred vision during pregnancy
- foul-smelling vaginal discharge during pregnancy
- the WHO 2022 split bleeding fields `Id10327` and `Id10329_b`

So the current pipeline retains only a reduced maternal antenatal subset.

## Code Map

- [Maternal General](maternal-general.md)
- [Maternal Periods Delivery Abortion](maternal-periods-delivery-abortion.md)
