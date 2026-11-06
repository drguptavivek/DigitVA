---
title: Reporting-guideline check of the DigitVA Lancet Digital Health manuscript
doc_type: review
status: draft
owner: engineering
last_updated: 2026-11-06
---

# Reporting-guideline check: DigitVA manuscript for The Lancet Digital Health

Manuscript checked: `scripts/build_digitva_ldh_manuscript.py` as built into
`docs/manuscript/DigitVA_LDH_Manuscript.docx` on 2026-11-06 (main text at 3498 of 3500
words). Analysis code: `scripts/stata/`. Status words: **reported**, **partly**
(partly reported), **missing**, **n/a** (not applicable, left out of the counts).
"Appendix" means the supplementary appendix or the uploaded checklist, so no main-text
words. A fix marked **MT** needs main-text words (swap against a cut).

## What was fetched

| Source | Result |
| --- | --- |
| RECORD checklist, `record-statement.org/Files/checklist/RECORD Checklist.pdf` | Fetched and read in full (STROBE items and all RECORD items). The equator-network.org page only links to it. |
| iCHECK-DH, JMIR 2023;25:e46694 (PMC10209789) | Article text fetched. The checklist itself is Multimedia Appendix 1, which was not available; the 20 items below are condensed from the paper's item descriptions, not verbatim. |
| mERA, BMJ 2016;352:i1174 | **Not fetched** (bmj.com returned 403; PMC showed a bot check). Only the 16 item names were obtained, from the JMIR mHealth 2016 companion paper (PMC5650671). Item descriptions are **from memory**. |
| Lancet Digital Health information for authors | **Not fetched** (thelancet.com returned 403). I did not retry around the block. Every LDH requirement below is **from memory / owner notes** and must be confirmed on the live page. |

## 1. RECORD (with STROBE)

| Item | Requirement (short) | Status | Where | Fix |
| --- | --- | --- | --- | --- |
| 1a | Study design in title or abstract | reported | Title; Summary | None. |
| 1b | Informative, balanced abstract | reported | Summary | None. |
| R1.1 | Data type, database named in title or abstract | partly | Summary Methods ("application database") | MT, zero net words: change "application database" to "routinely collected platform records (DigitVA database)". |
| R1.2 | Region and time frame in title or abstract | partly | Title (India); Summary (dates) | Fill the state names in Methods; the title and summary are fine. |
| R1.3 | Linkage stated in title or abstract | partly | Not stated | Appendix: "No linkage between databases was done; all indicators come from the DigitVA database." |
| 2 | Background and rationale | reported | Introduction | None. |
| 3 | Specific objectives, prespecified hypotheses | partly | Introduction last paragraph | Appendix: state which indicators were prespecified (Table 2 list) and that the documents versus ill-defined cause comparison was [prespecified or post hoc]; the do-file date can show which. |
| 4 | Key design elements early | reported | Methods, Study design | None. |
| 5 | Setting, locations, dates | partly | Methods, Study design | Replace "[states]" and add an appendix table of the 11 sites by state, programme and start and end of data collection. |
| 6a | Eligibility, sources, selection (cross-sectional) | partly | Methods, Indicators ("Test, training and demonstration projects were excluded") | Appendix: give the inclusion rule in one sentence (all verbal autopsies submitted to the 11 programme sites by the cut-off) and the project IDs excluded. |
| 6b | Matching | n/a | | |
| R6.1 | Codes or algorithms used to select the population | partly | Methods | Appendix: cite the selection clause of `digitva_ldh_export.sql` (project and site filter, test-project exclusion) and print it in the appendix. |
| R6.2 | Validation of selection algorithms | missing | | Appendix: either report a reconciliation of extracted counts against ODK Central submission counts and dashboard totals, or state "the extraction was not validated against an independent source" (and add to limitations). |
| R6.3 | Flow diagram if linkage | n/a | | See 13c; no linkage. |
| 7 | Define outcomes, exposures, confounders | reported | Methods, Indicators | None. |
| R7.1 | Complete list of codes and algorithms | partly | Methods ("ICD-10 chapter XVIII", "cause group mapping as in the platform") | Appendix: the ICD-10 to WHO 2022 cause-group mapping table (or DOI/link to the public mapping page at the cut-off) and the rule for "ill-defined". |
| 8 | Data sources and measurement for each variable | partly | Methods, Indicators | Appendix table: indicator, database field or timestamp, and any difference between versions 1 and 2 (for example batch import versus incremental sync, which affects submission-to-final-cause). |
| 9 | Efforts to address bias | partly | Statistical analysis (stratified RR); Discussion limitations | Appendix paragraph: selection (only deaths that reached the platform), measurement (timestamps, recalled death date, narrative classification by length) and the batch-load artefact in version 2. |
| 10 | How study size was arrived at | missing | | Appendix: "No sample size was calculated; all verbal autopsies in the database at the cut-off were included." |
| 11 | Handling of quantitative variables, groupings | reported | Statistical analysis (age groups, 0 to 3650 day rule, 100 characters) | Optionally give the reason for the 100-character and 3650-day thresholds in the appendix. |
| 12a | Statistical methods | reported | Statistical analysis | None. |
| 12b | Subgroups, interactions | reported | Version-wise columns; MH strata | None. |
| 12c | Missing data | partly | Statistical analysis (intervals only when both dates present) | Add n missing per interval to Table 2 footnote or the appendix descriptive table (see 14b). |
| 12d | Sampling-strategy analysis | n/a | | |
| 12e | Sensitivity analyses | missing | | Appendix: run and report (a) intervals excluding the April 2, 2026 batch, (b) the risk ratio excluding placeholder narratives, (c) agreement with SmartVA excluding undetermined SmartVA results; or state none were done. |
| R12.1 | Investigators' access to the database | partly | "Only aggregate statistics were extracted" | Appendix: "The study team develops and administers the database and had full access to record-level data; extraction was done by [name/role]." |
| R12.2 | Data cleaning methods | partly | Statistical analysis (interval rule) | Appendix: list every cleaning rule and how many records each affected (negative or over 3650-day intervals, test projects, duplicates). |
| R12.3 | Linkage methods and quality | missing | | Same sentence as R1.3. |
| 13a | Numbers at each stage | partly | Results (7917, 7877, 7875, 7858, 7897 scattered) | Appendix flow diagram (see 13c). |
| 13b | Reasons for non-participation | partly | Results: 20 deaths without a SmartVA result "were not coded" | Appendix: reasons for the other 20 uncoded deaths [count by reason]. |
| 13c | Flow diagram | missing | | Appendix figure: submissions extracted, test projects removed, 7917 included, 7877 coded, 7875 with both steps, 7858 with both groups assigned, 7897 with SmartVA result. |
| R13.1 | Detailed selection incl. data-quality filtering | partly | Results | Same flow diagram plus the count removed by each cleaning rule. |
| 14a | Characteristics of participants | partly | Results (languages, facility share by document status) | Appendix table by programme: age group, sex, place of death, interview language, site. Not a cause-of-death table. |
| 14b | Missing data per variable | missing | | Appendix: n and % missing for date of death, interview date, age, sex, place of death, narrative. |
| 14c | Follow-up time | n/a | | |
| 15 | Outcome data | reported | Results; Table 2 | None. |
| 16a | Unadjusted and adjusted estimates with CI | partly | Results (adjusted RR only) | Appendix: add the crude risk ratio with CI beside the adjusted 0.34 (0.25 to 0.47). |
| 16b | Category boundaries | reported | Statistical analysis | None. |
| 16c | Absolute risk | reported | Results (5.5% vs 20.8%) | None. |
| 17 | Other analyses | missing | | Same as 12e. |
| 18 | Key results | reported | Discussion paragraph 1 | None. |
| 19 | Limitations, bias direction and size | reported | Discussion limitations | None. |
| R19.1 | Implications of using data not collected for the question | partly | Discussion limitations | MT (about 25 words, swap against a cut) or appendix: add misclassification (placeholder and short narratives, recalled dates), missing data and eligibility changing as the platform changed between versions. |
| 20 | Cautious interpretation | reported | Discussion | None. |
| 21 | Generalisability | partly | Discussion (no explicit paragraph) | MT, about 30 words: "Findings come from 11 sites in two research-funded programmes with trained coders and may not hold in routine district services." |
| 22 | Funding and role of funders | partly | Summary and Role of the funding source (placeholders) | Fill grant numbers and the funder statement. |
| R22.1 | Access to protocol, raw data, code | partly | Data sharing | Deposit `digitva_ldh_export.sql`, the do-file and the aggregate tables with a release tag or Zenodo DOI and cite it in the statement. |

## 2. iCHECK-DH (20 items, condensed; items 1 to 17 and 19 mandatory)

| # | Item | Status | Where | Fix |
| --- | --- | --- | --- | --- |
| 1 | Title identifies an implementation report | reported | Title | None. |
| 2 | Abstract: strategy, intervention, outcomes, KPIs | partly | Summary | Summary words are fixed; list the deployment strategy in the appendix checklist. |
| 3 | Context: geography, organisations, population, alignment with national digital health strategy | partly | Introduction; Study design | Appendix: a paragraph naming states, districts, the SRS and CRS context, and the link (or lack of link) to the national digital health mission and civil registration. |
| 4 | Problem statement | reported | Introduction | None. |
| 5 | Similar interventions and what is new | reported | Introduction; Discussion | None. |
| 6 | Aim, objectives, predefined outcomes and KPIs | partly | Introduction; Indicators | Appendix: table of KPIs with definitions and the prespecification statement (see RECORD 3). |
| 7 | Blueprint: design, features, strategy, roadmap | partly | Results, The platform; Table 1 | Appendix: rollout sequence (training, go-live dates per site, version changes) as a timeline. |
| 8 | Technical design: rationale, architecture, licence, links | reported | Platform development | None. |
| 9 | Target sites, staff, population, eligibility | partly | Study design | Appendix: numbers of interviewers, supervisors, coders and reviewers by programme. |
| 10 | Data governance: lifecycle, ownership, consent, law, hosting, cybersecurity | partly | Platform (privacy and access); Ethics | Appendix: hosting location and provider, data ownership, retention, and compliance with the Digital Personal Data Protection Act 2023. |
| 11 | Interoperability: systems and standards | partly | Platform (ODK, SmartVA, ICD-10/11, SRS and CMEA10 lists) | Appendix: table of interfaces and standards, and a sentence that no HL7 FHIR or national health ID exchange exists [if true]. |
| 12 | Participating entities, government role, IP | partly | Study design (funders); MIT licence | Appendix: implementers, government partners, who holds the copyright on the MIT-licensed code. |
| 13 | Budget planning and actual cost | missing | Statistical analysis and Table 2 hold "[to be completed]" | Report monthly cloud cost in Table 2 or the appendix, or state that costs were not tracked and why. |
| 14 | Sustainability and exit | missing | | Appendix paragraph: who funds hosting and maintenance after the grants, and handover plans. |
| 15 | Coverage: planned versus actual | partly | Results (11 sites, 7917 deaths) | Appendix: planned number of sites and deaths per programme against actual. |
| 16 | Outcomes against predefined measures | reported | Results; Table 2 | None. |
| 17 | Lessons: success factors, challenges, cost of ownership | partly | Table 3; Discussion | Add cost of ownership in the appendix (see item 13). |
| 18 | Unintended consequences (non-mandatory) | partly | Discussion (anchoring on SmartVA; April batch failures) | Appendix: one sentence on negative effects seen, including SmartVA reruns and the bulk-load backlog. |
| 19 | Discussion and future implications | reported | Discussion | None. |
| 20 | Approvals, registration, conflicts (non-mandatory) | partly | Ethics, Declaration of interests (placeholders) | Fill the IEC approval numbers and the interests statements. |

## 3. mERA (16 core items; item descriptions from memory, names from PMC5650671)

| # | Item | Status | Where | Fix |
| --- | --- | --- | --- | --- |
| 1 | Infrastructure (connectivity, power, devices) | partly | Platform; Table 3 ("unreliable connectivity") | Appendix: devices used by interviewers and coders, and typical network conditions. |
| 2 | Technology platform | reported | Platform development | None. |
| 3 | Interoperability and HIS context | partly | Platform | Same fix as iCHECK-DH 11. |
| 4 | Intervention delivery (mode, frequency, who) | partly | Results, The platform | Appendix: who did what in each programme and how many contacts per death. |
| 5 | Intervention content | reported | Results, The platform; Table 1 | None. |
| 6 | Usability and content testing | missing | | Appendix and limitations: "No formal usability testing was done; the usability survey was not reported." Do not imply testing; automated tests and the training project are not usability evidence. |
| 7 | User feedback | partly | Platform development ("review of programme needs") | Appendix: describe how feedback from coders and data managers was gathered, or state it was informal. |
| 8 | Access of individual participants | partly | Platform (mobile-number sign-in for ASHAs) | Appendix: which user groups had no device or email and how they were served. |
| 9 | Cost assessment | missing | | Same as iCHECK-DH 13. |
| 10 | Adoption inputs and programme entry | partly | Study design | Appendix: how sites joined, training given and on-boarding time. |
| 11 | Limitations for delivery at scale | partly | Discussion limitations; Table 3 | Appendix: server capacity during the 421-deaths-a-day peak and known scale limits. |
| 12 | Contextual adaptability | reported | Results (configuration; nine languages) | None. |
| 13 | Replicability | reported | MIT licence; GitHub link; Data sharing | Optionally cite the deployment guide in the appendix. |
| 14 | Data security | reported | Platform (access control, encryption, security review) | None. |
| 15 | Compliance with national guidelines or regulation | missing | | Appendix: ICMR ethical guidelines, Digital Personal Data Protection Act 2023, civil registration and MCCD rules, and that the software is not a regulated medical device [confirm]. |
| 16 | Fidelity of the intervention | reported | Results (both coding steps recorded for 7875 deaths) | None. |

## 4. Lancet Digital Health requirements (not fetched; from memory and owner notes, confirm on the live page)

| Requirement | Status | Where | Fix |
| --- | --- | --- | --- |
| Structured Summary, 300 words or fewer | partly | Summary is 300 words including a bracketed Funding line | The real funding text will push it over 300; cut about 15 words from Findings or Interpretation. |
| Research in context panel | partly | Panel is 326 words; search stops at 2876 records, "[Complete screening]", no Embase | Run and record the screening (databases, dates, terms, counts) in the appendix; tighten the panel if the live page gives a limit. |
| Main text 3500 words | reported | 3498 words | Any main-text fix above must be offset by a cut. |
| References limit | reported | 17 references (owner notes say the limit is 30) | None; references 1, 2, 6, 14, 15 still need Zotero import. |
| Figure and table limits | partly | 3 tables, 3 figures; limit not verified | Confirm the limit; if it is lower, move Figure 3 or Table 3 to the appendix. |
| Data sharing statement | partly | Data sharing | Name the repository, DOI or release tag, and the access criteria and decision timeline for the aggregate tables. |
| Contributors | missing | Placeholder | Write the CRediT statement and who verified the data. |
| Declaration of interests | missing | Placeholder | Each author completes the ICMJE form; state the interest of the developers in an open-source platform they built. |
| Ethics | partly | Ethics paragraph with placeholders | Give IEC names and approval numbers for both programmes and say whether respondent consent covered this secondary analysis. |
| Role of the funding source | partly | Placeholder in Methods (also in Summary) | Write the final statement once and keep it in the Methods and Summary Funding line. |
| Reporting checklist uploaded | missing | Mentions iCHECK-DH only | Upload completed RECORD and iCHECK-DH checklists with section and page numbers; the manuscript says "reported according to iCHECK-DH" and should add RECORD in the Study design sentence (two words). |

## Counts

| Guideline | Reported | Partly | Missing | n/a |
| --- | --- | --- | --- | --- |
| RECORD with STROBE | 14 | 22 | 7 | 4 |
| iCHECK-DH | 6 | 12 | 2 | 0 |
| mERA | 6 | 7 | 3 | 0 |
| LDH requirements | 2 | 6 | 3 | 0 |
