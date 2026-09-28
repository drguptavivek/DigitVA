---
title: WHO ICD-11 download files kept in docs/kb
doc_type: kb
status: active
owner: engineering
last_updated: 2026-09-28
---

# WHO ICD-11 download files kept in docs/kb

The WHO ICD-11 files below are kept unzipped under `docs/kb/`. The original
`.zip` bundles are git-ignored (`docs/kb/*.zip`): they duplicate the
unzipped folders. To refresh a folder, download the bundle again, unzip it
over the folder, and note the new release date here.

All four come from the WHO ICD-11 Browser, https://icd.who.int/browse/
(ICD-11 for Mortality and Morbidity Statistics, English), under its
Info / Downloads section. Use of the content is governed by the WHO ICD-11
licence in `docs/kb/ICD11-license.pdf`.

| Folder | WHO bundle | File dates in the bundle | Contents |
| --- | --- | --- | --- |
| `docs/kb/ICD10-ICD11-mapping/` | ICD-10 / ICD-11 mapping tables (`ICD10-ICD11-mapping.zip`) | 2026-02-16 | 10-to-11 and 11-to-10 maps (MMS and Foundation), txt and xlsx, `readme.txt` |
| `docs/kb/SimpleTabulation-ICD-11-MMS-en/` | MMS Simple Tabulation (`SimpleTabulation-ICD-11-MMS-en.zip`) | 2026-09-25 | every MMS entity with code, class kind, chapter, browser link and tabulation groupings, `readme.txt` |
| `docs/kb/MortalityTabulationList_en/` | ICD-11 Mortality Tabulation List (`MortalityTabulationList_en.zip`) | 2026-01-29 | tabulation list xlsx and readme PDF |
| `docs/kb/MorbidityTabulationList_en/` | ICD-11 Morbidity Tabulation List (`MorbidityTabulationList_en.zip`) | 2026-01-29 | tabulation list xlsx and readme PDF |

A frozen copy of the Mortality Tabulation List used for the cause-group
migration lives under `docs/icd-causegrp-mappings/migration-artifacts/`; do
not refresh that copy when refreshing this folder.
