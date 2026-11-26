---
title: ICD-11 MMS postcoordination axes (2026-01 release)
doc_type: kb
status: active
owner: engineering
last_updated: 2026-11-26
---

# ICD-11 MMS postcoordination axes (2026-01 release)

The full set of postcoordination axes that the ICD-11 MMS offers, taken from
the self-hosted WHO ICD API (`whoicd/icd-api:2.6.0`, release `2026-01`), with
how often each is offered and how WHO describes them. Input for the DORIS
builder UI (`mobile/digitva-collect/src/workspace/doris/picker/BuildCard.tsx`,
`app/services/icd11_postcoordination.py`).

## How this was gathered

- Every entity in the MMS tree (37,212, walked from the root through `child`)
  was fetched from the local API and its `postcoordinationScale` tallied by
  `axisName`. 41 distinct axes were found.
- "Stems" counts the MMS entities that offer the axis (residual `.Y`/`.Z`
  entities included). "Required on" counts those with
  `requiredPostcoordination: true`.
- "Value roots" are the `scaleEntity` roots for the example stem only; the
  roots of an axis differ from stem to stem.
- WHO's online API and Embedded Coding Tool docs do not list the axes. The
  ICD-11 Reference Guide (draft dated 09-03-2026, sections 2.9 and 2.10)
  describes only the three linking axes and lists the extension code families.
  The local API is the only complete list.

## What WHO says

- Reference Guide 2.10: `Has causing condition` is mandatory postcoordination
  when the cause is known (comparable to the ICD-10 dagger; shown as
  "Code also"). `Has manifestation` is optional (comparable to the ICD-10
  asterisk). `Associated with` links conditions reported together without a
  cause-effect claim, for example antimicrobial resistance to the infection;
  it may be allowed or required.
- Stem codes are joined with `/`, extension codes with `&`. An extension code
  never stands first in a cluster. `associatedWith` can offer either: on 3C0Y
  its root is the extension code XT9T Ageing-related.
- Reference Guide 2.9 extension code families. Type 1: severity, temporality,
  aetiology, topology, anatomy and topography, histopathology, dimensions of
  injury, dimensions of external causes, consciousness, substances, ICD-O,
  health devices. Type 2 (diagnosis code descriptors): discharge diagnosis
  type, diagnosis timing, method of confirmation, certainty, obstetric timing,
  encounter descriptors, capacity or context.
- "Other postcoordination" is not an axis. It is the WHO coding tool's
  `otherPostcoordination` setting (ECT 1.8): an open search over chapter X,
  which `BuildCard.tsx` mirrors as its last section.

## `allowMultipleValues`

- `AllowAlways`: any number of values (linking axes, anatomy, agents).
- `NotAllowed`: one value (laterality, severity, course, histopathology,
  consciousness, injury detail).
- `AllowedExceptFromSameBlock`: several values, but at most one from each
  sub-group (block) of the axis (most external-cause axes).

## Findings for the UI

- Only `hasCausingCondition` is effectively required (880 of 921 stems). No
  other axis is required on more than two stems.
- The three severity axes hold different scales per stem. On 2A0Z,
  `hasSeverity` is Stage 0/I/II, `hasAlternativeSeverity1` is Grade I/II/III,
  `hasAlternativeSeverity2` is "A Remission / B Local disease / ...". The axis
  id does not name the scale.
- The current label rule (split camelCase, capitalise;
  `app/services/icd11_postcoordination.py`) yields "Has alternative
  severity1" and "Has gcseye score".
- About two thirds of the axes (injury, external cause, consciousness) belong
  to chapters 22 and 23 and the GCS stems.

## Axes by group

### Linking axes (another stem code, cluster with `/`)

| Axis id | Stems | Required on | Multiple values | Example stem | Value roots (count: first few) |
| --- | ---: | ---: | --- | --- | --- |
| `hasCausingCondition` | 921 | 880 | AllowAlways | CB40 Certain diseases of the respiratory system | 1: 4B22 Cryoglobulinaemia |
| `hasManifestation` | 3,347 | 2 | AllowAlways | 1A92 Trichomoniasis | 4: GA02.0 Acute vaginitis / GA91 Inflammatory or other diseases of prosta / GC00 Cystitis |
| `associatedWith` | 4,255 | 0 | AllowAlways | 3C0Y Other specified diseases of the blood or blood-forming organs | 1: XT9T Ageing-related |

### Anatomy

| Axis id | Stems | Required on | Multiple values | Example stem | Value roots (count: first few) |
| --- | ---: | ---: | --- | --- | --- |
| `specificAnatomy` | 3,976 | 1 | AllowAlways | AC0Y Other specified diseases of the ear or mastoid process | 1: XA01U5 Ear |
| `laterality` | 3,278 | 0 | NotAllowed | 9E1Y Other specified diseases of the visual system | 4: XK9J Bilateral / XK8G Left / XK9K Right |
| `relational` | 33 | 0 | NotAllowed | 2A00 Primary neoplasms of brain | 16: XK7V Anterior / XK8L Posterior / XK9H Medial |
| `distribution` | 20 | 0 | NotAllowed | GC7B Postinterventional ischemia or infarction of kidney | 2: XK2J Complete distribution / XK36 Segmental distribution |

### Neoplasm

| Axis id | Stems | Required on | Multiple values | Example stem | Value roots (count: first few) |
| --- | ---: | ---: | --- | --- | --- |
| `histopathology` | 788 | 2 | NotAllowed | 2A00 Primary neoplasms of brain | 50: - Acinar cell neoplasms / - Adenomas and adenocarcinomas / - Adnexal and skin appendage neoplasms |

### Severity

| Axis id | Stems | Required on | Multiple values | Example stem | Value roots (count: first few) |
| --- | ---: | ---: | --- | --- | --- |
| `hasSeverity` | 945 | 2 | NotAllowed | 2A0Z Other and unspecified neoplasms of brain or central nervous system | 5: XS76 Stage 0 / XS1G Stage I / XS4P Stage II |
| `hasAlternativeSeverity1` | 287 | 0 | NotAllowed | 2A0Z Other and unspecified neoplasms of brain or central nervous system | 5: XS56 Grade I / XS58 Grade II / XS7Z Grade III |
| `hasAlternativeSeverity2` | 642 | 0 | NotAllowed | 2A0Z Other and unspecified neoplasms of brain or central nervous system | 4: XS0J A Remission / Free of disease / XS05 B Local Disease / XS9S C Regional disease |

### Time

| Axis id | Stems | Required on | Multiple values | Example stem | Value roots (count: first few) |
| --- | ---: | ---: | --- | --- | --- |
| `course` | 502 | 2 | NotAllowed | 1A40 Gastroenteritis or colitis without specification of infectious agent | 2: XT5R Acute / XT8W Chronic |
| `temporalPatternAndOnset` | 62 | 0 | NotAllowed | DD51 Inguinal hernia | 1: XT44 Recurrent |
| `timeInLife` | 27 | 0 | NotAllowed | 4A20 Acquired immunodeficiencies | 14: XT0S Pregnancy / XT4Z Postpartum / XT1G Puerperium |

### Aetiology and agents

| Axis id | Stems | Required on | Multiple values | Example stem | Value roots (count: first few) |
| --- | ---: | ---: | --- | --- | --- |
| `causality` | 41 | 0 | NotAllowed | CA40 Pneumonia | 5: XB5F Idiopathic / XB25 Nosocomial / XB4Q Environmental |
| `infectiousAgent` | 495 | 0 | AllowAlways | 1A9Y Other specified predominantly sexually transmitted infections | 5: XN74M Bacteria / XN3BH Virus / XN8AY Fungi |
| `medication` | 193 | 0 | AllowAlways | NE60 Harmful effects of drugs, medicaments or biological substances, not elsewhere classified | 1: XM6S30 Medicaments |
| `chemicalAgent` | 84 | 0 | AllowAlways | KA06 Fetus or newborn affected by noxious influences transmitted via placenta or breast milk | 1: XM9N55 Substances, chiefly nonmedicinal |

### Diagnosis descriptor

| Axis id | Stems | Required on | Multiple values | Example stem | Value roots (count: first few) |
| --- | ---: | ---: | --- | --- | --- |
| `diagnosisConfirmedBy` | 1 | 0 | NotAllowed | 1B10.0 Respiratory tuberculosis, confirmed | 3: XY9Q Diagnosis confirmed by histology / XY19 Diagnosis confirmed by microscopy / XY0K Diagnosis confirmed by culture |

### Consciousness

| Axis id | Stems | Required on | Multiple values | Example stem | Value roots (count: first few) |
| --- | ---: | ---: | --- | --- | --- |
| `hasGCSEyeScore` | 70 | 0 | NotAllowed | 7B2Y Other specified sleep-wake disorders | 5: XC3W One or both eyes are opening spontaneous / XC5L One or both eyes opening to verbal stimu / XC3H One or both eyes opening to pressure sti |
| `hasGCSMotorScore` | 70 | 0 | NotAllowed | 7B2Y Other specified sleep-wake disorders | 7: XC4L Obeys commands / XC6J Localising response to pressure stimulat / XC8Q Normal flexion response to pressure stim |
| `hasGCSVerbalScore` | 70 | 0 | NotAllowed | 7B2Y Other specified sleep-wake disorders | 6: XC2X Oriented, normal speech / XC4Y Confused, disoriented speech / XC4A Intelligible single words |
| `hasPupilReactionScore` | 70 | 0 | NotAllowed | 7B2Y Other specified sleep-wake disorders | 4: XC5Y Neither pupil reacts / XC16 One pupil reacts / XC5K Both pupils react |

### Injury detail

| Axis id | Stems | Required on | Multiple values | Example stem | Value roots (count: first few) |
| --- | ---: | ---: | --- | --- | --- |
| `fractureOpenOrClosed` | 225 | 0 | NotAllowed | NA02 Fracture of skull or facial bones | 2: XJ44E Closed fracture / XJ7YM Open fracture |
| `fractureSubtype` | 214 | 0 | NotAllowed | NA02 Fracture of skull or facial bones | 26: XJ36W Avulsion fracture / XJ2EL Bucket handle or corner fracture / XJ76E Buckle fracture |
| `jointInvolvementInFracture` | 80 | 0 | NotAllowed | NC53 Fracture at wrist or hand level | 2: XJ5GS Fracture extends into joint / XJ5VJ Fracture does not extend into joint |
| `typeOfInjury` | 45 | 0 | NotAllowed | NA00 Superficial injury of head | 7: XJ652 Abrasion / XJ8JK Blister, nonthermal / XJ9NV Contusion |
| `extentOfBurnByBodySurface` | 70 | 0 | NotAllowed | ND90 Burn of head or neck except face | 10: XJ4PF Burns involving less than 10% of body su / XJ257 Burns involving 10-19% of body surface / XJ5GA Burns involving 20-29% of body surface |
| `extentOfFullThicknessBurnByBodySurface` | 40 | 0 | NotAllowed | ND90 Burn of head or neck except face | 10: XJ31W Full thickness or deep full thickness bu / XJ82Z Full thickness or deep full thickness bu / XJ3XZ Full thickness or deep full thickness bu |
| `outcomeOfFullThicknessBurn` | 39 | 0 | NotAllowed | ND90 Burn of head or neck except face | 3: XJ71T Deep full thickness or complex burn with / XJ6NX Deep full thickness or complex burn with / XJ36Y Deep full thickness or complex burn with |

### External cause detail (chapter 23)

| Axis id | Stems | Required on | Multiple values | Example stem | Value roots (count: first few) |
| --- | ---: | ---: | --- | --- | --- |
| `placeOfOccurrence` | 433 | 0 | AllowedExceptFromSameBlock | PF2Y Other specified assault | 15: XE266 Home / XE9DC Residential institution / XE9VC Medical service area |
| `activityWhenInjured` | 389 | 0 | NotAllowed | PF2Y Other specified assault | 5: XE545 Paid work / XE8VF Unpaid work / XE729 Educational activity |
| `objectOrSubstanceProducingInjury` | 331 | 0 | NotAllowed | PF2Y Other specified assault | 28: - Land vehicle or means of land transport / - Mobile machinery or special purpose vehi / - Watercraft or means of water transport |
| `alcoholUseInInjury` | 309 | 0 | AllowedExceptFromSameBlock | PF2Y Other specified assault | 5: XE47R Alcohol use, no information available / XE08X Alcohol use, no suspicion or evidence of / XE1G3 Alcohol use, suspicion or evidence of al |
| `psychoactiveDrugUseInInjury` | 309 | 0 | AllowedExceptFromSameBlock | PF2Y Other specified assault | 5: XE43G Psychoactive drug use, no information av / XE5TU Psychoactive drug use, no suspicion or e / XE5VY Psychoactive drug use, suspicion or evid |
| `transportEventDescriptor` | 136 | 0 | AllowedExceptFromSameBlock | PA50 Unintentional air or space transport injury event | 5: XE42A Vehicle driver injured in transport rela / XE1LZ Vehicle passenger injured in transport r / XE9Y1 Person boarding or alighting a vehicle i |
| `aspectsOfIntentionalSelfHarm` | 97 | 0 | AllowedExceptFromSameBlock | PB80 Intentional self-harm by land transport road traffic injury event | 3: - Proximal risk-factors for intentional se / - Previous non-fatal intentional self harm / - Intention to die aspect of self-harm |
| `aspectsOfAssaultAndMaltreatment` | 96 | 0 | AllowedExceptFromSameBlock | PJ20 Physical maltreatment | 3: - Perpetrator-victim relationship / - Gender of perpetrator / - Context of assault and maltreatment |
| `aspectsOfArmedConflict` | 45 | 0 | AllowedExceptFromSameBlock | PK6Y Other specified armed conflict | 2: - Type of armed conflict / - Role of injured person in armed conflict |
| `mechanismOfInjury` | 5 | 0 | NotAllowed | PA00 Unintentional land transport traffic event injuring a pedestrian | 9: XE72E Exposure to injurious transport event / XE3Y8 Exposure to fall / XE4U1 Exposure to person, animal or plant |
| `sportsActivityDescriptor` | 1 | 0 | AllowedExceptFromSameBlock | PA1E Unintentional land transport nontraffic event injuring a rider of an animal | 4: - Type of sport or exercise activity / - Phase of sport or exercise activity / - Personal countermeasures in sport or exe |

