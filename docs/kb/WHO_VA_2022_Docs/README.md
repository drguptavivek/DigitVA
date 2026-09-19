---
title: WHO 2022 VA reference forms and deployed project workbooks
doc_type: reference
status: active
owner: DigitVA Data Collection
last_updated: 2026-09-19
---

# WHO 2022 VA reference forms and deployed project workbooks

Reference material for the web questionnaire (decision E8 in
`docs/planning/va-data-collection-plan.md`: reference material comes from
ODK Central's deployed definitions). The instrument is built only from the
curated reference form; the deployed project workbooks supply **translation
overlays** and cross-checks, never structure. Which workbook is the source
for each language is policy, recorded in
`docs/policy/va-form-project-configuration.md` ("Translation sources");
this README only inventories the files.

Downloaded from the projects' ODK Central deployments by the owner on
2026-09-19 (the reference form on 2026-09-17; the WHO multilingual V2.0 form on 2026-09-19). No respondent data; XLSForm
definitions only. `sha256` is the first twelve hex characters.

| File | ODK form id | Version | Title | Label languages | sha256 |
| --- | --- | --- | --- | --- | --- |
| `whova2022_xls_form_for_odk.xlsx` | `va_who_2022` | `2023072701` | 2022 WHO Verbal Autopsy instrument V1.1 (reference) | en, fr | `50b019ff163e` |
| `2022whova_xls_form_for_odk_multilingual.xlsx` | `va_who_2022` | `2026081401` | 2022 WHO Verbal Autopsy instrument V2.0 (WHO multilingual release; translation source only) | en, fr, pt, ar, sw, es | `05e123884c04` |
| `ND01_ICMRVA_WHOVA2022.xlsx` | `ND01_ICMRVA_WHOVA2022` | `ND01_ICMRVA_WHOVA2022_20251203` | (ND01 ICMR VA) 2022 WHO Verbal Autopsy Instrument V1.1; the most commonly deployed ICMR form, carries the DigitVA layer fields | en, hi | `ce79eb39eed9` |
| `RJ01_ICMRVA_WHOVA2022.xlsx` | `RJ01_ICMRVA_WHOVA2022` | `RJ01_ICMRVA_WHOVA2022_20251203` | (RJ01 ICMR VA) 2022 WHO Verbal Autopsy Instrument V1.1 | en, hi | `3519fc20295a` |
| `KA01_DS_WHOVA2022.xlsx` | `KA01_DS_WHOVA2022` | `KA01_DS_WHOVA2022_20250726` | (KA01) 2022 WHO Verbal Autopsy Instrument V1.1 | en, hi, kn, mr | `dee58c3d9828` |
| `KEM_VAADU_WHOVA2022.xlsx` | `KEM_VAADU_WHOVA2022` | `KEM_VAADU_WHOVA2022_V2.2` | KEM VAADU 2022 WHO Verbal Autopsy Instrument V2.2 | en, hi, mr | `d826bc0e18b6` |
| `JIPMER_DS_WHOVA2022.xlsx` | `JIPMER_DS_WHOVA2022` | `JIPMER_DS_WHOVA2022_V1.1` | (JIPMER) 2022 WHO Verbal Autopsy Instrument V1.1 | en, ta | `d139c436b1d4` |
| `PY01_ICMRVA_WHOVA2022.xlsx` | `PY01_ICMRVA_WHOVA2022` | `PY01_ICMRVA_WHOVA2022_20251203` | (PY01 ICMR VA) 2022 WHO Verbal Autopsy Instrument V1.1 | en, ta | `4c5b78a7ae1c` |
| `KL01_DS_WHOVA2022.xlsx` | `KL01_DS_WHOVA2022` | `KL01_DS_WHOVA2022_20250625` | (KL01) 2022 WHO Verbal Autopsy Instrument V1.1 | en, ml | `048962e3491a` |
| `ML01_ICMRVA_WHOVA2022.xlsx` | `ML01_ICMRVA_WHOVA2022` | `ML01_ICMRVA_WHOVA2022_20251203` | (ML01 ICMR VA) 2022 WHO Verbal Autopsy Instrument V1.1 | en, kha | `146a78a500bf` |
| `OD01_ICMRVA_WHOVA2022.xlsx` | `OD01_ICMRVA_WHOVA2022` | `OD01_ICMRVA_WHOVA2022_20251203` | (OD01 ICMR VA) 2022 WHO Verbal Autopsy Instrument V1.1 | en, or | `544ba5cf77d2` |
| `TR01_DS_WHOVA2022.xlsx` | `TR01_DS_WHOVA2022` | `TR01_DS_WHOVA2022_20250526` | (TR01) 2022 WHO Verbal Autopsy Instrument V1.1 | bn, en | `73855b494355` |

Locale codes here are the XLSForm `label::Name (code)` codes and are the
instrument's locale axis. They are not `mas_languages` codes (`kha` here is
`khasi` there); nothing maps between the two.

The PDFs in this folder are the WHO manuals the forms implement.
