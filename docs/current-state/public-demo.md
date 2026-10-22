---
title: Public Demo Reports, Downloads And Dashboard
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-22
---

# Public demo reports, downloads and dashboard

Policy: [public-demo.md](../policy/public-demo.md) sections 5 to 7. Accounts,
sign-up, confinement and limits are in
[authentication-and-onboarding.md](authentication-and-onboarding.md). Everything
here answers 404 unless `PUBLIC_DEMO_ENABLED`.

## Routes

One blueprint, `public_demo` (`app/routes/public_demo.py`), registered always
and gated by the flag in each view. All GET: no CSRF surface.

| Route | Who | Answer |
| --- | --- | --- |
| `/public-demo/cases` | signed-in public-demo account | its submitted cases, newest first, with pipeline state and a report link |
| `/public-demo/cases/<va_sid>/report` | the submitter | the report page, printable (`@media print`, Print button) |
| `/api/v1/public-demo/my-responses.csv` and `.json` | the same | own responses and report fields |
| `/public-demo/dashboard` | anyone | aggregate page |
| `/api/v1/public-demo/dashboard.json` | anyone | the same figures |

The personal routes use `login_required`. Any account that is not a
public-demo account (admins included) and any case that is not the caller's,
existing or not, is one 404. The report page asks `authz.can(VIEW)` first (for a
demo account that includes the own-case predicate, `authz.predicates._own_cases`).
The two dashboard routes are on `PUBLIC_ENDPOINTS`
(`app/services/authz/consulted.py`). Personal responses carry
`Cache-Control: no-store`; the dashboard `public, max-age=60`.

## Reading a report (`app/services/public_demo_report_service.py`)

`own_reports(user)` feeds the list, the report and the downloads: a fixed number of queries
whatever the number of cases (eight at most: cases, SmartVA, coder finals, reviewer finals, the authority pointers and the finals they name, answers), bounded by `LIST_LIMIT` (200). It first builds
`scope_filter(user, VIEW)`, then joins the user's own `submitted` draft on the
demo project.

| Section | Source |
| --- | --- |
| Deceased: age, sex, interview date | `va_submissions` (`va_deceased_age_normalized_years/_days`, `va_deceased_gender`, `va_submission_date`); submitted time from `va_web_intake_drafts.submitted_at` |
| Pipeline state | `va_submission_workflow.workflow_state`, mapped by `PIPELINE` (a test holds its keys equal to every workflow state) |
| SmartVA | the active `va_smartva_results` row: `va_smartva_cause1..3`, `likelihood1..3`, `cause1icd..3icd`, `va_smartva_outcome` |
| Coder's final | the newest active `va_final_assessments` row (not a tester's) for the active payload version, or the row `va_final_cod_authority` points at when it names one (same rule as `final_cod_authority_service.get_authoritative_final_cod_record`, `_apply_authority`): code and title from `icd11_provenance["conclusive"]`, Part I and II from `doris_certificate` (else `va_immediate_cod`, `va_other_conditions`) |
| Reviewer's final | the same from `va_reviewer_final_assessments`; a valid reviewer pointer wins and names the coder final it superseded, a valid coder pointer alone hides the reviewer verdict |
| Answers (download only) | `va_submission_payload_versions.payload_data` of the active version |

A cause's title is the stored provenance title, never the text typed after the
code. The report page does show the caller's own coder text: the DORIS
certificate's condition text and, in the simple mode, `va_immediate_cod` and
`va_other_conditions`. Sealed death-register PII is not read. If the deployment turns on
`PAYLOAD_PII_SPLIT_ENABLED`, the fields split out of the payload are not in
`payload_data` and so are not downloaded.

## Downloads

Rate limit `PUBLIC_DEMO_DOWNLOAD_RATE_LIMIT` (default `10 per hour`), one bucket
per user shared by CSV and JSON; one running download per user
(`cache.add("public-demo-export:<user_id>")`, released in `finally`); one
`auth_security_events` row (`event_type = public_demo_download`, detail `format`
and `cases` only). CSV cells go through `case_export_service.safe_cell` (a
leading apostrophe on `= + - @`, tab, CR, LF); the answers are one JSON cell.

## Dashboard (`app/services/public_demo_dashboard_service.py`)

Aggregates over the demo project's forms only: active public-demo accounts,
submissions, coded (the area dashboard's "coded" bucket), reviewed
(`reviewer_finalized`), SmartVA cause shares and coder ICD-11 cause shares (top
10 and "other"), age bands and sex. Five aggregate queries; the result is cached
for 5 minutes (`PUBLIC_DEMO_DASHBOARD_CACHE_SECONDS`) under
`public_demo:dashboard:v1`, namespaced by `CACHE_KEY_PREFIX`. No case row, id,
username or free text; bars are `<progress>` elements with the numbers beside
them. The page is `public, max-age=60` for an anonymous viewer and
`private, no-store` for a signed-in one (the navbar is personal); the JSON is
always public.

## Tests

`tests/test_public_demo_report.py`, `tests/test_public_demo_dashboard.py`.
