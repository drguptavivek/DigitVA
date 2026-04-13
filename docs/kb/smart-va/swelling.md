---
title: SmartVA Swelling Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Swelling

This document traces the WHO swelling, edema, puffiness, and related body-swelling question family forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Jaundice](jaundice.md)
- [Rash](rash.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10247` | Puffiness of face |
| duration field(s) for puffiness | Duration of puffiness |
| `Id10252` | General swelling of the body |
| `Id10249` | Swollen legs or feet |
| duration field(s) for swelling | Duration of swelling |
| `Id10251` | Both feet swollen |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10247` | `adult_2_25 -> a2_25` | `s42` | retained as puffiness of face |
| puffiness duration field(s) | `adult_2_26 -> a2_26` | `s43` | separate duration feature |
| `Id10252` | `adult_2_27 -> a2_27` | `s44` | retained as general puffiness of body |
| general-swelling duration field(s) | `adult_2_28 -> a2_28` | `s45` | separate duration feature |
| `Id10249` and related leg/feet-swelling fields | adult swelling path in the WHO adapter | downstream adult edema/swelling family | present in the WHO questionnaire, but the adapter path is less explicit than the face/body-puffiness path |
| `Id10476` contains swelling-related words | `adult_7_c -> a7_01` | `s999960` and related words | narrative word lane |

### Adult Summary

Adult swelling is represented as a structured edema/puffiness family with separate face, general-body, and duration signals. Narrative text adds a separate word lane.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10249` | Swollen legs or feet |
| duration field(s) for swelling | Duration of swelling |
| `Id10240` | Areas of skin with redness / swelling |
| armpit-swelling path | swelling in the armpits |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| swollen legs / feet group | child swelling path in the WHO adapter | `s145` | retained as swollen legs or feet |
| swelling duration field(s) | child swelling-duration path in the WHO adapter | `s146` | separate duration feature |
| `Id10240` | `child_4_40 -> c4_40` | skin-redness/swelling family | separate skin-swelling feature |
| armpit swelling path | `child_4_44+` | `s151`-adjacent family | separate lymph/swelling-related feature |
| `Id10476` narrative | `child_6_c -> c6_01` | `s999947` and related words | narrative word lane |

### Child Summary

Child swelling is split across:

- peripheral swelling (`s145/s146`)
- skin swelling / redness
- armpit swelling and related findings

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| neonatal swelling / edema-like skin findings | swelling-related neonatal skin findings |
| `Id10476` | Narration |
| `Id10479` | Neonatal narration keywords |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| swelling-related neonatal skin findings | `c3_37+` family | skin redness / swelling and pus-related neonatal features | represented through neonatal skin-infection-style features |
| `Id10476` narrative | `child_6_c -> c6_01` | `s999934` and related words | narrative word lane for swelling-related words |
| `Id10479` keywords | `neonate_6_*` | no direct swelling keyword exists | no dedicated keyword lane |

### Neonate Summary

Neonatal swelling is not modeled as a simple edema family. It is represented through broader neonatal skin and infection findings, with a weak narrative word lane.

## Current-State Takeaways

- adult swelling: structured edema/puffiness family plus narrative word lane
- child swelling: peripheral swelling plus skin and armpit-related swelling families
- neonate swelling: broader skin/infection-family representation rather than a direct edema family

## Code Map

- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)
