---
title: SmartVA Urine Problems Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Urine Problems

This document traces the WHO urine-problems question block `Id10223` through `Id10226` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Abdominal Pain](abdominal-pain.md)
- [Medical History](medical-history.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10223` | Urine problems |
| `Id10224` | Stop urinating |
| `Id10226` | Blood in the urine during final illness |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10224` | `adult_2_52 -> a2_52` | `s71` | retained as `Stopped urinating` |
| `Id10223` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10226` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10476` contains urine-related words | `adult_7_c -> a7_01` | `s9999161` | generic narrative word lane for `urin` |

### Adult Summary

The current adult urine block is much narrower than the WHO questionnaire section suggests.

What survives structurally:

- `Id10224` -> `s71` for stopped urinating

What does not currently survive as a structured adult tariff feature from this WHO block:

- `Id10223` urine problems
- `Id10226` blood in the urine during final illness

So the practical current state is:

1. one structured urine feature is retained: `s71`
2. the broader urine-problems field is ignored
3. blood-in-urine is ignored
4. narrative text can still contribute a weak generic urine word feature `s9999161`

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10223` through `Id10226` | urine-problems block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10223` through `Id10226` | no child WHO-to-PHMRC mapping in the current adapter | none | ignored for child tariff scoring |
| `Id10476` narrative | `child_6_c -> c6_01` | no dedicated urine word feature identified in child tariff output | no clear child urine lane |

### Child Summary

The child pipeline does not currently expose a direct urine-problems family from this WHO block.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10223` through `Id10226` | urine-problems block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10223` through `Id10226` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |
| `Id10476` narrative | `child_6_c -> c6_01` | no dedicated neonatal urine word feature identified in tariff output | no clear neonate urine lane |

### Neonate Summary

The neonate pipeline does not currently expose a direct urine-problems family from this WHO block.

## Current-State Takeaways

- adult urine problems: only `stopped urinating` survives structurally, plus a weak generic narrative urine word lane
- child urine problems: this WHO block is not used in the current tariff path
- neonate urine problems: this WHO block is not used in the current tariff path
- the current mapping is selective and much narrower than the WHO urine section itself

## Code Map

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [Medical History](medical-history.md)
- [SmartVA Symptom KB](README.md)
