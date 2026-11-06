# DigitVA LDH manuscript: data sheet and analysis

Reproduces every number in table 2 and the Results text of the Lancet Digital
Health manuscript (`docs/manuscript/DigitVA_LDH_Manuscript.docx`), plus the
appendix flow, missing-data and sensitivity numbers, figures 2 and 3. Each
output in the do file is commented with the manuscript item it produces.
Data cut-off: 31 May 2026.

## Package folder

`scripts/stata/build_package.sh` builds `private/digitva-ldh-data/` (git-ignored;
research data is never committed). A co-author needs only that folder:

| File | What it is |
|---|---|
| `data/digitva_ldh_cases.csv` | Data sheet: one row per verbal autopsy (7917 rows) |
| `data/digitva_ldh_syncruns.csv` | One row per ODK synchronisation run |
| `digitva_ldh_analysis.do` | Stata 17 analysis (paths relative to this folder) |
| `README.md` | This file |
| `output/` | `digitva_ldh_analysis.log`, `digitva_ldh_tables.xlsx` (sheets Table 2, Results text, Check), `figure2_monthly.png`, `figure3_workload.png` |

Sources in git: `scripts/stata/digitva_ldh_export.sql`,
`digitva_ldh_syncruns.sql`, `digitva_ldh_analysis.do`, `build_package.sh`.

The data sheet is de-identified: no names, identifiers, record keys,
narratives or free text, no dates finer than the submission month except the
coding date; coders and sites are pseudonymous numbers. Share it only with
study authors, and keep it out of git, email attachments to outsiders and
public folders.

## Steps

1. Build and run everything (needs the dev database holding the study dataset,
   Docker and Stata; from anywhere in the repository):

   ```bash
   scripts/stata/build_package.sh
   ```

   It extracts both CSV files, copies the do file and this README into the
   package folder, and runs Stata in batch from there.

2. Co-author, from the package folder only (Stata 17 or later):

   ```bash
   /Applications/Stata/StataSE.app/Contents/MacOS/stata-se -b do digitva_ldh_analysis.do
   ```

3. Verify: open `output/digitva_ldh_tables.xlsx`. "Check" compares every
   table 2 cell and Results-text value with the manuscript; mismatches are
   also listed at the end of the log. A second author who reruns the steps and
   checks key counts against ODK Central can be named as having accessed and
   verified the data.

Not reproducible from the data sheet (stated in the do file header): server
cost; free-text flag reasons; attachment error status; the April 2 batch-load
date (submission month only is exported); commit counts.

Rows are shuffled within each programme, so row order carries no
information; coder and site numbers are stable only within one extraction.

## Codebook: `digitva_ldh_cases.csv`

Population: every submission in projects UNSW01 (version 1) and ICMR01
(version 2) submitted before 1 June 2026. "Final cause" is the active final
assessment saved before 1 June 2026. Binary variables are 1 = yes, 0 = no;
empty means not applicable or not computable.

| Variable | Description |
|---|---|
| `version` | 1 = version 1 (UNSW01 programme), 2 = version 2 (ICMR01 programme) |
| `coded` | Has an active final cause |
| `sub_month` | Month the interview was submitted to ODK (YYYY-MM) |
| `coded_date` | Date the final cause was saved (YYYY-MM-DD); empty if not coded |
| `site` | Site number within the programme (pseudonymous) |
| `coder` | Pseudonymous coder number within the programme; 0 if not coded |
| `coder_all` | Pseudonymous coder number across both programmes (same physician, same number); 0 if not coded |
| `death_to_interview_d` | Days from date of death (Id10023) to interview date (Id10012) |
| `sub_to_final_d` | Days from ODK submission to the saved final cause |
| `coding_min` | Minutes from the latest coding allocation (training excluded) to the saved final cause |
| `lang` | Narration language; `unknown` if not recorded |
| `ageband` | Age at death: 0 unknown, 1 under 15 years, 2 15–69 years, 3 70 years or older |
| `place` | Place of death (Id10058): 1 health facility, 2 home, 3 other or unknown |
| `narr_chars` | Characters in the written narrative (Id10476) |
| `narr_class` | Written narrative: 0 empty or placeholder, 1 pointer to an uploaded photograph, 2 short statement under 100 characters, 3 narrative of 100 characters or more |
| `narr_image` | A photograph of the written narrative is attached |
| `narr_audio` | An audio-recorded narrative is attached |
| `doc_pages` | Number of medical document photographs (md_im1–md_im30) |
| `ill_defined` | Final cause is ICD-10 chapter XVIII (R00–R99) |
| `flagged` | A coder flagged the case as difficult to code |
| `recoded` | The final cause was replaced at least once (excluding demonstration and tester records) |
| `recoded_code_chg` | Of recoded deaths: the three-character ICD-10 code differs from at least one replaced assessment |
| `sv_failed_any` | SmartVA failed at least once on this death (any later rerun may have succeeded) |
| `payload_versions` | Number of interview data versions received from ODK |
| `rejected_versions` | Number of those versions a data manager rejected |
| `attachments` | Number of attachment files stored |
| `odk_edited` | The second version came from an ODK Central edit (new instanceID) |
| `answer_changes` | Number of questionnaire fields that differ between the first and second versions |
| `two_step` | Coded with a recorded step 1 (SmartVA masked) cause |
| `s12_code_chg` | Underlying cause changed between step 1 and step 2 (three-character ICD-10) |
| `s12_bucket_chg` | Changed WHO 2022 verbal autopsy cause group between steps |
| `s12_cat_chg` | Changed WHO 2022 verbal autopsy cause category between steps |
| `s1_sv_agree` | Step 1 cause group equals SmartVA's most likely cause group |
| `s2_sv_agree` | Step 2 (final) cause group equals SmartVA's most likely cause group |
| `sv_available` | A successful SmartVA result exists |
| `sv_undetermined` | SmartVA's most likely cause is ill-defined (ICD-10 R codes) |

Cause groups use the `WHO_2022_VA` scheme, three-character ICD-10 codes with
legacy reporting aliases applied, as the platform's reporting does.
Intervals outside 0–3650 days are set to missing in the do file.

## Codebook: `digitva_ldh_syncruns.csv`

| Variable | Description |
|---|---|
| `run_month` | Month the run started (YYYY-MM) |
| `triggered_by` | What started the run (scheduled or manual) |
| `in_window` | 1 if the run started on or after 31 March 2026 (the manuscript's window) |
| `status` | Run outcome (success, partial, error and so on) |
