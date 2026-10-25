---
title: Training and Demo Project (TRN01)
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-25
---

# Training and demo project (TRN01)

A permanent, signed-in organization project for training new staff in every
role (death reporter, interviewer, interview supervisor, coder, reviewer and
data manager) on realistic, consented, pseudonymised cases. It is separate from
the weekly synthetic demo (`DEMO01`, `docs/policy/organization-demo.md`), whose
reset and accounts are unchanged.

## What the project is

- Project `TRN01`, "Training & demo (WHO 2022, ICD-11)", organization mode,
  web-only (`web_intake_mode` `both`, no ODK mapping, no ODK form), questionnaire
  WHO_2022_VA, English forms only (`web_intake_available_locales` `["en"]`).
  Narration languages are `["english", "hindi"]`: the source narratives are
  Hindi (199 of the 200 in `UNSW01NC0101`). `setup` sets this on an existing
  TRN01 too.
- ICD-11 coding through DORIS (`icd_classification` `icd11`, `cod_entry_mode`
  `doris`), `masked_cod_required` off, narrative quality assessment off, social
  autopsy off for coders and reviewers, no intake welcome note, no ABHA.
  Enabled form extensions: `digitva_core`, `doris_support_whova_2022`,
  `narration_language`, `death_summary`, `medical_records`, `geography`.
  Coding intake is `pick_and_choose`.
- The coder recode window (`recode_window_minutes`) is 60 minutes, not the
  24-hour default (owner 2026-10-22), so a trainee's coded case reaches review
  within the training. `setup` sets it on a new TRN01 and resets it to 60 on an
  existing one; migration `c8e4a2f6b1d3` sets it on a TRN01 row that exists
  when it runs. See docs/policy/coding-workflow-state-machine.md ("Recode
  Window").
- It is not a `demo_training_enabled` project and is never reset: the demo
  virtual coder/reviewer grants do not apply to it, and nothing deletes its
  data. Training is on by default: `DIGITVA_TRAINING_PROJECT_ID` defaults to
  `TRN01` (owner 2026-10-22); an empty value turns it off. Setup requires the
  value `TRN01`.

## No generated accounts

There are no generated accounts, no passwords and no account expiry. Trainees
sign in with their own existing DigitVA accounts. The trainer (an admin)
creates a training session for each training and adds existing users to it
with a role. An unknown email is refused; the feature never creates a user.
After the training the admin grants the trainee access to their real project
through the ordinary grant screens; that is outside this feature.

## Training sessions

A session is one training. Sessions and everything in them are retained;
later trainings add more sessions. Sessions are numbered `S001`, `S002`, ... per
project.

Creating a session builds, in one transaction:

- a session root unit (PHC level, under a fixed training district and CHC) named
  after the session, and one child unit per coder slot at the sub-centre level,
  "Coder slot 01" onwards. The trainer chooses the number of coder slots when
  creating the session: 1 to 100, default 20 (a training may have 50 to 60
  coders). Each slot holds 10 cases, so a session has slots x 10 cases;
- a fresh copy, for each slot, of 10 cases taken from the real, consented ODK form
  `UNSW01NC0101` (project UNSW01, site NC01): the owner's frozen list of 200
  consented cases chosen at random on 2026-10-22,
  `app/services/training_corpus/UNSW01NC0101.txt` (one `va_sid` per line, line
  order is the case number). A listed case must still have an active payload
  version and valid consent, or the session is refused. A form without a list
  takes the first 200 eligible cases by `va_sid`. Slot `k` takes 10
  consecutive source cases, wrapping round the source list: when slots x 10 is
  more than the source cases, the same source case is copied into more than one
  slot (owner, 2026-10-22: the forms may be duplicated). A slot never holds one
  source case twice, and each further pass over the list starts three cases
  later so a later slot is not a copy of an earlier one. Every copy is its own
  case with its own pseudonymised payload and attachments. Case `n` goes to
  slot `((n-1)//10)+1`, and the copy's submission unit is that slot unit. Copies have new `va_sid` values (`trn-<session>-<n>`), new
  unique ids, and workflow state `ready_for_coding`. Source rows are never
  modified, and the source case's coding is never copied into the copy's
  assessment tables;
- `map_training_cases`, one row per copy, with the source case's authoritative
  final cause (ICD-10) as the answer key. The key is read only by the trainer
  report; it is never shown on a coder screen.

A session is refused when a listed source case is no longer eligible, or when
a form without a list has fewer than 10 eligible cases.

## Pseudonymisation

The copies are de-identified by replacing, not removing, personal data with
random synthetic values, consistently within a case: the same original value
becomes the same fake value everywhere in that case, including inside the
narrative (Id10476) and any other free-text answer where the original string
occurs (case-insensitive, whole word).

- Names (Id10007, Id10010, Id10017, Id10018, Id10061, Id10062): random common
  Indian first and last names from a built-in list (Devanagari names get
  Devanagari fakes). Initials and honorifics are kept as written.
- Addresses (Id10055, Id10057, visit_address, visit_remarks):
  "House n, Ward n, Synthetic Village n". In free text each place-name word
  (four letters or more, not a generic address word such as house, ward,
  road, village, near, nagar) of these values is replaced by one made-up place
  name per case.
- Phones and identifiers (Id10070 to Id10073, Id10010a/b/c, abha_*): random
  values of the same shape; Id10073 keeps its stored last-three-digits shape.
- All other answers, dates and ages are kept, so the clinical picture is
  unchanged.
- The random generator is seeded per case from the session and case number, so
  a rerun gives the same fakes. Logs carry counts only, never values.
- Indian phone numbers in free text (optional +91 or 0, ten digits, spaces or
  hyphens) are replaced by a random ten-digit number, the same one for the
  same number within a case.
- Word boundaries treat Devanagari and other Indic combining marks as part of
  a word, so Hindi names are found and replaced inside Hindi narratives.
- The payload's SubmitterID and DeviceID are replaced by fixed synthetic
  values and `death_register_id` is dropped.
- Limits of free text: only values that also appear in the structured fields
  are found. A name, place or number that appears only in a narrative, or in a
  form the matcher does not recognise (a different spelling or transliteration,
  an inflected form), stays. `flask training-demo check-source` (read-only,
  counts only) reports how many source cases still hold an original value
  after pseudonymisation; run it after changing the pseudonymiser.
- Attachment decision: attachments (narrative image, audio, medical-record
  images, death document images) are kept unchanged, because the originals
  were consented for this use and clinical coding needs them. Each copy gets
  its own attachment row and stored object holding the same bytes. Only
  attachments whose bytes DigitVA holds are copied; rows never downloaded from
  ODK are not, and session creation reports `attachments_copied`,
  `attachments_skipped` (stored object missing) and `attachments_not_stored`.
  They may
  show real details, so trainees are told not to copy, photograph or share
  them (public page, welcome page, help page).

## Participants and grants

Participant roles: `death_reporter`, `interview_supervisor`, `interviewer`,
`coder`, `reviewer_data_manager`.

- A user may be given several roles in one call (the panel's role checkboxes,
  `roles` in the API, a comma-separated list or repeated `--role` in the CLI;
  a single `role` is still accepted). Each (user, role) stays its own
  participation. The call is all or nothing in one transaction: if any role is
  refused (already active, no free slot, missing coder language, a grant the
  access rules refuse) nothing is written; an empty list is refused. Holding
  coder and reviewer_data_manager together is allowed, and in training a
  trainee may review a case they coded (owner decision 2026-10-22: "its
  training - let them"). The same holds in every project: a coder who also
  holds a reviewer role may review a case they coded (owner decision
  2026-10-22, digitva-54in); there is no self-review guard by design.
- A coder gets the next free coder slot (the slot stays theirs for the life of
  the session, even when removed) and a unit-scoped coder grant on that slot's
  unit, so they see exactly their 10 cases. A 21st coder is refused. A coder
  whose coding languages (`vacode_language`) lack a narration language of that
  slot's cases (for example Hindi) is refused with a message naming the
  missing language; add it to the user first.
- A death reporter, interview supervisor or interviewer gets a unit-scoped grant
  on the session root.
- A reviewer_data_manager gets both a reviewer and a data_manager unit-scoped
  grant on the session root and so sees the whole session.
- Grants are written through the ordinary rules (level by cadre, grants audit
  log). Training grants use a dedicated "Trainee" cadre defined for the TRN01
  levels. A user's grants on any other project are never touched.
- Removing a participant deactivates only their training grants; adding them
  again reactivates the same grants. Closing a session deactivates every
  participant's training grants; reopening reactivates those of participants who
  are still active. Nothing is deleted.

## Onboarding and the public page

`GET /demo` is a public page (no login) describing the training project, the
roles and what each can try, that trainees use their own accounts and are added
to a session by the trainer, that cases are consented and their text answers
pseudonymised, that photos, documents and audio are original and must not be
copied, photographed or shared, and that coders see only their own 10 cases
while the other roles see the whole session. It lists no users.

Training lives in the Expo app (owner, 2026-10-23, `digitva-r2pf`), not on a
Flask page. A signed-in user with an active participation in an active session
sees a **Training** item in the left menu (`navEntries`), and nobody else does.
Its sub-items follow the training roles the user holds:

| Sub-item | Roles that open it | Route |
| --- | --- | --- |
| Interview | `death_reporter`, `interviewer`, `interview_supervisor` | `/app/training/interview` |
| Coding | `coder` (the screen names the coder slot) | `/app/training/coding` |
| Review | `reviewer_data_manager` | `/app/training/reviewing` |

- `/app/training` is the overview: the confidentiality notice (cases are
  consented and their text answers pseudonymised; photos, documents and audio
  are original and must not be copied, photographed or shared), the session
  name and code, and the **Start** button. Start records `onboarded_at`
  (`complete_onboarding` and `remember_onboarding_checked`) and is idempotent.
- `/app/training/interview|coding|reviewing` show that area's checklist and its
  work list, which are the ordinary Interview, Coding and Review screens in a
  training scope (below).
- Training death reporting uses `/app/training/reporting`. Interview case
  details and forms use `/app/training/interview/case` and
  `/app/training/interview/form`; coding and review details use
  `/app/training/coding/case` and `/app/training/reviewing/case`.
  These reuse the ordinary screens under the training wrapper. The stable API
  permission areas remain `interview`, `coding`, and `review`; reporting uses
  the existing interview-area registration permissions. Legacy training URLs
  redirect into this namespace while retaining record and revision parameters.
- The JSON API is `GET /api/v1/training/me` (the participations, the areas to
  show, whether onboarding is pending) and `POST /api/v1/training/me/start`
  (browser writes carry `X-CSRFToken`, JSON included). The menu needs no
  request of its own: `GET /api/v1/me/access` carries `training`
  (`project_id`, `areas`, `pending`).
- The one-time redirect: while the Expo export is present (`export_ready()`),
  a trainee with a pending onboarding is sent once to `/app/training`
  (a Flask page load, or the Expo home itself, once per browser session until
  Start). `/app/` is never redirected to a Flask page. `/demo/welcome`
  redirects to `/app/training` when the export is present. Without the export
  it stays as a fallback page that says training is done in the DigitVA app and
  links to `/app/training`; its Start button opens `/app/training` too. It
  never links to a Flask work page. The public `/demo` page and the help pages
  link to `/app/training` when the export is present.

### Separation from real work

The training project and real work never mix in the Expo app, in either
direction, and the server enforces it (not only the menu):

- The Training sub-menus list only training-project forms and cases. The
  list, count and allocation endpoints the Expo screens call (coding,
  reviewing, intake worklist, registered deaths, supervision, Home blocks and
  activity counts) take `training=1`: it returns only the training project and
  needs an active participation in an active session with a role of that area
  (coding: `coder`; reviewing: `reviewer_data_manager`; intake: an interview
  role), else 403 `forbidden`. Without a participation, and with the feature
  off, nothing is returned.
- Without `training`, or with `training=0`, those endpoints exclude the
  training project for every user: its cases are never listed, counted or
  allocated, and asking for `project_id=TRN01` in that scope answers an empty
  list. A coder or reviewer pick, recode or "Code this case now" of a case in
  the other scope is refused (409 `not_available`). An intake write (register
  a death, start, sync, submit or discard a draft, a contact attempt, a
  supervision action ...) that names a project, death, draft or submission in
  the other scope is refused (409 `training_scope`); the Expo Training screens
  send `training=1` on every write. The native phone app sends no `training`,
  so it works real projects only: training is an Expo-web surface.
- **Training is Expo-only.** Every request runs in the exclude scope by
  default (Flask pages and API alike; the app-level default in
  `app/services/training_scope.py`), so a Flask work page (coding, reviewing,
  intake, data management, the dashboards) never lists, counts or allocates
  the training project. Only `?training=1` on an authorized Expo route widens
  a request to the training side, and only the trainer tools run unfiltered.
  An admin page other than those loses TRN01 too. These surfaces always leave it out, for every user: the Home
  KPIs (`/api/v1/me/kpis`), the area dashboard, `/api/v1/me/activity` and
  `/home`, the notification poll (the cursor still moves past a training
  notification), the cases list, its filters and CSV (`/api/v1/cases`), and
  every data management page, submission list, KPI, filter and CSV or other
  export (`/data-management`, `/api/v1/data-management`, the COD bucket and
  analytics endpoints). The trainer's own tools (the admin Training sessions
  panel and its JSON API under `/admin/api/training`, the trainer report under
  `/data-management/training`, `flask training-demo` and Celery tasks, which
  have no request) are unchanged: they see everything.
- **One allocation per side.** A coder (or reviewer) may hold one active
  allocation on the training side and one on the real side at once
  (`digitva-rcwt`): a training allocation never blocks real coding or review,
  nor the reverse. Allocate, resume, release and the "you have an active case"
  answer (`GET .../allocation`) consider only the allocation of the request's
  scope, so each side shows its own Resume and Release. The stale-allocation
  timeouts apply to both. See `docs/policy/coding-workflow-state-machine.md`.
- `GET /api/v1/me/access` keeps the training project out of `projects` and its
  grants out of `roles`, and gives them as `training.project` instead, so the
  normal menus (VA Interview, Deaths, VA Code, VA Review) are built from real
  work only and a trainee with nothing else sees none of them. The Training
  screens run on a bootstrap holding only that project.
- The scope comes from the route a screen sits on (`/app/training/...`), never
  from a query string a user can edit: editing the URL cannot cross the line,
  because the server re-checks the participation on every request.
- Out of scope and unchanged: the admin Training sessions panel, the
  `flask training-demo` commands, the trainer report and the admin views, which
  do not use these endpoints.

## Trainer management

Admin only: the Training sessions panel and its JSON API (CSRF token on every
write), and the `flask training-demo` commands, list sessions, create one, add
and remove participants, close and reopen, and print a session's report.

### Bulk add

The panel finds candidate users and adds many at once in one role.

- Candidates (`GET .../candidates`) are active users created since a date
  (read as midnight in the admin's time zone against the stored UTC creation
  time) by the admin (`created_by` `me`, the default: accounts whose
  `other.created_by_user_id` is the admin, written when an admin or a data
  manager creates an account or the project users import creates one) or by
  anyone (`any`), optionally filtered by name or email. Users already active in
  the session in any role are left out. At most 200 are returned (`truncated`
  says more matched); only id, name, email and status are returned, and a
  mobile-only account shows its masked number.
- Add (`POST .../participants/bulk`, up to 200 user ids and one or more roles, one row per user and role) previews
  first (`dry_run`, the default): every row is `add`, `reactivate`, `already`
  or `refuse` with a reason (unknown or inactive user, no free coder slot, a
  coder lacking a narration language, a grant the access rules refuse). Apply
  is all or nothing: it writes only when no row is refused, and otherwise
  writes nothing and answers 409 with the rows. Coder slots go out in the order
  the ids were sent, a refused row takes none, and the grants are the same as
  for a single add.

### Graduation

`GET .../graduation.csv` returns the session's active participants in the
columns of the organization users import (`email`, `name`, `role`,
`org_unit_code`, `cadre_code`, `language_codes`, `phone`), for loading into the
participants' real project through the existing import (preview, then apply).
The training role gives the import role (coder to `coder`, and so on); a
reviewer_data_manager gives two rows, `reviewer` and `data_manager`. The unit
and cadre codes are those given in the request, else blank; a mobile-only user
is identified by phone. This writes no grant: the ordinary import and its rules
do.

## Trainer report

A session's report is at `/data-management/training/<code>` (the list of
sessions the viewer may read is `/data-management/training`), with CSV exports
of the coder table (`coders.csv`) and of the coded cases (`cases.csv`). It holds
the answer key, so only an administrator and a user with an **active**
`reviewer_data_manager` participation in that same session may read it; every
other user, other sessions' managers and all trainees included, is refused
(403, the same answer for an unknown session so existence is not probed).

- Per coder: name, email, slot, cases coded (an active final assessment) out of
  10, cases in progress (a coding workflow state without a final), not started,
  last activity, completed at 10 of 10.
- Agreement: for each coded case the trainee's final cause is mapped to its
  WHO 2022 VA cause (`VAs-..`) and so is the source case's ICD-10 cause, from
  the shipped WHO annex tables in `resource/` (ICD-10: a single code beats a
  range, two causes at the same specificity are ambiguous; ICD-11: the expanded
  `WHO_2022_VA_2026` table, a missing code falling back to its stem). The case
  is a match, a mismatch, or unmappable when either side has no single cause;
  unmappable cases are counted apart and left out of the percentage.
- Other roles: per death reporter, interviewer, interview supervisor and
  reviewer_data_manager, deaths registered, interviews started and submitted,
  and supervisor actions, counted inside the session's units. Supervisor
  actions are the case moves that relied on a supervisor grant; other
  supervision leaves no record and is not counted.
- Session totals. The report shows trainee names, emails (masked mobile
  numbers) and cause codes, never the source case's id or any case content.
  It runs a fixed number of aggregate queries whatever the participant count.
- The reviewer_data_manager onboarding checklist links to the report list.

## Data protection

The copied narratives are pseudonymised, but the project still holds clinical
content: it is signed-in only, every grant is explicit, and the trainer report's
answer key is restricted to admins and the session's reviewer_data_manager. Pseudonymisation must be checked after any
change to `PII_FIELDS` or to the free-text fields that can repeat a name.

## Cross-project reporting

Training coding is real coding activity in the database. Views scoped by
project, grant or site (data-manager and admin KPIs, the case grids) show TRN01
as they show any project. The one all-projects aggregate of a person's own
work, the coder output summary, excludes TRN01 unless the project is asked for
by id. Nothing else sums coding across projects.
