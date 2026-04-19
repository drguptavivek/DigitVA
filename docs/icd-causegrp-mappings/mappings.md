Absolutely — here is a **workflow-ready summary of the entire discussion**, organized so you can drop it into an agentic coding pipeline.

Also, I created the **WHO 2022 VA XLSX** here:

* [WHO_2022_VA_Crosswalk.xlsx](WHO_2022_VA_Crosswalk.xlsx)

It includes:

* `VA_2022_Crosswalk`
* `RoadTraffic_Footnote`
* `Notes`

The WHO 2022 VA table itself is a direct ICD-10 → VA-code crosswalk, but several rows depend on **4-character ICD codes** and some depend on **context** such as neonatal status, stillbirth status, or road-traffic detail. 

## 1) What the base data is

Your base file is a **3-character ICD-10 master list**. That was enough for:

* Annexure I / II / III mapping
* CMEA10 mapping
* overlap detection

But it is **not enough for precise WHO 2022 VA mapping**, because WHO VA uses decimal-specific codes in several places. Examples:

* `U07.1`, `U07.2` for COVID
* `I11.0` vs `I11.9-I15`
* `K70.2`, `K70.3`, `K71.7`
* `O75.3`
* `O99.0`
* `O71.0-O71.1` 

## 2) What we built already

### A. Annexure III (Adult) mapping

We first mapped your ICD list to **Annexure III Adult Classification** using:

* **specific ICD codes first**
* then **ranges**
* leaving unmatched rows blank
* flagging ambiguous rows separately

Important adult example:

* `C46` was assigned to **HIV/AIDS** because it is an explicit code there, even though neoplasm ranges also exist in the adult table.
* `R96` was kept as **ambiguous**, because Annexure III itself says it changes by age:

  * perinatal if age < 1
  * cardiovascular if age > 30
  * ill-defined otherwise. 

### B. Annexure I + II + III mapping

We then extended the file to include:

* **Annexure I Neonatal**
* **Annexure II Child**
* **Annexure III Adult**

The important lesson from this stage was:

* Annexure I / II / III are **ICD-range classification systems**
* they are **age-specific**
* the same ICD code can classify differently across annexures because the annexure itself assumes a different age band. 

Concrete examples:

* `P23` is neonatal pneumonia in Annexure I and pneumonia in Annexure II. 
* `A33` is tetanus in Annexure II/III, but in WHO VA later it splits because neonatal tetanus becomes a separate neonatal code.
* `O00` belongs to maternal conditions in adult/WHO maternal logic, but not in neonatal/child annexure logic.

### C. MDS crosswalk review

We then examined the **India MDS → WHO-VA 2012 / GBD 2010** file.

Conclusion:

* it is **not an ICD-to-category mapping**
* it is a **category-to-category crosswalk**
* so it cannot directly map your ICD master file unless an earlier step already assigns each death into an MDS category. 

Important conclusion:

* **SRS Annexures I/II/III are more detailed and structurally different from MDS**
* so a direct collapse from Annexure labels into MDS is only **partially possible**, not cleanly one-to-one.

### D. CMEA10 mapping

We then examined **CMEA10**, and this was much more promising.

Conclusion:

* CMEA10 is an **ICD-10 → grouped cause** mapping
* so it is much more suitable than MDS as an intermediate codebook. 

Examples:

* `A00-A09` → **Diarrhoeal diseases**
* `B20-B24, C46, D84, R75` → **HIV/AIDS**
* `C50, D05, D24, N60, N62-N64` → **Breast cancer**
* `V20-V29` → **Road traffic accidents - (3)**
* `X60-X84` → **Self-inflicted injuries (suicide)** 

We created:

* ICD10 → CMEA10 mapped file
* overlap report for CMEA10

### E. CMEA10 overlap analysis

CMEA10 has **real internal overlaps**. These are source overlaps, not code bugs.

Important overlap examples:

* `C46` appears under both **HIV/AIDS** and **Other neoplasms (4)**
* `D84` appears under **HIV/AIDS** and also under endocrine/immune disorders
* `R75` appears under **HIV/AIDS** and also in endocrine/immune disorders
* `G45-G46` appear under both **Other neuropsychiatric disorders - nervous system** and **Cerebrovascular diseases**
* `G81-G83` appear under both **Cerebral palsy** and **Cerebrovascular diseases**
* `I11` appears under **Hypertensive heart diseases** and **Ischemic heart diseases**
* `I70` appears under **Ischemic heart diseases** and **Other cardiovascular diseases**
* `O43` appears under **Obstetric haemorrhage** and **Other maternal conditions (2)**
* `R00-R07`, `R09` appear under both **Circulatory and respiratory systems - Ill-defined** and **Other ill-defined and abnormal findings**. 

So for CMEA10 we used a deterministic precedence rule:

1. exact code beats range
2. narrower range beats broader range
3. if still tied, earlier source order wins

That gives reproducible results, but it is still a **policy decision**, not a unique truth.

## 3) What we found about WHO 2022 VA

WHO 2022 VA is different from the annexures and from CMEA10.

It is a direct **ICD-10 → WHO VA code** mapping, but:

* some rows are easy at 3-character level
* some rows require **4-character precision**
* some rows require **age/context**
* some rows have **internal overlaps or operational rules**. 

### Good 3-character examples

These can usually be mapped from 3-character codes:

* `A40-A41` → `VAs-01.01 Sepsis`
* `A00-A09` → `VAs-01.04 Diarrheal diseases`
* `B50-B54` → `VAs-01.05 Malaria`
* `B05` → `VAs-01.06 Measles`
* `G40-G41` → `VAs-08.01 Epilepsy`
* `N17-N19` → `VAs-07.01 Renal failure`
* `P36` → `VAs-10.04 Neonatal sepsis`
* `Q00-Q99` → `VAs-10.06 Congenital malformation`. 

### 4-character-dependent examples

These cannot be done correctly from only a 3-character master:

* `U07.1`, `U07.2` → `VAs-01.13 COVID-19`
* `I11.0` → `VAs-04.01 Acute cardiac disease`
* `I11.9-I15` → `VAs-04.99 Other and unspecified cardiac disease`
* `K70.2`, `K70.3`, `K71.7`, `K74` → `VAs-06.02 Liver cirrhosis`
* `O75.3` → `VAs-09.06 Pregnancy-related sepsis`
* `O99.0` → `VAs-09.07 Anaemia of pregnancy`
* `O71.0-O71.1` → ruptured uterus row. 

### Context-dependent examples

These are not resolvable from ICD code alone:

* `A33` appears in general tetanus but WHO VA explicitly excludes **neonatal tetanus** from the general tetanus row and maps neonatal tetanus separately to `VAs-10.05`. That means you need **age/neonatal context**. 
* `P95` is used for both **fresh stillbirth** and **macerated stillbirth**. ICD alone cannot separate these two WHO VA outcomes. 
* `VAs-12.01 Road traffic accident` vs `VAs-12.02 Other transport accident` depends on a long **decimal-level external-cause footnote list**, not just the 3-character `V` code. 

### Internal WHO VA overlaps / residuals

WHO VA also has source-level ambiguity:

* `X10-X19` is explicitly under **Accidental exposure to smoke, fire and flames** and also appears within the broader residual **VAs-12.99 Other and unspecified external cause of death**
* maternal decimal-specific codes sit beside broad maternal residual ranges
* the ruptured uterus row appears as `VAs-09.0` in parsed text, suggesting an OCR/display truncation; in sequence it is likely `VAs-09.08`, but this should be treated carefully. 

## 4) Main design conclusion

If your final target includes **WHO 2022 VA**, then the current 3-character base CSV should be **extended**, not replaced.

Recommended master structure:

* `disease_id`
* `icd10_3char`
* `icd10_full`
* `icd10_display`
* `source_category_original`
* `age_group`
* `neonatal_flag`
* `stillbirth_flag`
* `pregnancy_related_flag`
* `external_cause_detail`
* `mapping_note`
* `mapping_confidence`

Why:

* `icd10_3char` is still useful for Annexure and CMEA logic
* `icd10_full` is needed for WHO VA precision
* context fields are needed for neonatal, maternal, stillbirth, and transport logic. 

## 5) Recommended agentic code flow

Here is the cleanest pipeline.

### Step 1: Ingest source files

Inputs:

* base ICD CSV
* Annexure I/II/III source tables
* CMEA10 source table
* WHO 2022 VA source table

### Step 2: Normalize ICD values

For every row:

* uppercase code
* strip whitespace
* preserve original full code if present
* derive `icd10_3char` from full ICD
* store `icd10_full` separately

Example:

* `I11.0` → `icd10_3char = I11`, `icd10_full = I11.0`
* `U07.2` → `icd10_3char = U07`, `icd10_full = U07.2`

### Step 3: Build mapping tables as rule tables

Each mapping source should become a rule table with:

* `source_name`
* `priority_type` (`exact`, `range`, `decimal_exact`, `decimal_range`, `residual`, `contextual`)
* `icd_spec_raw`
* `expanded_match_logic`
* `target_code`
* `target_label`
* `required_context`
* `notes`

Example WHO rows:

* `VAs-01.13`, `Coronavirus disease (COVID-19)`, `U07.1; U07.2`, `priority_type = decimal_exact`
* `VAs-10.05`, `Neonatal tetanus`, `A33`, `required_context = neonatal`
* `VAs-11.01`, `Fresh stillbirth`, `P95`, `required_context = stillbirth subtype`

### Step 4: Apply deterministic precedence

Use this order:

1. decimal exact
2. exact 3-character
3. narrower decimal range
4. narrower 3-character range
5. broader range
6. residual bucket
7. unresolved / blank

Example:

* `C46` in CMEA:

  * exact HIV/AIDS wins over broad neoplasm range
* `G45` in CMEA:

  * narrower `G45-G46` cerebrovascular rule beats broader `G43-G47` nervous system rule
* `O43` in CMEA:

  * narrower `O42-O43` maternal rule beats broader `O43-O46` haemorrhage rule

### Step 5: Apply context overrides

After ICD matching, apply context-based overrides.

Examples:

* if code = `A33` and `neonatal_flag = true`, map to `VAs-10.05`, not general tetanus
* if code = `P95` and stillbirth subtype known, choose fresh vs macerated
* if external cause is transport and decimal code matches the road-traffic footnote set, assign `VAs-12.01`; else `VAs-12.02`
* if Annexure III and code = `R96`, use age rule exactly as source note states.

### Step 6: Emit ambiguity logs

Never silently collapse ambiguous rows.

Create:

* `chosen_mapping`
* `all_candidate_mappings`
* `ambiguity_flag`
* `ambiguity_reason`

Examples:

* `C46` → HIV/AIDS | Other neoplasms (4)
* `I11` → hypertensive heart disease | ischemic heart disease
* `X10-X19` → fire/flame | residual external cause
* `P95` → fresh stillbirth | macerated stillbirth

### Step 7: Export family-specific outputs

Recommended outputs:

* Annexure mapping workbook
* CMEA mapping workbook
* CMEA overlap workbook
* WHO VA workbook
* final integrated master workbook

## 6) Concrete “if this, then that” examples

### Example 1: `B20`

* Annexure II → HIV/AIDS
* Annexure III → HIV/AIDS
* CMEA10 → HIV/AIDS
* WHO VA → `VAs-01.03 HIV/AIDS related death`
  This is a stable code across systems.

### Example 2: `A33`

* Annexure II / III: tetanus
* CMEA10: tetanus
* WHO VA:

  * general tetanus in `VAs-01.08`
  * but neonatal tetanus is `VAs-10.05`
    So WHO VA needs age context.

### Example 3: `U07`

* base 3-character master only knows `U07`
* WHO VA needs `U07.1` or `U07.2` for COVID
  So `U07` alone is insufficient for precise WHO VA mapping. 

### Example 4: `I11`

* CMEA10 source overlaps between hypertensive heart disease and ischemic heart disease
* WHO VA splits `I11.0` into acute cardiac disease, but pushes `I11.9-I15` into other cardiac disease
  So full ICD precision and precedence both matter.

### Example 5: `P95`

* WHO VA uses it for both fresh stillbirth and macerated stillbirth
  So this is impossible to resolve from ICD alone; you need a separate stillbirth subtype field. 

## 7) Practical recommendation for the next coding sprint

If you are turning this into an agentic workflow, I would do it in this order:

1. **Extend the master CSV**

   * add `icd10_full`
   * add context columns

2. **Keep mapping tables separate**

   * `annexure_rules`
   * `cmea_rules`
   * `who_va_rules`

3. **Run mappings independently**

   * do not force one system to emulate another

4. **Use an ambiguity engine**

   * exact > narrow range > broad range > residual
   * then context override
   * then unresolved flag

5. **Preserve blank rows**

   * if a code is not explicitly covered, keep it blank
   * do not auto-invent a destination

## 8) Files already produced in this workstream

Artifacts created so far:

* [Annexure III adult mapped CSV](icd-10-CODES_annexureIII_adult_mapped.csv)
* [Annexure III adult mapped XLSX](icd-10-CODES_annexureIII_adult_mapped.xlsx)
* [Annexure I/II/III mapped CSV](icd-10-CODES_annexureI_II_III_mapped.csv)
* [Annexure I/II/III mapped XLSX](icd-10-CODES_annexureI_II_III_mapped.xlsx)
* [CMEA10 mapped CSV](icd-10-CODES_CMEA10_mapped.csv)
* [CMEA10 mapped XLSX](icd-10-CODES_CMEA10_mapped.xlsx)
* [CMEA10 overlap report CSV](icd-10-CODES_CMEA10_overlap_report.csv)
* [CMEA10 overlap report XLSX](icd-10-CODES_CMEA10_overlap_report.xlsx)
* [WHO 2022 VA crosswalk XLSX](WHO_2022_VA_Crosswalk.xlsx)
