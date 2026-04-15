---
title: SmartVA Trace Summary Matrix
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# SmartVA Trace Summary Matrix

This is a navigation-level summary matrix for the `WHO_2022_VA_SOCIAL` tracing pass.

Use the linked KB doc for field-level retained/transformed/collapsed details. This matrix is intentionally concise.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Uncategorized And System Fields](uncategorized-system-fields.md)
- [SmartVA Trace QA Review](trace-qa-review.md)

## Configured Subcategory Matrix

| Field(s) | Category / Subcategory | KB doc | Current SmartVA status |
|---|---|---|---|
| `Id10010`, `Id10010a`, `Id10010b`, `Id10010c` | Interview Details / va_interviewer | out of scope by user request (interviewer metadata) | out of scope by user request; interviewer metadata only |
| `language`, `Id10012`, `Id10013`, `Id10011`, `Id10481` | Interview Details / interview | [Interview Details](interview-details-interview.md) | consent gating plus output metadata; not a symptom block |
| `Id10007`, `Id10007a`, `Id10007b`, `Id10008`, `Id10009` | Interview Details / va_respondent | out of scope by user request (respondent metadata) | out of scope by user request; respondent metadata only |
| `Site`, `unique_id`, `site_individual_id`, `Id10017`, `Id10018`, `Id10021`, `Id10023`, `Id10024`, `isNeonatal`, `isChild`, `isAdult`, `ageInDays`, `ageInDays2`, `ageInYears`, `ageInMonths`, `age_group`, `age_neonate_days`, `age_neonate_hours`, `ageInYears2`, `Id10019`, `survey_state`, `survey_district`, `Id10002`, `Id10003`, `Id10004`, `Id10058`, `Id10052`, `Id10053`, `Id10054`, `Id10055`, `Id10057`, `Id10059`, `Id10063`, `Id10064`, `Id10065`, `Id10066`, `Id10061`, `Id10062` | Demographic Details / general | [Demographic General](demographic-general.md) | age/sex routing helpers plus metadata; only a narrow subset influences SmartVA routing |
| `Id10411`, `Id10413`, `Id10413_d`, `Id10413_a`, `Id10413_b`, `Id10414`, `Id10414_d`, `Id10414_a`, `Id10414_b`, `Id10487` | Demographic Details / risk_factors | [Risk Factors](risk-factors.md) | partly retained adult tobacco path; most visible WHO fields ignored |
| `Id10354`, `Id10367` | Neonatal Period Details / general | [Neonatal Period General](neonatal-period-general.md) | direct retained neonatal-period signals |
| `Id10387`, `Id10388`, `Id10389`, `Id10369`, `Id10382`, `Id10383`, `Id10384`, `Id10385`, `Id10403`, `Id10404`, `Id10405` | Neonatal Period Details / delivery | [Neonatal Delivery](neonatal-delivery.md) | mixed retained/transformed neonatal delivery family; some adapter links less explicit |
| `Id10104`, `Id10105`, `Id10106`, `Id10107`, `Id10377`, `Id10376`, `Id10109`, `Id10110`, `Id10111`, `Id10112`, `Id10113`, `Id10114`, `Id10115`, `Id10116` | Neonatal Period Details / stillbirth | [Neonatal Birth Condition](neonatal-birth-condition.md) | direct retained stillbirth/birth-condition family |
| `Id10366_check`, `Id10366`, `Id10363`, `Id10365` | Neonatal Period Details / birth_weight | [Neonatal Birth Weight](neonatal-birth-weight.md) | mixed retained birth-size/weight family |
| `Id10406`, `Id10284`, `Id10286`, `Id10287`, `Id10288`, `Id10289` | Neonatal Period Details / symptoms | [Neonatal Danger Signs](neonatal-danger-signs.md) | direct retained neonatal danger-sign family |
| `Id10370`, `Id10371`, `Id10372`, `Id10373` | Neonatal Period Details / physical_abnormalities | [Neonatal Period Physical Abnormalities](neonatal-period-physical-abnormalities.md) | retained with cross-use in stillbirth and neonatal-illness paths |
| `Id10391`, `Id10393`, `Id10395`, `Id10396`, `Id10397`, `Id10398`, `Id10399`, `Id10400`, `Id10401`, `Id10402` | Neonatal Period Details / baby_mother | [Neonatal Baby Mother](neonatal-baby-mother.md) | partly retained maternal-complication family with cross-subcategory merge |
| `Id10077`, `Id10077_a`, `Id10079`, `Id10082`, `Id10083`, `Id10084`, `Id10085`, `Id10086`, `Id10087`, `Id10088`, `Id10089`, `Id10091`, `Id10092`, `Id10093`, `Id10096`, `Id10094`, `Id10095`, `Id10097`, `Id10098`, `Id10099`, `Id10100` | Injuries Details / default | [Injuries](injuries.md) | mixed retained injury family with many visible WHO fields ignored |
| `Id10351`, `Id10408` | Health History Details / neonate | [Health History Neonate](health-history-neonate.md) | helper-dependent onset-age path plus one ignored growth field |
| `Id10125`, `Id10126`, `Id10127`, `Id10128`, `Id10129`, `Id10482`, `Id10483`, `Id10484`, `Id10130`, `Id10131`, `Id10132`, `Id10133`, `Id10134`, `Id10135`, `Id10136`, `Id10137`, `Id10138`, `Id10139`, `Id10140`, `Id10141`, `Id10142`, `Id10143`, `Id10144` | Health History Details / medical_history | [Medical History](medical-history.md) | partly retained adult diagnosis history; mostly ignored outside narrow subset |
| `Id10123`, `Id10121`, `Id10122`, `Id10120` | General Symptoms / duration_of_illness | [Duration Of Illness](duration-of-illness.md) | retained duration family; adult WHO-side builder less explicit |
| `Id10147`, `Id10148_a`, `Id10148_c`, `Id10148`, `Id10149`, `Id10150`, `Id10151` | General Symptoms / fever | [Fever](fever.md) | direct retained fever family with structured plus free-text lanes |
| `Id10265`, `Id10266_b`, `Id10266`, `Id10267` | General Symptoms / yellow_discoloration | [Jaundice](jaundice.md) | direct retained jaundice family |
| `Id10268`, `Id10269`, `Id10252`, `Id10485` | General Symptoms / nutrition | [Nutrition](nutrition.md) | split partial retention across adult swelling and child pallor paths |
| `Id10247`, `Id10248_b`, `Id10248` | General Symptoms / puffiness | [Swelling](swelling.md) | direct retained adult puffiness family |
| `Id10249`, `Id10250_b`, `Id10250`, `Id10251` | General Symptoms / swelling | [Swelling](swelling.md) | mixed retained swelling/edema family; some paths less explicit |
| `Id10153`, `Id10154_b`, `Id10154`, `Id10155`, `Id10156`, `Id10157`, `Id10158` | Respiratory / Cardiac Symptoms / cough | [Cough](cough.md) | direct retained cough family |
| `Id10159`, `Id10161_0`, `Id10162`, `Id10163`, `Id10161`, `Id10165`, `Id10170`, `Id10171` | Respiratory / Cardiac Symptoms / breathlessness | [Breathing Difficulty](breathing-difficulty.md) | direct retained breathing-difficulty family |
| `Id10166`, `Id10167_a`, `Id10167_c`, `Id10167` | Respiratory / Cardiac Symptoms / fast_breathing | [Breathing Difficulty](breathing-difficulty.md) | direct retained breathing-difficulty family |
| `Id10172`, `Id10173_nc`, `Id10173_a` | Respiratory / Cardiac Symptoms / breathing_pattern | [Breathing Difficulty](breathing-difficulty.md) | direct retained breathing-difficulty family |
| `Id10174`, `Id10175`, `Id10176`, `Id10179`, `Id10179_1` | Respiratory / Cardiac Symptoms / chest_pain | [Chest Pain](chest-pain.md) | partly retained chest-pain family; follow-up wiring less explicit |
| `Id10181`, `Id10182_b`, `Id10182`, `Id10183`, `Id10184_a`, `Id10184_b`, `Id10184_c`, `Id10185`, `Id10186` | Abdominal Symptoms / diarrhoea | [Diarrhea](diarrhea.md) | direct retained diarrhea family |
| `Id10188`, `Id10190_a`, `Id10190_b`, `Id10189`, `Id10189_1`, `Id10191`, `Id10192` | Abdominal Symptoms / vomit | [Vomiting](vomiting.md) | direct retained vomiting family |
| `Id10194`, `Id10195`, `Id10196`, `Id10198`, `Id10197`, `Id10199` | Abdominal Symptoms / abdominal_pain | [Abdominal Pain](abdominal-pain.md) | direct retained abdominal-pain family |
| `Id10200`, `Id10202`, `Id10201`, `Id10203` | Abdominal Symptoms / protuding_abdomen | [Protruding Abdomen](protruding-abdomen.md) | direct retained protruding-abdomen family |
| `Id10204`, `Id10206`, `Id10205` | Abdominal Symptoms / mass_abdomen | [Mass Abdomen](mass-abdomen.md) | direct retained mass-abdomen family |
| `Id10223`, `Id10226`, `Id10224` | Abdominal Symptoms / urine_issues | [Urine Problems](urine-problems.md) | mostly ignored in current adult adapter |
| `Id10207` | Neurological Symptoms / headache | [Headache](headache.md) | partly retained; downstream family clear but WHO adapter less explicit |
| `Id10486` | Neurological Symptoms / smell_taste | [Smell Or Taste](smell-taste.md) | ignored across adult, child, and neonate |
| `Id10212`, `Id10213_a`, `Id10213` | Neurological Symptoms / mental_confusion | [Mental Confusion](mental-confusion.md) | partly retained; downstream family clear but WHO adapter less explicit |
| `Id10214`, `Id10216_b`, `Id10216`, `Id10217` | Neurological Symptoms / unconscious | [Unconsciousness](unconsciousness.md) | direct retained unconsciousness family |
| `Id10258`, `Id10259`, `Id10260` | Neurological Symptoms / paralyses | [Paralysis](paralysis.md) | direct retained paralysis family |
| `Id10208`, `Id10209_b`, `Id10209` | Neurological Symptoms / stiff_painful_neck | [Stiff Neck](stiff-neck.md) | partly retained; duration adapter less explicit |
| `Id10220`, `Id10222`, `Id10275`, `Id10276` | Neurological Symptoms / convulsions | [Convulsions](convulsions.md) | direct retained convulsion family |
| `Id10261`, `Id10262_b`, `Id10262`, `Id10262_c` | Neurological Symptoms / swallowing | [Swallowing](swallowing.md) | direct retained swallowing family |
| `Id10230`, `Id10231`, `Id10232_b`, `Id10232`, `Id10227`, `Id10229` | Skin / Mucosal Symptoms / ulcers | [Ulcers](ulcers.md) | direct retained ulcers family |
| `Id10233`, `Id10234`, `Id10235`, `Id10236` | Skin / Mucosal Symptoms / skin_rash | [Rash](rash.md) | direct retained rash family |
| `Id10254`, `Id10255`, `Id10256`, `Id10257` | Skin / Mucosal Symptoms / lumps | [Lumps](lumps.md) | mostly ignored for adult; partially retained elsewhere |
| `Id10237`, `Id10238`, `Id10239`, `Id10240`, `Id10242`, `Id10243`, `Id10244`, `Id10245`, `Id10246` | Skin / Mucosal Symptoms / others | [Skin Other](skin-other.md) | mostly ignored with a few retained child/neonate skin signals |
| `Id10271`, `Id10272`, `Id10273`, `Id10274_c`, `Id10274` | Neonatal Feeding Symptoms / feeding | [Neonatal Feeding](neonatal-feeding.md) | direct retained neonatal feeding family |
| `Id10277`, `Id10278`, `Id10279` | Neonatal Feeding Symptoms / physical_abnormalality | [Neonatal Physical Abnormality](neonatal-physical-abnormality.md) | partly retained neonatal physical-abnormality family |
| `Id10281`, `Id10282`, `Id10283` | Neonatal Feeding Symptoms / unresponsive | [Neonatal Unresponsive](neonatal-unresponsive.md) | retained main unresponsive feature; timing split less explicit |
| `Id10296`, `Id10299`, `Id10300`, `Id10301`, `Id10294`, `Id10340` | Maternal Symptoms / general | [Maternal General](maternal-general.md) | mixed retained maternal-general family with a breast-field collapse point |
| `Id10302`, `Id10303`, `Id10305`, `Id10312`, `Id10314`, `Id10306`, `Id10334`, `Id10333`, `Id10308`, `Id10310` | Maternal Symptoms / Periods, Delivery, Miscarriage,  Abortion before death | [Maternal Periods Delivery Abortion](maternal-periods-delivery-abortion.md) | direct retained maternal timing/bleeding family |
| `Id10319`, `Id10317`, `Id10309`, `Id10320`, `Id10321`, `Id10323`, `Id10324`, `Id10304`, `Id10304_a`, `Id10322_a`, `Id10325`, `Id10329_b`, `Id10327` | Maternal Symptoms / antenatal | [Maternal Antenatal](maternal-antenatal.md) | partly retained reduced antenatal subset |
| `Id10337`, `Id10332`, `Id10342`, `Id10343`, `Id10344`, `Id10331`, `Id10330`, `Id10328`, `Id10322_b`, `Id10329_a` | Maternal Symptoms / delivery | [Maternal Delivery](maternal-delivery.md) | partly retained delivery subset; some older hidden fields still feed downstream |
| `Id10418`, `Id10419`, `Id10420`, `Id10421`, `Id10422`, `Id10423`, `Id10424`, `Id10425`, `Id10426` | Health Service Utilisation / treatment | [Health Service Treatment](health-service-treatment.md) | metadata only for current SmartVA; visible treatment block ignored |
| `Id10435`, `Id10436` | Health Service Utilisation / hcw_cod | [Health Service HCW Cause Of Death](health-service-hcw-cod.md) | comment field retained through free-text path; yes/no field is metadata/gating |
| `Id10446` | Health Service Utilisation / mother_related | [Health Service Mother Related](health-service-mother-related.md) | direct child/neonate maternal-HIV context feature |
| `narr_language`, `Id10476_audio`, `imagenarr`, `Id10476`, `Id10477`, `Id10478`, `Id10479` | Narration / Documents / narration | [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md) | primary free-text and keyword path into SmartVA word features |
| `Id10070`, `Id10071`, `Id10072` | Narration / Documents / death_registeration | [Death Registration](death-registration.md) | metadata only; ignored by SmartVA scoring |
| `Id10462`, `Id10463`, `Id10464`, `Id10465`, `Id10466`, `Id10467`, `Id10468`, `Id10469`, `Id10470`, `Id10471`, `Id10472`, `Id10473` | Narration / Documents / medical_certs | [Medical Certificates](medical-certs.md) | certificate cause-text retained via free-text branch; flags/durations mostly ignored |
| `md_im1`, `md_im2`, `md_im3`, `md_im4`, `md_im5`, `md_im6`, `md_im7`, `md_im8`, `md_im9`, `md_im10`, `md_im11`, `md_im12`, `md_im13`, `md_im14`, `md_im15`, `md_im16`, `md_im17`, `md_im18`, `md_im19`, `md_im20`, `md_im21`, `md_im22`, `md_im23`, `md_im24`, `md_im25`, `md_im26`, `md_im27`, `md_im28`, `md_im29`, `md_im30` | Narration / Documents / medical_documents | [Medical Documents](medical-documents.md) | attachment storage only; ignored by SmartVA |
| `ds_im1`, `ds_im2`, `ds_im3`, `ds_im4`, `ds_im5` | Narration / Documents / death_documents | [Death Documents](death-documents.md) | attachment storage only; ignored by SmartVA |
| `comment` | Narration / Documents / iv_final | [Interviewer Final Comment](iv-final.md) | interviewer final comment ignored by SmartVA |
| `sa01`, `sa06`, `sa06_a`, `sa02`, `sa03`, `sa04`, `sa05`, `sa05_a`, `sa07`, `sa07_a`, `sa09`, `sa10`, `sa11`, `sa12`, `sa08`, `sa13`, `sa_tu13`, `sa14`, `sa_tu14`, `sa15`, `sa_tu15`, `sa16`, `sa_tu16`, `sa17`, `sa_tu17`, `sa18`, `sa_tu18`, `sa19`, `sa_tu19` | Social Autopsy / Social Autopsy | [Social Autopsy](social-autopsy.md) | explicitly dropped before SmartVA input is written |

## Uncategorized And System Matrix

| Field or field group | KB doc | Current SmartVA status |
|---|---|---|
| `age_adult, age_child_*, ageInDaysNeonate, ageInMonthsByYear, ageInMonthsRemain, ageInYearsRemain, isAdult1/2, isChild1/2, isNeonatal1/2` | [Uncategorized And System Fields](uncategorized-system-fields.md) | age-derivation and routing helpers |
| `finalAgeInYears` | [Uncategorized And System Fields](uncategorized-system-fields.md) | DigitVA fallback used to synthesize ageInDays before SmartVA input |
| `Id10120_0, Id10120_1, id10120_unit` | [Uncategorized And System Fields](uncategorized-system-fields.md) | illness-duration helpers; Id10120_1 is the important prepared day value |
| `Id10148_b, Id10148_units, Id10154_a, Id10154_units, Id10161_1, id10161_unit, Id10167_b, Id10167_units, Id10178_unit, Id10182_a, Id10182_units, Id10184_units, Id10190_units, id10196_unit, Id10197_a, Id10201_a, Id10201_unit, Id10205_a, Id10205_unit, Id10209_a, Id10209_units, Id10213_b, Id10213_units, Id10216_a, Id10216_units, Id10232_a, Id10232_units, Id10248_a, Id10248_units, Id10250_a, Id10250_units, Id10262_a, Id10262_units, Id10266_a, Id10266_units, Id10274_a, Id10274_b, Id10274_units` | [Uncategorized And System Fields](uncategorized-system-fields.md) | duration/unit helpers for linked symptom families |
| `survey_block, telephonic_consent` | [Uncategorized And System Fields](uncategorized-system-fields.md) | explicitly dropped before SmartVA input |
| `md_available, md_count, ds_available, ds_count` | [Uncategorized And System Fields](uncategorized-system-fields.md) | attachment counters only; not used by SmartVA scoring |
| `audit, confirm_inst, deviceid, start, today` | [Uncategorized And System Fields](uncategorized-system-fields.md) | submission/runtime metadata; not symptom inputs |
| `Id10020, Id10022, Id10023_a, Id10023_b, Id10051, Id10069_a, Id10071_check, Id10073, Id10077_b, Id10253, Id10313` | [Uncategorized And System Fields](uncategorized-system-fields.md) | no direct current WHO-to-PHMRC mapping surfaced in this pass |
