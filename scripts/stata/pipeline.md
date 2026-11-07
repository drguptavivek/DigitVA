# DigitVA LDH manuscript: data pipeline

How the numbers in the Lancet Digital Health manuscript
(`docs/manuscript/DigitVA_LDH_Manuscript.docx`) are produced, from the
platform database to table 2. Data cut-off: 31 May 2026. Column definitions
are in `README.md`.

## Overview

```
DigitVA database (PostgreSQL, study projects UNSW01 and ICMR01)
   │  1. Extract and de-identify   digitva_ldh_export.sql, digitva_ldh_syncruns.sql
   ▼
data/digitva_ldh_cases.csv      one row per verbal autopsy (7917)
data/digitva_ldh_syncruns.csv   one row per ODK synchronisation run
   │  2. Analyse                    digitva_ldh_analysis.do (Stata 17+)
   ▼
output/digitva_ldh_analysis.log   every result, with the manuscript item it reproduces
output/digitva_ldh_tables.xlsx    Table 2 | Results text | Check
output/figure2_monthly.png, figure3_workload.png
   │  3. Check                      "Check" sheet and the CHECK line at the end of the log
   ▼
Manuscript table 2, Results text, appendix tables S4 and S6, figures 2 and 3
```

One command runs steps 1 to 3 (needs Docker with the database running, and
Stata):

```bash
scripts/stata/build_package.sh
```

It writes the package to `private/digitva-ldh-data/` (git-ignored).

## Step 1: extraction and de-identification

Source: the DigitVA database, projects UNSW01 (version 1, CDC Foundation
programme) and ICMR01 (version 2, ICMR programme). Interviews were collected in
ODK Collect and synchronised from ODK Central; DigitVA held them for coding.

Population and cut-off:

- every submission in the two projects submitted to ODK before 1 June 2026
  (965 in version 1, 6952 in version 2);
- a death counts as coded when it has an active final cause saved before
  1 June 2026;
- the interview answers come from the active payload version (the version a
  data manager accepted).

What the query derives from the interview and the platform record:

- intervals: death to interview (questionnaire dates Id10023 and Id10012),
  submission to final cause, and coding time (latest coding allocation to the
  saved final cause, training allocations excluded);
- narrative capture: written narrative length and class (empty or placeholder,
  pointer to a photograph, short statement, 100 characters or more),
  photographed and audio narratives, and medical document pages;
- coding: ill-defined final cause (ICD-10 R00–R99), flagged difficult to code,
  recoded, the step 1 (SmartVA masked) and step 2 causes compared by
  three-character ICD-10 code and by WHO 2022 verbal autopsy cause group and
  category (the `WHO_2022_VA` scheme with legacy aliases, as the platform's
  reports use), and agreement of each with SmartVA's most likely cause;
- data handling: later versions from ODK, ODK Central edits, changed answers,
  rejected versions, attachments, SmartVA availability and failures.

De-identification, done inside the query so identifiable data never leave the
database:

- no names, identifiers, record keys, narratives or other free text;
- dates: submission month only; the coding date is kept (it carries no
  personal information and is needed for figure 2 and throughput);
- age as a band (under 15, 15–69, 70 or older, unknown) and place of death as
  facility, home or other;
- coders and sites are numbers assigned by hashing (`coder` within a
  programme, `coder_all` across both, `site` within a programme), stable only
  within one extraction;
- rows are shuffled within each programme.

Synchronisation runs: month, trigger, status and whether the run falls in the
reporting window (31 March to 31 May 2026). Reporting-view refreshes are
counted apart from ODK synchronisation.

## Step 2: analysis

`digitva_ldh_analysis.do` runs from the package folder with relative paths
(`data/`, `output/`), so a co-author needs only the folder and Stata. It follows
the manuscript order; each section starts with a comment quoting the table 2
row or Results sentence it reproduces and the value printed in the manuscript.

Methods used:

- counts and percentages by version and in total;
- medians with interquartile ranges for intervals (among coded deaths;
  intervals outside 0–3650 days set to missing), coding time, deaths per
  coder-day and deaths per coder;
- the share of deaths coded by the top 10% of coders and the daily peak;
- change in agreement with SmartVA between step 1 and step 2: paired
  difference with its 95% CI and the McNemar test (`mcc`), for all two-step
  deaths and for deaths where SmartVA assigned a cause;
- medical documents and an ill-defined final cause: Mantel-Haenszel risk ratio
  stratified by programme, age band and place of death (`cs, by()`), with the
  crude ratio and a sensitivity analysis excluding placeholder narratives;
- appendix: the flow of submissions (table S4) and missing data (table S6);
- figure 2 (interviews submitted and deaths coded per month) and figure 3
  (deaths coded per coder, ranked).

## Step 3: check against the manuscript

Every table 2 cell and every number in the Results text and appendix tables S4
and S6 is typed into the do file as printed in the manuscript and compared
with the computed value. The "Check" sheet lists item, manuscript value,
computed value and match; the log ends with
`CHECK: <n> of <n> manuscript values reproduced` and lists any mismatch. On
6 November 2026 all 143 values matched.

Numbers that do not come from the data sheet, and their source:

| Manuscript number | Source |
|---|---|
| Hosting cost: US$416 from March 2025 to May 2026, mean US$28 a month (range 23–42), including tax | AWS monthly invoices (`aws invoicing list-invoice-summaries`) |
| Reasons coders flagged deaths ("insufficient information", language) | Free text in the database, not exported |
| No attachment refused or recorded with an error | Database attachment status |
| Most version 2 interviews loaded on 2 April 2026 | Database load timestamps (the sheet holds months only) |
| Development effort (commit days) | `git log` of the repository |

## Verification by a second author

To be named as having accessed and verified the data, a second author:

1. receives `private/digitva-ldh-data/` (data, do file, README, this file) by
   a secure route, not email to outsiders or a public folder;
2. runs `digitva_ldh_analysis.do` in Stata from that folder and confirms the
   log ends with all values reproduced;
3. checks a few counts against ODK Central (for example the number of
   submissions per programme before 1 June 2026) and, where they have
   database access, reruns `scripts/stata/build_package.sh`.

## Rerunning before submission

The data sheet is rebuilt from the live database, so rerun
`scripts/stata/build_package.sh` before submission and after any change to
the study projects. If a value no longer matches, correct it in the
manuscript on Google Drive and the expected value in the do file together.
Since 7 November 2026 the manuscript and appendix are edited on Drive only:
`scripts/manuscript-drive.sh pull` fetches them into `private/manuscript-drive/`
(the `docs/manuscript` files are symlinks to that copy), and `push` uploads an
edit to the same Drive files, refusing if Drive changed since the pull. The
builder `scripts/build_digitva_ldh_manuscript.py` is retired.
