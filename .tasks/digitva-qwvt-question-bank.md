# digitva-qwvt: question bank (owner review)

These are questions that users ask, grouped by who asks them. Each question is
tagged with the data it needs. Answers are comparative where that makes sense:
against peers, the previous period, or the same month last year.

**Data tags**
- **A**: answerable now from `ai_cube`, the case counts. The 51 catalog
  questions are all A.
- **B**: needs language and org-unit (sub-centre, block, district) columns
  added to `ai_cube`.
- **C**: needs `ai_staff`, staff counts per unit and role, with no names.
- **D**: needs a named per-person table, visible to data managers and
  admins in their scope and never to the model.
- **E**: the data is not recorded yet, or its source needs checking.

## Data manager: intake and pipeline

| Question | Data |
|---|---|
| Which sites or sub-centres sent fewer cases this month than their 3-month average? | A (sites), B (sub-centres) |
| Which sub-centres have sent no cases for 30 days? | B |
| How long do cases wait between submission and ready-for-coding, by site? | E (state-change timestamps; check `va_submission_workflow_events`) |
| Where are cases stuck in attachment sync, and for how long? | A (count), E (age) |
| Which sites have the most consent refusals, compared with the project rate? | A |
| What share of interviews is telephonic versus in person, by site? | E (consent mode is not in the cube) |
| Which sites have the most cases not codeable by data managers, and why? | A (count), E (reason) |
| Which sites have the most ODK sync problems or missing-in-ODK cases? | E (core MV has `has_sync_issue` and `odk_missing`; not in the cube) |
| Where is narrative quality falling, month on month? | A |
| Which sites have sex or age missing most often? | A |
| How many duplicates were confirmed, per site? | E (excluded from the cube by design) |

## Data manager: coding throughput and backlog

| Question | Data |
|---|---|
| In which languages is coding held back? Backlog per narration language. | B |
| Backlog in a language against the coders who code in it | B + C |
| How old is the coding backlog, by intake month? | A |
| Which units have backlog but no active coder? | B + C |
| How many cases were finalised this week compared with last week? | E (needs final-save date; the cube has submission month only) |
| How many cases reached the recode window, and how many were recoded? | E (`va_coding_episodes`, 78 recodes on dev) |
| What is the reviewer queue per site against the reviewers available? | A + C |
| How many allocations timed out or were released, per site? | E (allocation status history) |

## Coder speed and quality (owner question 2026-10-27)

| Question | Data |
|---|---|
| Who spends too little time on coding? Median minutes from allocation to final save, and share under 3 minutes. | D (elapsed time, not active time) |
| Which coders finalise the most cases per week, against the project median? | D |
| Which coders have the highest share of unknown or ill-defined causes? | D |
| Which coders disagree most with SmartVA, against peers? | D |
| Which coders' finals are most often changed by a reviewer? | D |
| Which coders mark the most cases not codeable? | D |
| Which coders appear to copy SmartVA? Share of finals whose WHO VA cause (or exact ICD) equals SmartVA's top cause, against peers. Strongest signal: high agreement even when SmartVA's likelihood is low, together with fast finals. | D (snapshot MV has `coder_final_icd`, `smartva_cause1_icd`, buckets and likelihoods) |
| Which coders get the most DORIS flags? Rejections, warnings, plausibility (age/sex) confirmations, and "causing condition not known" use, against peers. | D, E (DORIS results are stored in `doris_result` on Step 1 and final assessments, 38 of 8,590 finals on dev, ICD-11 DORIS projects only; age confirmations in `icd11_provenance`) |
| Do coders who override DORIS's underlying cause do so more often than peers? | D, E (compare the saved final with `doris_result`) |
| Unknown-cause share per coder in neonatal cases | D |

## Interviewers and field

| Question | Data |
|---|---|
| Which sub-centres have no interviewer, or no coder? | B + C |
| Which sub-centres have a coder but no interviewer? | B + C |
| Which interviewers produce the most poor-quality narratives? | D (needs interviewer on the case; check source) |
| Interviews per interviewer per month, against peers | D, E |
| Consent refusal rate per interviewer | D, E |

## Users, training and onboarding

| Question | Data |
|---|---|
| Which users were granted a role but have never signed in? | C (count), D (who) |
| Which grants have been dormant for 30 days? | C, D |
| Who has an unverified email? | C, D |
| Which units have staff who have not finished training? | C, E (training completion source: `mas_training`) |
| Training cases coded per participant, and agreement with the reference answer | D, E |
| Which coders lack a coding language, or whose languages don't match their unit's narrations? | B + C/D, E (coder language source) |

## Site PI and project PI

| Question | Data |
|---|---|
| Project progress: share of cases with a final cause, by site, against target | A (target: E) |
| Which sites lag most on coding completeness? | A |
| Cause mix per site against the project mix | A |
| Narrative-quality trend per site | A |

## State programme office

| Question | Data |
|---|---|
| Top causes by district, against the state | B |
| Maternal deaths by district and month | B |
| Neonatal and child deaths by district against the state rate | B |
| Injury and suicide deaths by district, sex and age | B |
| Districts with the highest unknown-cause share | B |
| Coverage: VA cases per district, and districts with no data | B |
| Where are fewer deaths reported than in comparable units? Deaths per sub-centre or district against the block or district median, and against the unit's own last 3 months. | B |
| Where are fewer deaths reported than expected? Deaths per 1,000 population against an expected crude death rate (for example the SRS state rate). | B, E (no population or catchment figure is stored on org units) |
| Under-reporting by group: units reporting few neonatal, female or maternal deaths compared with peers | B |
| Seasonal pattern of infectious deaths | A |
| SmartVA versus physician agreement by district | B |
| Workforce coverage: districts without coders or interviewers | B + C |

## Notes
- **Who uses this:** data managers and admins only (policy). Coder self-view
  ("my backlog", "my speed") is not in scope; it would need its own policy.
- **D-tagged questions:** they wait on the owner's decision about named staff
  results.
- **E-tagged questions:** check each source before promising it.
