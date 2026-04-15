---
title: WHO_2022_VA_SOCIAL Category Subcategory Inventory
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# WHO_2022_VA_SOCIAL Category / Subcategory Inventory

This document is the first-pass inventory for the `WHO_2022_VA_SOCIAL` form in DigitVA.

It lists each configured category and subcategory from the field display configuration, the fields currently assigned to it, and whether the subcategory already has a `smart-va-pipeline` trace document.

Use this inventory as the checklist for the next pass: one subcategory at a time, confirming what reaches SmartVA, what is transformed, and what is ignored.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Field Mapping System](../../current-state/field-mapping-system.md)
- [Category Rendering And Visibility](../../current-state/category-rendering-and-visibility.md)

## Configured Subcategories

| Category | Subcategory | Fields | Current trace |
|---|---|---|---|
| Interview Details | va_interviewer | `Id10010`, `Id10010a`, `Id10010b`, `Id10010c` | pending |
| Interview Details | interview | `language`, `Id10012`, `Id10013`, `Id10011`, `Id10481` | [Interview Details](interview-details-interview.md) |
| Interview Details | va_respondent | `Id10007`, `Id10007a`, `Id10007b`, `Id10008`, `Id10009` | pending |
| Demographic Details | general | `Site`, `unique_id`, `site_individual_id`, `Id10017`, `Id10018`, `Id10021`, `Id10023`, `Id10024`, `isNeonatal`, `isChild`, `isAdult`, `ageInDays`, `ageInDays2`, `ageInYears`, `ageInMonths`, `age_group`, `age_neonate_days`, `age_neonate_hours`, `ageInYears2`, `Id10019`, `survey_state`, `survey_district`, `Id10002`, `Id10003`, `Id10004`, `Id10058`, `Id10052`, `Id10053`, `Id10054`, `Id10055`, `Id10057`, `Id10059`, `Id10063`, `Id10064`, `Id10065`, `Id10066`, `Id10061`, `Id10062` | [Demographic General](demographic-general.md) |
| Demographic Details | risk_factors | `Id10411`, `Id10413`, `Id10413_d`, `Id10413_a`, `Id10413_b`, `Id10414`, `Id10414_d`, `Id10414_a`, `Id10414_b`, `Id10487` | [Risk Factors](risk-factors.md) |
| Neonatal Period Details | general | `Id10354`, `Id10367` | [Neonatal Period General](neonatal-period-general.md) |
| Neonatal Period Details | delivery | `Id10387`, `Id10388`, `Id10389`, `Id10369`, `Id10382`, `Id10383`, `Id10384`, `Id10385`, `Id10403`, `Id10404`, `Id10405` | [Neonatal Delivery](neonatal-delivery.md) |
| Neonatal Period Details | stillbirth | `Id10104`, `Id10105`, `Id10106`, `Id10107`, `Id10377`, `Id10376`, `Id10109`, `Id10110`, `Id10111`, `Id10112`, `Id10113`, `Id10114`, `Id10115`, `Id10116` | [Neonatal Birth Condition](neonatal-birth-condition.md) |
| Neonatal Period Details | birth_weight | `Id10366_check`, `Id10366`, `Id10363`, `Id10365` | [Neonatal Birth Weight](neonatal-birth-weight.md) |
| Neonatal Period Details | symptoms | `Id10406`, `Id10284`, `Id10286`, `Id10287`, `Id10288`, `Id10289` | [Neonatal Danger Signs](neonatal-danger-signs.md) |
| Neonatal Period Details | physical_abnormalities | `Id10370`, `Id10371`, `Id10372`, `Id10373` | [Neonatal Period Physical Abnormalities](neonatal-period-physical-abnormalities.md) |
| Neonatal Period Details | baby_mother | `Id10391`, `Id10393`, `Id10395`, `Id10396`, `Id10397`, `Id10398`, `Id10399`, `Id10400`, `Id10401`, `Id10402` | [Neonatal Baby Mother](neonatal-baby-mother.md) |
| Injuries Details | default | `Id10077`, `Id10077_a`, `Id10079`, `Id10082`, `Id10083`, `Id10084`, `Id10085`, `Id10086`, `Id10087`, `Id10088`, `Id10089`, `Id10091`, `Id10092`, `Id10093`, `Id10096`, `Id10094`, `Id10095`, `Id10097`, `Id10098`, `Id10099`, `Id10100` | [Injuries](injuries.md) |
| Health History Details | neonate | `Id10351`, `Id10408` | [Health History Neonate](health-history-neonate.md) |
| Health History Details | medical_history | `Id10125`, `Id10126`, `Id10127`, `Id10128`, `Id10129`, `Id10482`, `Id10483`, `Id10484`, `Id10130`, `Id10131`, `Id10132`, `Id10133`, `Id10134`, `Id10135`, `Id10136`, `Id10137`, `Id10138`, `Id10139`, `Id10140`, `Id10141`, `Id10142`, `Id10143`, `Id10144` | [Medical History](medical-history.md) |
| General Symptoms | duration_of_illness | `Id10123`, `Id10121`, `Id10122`, `Id10120` | [Duration Of Illness](duration-of-illness.md) |
| General Symptoms | fever | `Id10147`, `Id10148_a`, `Id10148_c`, `Id10148`, `Id10149`, `Id10150`, `Id10151` | [Fever](fever.md) |
| General Symptoms | yellow_discoloration | `Id10265`, `Id10266_b`, `Id10266`, `Id10267` | [Jaundice](jaundice.md) |
| General Symptoms | nutrition | `Id10268`, `Id10269`, `Id10252`, `Id10485` | [Nutrition](nutrition.md) |
| General Symptoms | puffiness | `Id10247`, `Id10248_b`, `Id10248` | [Swelling](swelling.md) |
| General Symptoms | swelling | `Id10249`, `Id10250_b`, `Id10250`, `Id10251` | [Swelling](swelling.md) |
| Respiratory / Cardiac Symptoms | cough | `Id10153`, `Id10154_b`, `Id10154`, `Id10155`, `Id10156`, `Id10157`, `Id10158` | [Cough](cough.md) |
| Respiratory / Cardiac Symptoms | breathlessness | `Id10159`, `Id10161_0`, `Id10162`, `Id10163`, `Id10161`, `Id10165`, `Id10170`, `Id10171` | [Breathing Difficulty](breathing-difficulty.md) |
| Respiratory / Cardiac Symptoms | fast_breathing | `Id10166`, `Id10167_a`, `Id10167_c`, `Id10167` | [Breathing Difficulty](breathing-difficulty.md) |
| Respiratory / Cardiac Symptoms | breathing_pattern | `Id10172`, `Id10173_nc`, `Id10173_a` | [Breathing Difficulty](breathing-difficulty.md) |
| Respiratory / Cardiac Symptoms | chest_pain | `Id10174`, `Id10175`, `Id10176`, `Id10179`, `Id10179_1` | [Chest Pain](chest-pain.md) |
| Abdominal Symptoms | diarrhoea | `Id10181`, `Id10182_b`, `Id10182`, `Id10183`, `Id10184_a`, `Id10184_b`, `Id10184_c`, `Id10185`, `Id10186` | [Diarrhea](diarrhea.md) |
| Abdominal Symptoms | vomit | `Id10188`, `Id10190_a`, `Id10190_b`, `Id10189`, `Id10189_1`, `Id10191`, `Id10192` | [Vomiting](vomiting.md) |
| Abdominal Symptoms | abdominal_pain | `Id10194`, `Id10195`, `Id10196`, `Id10198`, `Id10197`, `Id10199` | [Abdominal Pain](abdominal-pain.md) |
| Abdominal Symptoms | protuding_abdomen | `Id10200`, `Id10202`, `Id10201`, `Id10203` | [Protruding Abdomen](protruding-abdomen.md) |
| Abdominal Symptoms | mass_abdomen | `Id10204`, `Id10206`, `Id10205` | [Mass Abdomen](mass-abdomen.md) |
| Abdominal Symptoms | urine_issues | `Id10223`, `Id10226`, `Id10224` | [Urine Problems](urine-problems.md) |
| Neurological Symptoms | headache | `Id10207` | [Headache](headache.md) |
| Neurological Symptoms | smell_taste | `Id10486` | [Smell Or Taste](smell-taste.md) |
| Neurological Symptoms | mental_confusion | `Id10212`, `Id10213_a`, `Id10213` | [Mental Confusion](mental-confusion.md) |
| Neurological Symptoms | unconscious | `Id10214`, `Id10216_b`, `Id10216`, `Id10217` | [Unconsciousness](unconsciousness.md) |
| Neurological Symptoms | paralyses | `Id10258`, `Id10259`, `Id10260` | [Paralysis](paralysis.md) |
| Neurological Symptoms | stiff_painful_neck | `Id10208`, `Id10209_b`, `Id10209` | [Stiff Neck](stiff-neck.md) |
| Neurological Symptoms | convulsions | `Id10220`, `Id10222`, `Id10275`, `Id10276` | [Convulsions](convulsions.md) |
| Neurological Symptoms | swallowing | `Id10261`, `Id10262_b`, `Id10262`, `Id10262_c` | [Swallowing](swallowing.md) |
| Skin / Mucosal Symptoms | ulcers | `Id10230`, `Id10231`, `Id10232_b`, `Id10232`, `Id10227`, `Id10229` | [Ulcers](ulcers.md) |
| Skin / Mucosal Symptoms | skin_rash | `Id10233`, `Id10234`, `Id10235`, `Id10236` | [Rash](rash.md) |
| Skin / Mucosal Symptoms | lumps | `Id10254`, `Id10255`, `Id10256`, `Id10257` | [Lumps](lumps.md) |
| Skin / Mucosal Symptoms | others | `Id10237`, `Id10238`, `Id10239`, `Id10240`, `Id10242`, `Id10243`, `Id10244`, `Id10245`, `Id10246` | [Skin Other](skin-other.md) |
| Neonatal Feeding Symptoms | feeding | `Id10271`, `Id10272`, `Id10273`, `Id10274_c`, `Id10274` | [Neonatal Feeding](neonatal-feeding.md) |
| Neonatal Feeding Symptoms | physical_abnormalality | `Id10277`, `Id10278`, `Id10279` | [Neonatal Physical Abnormality](neonatal-physical-abnormality.md) |
| Neonatal Feeding Symptoms | unresponsive | `Id10281`, `Id10282`, `Id10283` | [Neonatal Unresponsive](neonatal-unresponsive.md) |
| Maternal Symptoms | general | `Id10296`, `Id10299`, `Id10300`, `Id10301`, `Id10294`, `Id10340` | [Maternal General](maternal-general.md) |
| Maternal Symptoms | Periods, Delivery, Miscarriage,  Abortion before death | `Id10302`, `Id10303`, `Id10305`, `Id10312`, `Id10314`, `Id10306`, `Id10334`, `Id10333`, `Id10308`, `Id10310` | [Maternal Periods Delivery Abortion](maternal-periods-delivery-abortion.md) |
| Maternal Symptoms | antenatal | `Id10319`, `Id10317`, `Id10309`, `Id10320`, `Id10321`, `Id10323`, `Id10324`, `Id10304`, `Id10304_a`, `Id10322_a`, `Id10325`, `Id10329_b`, `Id10327` | [Maternal Antenatal](maternal-antenatal.md) |
| Maternal Symptoms | delivery | `Id10337`, `Id10332`, `Id10342`, `Id10343`, `Id10344`, `Id10331`, `Id10330`, `Id10328`, `Id10322_b`, `Id10329_a` | [Maternal Delivery](maternal-delivery.md) |
| Health Service Utilisation | treatment | `Id10418`, `Id10419`, `Id10420`, `Id10421`, `Id10422`, `Id10423`, `Id10424`, `Id10425`, `Id10426` | [Health Service Treatment](health-service-treatment.md) |
| Health Service Utilisation | hcw_cod | `Id10435`, `Id10436` | [Health Service HCW Cause Of Death](health-service-hcw-cod.md) |
| Health Service Utilisation | mother_related | `Id10446` | [Health Service Mother Related](health-service-mother-related.md) |
| Narration / Documents | narration | `narr_language`, `Id10476_audio`, `imagenarr`, `Id10476`, `Id10477`, `Id10478`, `Id10479` | [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md) |
| Narration / Documents | death_registeration | `Id10070`, `Id10071`, `Id10072` | [Death Registration](death-registration.md) |
| Narration / Documents | medical_certs | `Id10462`, `Id10463`, `Id10464`, `Id10465`, `Id10466`, `Id10467`, `Id10468`, `Id10469`, `Id10470`, `Id10471`, `Id10472`, `Id10473` | [Medical Certificates](medical-certs.md) |
| Narration / Documents | medical_documents | `md_im1`, `md_im2`, `md_im3`, `md_im4`, `md_im5`, `md_im6`, `md_im7`, `md_im8`, `md_im9`, `md_im10`, `md_im11`, `md_im12`, `md_im13`, `md_im14`, `md_im15`, `md_im16`, `md_im17`, `md_im18`, `md_im19`, `md_im20`, `md_im21`, `md_im22`, `md_im23`, `md_im24`, `md_im25`, `md_im26`, `md_im27`, `md_im28`, `md_im29`, `md_im30` | [Medical Documents](medical-documents.md) |
| Narration / Documents | death_documents | `ds_im1`, `ds_im2`, `ds_im3`, `ds_im4`, `ds_im5` | pending |
| Narration / Documents | iv_final | `comment` | pending |
| Social Autopsy | Social Autopsy | `sa01`, `sa06`, `sa06_a`, `sa02`, `sa03`, `sa04`, `sa05`, `sa05_a`, `sa07`, `sa07_a`, `sa09`, `sa10`, `sa11`, `sa12`, `sa08`, `sa13`, `sa_tu13`, `sa14`, `sa_tu14`, `sa15`, `sa_tu15`, `sa16`, `sa_tu16`, `sa17`, `sa_tu17`, `sa18`, `sa_tu18`, `sa19`, `sa_tu19` | pending |

## Uncategorized Or System Fields

These fields are present in `mas_field_display_config` for the form but do not currently sit under a configured category/subcategory pair. Treat them separately from the user-facing subcategory review pass.

`age_adult`, `age_child_days`, `age_child_months`, `age_child_unit`, `age_child_years`, `ageInDaysNeonate`, `ageInMonthsByYear`, `ageInMonthsRemain`, `ageInYearsRemain`, `audit`, `confirm_inst`, `deviceid`, `ds_available`, `ds_count`, `finalAgeInYears`, `Id10020`, `Id10022`, `Id10023_a`, `Id10023_b`, `Id10051`, `Id10069_a`, `Id10071_check`, `Id10073`, `Id10077_b`, `Id10120_0`, `Id10120_1`, `id10120_unit`, `Id10148_b`, `Id10148_units`, `Id10154_a`, `Id10154_units`, `Id10161_1`, `id10161_unit`, `Id10167_b`, `Id10167_units`, `Id10173`, `Id10178_unit`, `Id10182_a`, `Id10182_units`, `Id10184_units`, `Id10190_units`, `id10196_unit`, `Id10197_a`, `Id10201_a`, `Id10201_unit`, `Id10205_a`, `Id10205_unit`, `Id10209_a`, `Id10209_units`, `Id10213_b`, `Id10213_units`, `Id10216_a`, `Id10216_units`, `Id10232_a`, `Id10232_units`, `Id10248_a`, `Id10248_units`, `Id10250_a`, `Id10250_units`, `Id10253`, `Id10262_a`, `Id10262_units`, `Id10266_a`, `Id10266_units`, `Id10274_a`, `Id10274_b`, `Id10274_units`, `Id10313`, `isAdult1`, `isAdult2`, `isChild1`, `isChild2`, `isNeonatal1`, `isNeonatal2`, `md_available`, `md_count`, `start`, `survey_block`, `telephonic_consent`, `today`

## Current-State Notes

- This inventory is driven from the DB-backed field display config for `WHO_2022_VA_SOCIAL`, not from the raw XLSForm alone.
- Some subcategories already map cleanly to existing SmartVA KB pages. Others are still pending and need a first trace document.
- A subcategory being present here does not mean every field in it reaches SmartVA. Some groups are mostly routing, metadata, or UI-only fields.
- The next pass should be done subcategory by subcategory, starting with the pending rows and then checking existing docs for missed fields.
