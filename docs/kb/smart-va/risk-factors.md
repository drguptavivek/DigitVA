---
title: SmartVA Risk Factors Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Risk Factors

This document traces the WHO risk-factor question block around `Id10411` through `Id10414` and `Id10487` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Medical History](medical-history.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10411` | Drink alcohol |
| `Id10413` | Ever smoke tobacco |
| `Id10413_a` | Duration of smoking tobacco mentioned in months or years |
| `Id10413_b` | Smoke daily |
| `Id10413_d` | Exact duration of smoking tobacco in months or years |
| `Id10414` | Chew and/or sniff tobacco |
| `Id10414_a` | Duration of chew and/or sniff tobacco mentioned in months or years |
| `Id10414_b` | Chew and/or sniff tobacco daily |
| `Id10414_d` | Exact duration of chew and/or sniff tobacco in months or years |
| `Id10487` | COVID-19 contact in the two weeks before death |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10412` | `adult_4_1 -> a4_01` | `s138` | retained as `Used tobacco` |
| `Id10414` | `adult_4_2 -> a4_02` | `s139`, `s140`, `s141`, `s142`, `s143`, `s145`, `s146` | transformed into tobacco-type features through a one-hot split |
| `adult_4_2` value `cigarettes` | `a4_02_1` | `s139` | retained as tobacco type: cigarettes |
| `adult_4_2` value `pipe` | `a4_02_2` | `s140` | retained as tobacco type: pipe |
| `adult_4_2` value `chewing_tobacco` | `a4_02_3` | `s141` | retained as tobacco type: chewing tobacco |
| `adult_4_2` value `local_form_of_tobacco` | `a4_02_4` | `s142` | retained as tobacco type: local tobacco |
| `adult_4_2` value `other` | `a4_02_5a` | `s143` | retained as tobacco type: other |
| `adult_4_2` value `ref` | `a4_02_6` | `s145` | retained as tobacco type: refused |
| `adult_4_2` value `dk` | `a4_02_7` | `s146` | retained as tobacco type: don't know |
| `Id10411` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10413` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10413_a` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10413_b` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10413_d` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10414_a` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10414_b` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10414_d` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10487` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |

### Adult Summary

Current adult behavior is narrower than the WHO risk-factor block suggests.

What is retained:

- one tobacco-use flag: `s138`
- one tobacco-type split: `s139`, `s140`, `s141`, `s142`, `s143`, `s145`, `s146`

What is not currently retained from this WHO block:

- alcohol use question `Id10411`
- smoking yes/daily/duration fields `Id10413*`
- chew/sniff daily/duration fields `Id10414*`
- COVID-contact question `Id10487`

Important current-state note:

The adapter path uses `Id10412` as the adult tobacco-use source, even though the visible WHO risk-factor group in DigitVA surfaces `Id10411`, `Id10413*`, `Id10414*`, and `Id10487`. So the current pipeline is not a direct one-to-one trace from the displayed WHO field labels in this block.

Also, adult alcohol-related SmartVA features do exist downstream:

- `s149` = drank alcohol
- `s150991` / `s150992` = alcohol amount bins

But in the current WHO adapter here, those are not fed from `Id10411`.

So the practical current state is:

1. adult tobacco survives partly
2. adult alcohol exists downstream but is not wired from this WHO field block here
3. COVID exposure does not reach adult tariff scoring from this block

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10411` through `Id10414`, `Id10487` | risk-factor block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10411` through `Id10414`, `Id10487` | no child WHO-to-PHMRC mapping in the current adapter | none | ignored for child tariff scoring |

### Child Summary

The child pipeline does not currently use this WHO risk-factor block in its tariff path.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10411` through `Id10414`, `Id10487` | risk-factor block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10411` through `Id10414`, `Id10487` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |

### Neonate Summary

The neonate pipeline does not currently use this WHO risk-factor block in its tariff path.

## Current-State Takeaways

- adult risk factors: only a reduced tobacco path is currently wired from this WHO-side adapter
- adult alcohol features exist downstream, but not from `Id10411` here
- child risk factors: this WHO block is not used in the current tariff path
- neonate risk factors: this WHO block is not used in the current tariff path
- the current risk-factor mapping is selective and legacy-shaped, not a full import of all WHO risk-factor questions

## Code Map

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [Medical History](medical-history.md)
- [SmartVA Symptom KB](README.md)
