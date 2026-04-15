---
title: SmartVA Injuries Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Injuries

This document traces the `Injuries Details / default` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Duration Of Illness](duration-of-illness.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10077` | Injury or accident that led to death |
| `Id10077_a` | Duration between injury / accident and death |
| `Id10079` | Road transport injury |
| `Id10082` | Non-road transport injury |
| `Id10083` | Injured in a fall |
| `Id10084` | Poisoning |
| `Id10085` | Drowning |
| `Id10086` | Venomous bite or sting |
| `Id10087` | Injured by an animal or insect (non-venomous) |
| `Id10088` | Animal/insect that injured |
| `Id10089` | Burns/fire |
| `Id10091` | Firearm |
| `Id10092` | Stabbed, cut or pierced |
| `Id10093` | Strangled |
| `Id10096` | Electrocuted |
| `Id10094` | Blunt force |
| `Id10095` | Force of nature |
| `Id10097` | Other injury |
| `Id10098` | Injury accidental |
| `Id10099` | Injury self-inflicted |
| `Id10100` | Injury intentionally inflicted by someone else |

## Forward Trace

### Adult

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10077` | `adult_5_1` | `adult_5_1` with binary split to `a5_01_8` when `no` | determines whether the adult injury family is active or converted to `no injury` |
| `Id10079`, `Id10083`, `Id10085`, `Id10084`, `Id10086`, `Id10089`, `Id10097` | `adult_5_2` multiselect -> `adultinjury1..8 -> a5_01_*` | `s151`, `s152`, `s153`, `s154`, `s155`, `s156`, `s159` | retained as adult injury-type features |
| violence-coded injury selections in the adult injury family | `adult_5_2 -> a5_01_7` | `s157` | retained as victim-of-violence injury feature |
| `Id10099` | `adult_5_3 -> a5_02` | `s161` | retained as self-inflicted injury |
| `Id10100` | `adult_5_4 -> a5_03` | `s162` | retained as intentionally inflicted by someone else |
| `Id10077_a` | `adult_5_5 -> a5_04` via unit/value conversion | `s163` | retained as the adult injury-duration gate used to activate injury variables within 30 days |
| `Id10082`, `Id10087`, `Id10088`, `Id10091`, `Id10092`, `Id10093`, `Id10094`, `Id10095`, `Id10098` | no direct first-class adult WHO mapping in this adapter | none | not retained as their own adult tariff features |

### Child

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10077` | `child_4_47` | `c4_47_11 -> s164` when `no` | determines whether child injury is present or marked as `did not suffer accident` |
| `Id10079`, `Id10083`, `Id10085`, `Id10084`, `Id10086`, `Id10089`, `Id10097` | `child_4_48` multiselect | `s155`, `s156`, `s157`, `s158`, `s159`, `s160`, `s162` | retained as child injury-type features |
| violence-coded injury selections in the child injury family | `child_4_48 -> c4_47_7` | `s161` | retained as victim-of-violence feature |
| `Id10100` | `child_4_49 -> c4_48` | `s165` | retained as intentionally inflicted by someone else |
| injury duration path | `c4_49` / injury-duration gate | `s166` | retained as the child injury-duration gate used to activate injury variables within 10 days |
| `Id10082`, `Id10087`, `Id10088`, `Id10091`, `Id10092`, `Id10093`, `Id10094`, `Id10095`, `Id10098`, `Id10099` | no direct first-class child WHO mapping in this adapter | none | not retained as their own child tariff features |

### Neonate

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| injury block `Id10077` through `Id10100` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |

## Current-State Summary

Adult and child both keep a real injury family, but they are not identical.

Adult keeps:

- injury types `s151` to `s159` selectively
- intent flags `s161` and `s162`
- internal duration gate `s163`
- explicit `no injury` flag `s158`

Child keeps:

- injury types `s155` to `s162` selectively
- intentional-infliction flag `s165`
- internal duration gate `s166`
- explicit `no accident` flag `s164`

Neonate does not use this WHO injury block in the current SmartVA path.

## Important Caveats

1. The displayed WHO injury block is richer than the retained tariff features.
2. Several visible fields such as `Id10082`, `Id10091`, `Id10092`, `Id10094`, and `Id10098` do not show up as separate first-class SmartVA features in this adapter.
3. Adult and child injury duration are retained mostly as gating features for injury activation, not as prominently labeled tariff descriptions in the same way as symptom questions.

## Code Map

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [Duration Of Illness](duration-of-illness.md)
