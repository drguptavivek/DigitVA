---
title: SmartVA Skin Other Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Skin Other

This document traces the WHO mixed skin-other question block `Id10237`, `Id10238`, `Id10239`, `Id10240`, and `Id10242` through `Id10246` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Rash](rash.md)
- [Lumps](lumps.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10237` | Shingles or herpes zoster |
| `Id10238` | Skin flake off in patches |
| `Id10239` | Areas of the skin turned black |
| `Id10240` | Areas of the skin with redness and swelling |
| `Id10242` | Bleed from the nose, mouth or anus |
| `Id10243` | Noticeable weight loss |
| `Id10244` | Severely thin or wasted |
| `Id10245` | Whitish rash inside the mouth or on the tongue |
| `Id10246` | Stiffness of the whole body or was unable to open the mouth |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10237`, `Id10238`, `Id10239`, `Id10240`, `Id10242` through `Id10246` | no explicit adult WHO-to-PHMRC mapping visible in the current adapter for these specific WHO fields | none from this exact WHO block | mostly ignored before symptom and tariff stages |

### Adult Summary

For adults, this mixed WHO skin-other block does not currently show the same kind of explicit one-to-one adapter wiring seen in cleaner blocks like swallowing or fever.

Important current-state caveat:

The adult downstream symptom model does contain nearby skin- and wasting-related signals, but the specific WHO fields `Id10237`, `Id10238`, `Id10239`, `Id10240`, and `Id10242` through `Id10246` are not exposed as a clean explicit adult mapping in this fork.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10238` | Skin flake off in patches |
| `Id10239` | Areas of the skin turned black |
| `Id10240` | Areas of the skin with redness and swelling |
| `Id10245` | Whitish rash inside the mouth or on the tongue |
| `Id10242`, `Id10243`, `Id10244`, `Id10246` | remaining mixed skin-other fields |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10238` | `child_4_38 -> c4_38` | `s147` | retained as skin flaked off in patches |
| `Id10239` | `child_4_46 -> c4_46` | `s154` | retained as skin that turned black |
| `Id10240` | no child `c4_*` mapping in the current tariff path | none | not used as a direct child tariff feature |
| `Id10245` | no explicit child WHO-to-PHMRC mapping visible in the current adapter | none | not exposed as a direct child tariff feature from this WHO field |
| `Id10242`, `Id10243`, `Id10244`, `Id10246` | no explicit child WHO-to-PHMRC mapping in the current adapter | none | ignored for child tariff scoring |

### Child Summary

The child pipeline keeps only a narrow part of this WHO block as direct structured features:

- `s147` for skin flaking in patches
- `s154` for skin turning black

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10240` | Areas of the skin with redness and swelling |
| `Id10237`, `Id10238`, `Id10239`, `Id10242` through `Id10246` | remaining mixed skin-other fields |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10240` | `child_3_40 -> c3_40` | `s101` | retained as area(s) of skin with redness and swelling |
| `Id10237`, `Id10238`, `Id10239`, `Id10242` through `Id10246` | no neonate WHO-to-PHMRC mapping in the current adapter from this block | none | ignored for neonate tariff scoring |

### Neonate Summary

The neonate pipeline reuses `Id10240` as a direct skin-inflammation signal, but the rest of this WHO block does not survive as a first-class neonatal family.

## Current-State Takeaways

- adult skin-other: this WHO block is mostly not exposed as explicit first-class adult tariff features
- child skin-other: only skin flaking and blackened skin are retained directly
- neonate skin-other: only `Id10240` is retained directly as a skin redness/swelling signal
- the WHO skin-other block is not preserved as one consistent downstream family across age groups
