---
title: WHO 2022 VA Cause of Death List with ICD-10 and ICD-11 Codes
doc_type: reference
status: active
owner: engineering
last_updated: 2026-09-16
---

# WHO 2022 VA Cause of Death List with ICD-10 and ICD-11 Codes

## Purpose

This document is the repository reference copy of the WHO target list of causes
of death for verbal autopsy (VA), with the ICD-10 and ICD-11 code
correspondences that WHO published in 2026. It is the only WHO source in this
repository that gives ICD-11 codes for the WHO 2022 VA cause list.

The same data is kept in machine-readable form next to this file:

- `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_cause_list_icd10_icd11.csv`
  (65 rows, one per VA cause code)
- `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_cause_list_footnotes.csv`
  (the six table footnotes)

Both CSV files and the table below are generated from one transcribed dataset,
so they cannot drift apart. Treat the CSV as the data of record and this page as
its readable form.

## Source

- Publisher: World Health Organization (WHO).
- Document: *Cause of death assignment by physicians from verbal autopsy data:
  Manual for physician reviewers* (2026).
- Location in the document: Annex 1, "2022 WHO target list of cause of death for
  verbal autopsy", Table A1 "WHO target list of causes of death for VA with
  correspondence for ICD-11 and ICD-10 codes". Printed pages 79 to 83, which are
  PDF pages 86 to 90.
- Repository copy of the document:
  `docs/kb/WHO_VA_2022_Docs/2026 - pcva_manual-for-physician-reviewers.pdf`
  (95 pages, PDF created 2026-01-07).
- WHO download URL at the time of transcription:
  `https://cdn.who.int/media/docs/default-source/classification/other-classifications/autopsy/varg-workplans/pcva_manual-for-physician-reviewers_2026.pdf`

Transcribed on 2026-09-16 from the repository copy. Every code string, title
and footnote below was checked programmatically against the PDF text layer of
those five pages, and the table layout was checked against rendered page images.

## Transcription Rules

- Codes are transcribed as printed. Only whitespace was normalized: line breaks
  inside ranges were removed and separators are written as `; ` or `, ` exactly
  where the source uses a semicolon or a comma.
- Apparent typos in the source are kept verbatim and listed under
  "Source irregularities" below. They were not corrected, so that this file
  stays a faithful copy of what WHO published.
- Footnote markers printed as superscript letters in the source appear here in
  square brackets after the cause title, for example `Tetanus [a]`.
- The ICD-10 cell for VAs-12.01 and VAs-12.02 is empty in the source apart from
  footnote marker f. The footnote f code list is shared by both rows and is
  split by whether the death was a road traffic accident. The ICD-11 range
  PA00-PA5Z is printed once across both rows and is recorded against each.

## Table A1

| VA code | VA cause of death title | ICD-10 codes | ICD-11 codes |
|---|---|---|---|
| **VAs-01 Infectious and parasitic diseases** | | | |
| VAs-01.01 | Sepsis | A40-A41 | 1G40-1G41 |
| VAs-01.02 | Acute respiratory infection, including pneumonia | J00-J22; J85 | CA00-CA07.1; CA40-CA43; CA45; CA4Z; 1E30-1E32 |
| VAs-01.03 | HIV/AIDS related death | B20-B24 | 1C60-1C62 |
| VAs-01.04 | Diarrheal diseases | A00-A09 | 1A00-1A40.Z |
| VAs-01.05 | Malaria | B50-B54 | 1F40-1F4Z |
| VAs-01.06 | Measles | B05 | 1F03 |
| VAs-01.07 | Meningitis and encephalitis | A39; G00-G05 | 1B53-1B54; 1C1C; 1C80-1C8F; 1D00-1D02; 8B41 |
| VAs-01.08 | Tetanus [a] | A33-A35 | 1C13-1C14 |
| VAs-01.09 | Pulmonary tuberculosis | A15-A16 | 1B10 |
| VAs-01.10 | Pertussis | A37 | 1C12 |
| VAs-01.11 | Haemorrhagic fever [b] | A92-A96, A98-A99 | 1D40-1D4Z; 1D6Z; 1D60-1D6Z |
| VAs-01.12 | Dengue fever | A97 | 1D20-1D2Z |
| VAs-01.13 | Coronavirus disease (COVID-19) | U07.1; U07.2 | RA01.0; RA01.1 |
| VAs-01.99 | Unspecified infectious disease | A17-A19; A20-A32; A36; A38; A42-A89; B00-B04; B06-B19; B25-B49; B55-B99 | 1A60-1A9Z; 1B11-1B51; 1B5Y-1B9Z; 1C10-1C11.Y; 1C16-1C1B; 1C1D-1C62; 1C8Y-1C8Z; 1D03-1D0Z; 1D80-1E1Z; 1E50-1E91.Z; 1F00-1F02; 1F04-1F2Z; 1F50-1G2Z; 1G60-1H0Z; AA00-AA0Z; AA3Y-AA3Z; DB90; EA00-EA6Y; EE12; EG61; FA90-FA91; FB30; GA00-GA02; GA05; GA07; GB02; GC08 |
| **Non-communicable diseases** | | | |
| VAs-98 | Other and unspecified non-communicable disease | D65-D89; E00-E07; E15-E35; E50-E90; F00-F99; G06-G09; G10-G37; G43-G47; G50-G99; H00-H95; J30-J39; J47-J84; J86-J99; K00-K31; K35-K38; K40-K69; K70-K93 L00-L99; M00-M99; N00-N16; N20-N99 | 3A60; 3B10-3C0Z; 4A00-4B4Z; DB96; 5A00-5A0Z; 5A40-5B3Z; 5B55-5C3Z; 5C50-5C51; 5C52.Y-5C52-Z; 5C55; 5C56.0-5C56.3; 5C58; 5C5A; 5C61.6; 5C64; 5C70-5C77; 5C80-5D46; 6A20-6A8Z; 6B00-6E8Z; 7A00-7A6Z; 7A80-7A81; 7A83-7B2Z; 8A00-8A4Z; 8A80-8A8Z; 8B24; 8B40; 8B42-8D8Z; 8E00-8E2Z; 8E40-8E7Z; 9A01-9E1Z; AA10-AA1Z; AA40-AC0Z; CA08-CA0Z; CA24-CA2Z; CA60-CB7Z; DA00-DB7Z; DB91-DB92; DB96-DE2Z; EA80-EB9Y; EC90-ED00; ED02-ED9Y; EE01-EE11; EE13-EE20; EE40-EG60; EG62-EG9Z; EH40-EL50; EL60-EM0Z; FA00-FA8Z; FA92-FB1Z; FB31-FC0Z; GA03-GA04; GA06; GA0Z-GB01; GB03-GB5Z; GB70-GB80; GB8Y; GB90-GC07; GC0Y-GC8Z; HA00-HA8Z; MB43; MB50-MB5Z; MC10-MC20; MC2Y-MC6Y; ME82; ME84-ME85; ME93; MF3A; MF54; MF56; MF80-MF8Z |
| **VAs-02 Neoplasms** | | | |
| VAs-02.01 | Oral neoplasms | C00-C06 | 2B60-2B66 |
| VAs-02.02 | Digestive neoplasms | C15-C26 | 2B56.3; 2B70-2B72; 2B80-2B81; 2B90-2B9Y; 2C00-2C1Z |
| VAs-02.03 | Respiratory neoplasms | C30-C39 | 2C20-2C2Z |
| VAs-02.04 | Breast neoplasms | C50 | 2C60-2C6Z |
| VAs-02.05 | Female reproductive neoplasms | C51-C58 | 2C70-2C7Z |
| VAs-02.06 | Male reproductive neoplasms | C60-C63 | 2C80-2C8Z |
| VAs-02.99 | Other and unspecified neoplasms | C07-C14; C40-C49; C64-D48; C91-C95 | 2A00-2A0Z; 2A20-2A90; 2B00-2B56.2; 2B56.Y-2B5Z; 2B67-2B6Y; 2C30-2C5Z; 2C90-2E6Z; 2E80-2F9Z |
| **VAs-03 Nutritional and endocrine disorders** | | | |
| VAs-03.01 | Severe anaemia | D50-D64 | 3A00-3A4.Z; 3A61-3A9Z |
| VAs-03.02 | Severe malnutrition | E40-E46 | 5B50-5B54; 5B71-5B7Z |
| VAs-03.03 | Diabetes mellitus | E10-E14 | 5A10-5A14 |
| **VAs-04 Diseases of the circulatory system** | | | |
| VAs-04.01 | Acute cardiac disease [c] | I11.0; I20-I26; I46.1; I46.9; I50.1 | BA01; BA40-BA6Z; BB00; BD11; MC82 |
| VAs-04.02 | Stroke | I60-I69 | 8B00-8B23; 8B25-8B2Z |
| VAs-04.03 | Sickle cell with crisis | D57 | 3A51 |
| VAs-04.99 | Other and unspecified cardiac disease | I00-I10; I11.9-I15; I27-I46.0; I47-I50.0; I50.9-I52; I70-I99 | BA00; BA02-BA2Z; BA50-BA5Z; BA81-BA8Z; BB01-BC91; BC9Y-BC9Z; BD10; BD12-BE2Z; 1B40-1B42 |
| **VAs-05 Respiratory disorders** | | | |
| VAs-05.01 | Chronic obstructive pulmonary disease (COPD) | J40-J44 | CA20-CA22 |
| VAs-05.02 | Asthma | J45-J46 | CA23 |
| **VAs-06 Gastrointestinal disorders** | | | |
| VAs-06.01 | Acute abdomen | R10 | MD81 |
| VAs-06.02 | Liver cirrhosis [d] | K70.2; K70.3; K71.7; K74 | DB93; DB94.2; DB94.3, DB95.5 |
| **VAs-07 Renal disorders** | | | |
| VAs-07.01 | Renal failure | N17-N19 | GB60-GB6Z |
| **VAs-08 Mental and nervous system disorders** | | | |
| VAs-08.01 | Epilepsy | G40-G41 | 8A60-8A6Z |
| **VAs-09 Pregnancy-, childbirth- and puerperium-related disorders** | | | |
| VAs-09.01 | Ectopic pregnancy | O00 | JA01 |
| VAs-09.02 | Abortion-related death | O03-O08 | JA00; JA05-JA0Z |
| VAs-09.03 | Pregnancy-induced hypertension | O10-O16 | JA20-JA2Z |
| VAs-09.04 | Obstetric haemorrhage | O46; O67; O72 | JA40-JA4Z |
| VAs-09.05 | Obstructed labour | O63-O66 | JB03-JB06 |
| VAs-09.06 | Pregnancy-related sepsis | O75.3; O85 | JB0D.2; JB40 |
| VAs-09.07 | Anaemia of pregnancy | O99.0 | JB64.0 |
| VAs-09.0 | Ruptured uterus | O71.0-O71.1 | JB0A.0; JB0A.1 |
| VAs-09.99 | Other and unspecified maternal cause | O01-O02; O20-O45; O47-O62; O68-O70; O71.3-O71.9; O73-O84; O86-O99 | JA02-JA04; JA60-JA6Z; JA80-JA8Z; JB00-JB02; JB07-JB09; JB0A.2-JB0D.1; JB0D.3-JB0Z; JB20-JB2Z; JB41-JB4Z; JB60-JB63; JB64.1-JB6Z |
| **VAs-10 Neonatal causes of death** | | | |
| VAs-10.01 | Prematurity or low birth weight | P05; P07 | KA20-KA21 |
| VAs-10.02 | Birth asphyxia [e] | P20-P22 | KB20-KB23; KD30.0; KD30.1 |
| VAs-10.03 | Neonatal pneumonia | P23-P24 | KB24; KB26 |
| VAs-10.04 | Neonatal sepsis | P36 | KA60 |
| VAs-10.05 | Neonatal tetanus | A33 | 1C15 |
| VAs-10.06 | Congenital malformation | Q00-Q99 | 9A00; EC10-EC7Y; GB81-GB82; GB8Z; LA00-LD9Z |
| VAs-10.99 | Other and unspecified perinatal cause of death | P00-P04; P08-P15; P25-P35; P37-P94; P96; R95 | EH10-EH3Y; KA00-KA0Z; KA22-KA4Z; KA61-KA8Z; KB00-KB0Z; KB25; KB27-KB8Z; KC00-KC9Z; KD10-KD1Z; KD30.2-KD5Z; MH11 |
| **VAs-11 Stillbirths** | | | |
| VAs-11.01 | Fresh stillbirth | P95 | KD3B.1 |
| VAs-11.02 | Macerated stillbirth | P95 | KD3B.0 |
| **VAs-12 External causes of death** Note: The list of questions contains sub questions that allow for more specificity for accidents. | | | |
| VAs-12.01 | Road traffic accident [f] | see footnote f | PA00-PA5Z |
| VAs-12.02 | Other transport accident [f] | see footnote f | PA00-PA5Z |
| VAs-12.03 | Accidental fall | W00-W19 | PA60-PA6Z |
| VAs-12.04 | Accidental drowning and submersion | W65-W74 | PA90-PA9Z |
| VAs-12.05 | Accidental exposure to smoke, fire and flames | X00-X19 | PB10-PB15; PB1Y-PB1Z; PB55 |
| VAs-12.06 | Contact with venomous animals and plants | X20-X29 | PA78; PA79 |
| VAs-12.07 | Accidental poisoning and exposure to noxious substance | X40-X49 | PB20-PB36 |
| VAs-12.08 | Intentional self-harm | X60-X84; Y87.0 | PB80-PD3Z |
| VAs-12.09 | Assault | X85-Y09; Y87.1 | PD50-PF2Z; PJ20-PJ2Z |
| VAs-12.10 | Exposure to force of nature | X30-X39 | PJ00-PJ0Z |
| VAs-12.99 | Other and unspecified external cause of death | S00-T99; W20-W64; W75-W99; X10-X19; X50-X59; Y10-Y84; Y86; Y87.2; Y88-Y89 | EL51-EL54; NA00-NF2Z; PA70-PA77; PA7Y-PA8Z; PB00-PB0Z; PB16; PB50-PB54; PB56-PB6Z; PF40-PH8Z; PJ20-PJ2Z; PJ40-PL2Z |
| VAs-99 | Unknown and ill-defined cause of death | R00-R09; R11-R94; R96-R99 | MA00-MB42; MB44-MB4D; MB60-MB9Y; MC21; MC80-MD80; MD82-ME81; ME83; ME86-ME92; ME9Y-MF39; MF3Y-MF53; MF55; MF57-MF7Z; MF90-MH10; MH12-MH2Y |

## Footnotes

- **[a]** (VAs-01.08) Excludes: Neonatal tetanus VAs-10.05
- **[b]** (VAs-01.11) Excludes: Dengue VAs-01.12
- **[c]** (VAs-04.01) Includes: Ischaemic heart disease; Pulmonary embolism; Sudden cardiac death; Cardiac arrest, unspecified; Left ventricular failure; and Hypertensive heart disease with heart failure
- **[d]** (VAs-06.02) Includes Alcoholic fibrosis/ cirrhosis; Toxic liver cirrhosis; Fibrosis and cirrhosis of liver, excluding alcoholic and toxic, but including 'unspecified liver cirrhosis'
- **[e]** (VAs-10.02) Includes: Hypoxia and respiratory distress
- **[f]** (VAs-12.01; VAs-12.02) Distinction on the codes between VAs-12.01 and VAs 12.02 is on the basis whether the death was a road traffic accident. V01.1; V02.1; V03.1; V04.1; V05.1; V06.1; V09.2; V09.3; V10.4-V10.9; V11.4-V11.9; V12.4-V12.9; V13.4-V13.9; V14.4-V14.9; V15.4-V15.9; V16.4-V16.9; V17.4-V17.9; V18.4-V18.9; V19.4-V19.9; V20.4-V20.9; V21.4-V21.9; V22.4-V22.9; V23.4-V23.9; V24.4-V24.9; V25.4-V25.9; V26.4-V26.9; V27.4-V27.9; V28.4-V28.9; V29.4-V29.9; V30.5-V30.9; V31.5-V31.9; V32.5-V32.9; V33.5-V33.9; V34.5-V34.9; V35.5-V35.9; V36.5-V36.9; V37.5-V37.9; V38.5-V38.9; V39.4-V39.9; V40.5-V40.9; V41.5-V41.9; V42.5-V42.9; V43.5-V43.9; V44.5-V44.9; V45.5-V45.9; V46.5-V46.9; V47.5-V47.9; V48.5-V48.9; V49.4-V49.9; V50.5-V50.9; V51.5-V51.9; V52.5-V52.9; V53.5-V53.9; V54.5-V54.9; V55.5-V55.9; V56.5-V56.9; V57.5-V57.9; V58.5-V58.9; V59.4-V59.9; V60.5-V60.9; V61.5-V61.9; V62.5-V62.9; V63.5-V63.9; V64.5-V64.9; V65.5-V65.9; V66.5-V66.9; V67.5-V67.9; V68.5-V68.9; V69.4-V69.9; V70.5-V70.9; V71.5-V71.9; V72.5-V72.9; V73.5-V73.9; V74.5-V74.9; V75.5-V75.9; V76.5-V76.9; V77.5-V77.9; V78.5-V78.9; V79.4-V79.9; V80.0-V80.9; V81.1-V81.9; V82.1-V82.9; V83.0-V83.3; V84.0-V84.3; V85.0-V85.3; V86.0-V86.3; V87.0-V87.9; V89.2-V89.3; Y85.0; V90-V99; Y85.9

## Source Irregularities

These are reproduced verbatim from the WHO table. Anyone building code lists
from this file should decide how to handle each one explicitly.

- `VAs-01.11` ICD-10 uses a comma separator: `A92-A96, A98-A99`.
- `VAs-01.11` ICD-11 lists `1D6Z` on its own and again inside `1D60-1D6Z`.
- `VAs-98` ICD-10 has no separator between `K70-K93` and `L00-L99`.
- `VAs-98` ICD-10 `K70-K93` overlaps the liver cirrhosis codes `K70.2`, `K70.3`,
  `K71.7` and `K74` that belong to `VAs-06.02`.
- `VAs-98` ICD-11 prints `5C52.Y-5C52-Z`, where `5C52.Z` was presumably intended,
  and lists `DB96` on its own and again inside `DB96-DE2Z`.
- `VAs-03.01` ICD-11 prints `3A00-3A4.Z`, where `3A4Z` was presumably intended.
- `VAs-06.02` ICD-11 uses a comma before the last code: `DB94.3, DB95.5`.
- `VAs-09.0` is printed with a two-digit suffix; the sequence suggests
  `VAs-09.08` was intended.
- `VAs-12.05` ICD-10 `X00-X19` and `VAs-12.99` ICD-10 `X10-X19` overlap.
- `VAs-12.09` and `VAs-12.99` both list ICD-11 `PJ20-PJ2Z`.
- Footnote f lists only traffic fourth-character subdivisions for land transport
  codes (for example `V10.4-V10.9`, not `V10.0-V10.3`), plus `V90-V99` and
  `Y85`. Non-traffic land transport codes are not placed anywhere by the table.

## Differences From the Earlier Extract in This Repository

`app/static/WHO_2022_VA_CODES.pdf` (also kept in this folder) is a four-page
ICD-10-only extract of the earlier WHO cause list, prepared in April 2026. It
has no ICD-11 column. Its ICD-10 column differs from the 2026 annex in four
places:

| VA code | Earlier extract | 2026 annex (this file) |
|---|---|---|
| VAs-98 | `G10-G37; G50-G99` and `K77-K93` | adds `G43-G47`; uses `K70-K93` |
| VAs-10.99 | ends at `P96` | adds `R95` |
| VAs-99 | "Cause of death unknown", `R95-R99` | "Unknown and ill-defined cause of death", `R00-R09; R11-R94; R96-R99` |
| VAs-12.99 | `(S00-T99)` in parentheses | `S00-T99` |

## Relationship to Application Behaviour

- Nothing in the application reads these files. They are reference data only.
- ICD-10 coding allowability in the app is generated from the WHO 2022 VA
  crosswalk workbook, as described in
  `docs/policy/who-2022-icd10-coding-allowability.md`. It has not been
  re-derived from the 2026 annex, so the four ICD-10 differences above are not
  reflected in the coding policy yet.
- WHO cause-of-death buckets in the app are loaded from
  `docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd-cod-2026-04-27/WHO_2022_VA_Bucket_Mapping_document_derived.xlsx`.
- The application has no ICD-11 catalog. This table gives VA bucket to ICD-11
  range correspondences only; expanding ranges such as `1A60-1A9Z` into
  selectable codes needs the WHO ICD-11 MMS linearization as a code master.
- Follow-up work is tracked in `.tasks/who-2026-annex-icd10-icd11-review.md`.
