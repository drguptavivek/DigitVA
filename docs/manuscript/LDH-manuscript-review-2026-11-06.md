---
title: Critical review of the DigitVA manuscript for The Lancet Digital Health
doc_type: review
status: draft
owner: Vivek Gupta
last_updated: 2026-11-06
---

# Critical review: DigitVA manuscript for The Lancet Digital Health

Reviewed: `docs/manuscript/DigitVA_NPJ_Digital_Medicine_Manuscript.docx`
(3,526 words, counts dated 22 September 2026, headed "Draft for npj Digital
Medicine"). The data checks were run against the dev database on 6 November 2026.
The SQL is kept outside the repository and can be rerun before submission.

## 1. Bottom line

The draft is a sound system description. It is not yet an LDH Article, for three reasons.

1. **It is written to npj's format, not LDH's.** It has no semistructured Summary, no
   Research in context panel, no Funding paragraph and no reporting guideline. Drafting
   notes are left in the text: "Draft for npj", the Zotero remarks, and the author
   checklist.
2. **It describes v3 as it stood in September, so much of it is already out of date.**
   ICD-11 with DORIS, passkeys, the organisation model, web intake and the two Collect
   apps are all built now, but the draft lists them as "future work". Meanwhile about a
   quarter of the text goes on speculative sections: LLMs, extra VA forms, and the
   real-time health system.
3. **Its only evidence of use is a count of coded deaths.** The dev database holds much
   more. It has timeliness, throughput, coder workload, not-codeable and recode rates,
   SmartVA–physician agreement, the proportion of ill-defined causes, language coverage
   and a cause-of-death profile. These are the real-world utility indicators that
   readers and reviewers will look for (section 5).

Recommended framing: **an Article that presents the DigitVA v3 platform, with a
retrospective observational evaluation of routine use in two Indian programmes (v1 and
v2).** The lessons from that use explain each v3 design choice. The closest LDH
templates are listed in section 2.3.

## 2. Fit to LDH requirements

### 2.1 What the guidelines require

thelancet.com blocks automated access with a bot check, so I could not read the
LDH-specific author page. The points below come from the Lancet family "Information
for Authors" and from published LDH Articles. **Confirm them on the live LDH page
before formatting.**

| Requirement | LDH / Lancet family | Current draft | Action |
|---|---|---|---|
| Article length | ≤3,500 words of text (trials 4,500) | ~2,900 words of text | Fits; reallocate words from the speculative sections to evaluation |
| Summary | ≤300 words, semistructured: Background, Methods, Findings, Interpretation, Funding | npj abstract: Results, Conclusions, no Funding | Rewrite (draft in section 7) |
| Research in context panel | Mandatory for research papers. Three headings (Evidence before this study, Added value of this study, Implications of all the available evidence). Must report the literature search: databases, exact dates, terms, no language limit. No references inside the panel | Absent | Run and document a search (draft in section 8) |
| References | ≤30 | 10, plus Benara pending | Add about 15 (CRVS, MCCD/SRS coverage, ICD-11, DORIS, SmartVA/Tariff, iCHECK-DH, comparators) |
| Reporting guideline | Name one and upload the checklist | None | **iCHECK-DH** (digital health implementations) is the best fit. Add STROBE items for the observational data |
| Data sharing statement | Required; "undecided" or "on request" without criteria is not accepted | "can be supplied … subject to project governance approval" | State what, when, where and under which access criteria (section 6, point 12) |
| Funding, role of funder, contributors, declaration of interests | Required | Placeholders | Complete |
| Article type | Articles, Health Policy, Viewpoint, Review, Comment | Unstated | Article (see 2.2). Send a pre-submission enquiry |

### 2.2 Article type

- **Article.** This is the right type if the paper reports pre-specified use indicators
  with denominators and dates. The dev data support that (section 5).
- **Health Policy.** This fits only if the paper turns into an argument for building
  VA into district CRVS. It would be weaker for presenting the platform.
- **Viewpoint.** This would lose the data.

A two-paragraph pre-submission enquiry to the LDH editors is worthwhile. Ask whether a
platform paper with retrospective use data from 7,917 deaths is in scope as an
Article.

### 2.3 LDH papers to model on (all verified in Europe PMC)

| Paper | Why it is a useful model |
|---|---|
| Titov N, et al. User characteristics and outcomes from a national digital mental health service (MindSpot). *Lancet Digit Health* 2020. doi:10.1016/S2589-7500(20)30224-7 | **Closest template.** It presents a routine national digital service through 7 years of observational use data: registrations, completion (96,018 of 121,652, 78.9%), user characteristics and outcomes. Its framing is "data are scarce on outcomes in routine care" |
| Simpson CR, et al. Temporal trends … using a national real-time patient-level data platform (EAVE II). *Lancet Digit Health* 2021. doi:10.1016/S2589-7500(21)00105-9 | Presents a surveillance platform, then shows what it can produce. This parallels the DigitVA cause-of-death profile |
| Clarke J, et al. Enrolment into a national COVID-19 pulse oximetry remote monitoring programme. *Lancet Digit Health* 2023. doi:10.1016/S2589-7500(23)00001-8 | A retrospective observational study of programme uptake and equity. It is a model for reporting coverage and equity |
| Venkateswaran M, et al. eRegQual, Palestine. *Lancet Digit Health* 2022. doi:10.1016/S2589-7500(21)00269-7 | An open-source (DHIS2 Tracker) national registry. It shows how LDH handles platform governance and data sharing under ministry ownership |
| Rono H, et al. Peek, Kenya. *Lancet Digit Health* 2021. doi:10.1016/S2589-7500(21)00083-2 | A programme-facing mHealth system in a low-income setting. It reports service use per 10,000 population |
| Mackey TK, et al. Development of a blockchain-based platform for Indigenous data sovereignty. *Lancet Digit Health* 2026. doi:10.1016/j.landig.2026.101070 | Evidence that LDH publishes platform-development Articles in 2026 |

What these have in common: each one names a **service problem**, states a **question
about routine use**, and answers it with **indicators that have denominators**. None
of them devotes space to a list of features.

## 3. Errors to correct

| # | Location | Problem | Fix |
|---|---|---|---|
| 1 | Table 1, Total row | "82" distinct final-assessment users is 24 + 58 added together. Three physicians coded in both projects. | **79** distinct physicians |
| 2 | Ref 1 | First author is Nichols EK, not Riley I (Zotero `SJLJFQEM`) | Correct |
| 3 | Ref 2 | First author is Serina P, not Lozano R (Zotero `M34P3RLJ`) | Correct |
| 4 | Ref 3 | First author is Flaxman AD, not Remolador H (Zotero `2CMAM96L`) | Correct |
| 5 | Ref 5 | MINErVA paper first author is Krishnan A, not Gupta V (Zotero `XX42INSZ`) | Correct |
| 6 | Ref 4 | openVA: R Journal volume 14 (2022), but the DOI is RJ-2023-020 | Use the year the journal prints |
| 7 | Benara et al. | Cited in the Discussion but not in Zotero or the reference list | Import it and insert as a live Zotero citation |
| 8 | Software scope; Security | ICD-11, DORIS mortality rules, passkeys, organisation model and web intake are called "proposed/planned". All are built. The draft also says TOTP is planned, but current policy (`docs/policy/authentication-factors.md`) says there is no TOTP | Rewrite to the current state (section 4) |
| 9 | Methods, "Evidence sources" | "project handoff", "author's Zotero library" and "codebase" are drafting notes, not a method | Replace with a documented literature search, a system-documentation review and the database extraction with a cut-off date |
| 10 | Limitations | "the Zotero library supplied metadata and abstracts … full-text verification should be completed" | Delete; do the verification |
| 11 | Title page | "Draft for npj Digital Medicine" | Remove |
| 12 | Ethics | "does not report individual-level clinical data". The analysis uses individual death records, even though it reports only aggregates | State the IEC approvals for UNSW and ICMR, or a waiver for secondary analysis of programme data |
| 13 | Throughout | "Phase 1 / Phase 2", "UNSW project", "MINErVA" and "v3" are used without one naming scheme. You describe the platform as v1, v2 and v3 | Define once: v1 = UNSW deployment (batch), v2 = ICMR deployment (service), v3 = current platform. Keep MINErVA as prior work in the Introduction only |
| 14 | Discussion | "feasibility at a scale exceeding 5,000 coded records" | An arbitrary threshold. State the numbers and the period |
| 15 | Introduction | "taken up by the Sample Registration System … remains in operation" | Needs a citation or an official source |
| 16 | Results | "Before August 2026" | Unclear: v2 coding ended in May 2026. Use dated version milestones |

## 4. What v3 is now (the draft describes September)

Main points, with the proving documents:

- **Collection.**
  - Three routes:
    - ODK Central sync.
    - Browser interview of the WHO 2022 instrument (`docs/policy/web-intake.md`).
    - DigitVA Collect, the Android app (`docs/current-state/expo-client.md`).
  - Offline drafts and queued submissions are kept in an encrypted local store. The
    local copy is deleted only after the server receipt matches.
  - The interface is in English and Hindi.
- **Coding.**
  - The same coding workspace runs on the web, in Collect online, and in Collect Plus
    online and offline.
  - Coding supports both ICD-10 and ICD-11 MMS, including postcoordination.
  - WHO DORIS mortality rules and CoDEdit select the underlying cause
    (`docs/current-state/doris-cod-workflow.md`).
  - SmartVA runs on the server and on the phone. On-phone parity was checked on 8,399
    cases (`docs/current-state/smartva-analysis.md`).
  - Narrative quality assessment and Social Autopsy are available as project options.
- **Health-system organisation.**
  - A seven-level hierarchy runs from State to facility
    (`docs/current-state/health-system-organization-model.md`).
  - Mentoring institutes support the districts.
  - Interviewers, supervisors and death reporters hold roles within the units.
  - PII is controlled in three tiers and is now decided per project
    (`docs/policy/access-control-model.md`).
- **Monitoring.**
  - Statistics dashboards cover deaths, interviews and codings.
  - A death is flagged overdue at 60 days from death, and an interview at 15 days.
- **Security and quality.**
  - Passkeys (WebAuthn) are available for every role.
  - Five external security audit rounds have been run.
  - The backend test suite has 7,286 automated tests, and the mobile suite has about 3,300.
- **Status to state honestly.**
  - Collect Plus offline coding is prerelease.
  - No real-project death has yet been coded in ICD-11.

The paper should present this platform. The v1 and v2 data then show why it was built
this way.

## 5. Real-world utility: what the dev data can show

Population: UNSW01 (v1) and ICMR01 (v2) only. Test, training and demo projects are
excluded: KEM001, TRN01, TELE01, DEMO01 and others.

The September counts reproduce exactly:

| Project | Submissions | Coded | Coverage |
|---|---|---|---|
| UNSW01 | 965 | 949 | 98.3% |
| ICMR01 | 6,952 | 6,928 | 99.7% |

### 5.1 Indicators that can go in the paper

| Domain | Indicator | v1 UNSW01 | v2 ICMR01 | Comment |
|---|---|---|---|---|
| Reach | Sites; interview languages | 4; 6 (Hindi, English, Malayalam, Kannada, Marathi, Bangla) | 7; 5 (Hindi, Tamil, Odia, Khasi, English) | 9 languages in total. Shows multilingual routine use |
| Reach | Physician coders (distinct) | 24 | 58 | 79 across both |
| Completeness | Coded / submitted | 949 / 965 (98.3%) | 6,928 / 6,952 (99.7%) | |
| Completeness | Attachments managed | 1,648 files | 15,103 files | 16,751 files, none refused or errored |
| Timeliness | Death → interview, median days (IQR) | 114 (54–178) | 208 (126–300) | **Main service gap.** It explains why v3 adds the death register and overdue flags |
| Timeliness | Submission → final cause, median days (IQR) | 60 (34–114) | 99 (72–133) | Includes an import backlog (see caveats) |
| Throughput | Peak coding rate | ~270–590 per month | 370–420 deaths per day, 16–28 Apr 2026 | 5,915 deaths coded in April 2026. Shows backlog clearance at scale |
| Efficiency | Case handling time, allocation → final, median minutes (IQR) | 5.1 (3.0–8.3) | 2.5 (1.6–4.3) | **Will draw questions.** Explain what the coder sees before allocation, or report it with care |
| Workload | Deaths per coder, median (IQR); max | 30.5 (28–54); 84 | 57.5 (11–143); 863 | Top 10% of coders coded 26% (v1) and 44% (v2) |
| Quality | Flagged "cannot code" by a coder | 17 (1.8%) | 51 (0.7%) | Reasons: no information, narration language, narrative mismatch. Only 3 deaths stayed not-codeable |
| Quality | Recoded after final | 33 (3.5%) | 52 (0.75%) | |
| Quality | Ill-defined causes (ICD-10 R chapter) | 14.2% | 20.3% | R99 9.7% and R54 6.7% overall. A standard CRVS quality indicator to compare with SRS/MCCD |
| Decision support | SmartVA available for coded deaths | 949/949 | 6,928/6,928 | 100% |
| Decision support | SmartVA–physician agreement, cause category | 67.9%* | 73.3%* | *Excluding "unknown" on either side; 58.5% when included (n=7,872). Raw agreement, not validity. Add kappa |
| Data integrity | Submissions with more than one payload version | 964 (44 rejected) | 107 | Coded records were protected from silent overwrite |
| Output | Cause profile by age and sex | — | — | Examples: liver cirrhosis 14.5% of male deaths at 15–49 years; acute cardiac disease 16–17% at 50–69 years; "unknown" 37% of female deaths at 70+ years |

### 5.2 Caveats (they must appear in the Methods or Limitations)

- **Arrival dates are not sync latency.** 6,836 of the 6,952 ICMR01 records arrived in
  DigitVA on one day, 2 April 2026, in a backfill. Report "submission → final cause"
  as programme timeliness, not as platform latency.
- **The workflow event log and sync logs start on 31 March 2026.** The 2025 UNSW
  workflow cannot be rebuilt from events.
- **The 949 "upstream change" decisions on UNSW01 were one administrative batch on 1
  April 2026.** They are not organic ODK edits, so do not cite them as data drift.
- **Reviewer use is too thin to report.** There are 5 reviewer final assessments.
- **Agreement is SmartVA against the physician, not against a reference standard.**
- **Handling times of 2–5 minutes need an explanation before reviewers see them.**
  Either show that review starts before allocation, or present them as a limitation of
  the timestamps.

### 5.3 What the dev data cannot show, and is worth adding

In order of effort:

1. **Coder usability survey.** Send the System Usability Scale plus 5 open questions to
   the 79 coders. It is cheap and directly addresses "utility".
2. **Inter-physician agreement.** Double-code a random 5% sample (~390 deaths) through
   the existing reviewer pathway. This gives a reliability estimate the paper currently
   lacks.
3. **Running cost.** Report server cost per month and per coded death (7,877 deaths
   over the period).
4. **Uptime and failed-task recovery.** The sync-run table since March 2026 can give
   this, but analytics refresh errors (1,381 unique-key collisions) must be separated
   from ODK sync errors.
5. **Early v3 field use from staging.** Collect app interviews, offline coding sessions,
   the KEM001 pilot (179 submissions to October 2026). Even small numbers show that the
   v3 pathway runs end to end. Pull these as aggregates, read-only.

## 6. Structure proposal (≤3,500 words)

| Section | Content | Words |
|---|---|---|
| Introduction | Burden: share of deaths in India without a medical certificate. Gap: VA data reach planners late and in pieces. Prior systems (openVA, VMan3, Unified Mobile App, MINErVA). Objective in one sentence | 450 |
| Methods | Setting (two programmes, 11 sites, dates). Platform development: three versions, open source, test suite, security audits. Data extraction with cut-off date. Indicator definitions (Table 1 footnotes). Analysis. Ethics. iCHECK-DH | 700 |
| Results 1: the platform | Pathway figure: death → interview → sync/offline → SmartVA → coding (ICD-10/11, DORIS) → review → dashboards. Three-tier access. Short module table | 600 |
| Results 2: routine use in v1 and v2 | Table 1 indicators. Throughput figure. Workload figure. Staging v3 field data, uptime, cost, usability | 700 |
| Results 3: lessons → v3 design | Table 2 (below) | 300 |
| Discussion | Main findings. Comparison with VMan3, openVA, Unified Mobile App and MINErVA. What it means for district CRVS. Limitations. Next evaluations | 750 |

**Cut:** the LLM section (one sentence in the Discussion is enough), "Additional
verbal autopsy forms", and the long real-time paragraph.

**Table 2 draft: lessons from v1 and v2 and the v3 response.** The evidence column
comes from the data. Confirm each lesson against your own experience before using it.

| Observation in v1/v2 | Evidence | v3 response |
|---|---|---|
| Interviews happen long after death | Median 193 days from death to interview | Death register, interviewer assignment by health unit, overdue flags at 60 days from death and 15 days from interview |
| Records reach coders in batches | 6,836 ICMR records loaded on one day; median 99 days from submission to coding | Incremental sync, phone collection with queued submissions, coding on the same device |
| Coders and families work in many languages | 9 interview languages; "narration language" among the reasons for not coding | Narration language recorded per case, Hindi interface, string review by native speakers |
| Many deaths end with an ill-defined cause, especially in the elderly | R codes 19.6%; "unknown" 37% at 70+ years in women | ICD-11 with DORIS rule-based underlying cause selection, narrative quality assessment |
| Field data change after coding | 964/965 UNSW records re-versioned, 44 rejected | Payload versions, protected final cause, explicit data-manager decision |
| Workload concentrates in a few coders | Top 10% coded 44% of ICMR deaths | Allocation timeouts, per-project recode window |
| Connectivity at district level is uncertain | (Programme experience: please supply) | Fully offline coding on the phone, with SmartVA and ICD-11 on the device |
| Programme staff need to see progress | (Programme experience: please supply) | Statistics dashboards by organisation unit, mentoring institutes |

**Figures (Lancet redraws them):**

1. The pathway and architecture.
2. Monthly submissions and coded deaths, v1 and v2, with version milestones.
3. Coder workload distribution (deaths per coder) for v1 and v2.

A screenshot panel of the coding workspace can go in the appendix.

## 7. Formulaic language

These counts come from the current text:

| Phrase | Count |
|---|---|
| "should" | 18, mostly in the future-work sections |
| "programme" | 20 |
| "rather than" | 7 |
| "fully open-source" | 3 |
| "real-time / near-real-time" | 12 |
| "mortality intelligence" | 2 |
| "salient" | 2 |

Patterns to remove:

- **Contrast formulas.**
  - "The principal operational problem is no longer only how to assign a cause."
  - "DigitVA does not introduce a new diagnostic algorithm. It presents…"
  - "This is more than a code-search change."
  - "rather than an assumption that…"
  - "rather than a replacement deployment"
- **Announcing importance instead of showing it.**
  - "The main contribution of DigitVA is…"
  - "demonstrates how verbal autopsy software can…"
  - "illustrate the wider need for…"
  - "A realistic near-real-time target is therefore…"
- **Buzzwords.**
  - "mortality intelligence": say "cause-of-death data for district planning".
  - "salient features".
  - "high-volume".
  - "living software system".
- **Repeated "should" lists.** The LLM and health-system paragraphs read as
  requirements specifications, not findings.

Example rewrites in your voice (burden → population → pathway gap → programme
implication):

> **Draft:** "Reliable cause-of-death information is a basic requirement for population
> health planning. However, many deaths occur outside facilities or without medical
> certification, leaving health programmes to plan services using incomplete or
> modelled mortality data."
>
> **Rewrite:** "In India, most deaths occur at home and only a minority receive a
> medical certificate of cause of death [cite MCCD report]. District health
> programmes, therefore, plan services without local cause-of-death data. Verbal
> autopsy can provide this information, but only if interviews are done soon after the
> death, coded by trained physicians, and returned to the district in a usable form."

> **Draft:** "The principal operational problem is no longer only how to assign a cause.
> Programmes must move interviews from field collection through completeness checks…"
>
> **Rewrite:** "Each verbal autopsy passes through several steps: notification of the
> death, interview, data transfer, physician coding, quality review and reporting.
> Delay or loss at any step reduces the coverage and timeliness of the final
> cause-of-death data. In many programmes these steps run on separate tools and
> spreadsheets, which makes it difficult to monitor where cases are held up."

> **Draft:** "The operational results show feasibility at a scale exceeding 5,000 coded
> records… These counts demonstrate use of the platform, not effectiveness."
>
> **Rewrite:** "Between March 2025 and May 2026, 79 physicians coded 7,877 of 7,917
> verbal autopsies (99.5%) across 11 sites and nine interview languages. These
> figures show routine use of the platform. They do not show diagnostic accuracy or an
> effect on mortality reporting, which need separate evaluation."

## 8. Draft Summary (LDH format, ~300 words; trim a few before submission)

> **Background** In India, most deaths occur at home without a medical certificate of
> cause of death. Verbal autopsy can fill this gap, but programmes often use separate
> tools for interviews, physician coding, review and reporting, which delays the return
> of cause-of-death data to districts. We describe DigitVA, an open-source verbal
> autopsy platform, and report its routine use in two Indian programmes.
>
> **Methods** DigitVA was developed in three versions between 2025 and 2026. We
> describe the current platform and analysed records from its use in two programmes:
> four sites from March to November 2025, and seven sites from June 2025 to May 2026.
> Indicators were defined in advance from the application database: coding coverage,
> intervals from death to interview and from submission to final cause, throughput,
> coder workload, not-codeable and recoding proportions, and data-integrity events.
>
> **Findings** 79 physicians coded 7,877 of 7,917 verbal autopsies (99.5%) collected
> in nine languages. The median interval from death to interview was 193 days (IQR
> 114–289), and from submission to final cause 96 days (68–132). In the second
> programme, a backlog of more than 5,900 deaths was coded within 1 month. The median
> time from opening a case to saving the final cause was 2.5 minutes (IQR 1.6–4.3) in
> the second programme and 5.1 minutes (3.0–8.3) in the first. Coders flagged 0.9%
> of cases as difficult to code and 1.1% were recoded. SmartVA output
> was available for every coded death, and 16,751 attachments were managed without
> loss. These findings led to the current version, which
> adds a death register, offline collection and coding on mobile phones, ICD-11 coding
> with WHO mortality rules, and district dashboards.
>
> **Interpretation** A single platform supported physician coding of verbal autopsies
> at programme scale. The main delay was between death and interview, not in coding.
> The current version needs prospective evaluation of timeliness, coding reliability
> and use of the data in district planning.
>
> **Funding** [ICMR; UNSW grant details].

Check before use:

- The 0.9% and 1.1% figures are pooled from the per-project counts: (17 + 51) / 7,917 and
  (33 + 52) / 7,877.
- The figures run to May 2026. Rerun the queries at the final cut-off date.

## 9. Research in context (outline)

- **Evidence before this study.** Search PubMed, Embase and Google Scholar from
  inception to [date]. No language limit. Terms: "verbal autopsy" AND (software OR
  platform OR "electronic" OR "mobile application" OR "information system"). Expected
  yield:
  - analysis toolkits (openVA, InterVA, SmartVA);
  - management systems (VMan3, Unified Mobile App);
  - India's SRS-linked MINErVA;
  - CRVS implementation reports (Philippines, Bangladesh, Papua New Guinea).

  The point to make: no published system combines collection, physician coding with
  ICD-11 mortality rules, offline use and programme monitoring, with routine-use data
  at this scale.
- **Added value of this study.** An open-source platform covering the whole pathway
  from death notification to district reporting. Routine-use indicators from 7,917
  deaths. Lessons from routine use, each traced to a design response.
- **Implications of all the available evidence.** VA programmes can measure where
  delays occur. In these programmes the delay was mostly before the interview, so
  death notification links to the health system matter more than coding speed.
  Prospective evaluation of the current version is needed.

## 10. Decisions (owner, 6 November 2026)

1. **Versions.** v1 = UNSW deployment (batch), v2 = ICMR deployment (service), v3 = current platform. MINErVA is prior work, cited in the Introduction only.
2. **Article type.** Lancet Digital Health Article, after a short pre-submission enquiry to the editors.
3. **Lessons table.** Keep the four data-backed lessons: delay from death to interview, batch arrival, languages, and field data changing after coding. Add four lessons from programme experience: connectivity → offline collection and coding; progress visibility → dashboards and overdue flags; health-system fit → organisation model, mentoring institutes and unit roles; coder workload → allocation timeouts and the recode window. The ill-defined-cause lesson is dropped.
4. **Extra platform data before submission.** Staging v3 field data (read-only aggregates), uptime and sync reliability, a coder usability survey (SUS and open questions), and running cost.
5. **Handling time.** Reported (owner, revised 6 November 2026). The median time from a coder opening a case to saving the final cause was 2.5 minutes (IQR 1.6–4.3) in v2 and 5.1 minutes (3.0–8.3) in v1. Report it alongside throughput per day and per coder. Define it in the Methods as the interval from case allocation to the saved final assessment. State in the Limitations that it measures time in the coding workspace only, not total review time or time spent outside the platform.
6. **Permissions.** Existing IEC approvals and programme agreements cover secondary use of the operational data. Cite them in Ethics.

**Scope rule.** SmartVA–physician agreement, ICD code distributions (including the ill-defined proportion) and cause-of-death tabulations belong to a separate manuscript. This paper reports platform and process data only. The relevant rows in section 5.1 and the cause-profile figure are therefore out of scope.

## 11. Later decisions and analyses (6 November 2026)

- **Data source and cut-off.** Dev database only, cut-off 31 May 2026. Staging is not used. All UNSW01 and ICMR01 submissions, payload versions and final assessments are before this date; the only later rows are 2 unused allocations.
- **Coding time.** Included (decision 5 reversed).
- **Narrative capture** (n = 7,917):

  | Capture | n | % |
  |---|---|---|
  | Written | 7,895 | 99.7 |
  | Written, ≥100 characters | 5,257 | 66.4 |
  | Photographed | 3,617 | 45.7 |
  | Audio | 443 | 5.6 |

  The median written narrative was 480 characters.
- **Medical documents.**
  - Documents were attached for 617 deaths (7.8%); 13.2% in v1 and 7.0% in v2. The median was 3 pages.
  - Deaths with documents had an ill-defined (R-chapter) final cause in 5.5% of cases, against 20.8% without documents. Mantel-Haenszel risk ratio, stratified by project, age band and place of death: 0.34 (95% CI 0.25–0.47).
  - Deaths with documents were more often facility deaths (38.0% vs 20.1%), so residual confounding is likely.
- **Sync reliability, 31 March to 31 May 2026.**
  - ODK sync: 976 of 1,008 runs (96.8%) succeeded, 15 were partial and 10 failed.
  - Analytics refreshes are counted separately: 1,383 of 1,386 succeeded.
- **Throughput.**

  | | Coded deaths per coder-day, median (IQR) | Peak per day |
  |---|---|---|
  | v1 | 7 (4–12) | 70 |
  | v2 | 15 (6–40) | 421 |

- **Not yet measured.**
  - Usability (System Usability Scale) and running cost: placeholders in the manuscript.
  - AWS cost needs `aws login --profile digitva`.
- **Manuscript.**
  - `docs/manuscript/DigitVA_LDH_Manuscript.docx`, built by `scripts/build_digitva_ldh_manuscript.py`.
  - References 1, 2, 6, 14 and 15 are not yet in Zotero.

### SmartVA masking and later owner decisions (6 November 2026)

- Usability survey (SUS) dropped. Running cost stays a placeholder.
- SmartVA was masked at Step 1 in both v1 (UNSW) and v2 (ICMR). In v3, masking is a project setting (`masked_cod_required`, `app/services/cod_entry_mode.py`).
- Step 1 vs Step 2, by WHO 2022 VA cause group (`WHO_2022_VA` scheme, 3-character ICD-10, legacy aliases):
  - Cause group changed: v1 179/944 (19·0%), v2 674/6914 (9·7%).
  - Direction of the 853 changes: 445 (52·2%) into agreement with SmartVA, 101 (11·8%) out of agreement, 307 (36·0%) between two other groups.
  - Agreement with SmartVA, Step 1 to Step 2 (McNemar): v1 37·5% to 44·2% (+6·7 points, 95% CI 4·5–8·9); v2 44·3% to 48·4% (+4·1, 3·5–4·7).
  - Stata section 2b; export columns `two_step`, `s12_*`, `s1_sv_agree`, `s2_sv_agree`, `sv_undetermined`.
- The v3 description now covers:
  - built-in AI: plain-language questions over aggregates only;
  - project configuration;
  - precomputed views and cause groups, for query speed;
  - personal data: per project, masked for other roles, encrypted registration numbers and phone store, retention set by project;
  - relationship-based access control.
- Code lists and cause groups (added after review): curated ICD-10 lists with sex and age-group filters (`docs/policy/icd10-reference-catalog.md` rule 12); ICD-11, where a sex mismatch is refused and an age mismatch warns (`docs/current-state/doris-cod-workflow.md`); WHO 2022 VA, SRS India and CMEA10 schemes; public pages `/help/cod-bucket-schemes` and `/help/va-code-mappings`, plus 13 public help pages.
- Collection, questionnaire and training (added after review): v1 and v2 used ODK only, and v3 adds its own web and Android collection, with ODK kept; DigitVA layers on the WHO 2022 base (`docs/policy/va-form-project-configuration.md`; register `docs/policy/digitva-who-form-overrides.md`); training project TRN01 (`docs/policy/training-demo-project.md`), weekly synthetic demo DEMO01 and the public demo site.
- Standalone mode (Collect Plus, epic `digitva-5bzf`): offline interview and coding without an account, encrypted backup, push to a project after enrolment.
- Equity layer (`docs/policy/digitva-who-form-overrides.md`, "Equity extension"): `residence_type`, `social_group`, `vulnerable_group`, `health_coverage` (DHS-aligned); optional, aggregate-only reporting; religion deliberately excluded.
- Translation: Azure machine drafts of missing questionnaire and UI strings, served only after an administrator accepts or edits them; district users suggest wording for admin or PI review (`instrument_translation_machine_job.py`, `instrument_translation_suggestion_service.py`).
- CI/CD: GitHub Actions rerun the mobile Jest tests and build signed Android APKs, the web export and server images from tags; server pytest runs locally before commit, not in CI, so the text does not claim CI server tests. Staging deploys via `scripts/deploy-staging.sh` after a verified DB backup.
- Main text adds (code checked): possible-duplicate check on the encrypted register (`register_duplicate_service.py`); send back for revision (`interview_send_back_service.py`); social autopsy three-delays analysis (`social_autopsy_analysis_service.py`); mobile-number sign-in and breached-password refusal (`docs/policy/mobile-sign-in.md`, `app/utils/password_policy.py`). Cuts: sync partial/failed counts, superseded-cause count, duplicate encrypted-store clause, photo-capture clause.
- Table 1 adds: signed, encrypted transfer files (server ingest `va_bundle_ingest.py`; the PHC desktop edition itself not verified as built), own-server phone performance counters, access audit page, public privacy and data-request pages. Stale-allocation timeouts left out: the policy dates from 2026-03-13, so it may also have applied to version 1 or 2.
- Not claimed because draft, deferred or unbuilt: iOS app, area dashboard, AI data-quality help, narrative AI, help chatbot (`digitva-wawz`).
- Reporting guidelines (checklist: `docs/manuscript/LDH-reporting-checklist.md`): new supplementary appendix `DigitVA_LDH_Appendix.docx` (built by `build_appendix()`): data source and selection, participant flow (40 uncoded = 20 without SmartVA + 20 flagged), indicator definitions, missing data, sensitivity analyses (v2 load-to-final 21 days, IQR 16–26, n=6813; crude RR 0·27; MH RR 0·35 without placeholder narratives), usability (none formal), governance, costs, literature search. Main text now cites RECORD and iCHECK-DH; running-cost sentence moved to the appendix.
- Correction: the text said all but three of 68 flagged deaths were later coded; the database shows 48 of 68 coded (with or without the cut-off). Text now says 48.
- Not claimed because not built: the planned Aadhaar last-3-digits reduction, the identifier erasure job, and narrative AI (still a draft policy).
- The deck comment calling the LLM gateway "speculative" is withdrawn: AI analytics is built.

## 12. Voice rules for the LDH draft

Sources: your own papers in Zotero (FV7JCET8, VKV79IJW, GE3KRXHJ, XX42INSZ, U7DZP5ZS, 9UVU3JA7) and three LDH Articles (PMC7571905, PMC8811715, PMC8239618).

1. **Sentences.** Put the subject and verb early. Long sentences are fine when qualifiers trail at the end.
2. **Introduction.** Open on burden or scale, then the service or measurement problem. Close with "We aimed to…".
3. **Discussion, first paragraph.** Say what was done and give the main finding with numbers. Hedge any first-of-its-kind claim with "To our knowledge".
4. **Numbers.** State the number first, with its denominator: "n of N (%)", "per 10 000", 95% CI in brackets. Use the midline decimal (·) and a space as the thousands separator from 10 000.
5. **Comparisons.** Compare with one earlier estimate at a time. Say whether the result is lower, similar or higher, and give one possible reason.
6. **Differences.** Explain them with a hedged list of plausible determinants.
7. **Modality.** State findings flatly ("We found…"). Hedge interpretation with may, suggests, indicates or likely. Never use "demonstrates" or "proves" for observational data.
8. **Limitations.** Use one plain paragraph that names each limitation, its consequence and any mitigation.
9. **Implications.** Keep them modest and programme-facing: "may be used for…", "needs to be…".
10. **Indicators.** Define each one (numerator, denominator, cut-off) before using it.
11. **Methods.** Use the past tense with "we". Give the design, setting, sample and dates.
12. **Platform description.** Describe components and workflow in operational terms, then the advantages and constraints observed.
13. **Summary Interpretation.** Use two sentences: the finding, then what it supports.
14. **Vocabulary.** Prefer programme, district, coverage, burden, health system, frontline workers. Avoid "etc."; keep abbreviations few.
15. **Ending.** End the Discussion with a short conclusion that restates the finding, its scope and its programme use.

**Avoid:** promotional verbs, contrast or slogan sentences, signposting openers, causal verbs stronger than the design allows, and interpretation not tied to a number or a citation.

## VA tool comparison (owner 2026-11-06)

- Appendix table S7 compares DigitVA with VMan3, the Indian unified mobile app, MINErVA (author overlap footnoted), SmartVA in the Philippines and Solomon Islands, and openVA; cells come from the evidence grid, quoted from each report.
- Discussion names VMan3 and the Indian app as closest. To stay at 3499 words, the unmasked-coding sentence was cut and the photographed-narrative reason shortened.
