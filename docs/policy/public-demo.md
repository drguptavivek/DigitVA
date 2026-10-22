---
title: Public Demo
doc_type: policy
status: approved baseline
owner: engineering
last_updated: 2026-10-22
---

# Public demo

Owner decisions of 2026-10-22 (digitva-77v5). Design and phases:
`.tasks/2026-10-22-public-demo.md`.

Anyone may try the whole system from a user's side: collect a verbal autopsy
(web, or the Android app digitva-collect) with respondent consent, audio
narration and document uploads; code it (ICD-11 with DORIS) and review it
themselves; see a cause-of-death report for every submission; download their
own responses; and see a public dashboard of demo totals.

This is the one place where people sign themselves up. The sign-up and
password rules are a scoped exception to
[account-onboarding-and-passwords.md](account-onboarding-and-passwords.md)
sections 1 and 3, and the own-data download is an exception to the exports
rule in [web-intake.md](web-intake.md). Nothing else in those policies changes.

## 1. Deployment and the flag

- A dedicated demo deployment, built from the same app image as the main app,
  with its own app, Celery worker and Celery beat services, its **own Redis**
  and its **own Postgres database**. It shares only the WHO ICD-11/DORIS API
  container.
- **Real VA data never lives on the demo database.** The demo database is
  never restored from, synced with or pointed at the main one.
- Host under `causeofdeathindia.com` (for example `demo.causeofdeathindia.com`),
  so release builds of digitva-collect accept it
  (`mobile/digitva-collect/src/enrolment.ts` allows any https
  `*.causeofdeathindia.com`).
- Everything in this policy sits behind one config flag,
  `PUBLIC_DEMO_ENABLED` (default off). With it off, none of the public-demo
  routes exist (404), the demo enrolment endpoint does not exist, the purge
  task does nothing, and no account can be created by sign-up. The main
  deployment never sets it.

## 2. Accounts

- Self sign-up with a **username and a password the user chooses**. No email,
  no mobile number.
- Username: 3 to 30 characters; lowercase letters, digits, dot, underscore and
  hyphen; must start with a letter, so it is never read as a 10-digit mobile
  number by the sign-in identifier branch; unique ignoring case.
- Password: at least 12 characters; checked against the breach list
  ([password-breach-checks.md](password-breach-checks.md)); not equal to the
  username. It is stored only as a hash.
- Sign-up shows the existing proof-of-work CAPTCHA and a notice the user must
  accept: this is a public demo; do not enter real personal or health data;
  entries are visible to the demo team; the account and its data are deleted
  30 days after the last sign-in.
- The account records `other.created_via = "self_signup"` (already reserved in
  `app/services/user_account_service.py`, `creation_other`) and is marked as a
  public-demo account.
- **No password reset**, since there is no email: a forgotten password means a
  new account.
- Sign-in is the existing password sign-in, with a username branch. Existing
  login limits are unchanged.

## 3. Confinement

- A public-demo account holds **exactly** `interviewer`, `coder` and
  `reviewer` on the public demo project, granted at sign-up.
- Any other grant for such an account is refused when it is written: a
  database-session guard checks every new or reactivated grant row, whatever
  code path writes it (admin pages, imports, CLI, seeds). This is enforced
  server-side, not in the UI. A demo account can never be made admin,
  PI, data manager or anything else, and holds no grant on any other project.
- Such accounts are excluded from the `demo_training_enabled` virtual
  coder/reviewer grants (`app/services/authz/grants.py`, `_resolve`), so those
  grants cannot widen what a demo account can do.
- **Isolation.** On the public demo project a user codes and reviews only
  submissions they submitted themselves. The restriction sits in the shared
  submission scope filter, so it covers viewing a case, its attachments,
  coding and review queues, allocation and every list, not only the queues; a
  guessed case or death-register id is refused. Nobody sees another person's
  entries. Pages that list people or show per-person or project-wide figures
  (people and roles, area dashboard and the like) are refused to demo
  accounts; the public dashboard (section 7) is the only aggregate view. The existing rule that a coder who also reviews may review their
  own case is unchanged; here it is the only case they can see.

## 4. The public demo project

Created by the idempotent CLI `flask public-demo setup`, modelled on
`app/services/training_demo_service.py`. A project in organization mode:

- web intake mode `both`; self-coding enabled;
- ICD-11 with DORIS; masked cause of death not required;
- narrative quality assessment and social autopsy off;
- medical records and death summary extensions on;
- narration languages English and Hindi (this turns on audio narration);
- respondent consent required, with the seeded English and Hindi notice,
  approved for demo use: the demo collects no real data, so the notice is
  approved by the owner for that use only (`app/services/consent_service.py`:
  `save_settings`, `seed_notice_versions`, `approve_notice_version`);
- recode window 5 minutes, and the sweep that makes a coded case reviewable
  runs every few minutes on the demo deployment (hourly elsewhere), so the
  same user can review soon after coding;
- one organization unit, used by every demo draft (the project has levels, and
  a draft needs a unit).

## 5. Cause-of-death report

Every completed submission gets SmartVA (already queued after a web submit). A
per-submission report page, visible only to the submitter, shows:

- the SmartVA result: cause and likelihoods as stored;
- the coder's final ICD-11 underlying cause from DORIS, once coded;
- the reviewer's verdict, once reviewed;
- the pipeline state: waiting for SmartVA, ready to code, coded, reviewed.

It is printable through the browser. No PDF library is added.

## 6. Download of own responses

A public-demo user may download their own submissions' responses as CSV and
JSON (answers plus the report fields). This is rate-limited (default 10 per
hour) and audited, and never returns another user's data.

## 7. Public dashboard

A public page, no login, aggregates only over the demo project:

- numbers of accounts, submissions, coded and reviewed;
- cause-of-death fractions (SmartVA and coder);
- age band and sex counts.

No case rows, no free text, no usernames. Small-cell suppression is not
needed because the data is synthetic, but no individual record may be shown.
The page is cached (default 5 minutes).

## 8. Limits

Defaults, all configurable:

| Limit | Default |
| --- | --- |
| Sign-up proof of work | required on the web form and on the app's JSON sign-up |
| Sign-ups per IP (IPv6 per /64) | 30 per hour, 200 per day |
| Sign-ups across the whole demo | 100 per hour |
| Active public-demo accounts | 500 (owner 2026-10-22); see eviction below |
| Submissions per account | 5 per day, 10 in total (owner 2026-10-22) |
| Drafts started per account | 3 open; 10 per day and 30 in total, whatever their status |
| Attachments (demo project) | 10 MB per file, 6 files per draft |
| Death registrations per account | 5 per day, 25 in total |
| ICD-11 lookups | 300 per hour per account; 2000 per hour across all demo accounts |
| Downloads | 10 per hour |
| Devices per account (Android) | 3 active; enrolling a 4th (after the password is checked) revokes the account's least recently used phone |

**Eviction at the cap (owner 2026-10-22).** When 500 accounts exist and someone
signs up, the account with the oldest last sign-in (or creation, if never
signed in) is deleted with everything it created, exactly as the 30-day purge
deletes (section 9), but only if it has been idle at least 7 days. If no
account has been idle that long, sign-up is refused with "The demo is full;
try again later." Eviction runs inside the sign-up transaction under the
account-cap lock and is audited like the purge (counts only). While the purge
is switched off (`PUBLIC_DEMO_PURGE_ENABLED`, section 9), sign-up at the cap
is refused.

Per-IP limits are a loose backstop only: Indian mobile networks put many users
behind one carrier-grade NAT address, and a training room shares one Wi-Fi
address, so a tight per-IP limit would lock out real people. The proof of work
(a cost per account, whatever the address), the demo-wide hourly limit and the
account cap carry the load.

Existing login limits are unchanged. Per-account limits are counted under a
per-account lock, so parallel requests cannot exceed them. Usernames such as
`admin`, `support` or `digitva`, and their variants with `.`, `_` or `-`, are
reserved.

## 8a. Isolation from the main deployment

- Own Redis and own Postgres database (section 1). In addition, with
  `PUBLIC_DEMO_ENABLED` every Redis use is namespaced (cache prefix, rate-limit
  key prefix, Celery broker and result key prefix) and Celery uses its own
  queue `demo`, so even a demo deployment pointed at the main Redis by mistake
  cannot read or consume the main deployment's keys or tasks.
- The demo's Celery beat schedules only the tasks the demo needs (SmartVA,
  coding sweeps, upload and demo purges); ODK sync and other main-only jobs
  are not scheduled.
- The demo services run with memory and CPU limits on the shared host; their
  data directories, SmartVA run folders and attachment storage are separate.
- The WHO ICD-11/DORIS container is shared; the demo-wide ICD limit above
  keeps demo users from starving the main deployment's coders.

## 9. Retention

An account and everything it created (drafts, submissions, payload versions,
attachments and their stored files, SmartVA results, coding, reviews, grants,
sessions and devices, and its own PII-access log rows) is deleted **30 days
after its last activity** by a daily audited task. Last activity is the latest
of its last sign-in, its creation, and its app's last session refresh, so an
account in active use on a phone is not deleted. The task is hard-guarded: it
touches only public-demo accounts and demo-project data, refuses an account
with anything outside the demo project or a case shared with another account,
runs only with `PUBLIC_DEMO_ENABLED` and `PUBLIC_DEMO_PURGE_ENABLED`, and
refuses on a database that holds any other project. Security events are kept
with the user reference cleared. Dashboard counts may drop
accordingly. The audit records counts, never usernames or content.

The 30-day deletion is an owner decision (2026-10-22). Real data never lives
on this database (section 1). The demo database is backed up nightly (owner
2026-10-22), so a purge can be recovered from the previous night's backup; the
purge stays off on any deployment whose backup is not in place.

## 10. Android

digitva-collect gets a "Try the demo" path: sign up or sign in with username
and password and enrol the device against the demo server **without a QR
code**, through a demo enrolment endpoint that exists only when
`PUBLIC_DEMO_ENABLED`. A huge public enrolment code is not used
(`enrol_device` caps `max_uses` at 200, `app/services/device_auth_service.py`
`ENROLMENT_MAX_USES`). Devices per account are limited (section 8). The
rest of the app and its device-token rules are unchanged.

## 11. Open item

The WHO ICD-11 API terms for anonymous public use must be checked by the
owner before launch. Not decided.
