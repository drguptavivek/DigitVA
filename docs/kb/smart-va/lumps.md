---
title: SmartVA Lumps Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Lumps

This document traces the WHO lump question block `Id10254` through `Id10257` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Swelling](swelling.md)
- [Ulcers](ulcers.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10254` | Lumps or sores in the mouth |
| `Id10255` | Lumps on the neck |
| `Id10256` | Lumps on the armpit |
| `Id10257` | Lumps on the groin |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10255` | `adult_2_29 -> a2_29` | `s46` | retained as lump in the neck |
| `Id10256` | `adult_2_30 -> a2_30` | `s47` | retained as lump in the armpit |
| `Id10257` | `adult_2_31 -> a2_31` | `s48` | retained as lump in the groin |
| `Id10254` | no adult WHO-to-PHMRC mapping in the current adapter | none | ignored before symptom and tariff stages |
| `Id10476` contains lump terms | `adult_7_c -> a7_01` | `s9999105` | narrative lump word lane |

### Adult Summary

The current adult lump block is selective.

What survives structurally:

- `s46` lump in the neck
- `s47` lump in the armpit
- `s48` lump in the groin

What does not survive as a first-class adult tariff feature from this WHO block:

- `Id10254` lumps or sores in the mouth

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10254` | Lumps or sores in the mouth |
| `Id10255` | Lumps on the neck |
| `Id10256` | Lumps on the armpit |
| `Id10257` | Lumps on the groin |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10256` | `child_4_42 -> c4_42` | `s151` | retained as swelling in the armpits |
| `Id10254`, `Id10255`, `Id10257` | no child WHO-to-PHMRC mapping in the current adapter | none | ignored for child tariff scoring |

### Child Summary

The child pipeline keeps only a narrow armpit-swelling signal from this WHO lump block.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10254` through `Id10257` | lump block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10254` through `Id10257` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |

### Neonate Summary

The neonate pipeline does not expose a direct lumps family from this WHO block.

## Current-State Takeaways

- adult lumps: neck, armpit, and groin are retained separately, plus a narrative lump word lane
- child lumps: only the armpit-swelling signal is retained from this block
- neonate lumps: this WHO block is not used in the current tariff path
- the WHO lump block is only partially retained; it does not survive as one unified downstream lump variable
