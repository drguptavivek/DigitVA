---
title: AI question catalog
doc_type: kb
status: active
owner: engineering
last_updated: 2026-10-27
---

# AI question catalog

Fixed questions with SQL over the AI tables (`ai_cube`, `ai_org_levels`, `ai_staff`,
`ai_coder`), offered on the AI questions page
(docs/policy/ai-analytics-questions.md). Choosing one runs its stored SQL
with no model call and no quota. Generated from
`app/data/ai_question_catalog.json`; regenerate with
`flask ai-catalog generate`, never edit this page by hand.

Source: hand-written catalog (digitva-qwvt), operational questions added 2026-10-27; comparative, staff and coder questions 2026-10-27. Questions: 94.

## How many cases are there in total?

Key `total_cases`. All submissions in your scope.

```sql
SELECT sum(n) AS cases FROM ai_cube
```

## How many cases does each project have?

Key `cases_by_project`. Submissions per project.

```sql
SELECT project_id, sum(n) AS cases FROM ai_cube GROUP BY project_id ORDER BY cases DESC
```

## What share of cases is coded at each site, against all sites?

Key `coded_share_by_site`. Cases with a final cause as a percentage of all cases, per site, with the all-sites share and rank.

```sql
WITH s AS (SELECT site_id, sum(n) FILTER (WHERE true) AS base, sum(n) FILTER (WHERE authoritative_source IS NOT NULL) AS hits FROM ai_cube GROUP BY site_id) SELECT site_id, coalesce(hits, 0) AS coded, round(100.0 * hits / NULLIF(base, 0), 1) AS coded_pct, round(100.0 * sum(hits) OVER () / NULLIF(sum(base) OVER (), 0), 1) AS all_sites_pct, rank() OVER (ORDER BY hits::numeric / NULLIF(base, 0) DESC NULLS LAST) AS rank FROM s ORDER BY coded_pct DESC NULLS LAST
```

## How many cases are waiting for coding at each site?

Key `pending_coding_by_site`. Cases ready for coding or being coded, per site.

```sql
SELECT site_id, sum(n) FILTER (WHERE workflow_state = 'ready_for_coding') AS ready, sum(n) FILTER (WHERE workflow_state = 'coding_in_progress') AS in_progress FROM ai_cube GROUP BY site_id ORDER BY ready DESC NULLS LAST
```

## How many cases were marked not codeable at each site?

Key `not_codeable_by_site`. Cases not codeable by the coder or the data manager, per site.

```sql
SELECT site_id, sum(n) FILTER (WHERE workflow_state = 'not_codeable_by_coder') AS by_coder, sum(n) FILTER (WHERE workflow_state = 'not_codeable_by_data_manager') AS by_data_manager FROM ai_cube GROUP BY site_id ORDER BY site_id
```

## Who gave the final cause: coder or reviewer?

Key `final_cause_source`. Coded cases by the source of the final cause.

```sql
SELECT authoritative_source, sum(n) AS cases FROM ai_cube WHERE authoritative_source IS NOT NULL GROUP BY authoritative_source ORDER BY cases DESC
```

## How many cases came in each month over the last year?

Key `monthly_cases_last_12`. Submissions per month for the last 12 months.

```sql
SELECT submission_month, sum(n) AS cases FROM ai_cube WHERE submission_month >= date_trunc('month', CURRENT_DATE) - interval '11 months' GROUP BY submission_month ORDER BY submission_month
```

## Monthly cases by site

Key `monthly_cases_by_site`. Submissions per month for the five largest sites.

```sql
WITH top_sites AS (SELECT site_id FROM ai_cube GROUP BY site_id ORDER BY sum(n) DESC LIMIT 5) SELECT submission_month, site_id, sum(n) AS cases FROM ai_cube WHERE site_id IN (SELECT site_id FROM top_sites) AND submission_month IS NOT NULL GROUP BY submission_month, site_id ORDER BY submission_month, site_id
```

## How many cases were submitted each year?

Key `cases_by_year`. Submissions per calendar year.

```sql
SELECT extract(year FROM submission_month)::int AS year, sum(n) AS cases FROM ai_cube WHERE submission_month IS NOT NULL GROUP BY 1 ORDER BY 1
```

## How many deaths are there in each age band?

Key `deaths_by_age_band`. Cases per analytics age band.

```sql
SELECT analytics_age_band, sum(n) AS deaths FROM ai_cube GROUP BY analytics_age_band ORDER BY deaths DESC
```

## How many deaths are male and female?

Key `deaths_by_sex`. Cases by sex of the deceased.

```sql
SELECT lower(sex) AS sex, sum(n) AS deaths FROM ai_cube GROUP BY lower(sex) ORDER BY deaths DESC
```

## What are the top 10 final causes of death?

Key `top_causes`. Most frequent WHO 2026 VA causes of the final cause.

```sql
SELECT authoritative_who_bucket, sum(n) AS deaths FROM ai_cube WHERE authoritative_who_bucket IS NOT NULL GROUP BY authoritative_who_bucket ORDER BY deaths DESC LIMIT 10
```

## What are the top causes of neonatal deaths?

Key `top_causes_neonates`. Top 10 final causes among neonates.

```sql
SELECT authoritative_who_bucket, sum(n) AS deaths FROM ai_cube WHERE analytics_age_band = 'neonate' AND authoritative_who_bucket IS NOT NULL GROUP BY authoritative_who_bucket ORDER BY deaths DESC LIMIT 10
```

## What are the top causes of child deaths?

Key `top_causes_children`. Top 10 final causes among children.

```sql
SELECT authoritative_who_bucket, sum(n) AS deaths FROM ai_cube WHERE analytics_age_band = 'child' AND authoritative_who_bucket IS NOT NULL GROUP BY authoritative_who_bucket ORDER BY deaths DESC LIMIT 10
```

## Cause sections by sex

Key `cause_sections_by_sex`. Deaths per WHO 2026 VA cause section, male and female.

```sql
SELECT authoritative_who_bucket_section, sum(n) FILTER (WHERE lower(sex) = 'male') AS male, sum(n) FILTER (WHERE lower(sex) = 'female') AS female FROM ai_cube WHERE authoritative_who_bucket_section IS NOT NULL GROUP BY authoritative_who_bucket_section ORDER BY authoritative_who_bucket_section
```

## How many deaths from external causes in each age band?

Key `external_causes_by_age`. Deaths in the external causes section per age band.

```sql
SELECT analytics_age_band, sum(n) AS deaths FROM ai_cube WHERE authoritative_who_bucket_section = 'External causes of death' GROUP BY analytics_age_band ORDER BY deaths DESC
```

## What share of coded deaths has an unknown cause at each site, against all sites?

Key `unknown_cause_share_by_site`. Coded deaths in the cause-unknown section as a percentage of coded deaths per site, with the all-sites share.

```sql
WITH s AS (SELECT site_id, sum(n) FILTER (WHERE authoritative_who_bucket_section IS NOT NULL) AS base, sum(n) FILTER (WHERE authoritative_who_bucket_section = 'Cause of death unknown') AS hits FROM ai_cube GROUP BY site_id) SELECT site_id, coalesce(hits, 0) AS unknown, round(100.0 * hits / NULLIF(base, 0), 1) AS unknown_pct, round(100.0 * sum(hits) OVER () / NULLIF(sum(base) OVER (), 0), 1) AS all_sites_pct, rank() OVER (ORDER BY hits::numeric / NULLIF(base, 0) DESC NULLS LAST) AS rank FROM s ORDER BY unknown_pct DESC NULLS LAST
```

## How often does SmartVA agree with the final cause?

Key `smartva_agreement_overall`. Coded cases with a SmartVA cause where the SmartVA top cause matches the final cause.

```sql
SELECT sum(n) FILTER (WHERE smartva_cause1_who_bucket IS NOT NULL AND authoritative_who_bucket IS NOT NULL) AS compared, sum(n) FILTER (WHERE smartva_cause1_who_bucket = authoritative_who_bucket) AS agree, round(100.0 * sum(n) FILTER (WHERE smartva_cause1_who_bucket = authoritative_who_bucket) / NULLIF(sum(n) FILTER (WHERE smartva_cause1_who_bucket IS NOT NULL AND authoritative_who_bucket IS NOT NULL), 0), 1) AS agree_pct FROM ai_cube
```

## What is the average narrative quality score at each site, against all sites?

Key `nqa_average_by_site`. Mean narrative quality score per site, with the all-sites mean and rank.

```sql
WITH s AS (SELECT site_id, sum(nqa_score_sum) AS score, sum(nqa_scored_n) AS scored FROM ai_cube GROUP BY site_id) SELECT site_id, scored, round(score::numeric / NULLIF(scored, 0), 2) AS avg_score, round(sum(score) OVER ()::numeric / NULLIF(sum(scored) OVER (), 0), 2) AS all_sites_avg, rank() OVER (ORDER BY score::numeric / NULLIF(scored, 0) DESC NULLS LAST) AS rank FROM s WHERE scored > 0 ORDER BY avg_score DESC
```

## Narrative quality ratings by site

Key `nqa_rating_by_site`. Cases rated Good, Fair and Poor, per site.

```sql
SELECT site_id, sum(n) FILTER (WHERE nqa_rating = 'Good') AS good, sum(n) FILTER (WHERE nqa_rating = 'Fair') AS fair, sum(n) FILTER (WHERE nqa_rating = 'Poor') AS poor FROM ai_cube GROUP BY site_id ORDER BY site_id
```

## What is the workflow state of cases at each site?

Key `workflow_state_by_site`. Cases per site split by workflow state.

```sql
SELECT site_id, workflow_state, sum(n) AS cases FROM ai_cube GROUP BY site_id, workflow_state ORDER BY site_id, cases DESC
```

## Which sites have cases waiting for attachments to sync?

Key `attachment_sync_pending_by_site`. Cases held in attachment sync pending, by site.

```sql
SELECT site_id, sum(n) AS waiting FROM ai_cube WHERE workflow_state = 'attachment_sync_pending' GROUP BY site_id ORDER BY waiting DESC
```

## Which sites have the most consent refusals, against all sites?

Key `consent_refused_by_site`. Consent-refused cases and their share of all cases per site, with the all-sites rate.

```sql
WITH s AS (SELECT site_id, sum(n) FILTER (WHERE true) AS base, sum(n) FILTER (WHERE workflow_state = 'consent_refused') AS hits FROM ai_cube GROUP BY site_id) SELECT site_id, coalesce(hits, 0) AS refused, round(100.0 * hits / NULLIF(base, 0), 1) AS refused_pct, round(100.0 * sum(hits) OVER () / NULLIF(sum(base) OVER (), 0), 1) AS all_sites_pct, rank() OVER (ORDER BY hits::numeric / NULLIF(base, 0) DESC NULLS LAST) AS rank FROM s ORDER BY refused_pct DESC NULLS LAST
```

## Is consent refusal rising or falling month by month?

Key `consent_refused_by_month`. Consent-refused cases per submission month.

```sql
SELECT submission_month, sum(n) FILTER (WHERE workflow_state = 'consent_refused') AS refused, sum(n) AS cases FROM ai_cube GROUP BY submission_month ORDER BY submission_month
```

## How many cases were marked not codeable by data managers and by coders?

Key `not_codeable_by_who`. Not-codeable cases by who decided, per site.

```sql
SELECT site_id, sum(n) FILTER (WHERE workflow_state = 'not_codeable_by_data_manager') AS by_data_manager, sum(n) FILTER (WHERE workflow_state = 'not_codeable_by_coder') AS by_coder FROM ai_cube GROUP BY site_id HAVING sum(n) FILTER (WHERE workflow_state IN ('not_codeable_by_data_manager', 'not_codeable_by_coder')) > 0 ORDER BY site_id
```

## How does this month's intake compare with last month at each site?

Key `intake_this_month_vs_last`. Cases submitted this calendar month (so far) and last month by site, with the change and percent change.

```sql
WITH m AS (SELECT site_id, sum(n) FILTER (WHERE submission_month = date_trunc('month', CURRENT_DATE)::date) AS this_month, sum(n) FILTER (WHERE submission_month = (date_trunc('month', CURRENT_DATE)::date - interval '1 month')::date) AS last_month FROM ai_cube GROUP BY site_id) SELECT site_id, coalesce(this_month, 0) AS this_month, coalesce(last_month, 0) AS last_month, coalesce(this_month, 0) - coalesce(last_month, 0) AS change, round(100.0 * (coalesce(this_month, 0) - last_month) / NULLIF(last_month, 0), 1) AS change_pct FROM m ORDER BY change
```

## Which sites have sent no cases this month?

Key `sites_silent_this_month`. Sites with earlier cases but none submitted in the current month.

```sql
SELECT site_id, sum(n) AS cases_ever, max(submission_month) AS last_month_with_cases FROM ai_cube GROUP BY site_id HAVING coalesce(sum(n) FILTER (WHERE submission_month = date_trunc('month', CURRENT_DATE)), 0) = 0 ORDER BY last_month_with_cases
```

## Which sites have cases with sex or age band missing?

Key `missing_sex_or_age_by_site`. Data quality: cases with sex or age band unknown or blank, by site.

```sql
SELECT site_id, sum(n) FILTER (WHERE sex IS NULL OR lower(sex) IN ('unknown', 'undetermined', '')) AS sex_missing, sum(n) FILTER (WHERE analytics_age_band IS NULL OR analytics_age_band = 'unknown') AS age_missing, sum(n) AS cases FROM ai_cube GROUP BY site_id ORDER BY sex_missing DESC NULLS LAST
```

## Which sites have the most poor or ungradable narratives?

Key `poor_narratives_by_site`. Share of NQA-rated cases rated Poor or Cannot Grade, by site.

```sql
SELECT site_id, sum(n) FILTER (WHERE nqa_rating IN ('Poor', 'Cannot Grade')) AS poor_or_ungradable, round(100.0 * sum(n) FILTER (WHERE nqa_rating IN ('Poor', 'Cannot Grade')) / NULLIF(sum(n) FILTER (WHERE nqa_rating IS NOT NULL), 0), 1) AS poor_pct FROM ai_cube GROUP BY site_id ORDER BY poor_pct DESC NULLS LAST
```

## How many coded cases are waiting for a reviewer at each site?

Key `awaiting_review_by_site`. Cases in reviewer-eligible state, by site.

```sql
SELECT site_id, sum(n) AS awaiting_review FROM ai_cube WHERE workflow_state = 'reviewer_eligible' GROUP BY site_id ORDER BY awaiting_review DESC
```

## How many cases did each project receive per month?

Key `intake_by_project_month`. Monthly intake by project.

```sql
SELECT submission_month, project_id, sum(n) AS cases FROM ai_cube GROUP BY submission_month, project_id ORDER BY submission_month, project_id
```

## How old is the coding backlog by the month cases came in?

Key `coding_backlog_by_intake_month`. Cases still ready for coding, by submission month: older months are the oldest waiting cases.

```sql
SELECT submission_month, sum(n) AS ready_for_coding FROM ai_cube WHERE workflow_state = 'ready_for_coding' GROUP BY submission_month ORDER BY submission_month
```

## Which age groups are waiting in the coding queue?

Key `coding_queue_by_age_band`. Ready-for-coding cases by age band.

```sql
SELECT analytics_age_band, sum(n) AS ready_for_coding FROM ai_cube WHERE workflow_state = 'ready_for_coding' GROUP BY analytics_age_band ORDER BY ready_for_coding DESC
```

## How good are the narratives of cases waiting to be coded?

Key `coding_queue_narrative_quality`. NQA rating mix of the ready-for-coding queue.

```sql
SELECT coalesce(nqa_rating, 'Not rated') AS nqa_rating, sum(n) AS cases FROM ai_cube WHERE workflow_state = 'ready_for_coding' GROUP BY coalesce(nqa_rating, 'Not rated') ORDER BY cases DESC
```

## How many cases were finalised each month, coder versus reviewer?

Key `coded_per_month`. Finalised cases by submission month and who holds the final cause.

```sql
SELECT submission_month, sum(n) FILTER (WHERE authoritative_source = 'coder') AS coder_final, sum(n) FILTER (WHERE authoritative_source = 'reviewer') AS reviewer_final FROM ai_cube GROUP BY submission_month ORDER BY submission_month
```

## Is the share of unknown causes improving over time?

Key `unknown_cause_by_month`. Percent of finalised causes in the 'Cause of death unknown' section, per month.

```sql
SELECT submission_month, round(100.0 * sum(n) FILTER (WHERE authoritative_who_bucket_section = 'Cause of death unknown') / NULLIF(sum(n) FILTER (WHERE authoritative_who_bucket_section IS NOT NULL), 0), 1) AS unknown_pct FROM ai_cube GROUP BY submission_month ORDER BY submission_month
```

## In which age groups are causes most often unknown?

Key `unknown_cause_by_age_band`. Percent of finalised causes that are unknown, by age band.

```sql
SELECT analytics_age_band, round(100.0 * sum(n) FILTER (WHERE authoritative_who_bucket_section = 'Cause of death unknown') / NULLIF(sum(n) FILTER (WHERE authoritative_who_bucket_section IS NOT NULL), 0), 1) AS unknown_pct FROM ai_cube GROUP BY analytics_age_band ORDER BY unknown_pct DESC NULLS LAST
```

## What are the most coded ICD codes this month?

Key `top_icd_this_month`. Top 15 final ICD codes for cases submitted this month.

```sql
SELECT authoritative_icd, sum(n) AS cases FROM ai_cube WHERE authoritative_icd IS NOT NULL AND submission_month = date_trunc('month', CURRENT_DATE) GROUP BY authoritative_icd ORDER BY cases DESC LIMIT 15
```

## Where does SmartVA most often disagree with the final cause?

Key `smartva_disagreements`. Top 15 SmartVA-cause versus final-cause pairs that differ.

```sql
SELECT smartva_cause1_who_bucket AS smartva_cause, authoritative_who_bucket AS final_cause, sum(n) AS cases FROM ai_cube WHERE smartva_cause1_who_bucket IS NOT NULL AND authoritative_who_bucket IS NOT NULL AND smartva_cause1_who_bucket <> authoritative_who_bucket GROUP BY smartva_cause1_who_bucket, authoritative_who_bucket ORDER BY cases DESC LIMIT 15
```

## At which sites does the reviewer hold the final cause most often?

Key `reviewer_share_by_site`. Share of finalised cases where the reviewer's cause is authoritative, by site.

```sql
SELECT site_id, round(100.0 * sum(n) FILTER (WHERE authoritative_source = 'reviewer') / NULLIF(sum(n) FILTER (WHERE authoritative_source IS NOT NULL), 0), 1) AS reviewer_pct FROM ai_cube GROUP BY site_id ORDER BY reviewer_pct DESC NULLS LAST
```

## What are the top five causes of death in each age group?

Key `top5_causes_per_age_band`. Five leading WHO VA causes within each age band.

```sql
WITH ranked AS (SELECT analytics_age_band, authoritative_who_bucket, sum(n) AS cases, rank() OVER (PARTITION BY analytics_age_band ORDER BY sum(n) DESC) AS rnk FROM ai_cube WHERE authoritative_who_bucket IS NOT NULL GROUP BY analytics_age_band, authoritative_who_bucket) SELECT analytics_age_band, authoritative_who_bucket, cases FROM ranked WHERE rnk <= 5 ORDER BY analytics_age_band, cases DESC
```

## How many maternal deaths are there, and from which causes?

Key `maternal_deaths`. Deaths in the pregnancy, childbirth and puerperium section, by cause.

```sql
SELECT authoritative_who_bucket, sum(n) AS deaths FROM ai_cube WHERE authoritative_who_bucket_section = 'Pregnancy-, childbirth and puerperium-related disorders' GROUP BY authoritative_who_bucket ORDER BY deaths DESC
```

## Which sites report maternal deaths?

Key `maternal_deaths_by_site`. Maternal deaths by site.

```sql
SELECT site_id, sum(n) AS maternal_deaths FROM ai_cube WHERE authoritative_who_bucket_section = 'Pregnancy-, childbirth and puerperium-related disorders' GROUP BY site_id ORDER BY maternal_deaths DESC
```

## What share of deaths under 15 are neonatal?

Key `neonatal_share_of_child_deaths`. Neonate deaths as a share of neonate plus child deaths, by site.

```sql
SELECT site_id, sum(n) FILTER (WHERE analytics_age_band = 'neonate') AS neonatal, sum(n) FILTER (WHERE analytics_age_band = 'child') AS child, round(100.0 * sum(n) FILTER (WHERE analytics_age_band = 'neonate') / NULLIF(sum(n) FILTER (WHERE analytics_age_band IN ('neonate', 'child')), 0), 1) AS neonatal_pct FROM ai_cube GROUP BY site_id ORDER BY neonatal_pct DESC NULLS LAST
```

## How many stillbirths are recorded at each site?

Key `stillbirths_by_site`. Cases in the stillbirths section, by site.

```sql
SELECT site_id, sum(n) AS stillbirths FROM ai_cube WHERE authoritative_who_bucket_section = 'Stillbirths' GROUP BY site_id ORDER BY stillbirths DESC
```

## Who dies of injuries, by sex and age?

Key `injury_deaths_by_sex_age`. External-cause deaths by age band and sex.

```sql
SELECT analytics_age_band, sum(n) FILTER (WHERE lower(sex) = 'male') AS male, sum(n) FILTER (WHERE lower(sex) = 'female') AS female FROM ai_cube WHERE authoritative_who_bucket_section = 'External causes of death' GROUP BY analytics_age_band ORDER BY analytics_age_band
```

## What share of adult deaths are from non-communicable diseases?

Key `ncd_share_adults`. Adults (15+): circulatory, neoplasms, NCD, respiratory, renal, endocrine and digestive sections as a share of known causes.

```sql
SELECT analytics_age_band, round(100.0 * sum(n) FILTER (WHERE authoritative_who_bucket_section IN ('Diseases of the circulatory system', 'Neoplasms', 'Non-communicable diseases', 'Respiratory disorders', 'Renal disorders', 'Nutritional and endocrine disorders', 'Gastrointestinal disorders')) / NULLIF(sum(n) FILTER (WHERE authoritative_who_bucket_section IS NOT NULL AND authoritative_who_bucket_section <> 'Cause of death unknown'), 0), 1) AS ncd_pct FROM ai_cube WHERE analytics_age_band IN ('15_49y', '50_64y', '65_plus') GROUP BY analytics_age_band ORDER BY analytics_age_band
```

## Are infectious disease deaths changing quarter by quarter?

Key `infectious_trend_by_quarter`. Infectious and parasitic deaths and their share, per quarter.

```sql
SELECT date_trunc('quarter', submission_month) AS quarter, sum(n) FILTER (WHERE authoritative_who_bucket_section = 'Infectious and parasitic diseases') AS infectious, round(100.0 * sum(n) FILTER (WHERE authoritative_who_bucket_section = 'Infectious and parasitic diseases') / NULLIF(sum(n) FILTER (WHERE authoritative_who_bucket_section IS NOT NULL), 0), 1) AS infectious_pct FROM ai_cube GROUP BY date_trunc('quarter', submission_month) ORDER BY quarter
```

## How many male deaths are there per 100 female deaths in each age group?

Key `sex_ratio_by_age_band`. Male-to-female death ratio by age band.

```sql
SELECT analytics_age_band, sum(n) FILTER (WHERE lower(sex) = 'male') AS male, sum(n) FILTER (WHERE lower(sex) = 'female') AS female, round(100.0 * sum(n) FILTER (WHERE lower(sex) = 'male') / NULLIF(sum(n) FILTER (WHERE lower(sex) = 'female'), 0), 0) AS males_per_100_females FROM ai_cube GROUP BY analytics_age_band ORDER BY analytics_age_band
```

## What share of cases in each project has a final cause?

Key `final_cause_completeness_by_project`. Programme completeness: percent of cases with a finalised cause, by project.

```sql
SELECT project_id, sum(n) AS cases, round(100.0 * sum(n) FILTER (WHERE authoritative_source IS NOT NULL) / NULLIF(sum(n), 0), 1) AS with_final_pct FROM ai_cube GROUP BY project_id ORDER BY project_id
```

## How does each month compare with the same month last year?

Key `year_on_year_by_month`. Cases per calendar month, this year against last year.

```sql
SELECT extract(month FROM submission_month) AS month_no, sum(n) FILTER (WHERE extract(year FROM submission_month) = extract(year FROM CURRENT_DATE)) AS this_year, sum(n) FILTER (WHERE extract(year FROM submission_month) = extract(year FROM CURRENT_DATE) - 1) AS last_year FROM ai_cube GROUP BY extract(month FROM submission_month) ORDER BY month_no
```

## Which sites sent fewer cases this month than their 3-month average?

Key `intake_vs_3_month_average`. Cases this month (so far) against each site's average of the previous three months, with the percent change.

```sql
WITH m AS (SELECT site_id, sum(n) FILTER (WHERE submission_month = date_trunc('month', CURRENT_DATE)::date) AS this_month, round(sum(n) FILTER (WHERE submission_month >= (date_trunc('month', CURRENT_DATE)::date - interval '3 months')::date AND submission_month < date_trunc('month', CURRENT_DATE)::date) / 3.0, 1) AS avg_last_3_months FROM ai_cube GROUP BY site_id) SELECT site_id, coalesce(this_month, 0) AS this_month, avg_last_3_months, round(100.0 * (coalesce(this_month, 0) - avg_last_3_months) / NULLIF(avg_last_3_months, 0), 1) AS change_pct FROM m WHERE avg_last_3_months > 0 ORDER BY change_pct
```

## Which sub-centres sent fewer cases this month than their 3-month average?

Key `subcentres_vs_3_month_average`. Cases this month at each level-5 unit (sub-centre in the state projects) against its average of the previous three months.

```sql
WITH m AS (SELECT project_id, org_l1_name, org_l5_name, sum(n) FILTER (WHERE submission_month = date_trunc('month', CURRENT_DATE)::date) AS this_month, round(sum(n) FILTER (WHERE submission_month >= (date_trunc('month', CURRENT_DATE)::date - interval '3 months')::date AND submission_month < date_trunc('month', CURRENT_DATE)::date) / 3.0, 1) AS avg_last_3_months FROM ai_cube WHERE org_l5_name IS NOT NULL GROUP BY project_id, org_l1_name, org_l5_name) SELECT org_l5_name, org_l1_name, project_id, coalesce(this_month, 0) AS this_month, avg_last_3_months, round(100.0 * (coalesce(this_month, 0) - avg_last_3_months) / NULLIF(avg_last_3_months, 0), 1) AS change_pct FROM m WHERE avg_last_3_months > 0 ORDER BY change_pct
```

## Which sub-centres have sent no cases this month or last month?

Key `subcentres_silent`. Level-5 units (sub-centres) that sent cases before but none since the start of last month, with their last case month.

```sql
SELECT org_l5_name, org_l1_name, project_id, max(submission_month) AS last_case_month, sum(n) AS cases_ever FROM ai_cube WHERE org_l5_name IS NOT NULL GROUP BY project_id, org_l1_name, org_l5_name HAVING max(submission_month) < (date_trunc('month', CURRENT_DATE)::date - interval '1 month')::date ORDER BY last_case_month
```

## What share of interviews is telephonic, by site?

Key `telephonic_share_by_site`. Telephonic consents as a percentage of consented interviews per site, with the all-sites share.

```sql
WITH s AS (SELECT site_id, sum(n) FILTER (WHERE consent_mode IN ('yes', 'telephonic_consent')) AS base, sum(n) FILTER (WHERE consent_mode = 'telephonic_consent') AS hits FROM ai_cube GROUP BY site_id) SELECT site_id, coalesce(hits, 0) AS telephonic, round(100.0 * hits / NULLIF(base, 0), 1) AS telephonic_pct, round(100.0 * sum(hits) OVER () / NULLIF(sum(base) OVER (), 0), 1) AS all_sites_pct, rank() OVER (ORDER BY hits::numeric / NULLIF(base, 0) DESC NULLS LAST) AS rank FROM s ORDER BY telephonic_pct DESC NULLS LAST
```

## Why did data managers mark cases not codeable, by site?

Key `dm_not_codeable_reasons`. Cases marked not codeable by a data manager, by site and recorded reason.

```sql
SELECT site_id, dm_not_codeable_reason, sum(n) AS cases FROM ai_cube WHERE dm_not_codeable_reason IS NOT NULL GROUP BY site_id, dm_not_codeable_reason ORDER BY cases DESC
```

## Which sites have the most ODK sync problems?

Key `odk_sync_issues_by_site`. Cases with an ODK sync issue by site and issue code. Cases retired from ODK are excluded from every AI table.

```sql
SELECT site_id, odk_sync_issue_code, sum(n) AS cases FROM ai_cube WHERE odk_sync_issue_code IS NOT NULL GROUP BY site_id, odk_sync_issue_code ORDER BY cases DESC
```

## Where is narrative quality falling month on month?

Key `nqa_trend_by_site`. Mean narrative quality score per site and month over the last six months, with the change from the previous month.

```sql
WITH m AS (SELECT site_id, submission_month, round(sum(nqa_score_sum)::numeric / NULLIF(sum(nqa_scored_n), 0), 2) AS avg_score FROM ai_cube WHERE submission_month >= (date_trunc('month', CURRENT_DATE)::date - interval '6 months')::date GROUP BY site_id, submission_month) SELECT site_id, submission_month, avg_score, avg_score - lag(avg_score) OVER (PARTITION BY site_id ORDER BY submission_month) AS change FROM m ORDER BY site_id, submission_month
```

## How does this month compare with the same month last year at each site?

Key `intake_same_month_last_year`. Cases this month (so far) against the same calendar month last year, per site, with the percent change.

```sql
WITH m AS (SELECT site_id, sum(n) FILTER (WHERE submission_month = date_trunc('month', CURRENT_DATE)::date) AS this_month, sum(n) FILTER (WHERE submission_month = (date_trunc('month', CURRENT_DATE)::date - interval '1 year')::date) AS same_month_last_year FROM ai_cube GROUP BY site_id) SELECT site_id, coalesce(this_month, 0) AS this_month, coalesce(same_month_last_year, 0) AS same_month_last_year, round(100.0 * (coalesce(this_month, 0) - same_month_last_year) / NULLIF(same_month_last_year, 0), 1) AS change_pct FROM m ORDER BY change_pct NULLS LAST
```

## In which narration languages is coding held back?

Key `backlog_by_language`. Cases waiting for or in coding per narration language, and their share of that language's cases.

```sql
SELECT narration_language, sum(n) FILTER (WHERE workflow_state IN ('ready_for_coding', 'coding_in_progress')) AS backlog, sum(n) AS cases, round(100.0 * sum(n) FILTER (WHERE workflow_state IN ('ready_for_coding', 'coding_in_progress')) / NULLIF(sum(n), 0), 1) AS backlog_pct FROM ai_cube GROUP BY narration_language ORDER BY backlog DESC NULLS LAST
```

## How does the backlog in each language compare with the coders who code in it?

Key `backlog_vs_coders_by_language`. Coding backlog per narration language against coders with that coding language, and those signed in within 30 days. A coder granted at two places counts once per place.

```sql
WITH b AS (SELECT narration_language AS lang, sum(n) AS backlog FROM ai_cube WHERE workflow_state IN ('ready_for_coding', 'coding_in_progress') GROUP BY narration_language), c AS (SELECT coding_language AS lang, sum(staff) AS coders, sum(signed_in_30d) AS active_coders FROM ai_staff WHERE role = 'coder' AND coding_language IS NOT NULL GROUP BY coding_language) SELECT b.lang AS narration_language, b.backlog, coalesce(c.coders, 0) AS coders, coalesce(c.active_coders, 0) AS coders_signed_in_30d, round(b.backlog::numeric / NULLIF(c.active_coders, 0), 1) AS backlog_per_active_coder FROM b LEFT JOIN c ON c.lang = b.lang ORDER BY b.backlog DESC
```

## Which sites have a coding backlog but no active coder?

Key `backlog_sites_without_coder`. Coding backlog per site against coders granted for that site and those signed in within 30 days. Project-wide and unit coders are not counted here.

```sql
WITH b AS (SELECT project_id, site_id, sum(n) AS backlog FROM ai_cube WHERE workflow_state IN ('ready_for_coding', 'coding_in_progress') GROUP BY project_id, site_id), c AS (SELECT project_id, site_id, sum(staff) AS coders, sum(signed_in_30d) AS active FROM ai_staff WHERE role = 'coder' AND coding_language IS NULL AND site_id IS NOT NULL GROUP BY project_id, site_id) SELECT b.site_id, b.project_id, b.backlog, coalesce(c.coders, 0) AS site_coders, coalesce(c.active, 0) AS site_coders_signed_in_30d FROM b LEFT JOIN c ON c.project_id = b.project_id AND c.site_id = b.site_id ORDER BY coalesce(c.active, 0), b.backlog DESC
```

## How many cases were finalised this week compared with last week?

Key `finalised_this_week_vs_last`. Final causes saved this ISO week (so far) and last week, by site.

```sql
SELECT site_id, sum(n) FILTER (WHERE final_saved_week = date_trunc('week', CURRENT_DATE)::date) AS this_week, sum(n) FILTER (WHERE final_saved_week = (date_trunc('week', CURRENT_DATE) - interval '1 week')::date) AS last_week FROM ai_cube WHERE final_saved_week >= (date_trunc('week', CURRENT_DATE) - interval '1 week')::date GROUP BY site_id ORDER BY this_week DESC NULLS LAST
```

## How many final causes were saved each week over the last 12 weeks?

Key `finals_by_week`. Final causes saved per ISO week, with the change from the week before.

```sql
WITH w AS (SELECT final_saved_week, sum(n) AS finals FROM ai_cube WHERE final_saved_week >= (CURRENT_DATE - interval '12 weeks')::date GROUP BY final_saved_week) SELECT final_saved_week, finals, finals - lag(finals) OVER (ORDER BY final_saved_week) AS change FROM w ORDER BY final_saved_week
```

## What is the reviewer queue per site against the reviewers available?

Key `reviewer_queue_vs_reviewers`. Cases eligible for or in review per site against reviewers granted for that site. Project-wide and unit reviewers are not counted here.

```sql
WITH b AS (SELECT project_id, site_id, sum(n) AS queue FROM ai_cube WHERE workflow_state IN ('reviewer_eligible', 'reviewer_coding_in_progress') GROUP BY project_id, site_id), r AS (SELECT project_id, site_id, sum(staff) AS reviewers, sum(signed_in_30d) AS active FROM ai_staff WHERE role = 'reviewer' AND coding_language IS NULL AND site_id IS NOT NULL GROUP BY project_id, site_id) SELECT b.site_id, b.project_id, b.queue, coalesce(r.reviewers, 0) AS site_reviewers, coalesce(r.active, 0) AS site_reviewers_signed_in_30d FROM b LEFT JOIN r ON r.project_id = b.project_id AND r.site_id = b.site_id ORDER BY b.queue DESC
```

## Which coders finalise fastest? Minutes from allocation to final, against peers

Key `coder_speed`. Per coder over the last three months: finals, average elapsed minutes from allocation to final save and share under 3 minutes, against the project median share. Elapsed time, not time on screen.

```sql
WITH c AS (SELECT coder_number, coder_name, project_id, sum(finals) AS finals, round(sum(alloc_to_final_min_sum)::numeric / NULLIF(sum(timed_finals), 0), 1) AS avg_minutes, round(100.0 * sum(finals_under_3_min) / NULLIF(sum(timed_finals), 0), 1) AS under_3_min_pct FROM ai_coder WHERE month >= (date_trunc('month', CURRENT_DATE)::date - interval '3 months')::date GROUP BY coder_number, coder_name, project_id HAVING sum(timed_finals) >= 5), p AS (SELECT project_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY under_3_min_pct) AS median_pct FROM c GROUP BY project_id) SELECT c.coder_name, c.project_id, c.finals, c.avg_minutes, c.under_3_min_pct, round(p.median_pct::numeric, 1) AS peer_median_pct FROM c JOIN p ON p.project_id = c.project_id ORDER BY c.under_3_min_pct DESC NULLS LAST
```

## Which coders finalised the most cases last month, against the project median?

Key `coder_finals_vs_median`. Finals per coder in the last full month against the median coder of the same project.

```sql
WITH c AS (SELECT coder_number, coder_name, project_id, sum(finals) AS finals FROM ai_coder WHERE month = (date_trunc('month', CURRENT_DATE)::date - interval '1 month')::date GROUP BY coder_number, coder_name, project_id HAVING sum(finals) > 0), p AS (SELECT project_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY finals) AS median_finals FROM c GROUP BY project_id) SELECT c.coder_name, c.project_id, c.finals, round(p.median_finals::numeric, 1) AS project_median, rank() OVER (PARTITION BY c.project_id ORDER BY c.finals DESC) AS rank FROM c JOIN p ON p.project_id = c.project_id ORDER BY c.finals DESC
```

## Which coders give an unknown cause most often, against peers?

Key `coder_unknown_share`. Share of each coder's finals in the cause-unknown section, against the project average of coders.

```sql
WITH c AS (SELECT coder_number, coder_name, project_id, sum(finals) AS finals, round(100.0 * sum(unknown_cause) / NULLIF(sum(finals), 0), 1) AS unknown_pct FROM ai_coder GROUP BY coder_number, coder_name, project_id HAVING sum(finals) >= 10) SELECT c.*, round(avg(unknown_pct) OVER (PARTITION BY project_id), 1) AS peer_average FROM c ORDER BY unknown_pct DESC NULLS LAST
```

## Which coders disagree most with SmartVA, against peers?

Key `coder_smartva_disagreement`. Share of each coder's finals whose WHO cause differs from SmartVA's top cause, where SmartVA gave one, against the project average.

```sql
WITH c AS (SELECT coder_number, coder_name, project_id, sum(smartva_compared) AS compared, round(100.0 - 100.0 * sum(smartva_match) / NULLIF(sum(smartva_compared), 0), 1) AS disagree_pct FROM ai_coder GROUP BY coder_number, coder_name, project_id HAVING sum(smartva_compared) >= 10) SELECT c.*, round(avg(disagree_pct) OVER (PARTITION BY project_id), 1) AS peer_average FROM c ORDER BY disagree_pct DESC NULLS LAST
```

## Whose finals are most often changed by a reviewer?

Key `coder_reviewer_changes`. Per coder: finals a reviewer also coded and the share where the reviewer's code differs, against the project average.

```sql
WITH c AS (SELECT coder_number, coder_name, project_id, sum(reviewer_finals) AS reviewed, round(100.0 * sum(reviewer_changed) / NULLIF(sum(reviewer_finals), 0), 1) AS changed_pct FROM ai_coder GROUP BY coder_number, coder_name, project_id HAVING sum(reviewer_finals) > 0) SELECT c.*, round(avg(changed_pct) OVER (PARTITION BY project_id), 1) AS peer_average FROM c ORDER BY changed_pct DESC NULLS LAST
```

## Which coders mark the most cases not codeable?

Key `coder_not_codeable`. Per coder: cases marked not codeable and their share of the coder's finals plus marks, against the project average.

```sql
WITH c AS (SELECT coder_number, coder_name, project_id, sum(not_codeable) AS not_codeable, round(100.0 * sum(not_codeable) / NULLIF(sum(finals) + sum(not_codeable), 0), 1) AS not_codeable_pct FROM ai_coder GROUP BY coder_number, coder_name, project_id HAVING sum(finals) + sum(not_codeable) >= 10) SELECT c.*, round(avg(not_codeable_pct) OVER (PARTITION BY project_id), 1) AS peer_average FROM c ORDER BY not_codeable_pct DESC NULLS LAST
```

## Which coders appear to copy SmartVA?

Key `coder_smartva_copying`. Per coder: share of finals matching SmartVA's top WHO cause, the same share when SmartVA's likelihood is low ('Somewhat Likely' or 'Possible'), exact ICD-10 matches and finals under 3 minutes, against the project average of the low-likelihood share. High agreement when SmartVA is unsure, with fast finals, is the strongest signal.

```sql
WITH c AS (SELECT coder_number, coder_name, project_id, sum(finals) AS finals, round(100.0 * sum(smartva_match) / NULLIF(sum(smartva_compared), 0), 1) AS match_pct, round(100.0 * sum(smartva_match_low_likelihood) / NULLIF(sum(smartva_low_likelihood), 0), 1) AS match_when_unlikely_pct, round(100.0 * sum(exact_icd_match) / NULLIF(sum(smartva_compared), 0), 1) AS exact_icd_pct, round(100.0 * sum(finals_under_3_min) / NULLIF(sum(timed_finals), 0), 1) AS under_3_min_pct FROM ai_coder GROUP BY coder_number, coder_name, project_id HAVING sum(smartva_compared) >= 10) SELECT c.*, round(avg(match_when_unlikely_pct) OVER (PARTITION BY project_id), 1) AS peer_average FROM c ORDER BY match_when_unlikely_pct DESC NULLS LAST
```

## Which coders get the most DORIS flags?

Key `coder_doris_flags`. Per coder in ICD-11 DORIS projects: finals checked by DORIS, rejections, warnings, age/sex confirmations, causing-condition-unknown uses and finals that differ from DORIS's underlying cause.

```sql
SELECT coder_name, project_id, sum(doris_checked) AS checked, sum(doris_rejections) AS rejections, sum(doris_warnings) AS warnings, sum(age_sex_confirmations) AS age_sex_confirmations, sum(causing_condition_unknown) AS causing_condition_unknown, sum(doris_overridden) AS overrides FROM ai_coder GROUP BY coder_number, coder_name, project_id HAVING sum(doris_checked) > 0 ORDER BY sum(doris_rejections) + sum(doris_warnings) DESC
```

## Which coders give an unknown cause most often in neonatal deaths?

Key `coder_neonatal_unknown`. Share of each coder's neonatal finals in the cause-unknown section, against the project average.

```sql
WITH c AS (SELECT coder_number, coder_name, project_id, sum(neonate_finals) AS neonatal_finals, round(100.0 * sum(neonate_unknown_cause) / NULLIF(sum(neonate_finals), 0), 1) AS unknown_pct FROM ai_coder GROUP BY coder_number, coder_name, project_id HAVING sum(neonate_finals) >= 5) SELECT c.*, round(avg(unknown_pct) OVER (PARTITION BY project_id), 1) AS peer_average FROM c ORDER BY unknown_pct DESC NULLS LAST
```

## How many users were granted a role but have never signed in?

Key `never_signed_in_by_role`. Active users per role and the number and share who have never signed in.

```sql
SELECT role, sum(staff) AS staff, sum(never_signed_in) AS never_signed_in, round(100.0 * sum(never_signed_in) / NULLIF(sum(staff), 0), 1) AS never_pct FROM ai_staff WHERE coding_language IS NULL GROUP BY role ORDER BY never_signed_in DESC
```

## Which sites have dormant grants for 30 days?

Key `dormant_grants_by_site`. Users granted over 30 days ago who have not signed in for 30 days, per project, site and role.

```sql
SELECT project_id, site_id, role, sum(staff) AS staff, sum(dormant_30d) AS dormant_30d FROM ai_staff WHERE coding_language IS NULL GROUP BY project_id, site_id, role HAVING sum(dormant_30d) > 0 ORDER BY dormant_30d DESC
```

## How many users have an unverified email, by role?

Key `unverified_email_by_role`. Active users per role whose email is not verified.

```sql
SELECT role, sum(staff) AS staff, sum(unverified_email) AS unverified_email FROM ai_staff WHERE coding_language IS NULL GROUP BY role ORDER BY unverified_email DESC
```

## Are newly granted users signing in?

Key `new_grants_activation`. Users granted in the last 30 days per role, against those signed in within 7 days and those never signed in.

```sql
SELECT role, sum(granted_30d) AS granted_30d, sum(signed_in_7d) AS signed_in_7d, sum(never_signed_in) AS never_signed_in FROM ai_staff WHERE coding_language IS NULL GROUP BY role HAVING sum(granted_30d) > 0 ORDER BY granted_30d DESC
```

## Which units have a coder but no interviewer, or an interviewer but no coder?

Key `units_coder_no_interviewer`. Org units holding unit grants, with coders and interviewers granted at that unit, where one of the two is missing.

```sql
SELECT project_id, coalesce(org_l7_name, org_l6_name, org_l5_name, org_l4_name, org_l3_name, org_l2_name, org_l1_name) AS unit_name, coalesce(sum(staff) FILTER (WHERE role = 'coder'), 0) AS coders, coalesce(sum(staff) FILTER (WHERE role = 'interviewer'), 0) AS interviewers FROM ai_staff WHERE coding_language IS NULL AND org_l1_name IS NOT NULL GROUP BY 1, 2 HAVING coalesce(sum(staff) FILTER (WHERE role = 'coder'), 0) = 0 OR coalesce(sum(staff) FILTER (WHERE role = 'interviewer'), 0) = 0 ORDER BY 1, 2
```

## Which sub-centres have cases but no interviewer?

Key `subcentres_without_interviewer`. Level-5 units (sub-centres) with cases, with no interviewer granted at that unit.

```sql
WITH u AS (SELECT project_id, org_l1_name, org_l5_name, sum(n) AS cases FROM ai_cube WHERE org_l5_name IS NOT NULL GROUP BY project_id, org_l1_name, org_l5_name), i AS (SELECT project_id, org_l1_name, org_l5_name, sum(staff) AS interviewers FROM ai_staff WHERE role = 'interviewer' AND coding_language IS NULL AND org_l5_name IS NOT NULL GROUP BY project_id, org_l1_name, org_l5_name) SELECT u.org_l5_name, u.org_l1_name, u.project_id, u.cases FROM u LEFT JOIN i ON i.project_id = u.project_id AND i.org_l1_name IS NOT DISTINCT FROM u.org_l1_name AND i.org_l5_name = u.org_l5_name WHERE i.interviewers IS NULL ORDER BY u.cases DESC
```

## Which districts with cases have no coder or no interviewer?

Key `districts_workforce_coverage`. Level-1 units (districts) with cases against coders and interviewers granted inside that district. Project and site grants are not counted here.

```sql
WITH d AS (SELECT project_id, org_l1_name, sum(n) AS cases FROM ai_cube WHERE org_l1_name IS NOT NULL GROUP BY project_id, org_l1_name), s AS (SELECT project_id, org_l1_name, sum(staff) FILTER (WHERE role = 'coder') AS coders, sum(staff) FILTER (WHERE role = 'interviewer') AS interviewers FROM ai_staff WHERE coding_language IS NULL AND org_l1_name IS NOT NULL GROUP BY project_id, org_l1_name) SELECT d.org_l1_name, d.project_id, d.cases, coalesce(s.coders, 0) AS coders, coalesce(s.interviewers, 0) AS interviewers FROM d LEFT JOIN s ON s.project_id = d.project_id AND s.org_l1_name = d.org_l1_name ORDER BY coalesce(s.coders, 0) + coalesce(s.interviewers, 0), d.cases DESC
```

## Which districts have staff who have not started training?

Key `training_by_district`. Users granted in each district, those added to a training session and those who started one. DigitVA does not record training completion.

```sql
SELECT org_l1_name, project_id, sum(staff) AS staff, sum(in_training) AS in_training, sum(training_started) AS training_started FROM ai_staff WHERE coding_language IS NULL AND org_l1_name IS NOT NULL GROUP BY project_id, org_l1_name ORDER BY sum(staff) - sum(training_started) DESC
```

## Which coders lack a coding language?

Key `coders_without_language`. Coders with no coding language set, per project and site.

```sql
SELECT project_id, site_id, sum(staff) AS coders, sum(no_coding_language) AS no_coding_language FROM ai_staff WHERE role = 'coder' AND coding_language IS NULL GROUP BY project_id, site_id ORDER BY no_coding_language DESC
```

## What are the top causes by district, against the state?

Key `top_causes_by_district`. The five most frequent WHO causes in each level-1 unit (district), with the district share and the project (state) share of the same cause.

```sql
WITH d AS (SELECT project_id, org_l1_name, authoritative_who_bucket, sum(n) AS deaths FROM ai_cube WHERE org_l1_name IS NOT NULL AND authoritative_who_bucket IS NOT NULL GROUP BY project_id, org_l1_name, authoritative_who_bucket), r AS (SELECT project_id, org_l1_name, authoritative_who_bucket, deaths, round(100.0 * deaths / NULLIF(sum(deaths) OVER (PARTITION BY project_id, org_l1_name), 0), 1) AS district_pct, round(100.0 * sum(deaths) OVER (PARTITION BY project_id, authoritative_who_bucket) / NULLIF(sum(deaths) OVER (PARTITION BY project_id), 0), 1) AS state_pct, row_number() OVER (PARTITION BY project_id, org_l1_name ORDER BY deaths DESC) AS position FROM d) SELECT org_l1_name, authoritative_who_bucket, deaths, district_pct, state_pct, project_id FROM r WHERE position <= 5 ORDER BY project_id, org_l1_name, deaths DESC
```

## How many maternal deaths were there by district and month?

Key `maternal_deaths_by_district_month`. Deaths in the pregnancy, childbirth and puerperium section per level-1 unit (district) and submission month.

```sql
SELECT org_l1_name, submission_month, sum(n) AS maternal_deaths FROM ai_cube WHERE authoritative_who_bucket_section = 'Pregnancy-, childbirth and puerperium-related disorders' GROUP BY org_l1_name, submission_month ORDER BY org_l1_name, submission_month
```

## Are neonatal and child deaths by district above or below the state rate?

Key `neonatal_child_by_district`. Neonatal and child deaths as a share of all deaths per level-1 unit (district), against the project (state) share.

```sql
WITH d AS (SELECT project_id, org_l1_name, sum(n) AS deaths, sum(n) FILTER (WHERE analytics_age_band = 'neonate') AS neonatal, sum(n) FILTER (WHERE analytics_age_band = 'child') AS child FROM ai_cube WHERE org_l1_name IS NOT NULL GROUP BY project_id, org_l1_name) SELECT org_l1_name, project_id, deaths, round(100.0 * neonatal / NULLIF(deaths, 0), 1) AS neonatal_pct, round(100.0 * child / NULLIF(deaths, 0), 1) AS child_pct, round(100.0 * sum(neonatal) OVER (PARTITION BY project_id) / NULLIF(sum(deaths) OVER (PARTITION BY project_id), 0), 1) AS state_neonatal_pct, round(100.0 * sum(child) OVER (PARTITION BY project_id) / NULLIF(sum(deaths) OVER (PARTITION BY project_id), 0), 1) AS state_child_pct FROM d ORDER BY neonatal_pct NULLS LAST
```

## Injury and suicide deaths by district, sex and age

Key `injury_suicide_by_district`. External-cause and intentional self-harm deaths per level-1 unit (district), by sex and among 15 to 49 year olds.

```sql
SELECT org_l1_name, sum(n) AS injury_deaths, sum(n) FILTER (WHERE authoritative_who_bucket = 'Intentional self-harm') AS self_harm, sum(n) FILTER (WHERE lower(sex) = 'male') AS male, sum(n) FILTER (WHERE lower(sex) = 'female') AS female, sum(n) FILTER (WHERE analytics_age_band = '15_49y') AS age_15_49 FROM ai_cube WHERE authoritative_who_bucket_section = 'External causes of death' GROUP BY org_l1_name ORDER BY injury_deaths DESC
```

## Which districts have the highest unknown-cause share?

Key `unknown_share_by_district`. Coded deaths in the cause-unknown section as a share of coded deaths per level-1 unit (district), against the project share.

```sql
WITH d AS (SELECT project_id, org_l1_name, sum(n) FILTER (WHERE authoritative_who_bucket_section IS NOT NULL) AS coded, sum(n) FILTER (WHERE authoritative_who_bucket_section = 'Cause of death unknown') AS unknown FROM ai_cube WHERE org_l1_name IS NOT NULL GROUP BY project_id, org_l1_name) SELECT org_l1_name, project_id, coded, round(100.0 * unknown / NULLIF(coded, 0), 1) AS unknown_pct, round(100.0 * sum(unknown) OVER (PARTITION BY project_id) / NULLIF(sum(coded) OVER (PARTITION BY project_id), 0), 1) AS state_pct FROM d ORDER BY unknown_pct DESC NULLS LAST
```

## How many VA cases does each district have, and which have none recently?

Key `cases_per_district`. Cases, coded cases and the last case month per level-1 unit (district). Districts that never sent a case do not appear.

```sql
SELECT org_l1_name, project_id, sum(n) AS cases, sum(n) FILTER (WHERE authoritative_source IS NOT NULL) AS coded, max(submission_month) AS last_case_month FROM ai_cube GROUP BY project_id, org_l1_name ORDER BY cases DESC
```

## Which sub-centres report fewer deaths than comparable units?

Key `underreporting_subcentres`. Deaths per level-5 unit (sub-centre) in the last three months against the median sub-centre of the same district and against its own previous three months.

```sql
WITH u AS (SELECT project_id, org_l1_name, org_l5_name, coalesce(sum(n) FILTER (WHERE submission_month >= (date_trunc('month', CURRENT_DATE)::date - interval '3 months')::date), 0) AS last_3_months, coalesce(sum(n) FILTER (WHERE submission_month >= (date_trunc('month', CURRENT_DATE)::date - interval '6 months')::date AND submission_month < (date_trunc('month', CURRENT_DATE)::date - interval '3 months')::date), 0) AS prior_3_months FROM ai_cube WHERE org_l5_name IS NOT NULL GROUP BY project_id, org_l1_name, org_l5_name), p AS (SELECT project_id, org_l1_name, percentile_cont(0.5) WITHIN GROUP (ORDER BY last_3_months) AS district_median FROM u GROUP BY project_id, org_l1_name) SELECT u.org_l5_name, u.org_l1_name, u.project_id, u.last_3_months, u.prior_3_months, round(p.district_median::numeric, 1) AS district_median FROM u JOIN p ON p.project_id = u.project_id AND p.org_l1_name IS NOT DISTINCT FROM u.org_l1_name ORDER BY u.last_3_months - p.district_median
```

## Which districts report few neonatal, female or maternal deaths compared with the state?

Key `underreporting_groups_by_district`. Neonatal, female and maternal deaths as shares of all deaths per level-1 unit (district), against the project (state) shares.

```sql
WITH d AS (SELECT project_id, org_l1_name, sum(n) AS deaths, sum(n) FILTER (WHERE analytics_age_band = 'neonate') AS neonatal, sum(n) FILTER (WHERE lower(sex) = 'female') AS female, sum(n) FILTER (WHERE authoritative_who_bucket_section = 'Pregnancy-, childbirth and puerperium-related disorders') AS maternal FROM ai_cube WHERE org_l1_name IS NOT NULL GROUP BY project_id, org_l1_name) SELECT org_l1_name, project_id, deaths, round(100.0 * female / NULLIF(deaths, 0), 1) AS female_pct, round(100.0 * sum(female) OVER (PARTITION BY project_id) / NULLIF(sum(deaths) OVER (PARTITION BY project_id), 0), 1) AS state_female_pct, round(100.0 * neonatal / NULLIF(deaths, 0), 1) AS neonatal_pct, round(100.0 * maternal / NULLIF(deaths, 0), 1) AS maternal_pct FROM d ORDER BY female_pct NULLS FIRST
```

## How often does SmartVA agree with the physician by district?

Key `smartva_agreement_by_district`. Share of coded deaths where SmartVA's top WHO cause equals the final cause, per level-1 unit (district), against the project share.

```sql
WITH d AS (SELECT project_id, org_l1_name, sum(n) FILTER (WHERE smartva_cause1_who_bucket IS NOT NULL AND authoritative_who_bucket IS NOT NULL) AS compared, sum(n) FILTER (WHERE smartva_cause1_who_bucket = authoritative_who_bucket) AS agree FROM ai_cube WHERE org_l1_name IS NOT NULL GROUP BY project_id, org_l1_name) SELECT org_l1_name, project_id, compared, round(100.0 * agree / NULLIF(compared, 0), 1) AS agreement_pct, round(100.0 * sum(agree) OVER (PARTITION BY project_id) / NULLIF(sum(compared) OVER (PARTITION BY project_id), 0), 1) AS state_pct FROM d ORDER BY agreement_pct NULLS LAST
```

## Is there a seasonal pattern in infectious deaths?

Key `infectious_by_calendar_month`. Infectious and parasitic disease deaths per calendar month, this year and last year.

```sql
SELECT extract(month FROM submission_month)::int AS month_no, sum(n) FILTER (WHERE extract(year FROM submission_month) = extract(year FROM CURRENT_DATE)) AS this_year, sum(n) FILTER (WHERE extract(year FROM submission_month) = extract(year FROM CURRENT_DATE) - 1) AS last_year FROM ai_cube WHERE authoritative_who_bucket_section = 'Infectious and parasitic diseases' GROUP BY 1 ORDER BY month_no
```

## How does each site's cause mix compare with the project mix?

Key `cause_mix_site_vs_project`. Share of coded deaths per WHO cause section at each site against the same share for all sites.

```sql
WITH s AS (SELECT site_id, authoritative_who_bucket_section AS section, sum(n) AS deaths FROM ai_cube WHERE authoritative_who_bucket_section IS NOT NULL GROUP BY site_id, authoritative_who_bucket_section) SELECT site_id, section, deaths, round(100.0 * deaths / NULLIF(sum(deaths) OVER (PARTITION BY site_id), 0), 1) AS site_pct, round(100.0 * sum(deaths) OVER (PARTITION BY section) / NULLIF(sum(deaths) OVER (), 0), 1) AS all_sites_pct FROM s ORDER BY site_id, deaths DESC
```
