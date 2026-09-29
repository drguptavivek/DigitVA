---
title: PHMRC verbal autopsy instruments (reference)
doc_type: reference
status: active
owner: DigitVA Data Collection
last_updated: 2026-09-29
---

# PHMRC verbal autopsy instruments

Reference copies of the Population Health Metrics Research Consortium (PHMRC)
verbal autopsy instruments, added by the owner. No respondent data.

| Path | What it is |
| --- | --- |
| `ODK PHMRC_Shortened_Instrument_12_10_2018_all-files/PHMRC_Shortened_Instrument_12_10_2018.xlsx` | Shortened instrument as an ODK XLSForm (form_id `SmartVA_Generic_v1`, 633 rows; English plus a placeholder `language` column). SmartVA's native input. |
| same folder, `.xml` and `-Change_ Log.xlsx` | Compiled XForm and the form's change log |
| same folder, `-media/` | Label media shown to respondents: 9 images (baby size, chest indrawing, head too small / too big, bulging fontanelle, mass defect, other defect, tetanus) and `grunting.wav` |
| `ODK PHMRC Full Instrument/FullInstrument4-3-13.xls` | Full instrument (2013) XLSForm, legacy `.xls`, with its `.xml` and media (adds wheezing, stridor audio and more images) |
| `PHMRC Shortened VAI - *.doc`, `PHMRC full instrument - *.docx` | Paper questionnaires: general, adult, child and neonate modules |

The `.zip` archives next to these folders are the original downloads and
are not committed (they duplicate the unzipped folders).

Planned use: the shortened form as a DigitVA web form, capture only
(bead `digitva-d1x`, after the WHO VA 2022 form is stable). The full
instrument stays reference only.
