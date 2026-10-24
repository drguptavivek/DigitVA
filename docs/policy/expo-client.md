---
title: Expo Web Client Boundary
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-24
---

# Expo Web Client Boundary

The first Expo client supports the DigitVA collection workflow in a browser
and on native devices. The browser client is an online client. It uses the
ordinary Flask login session and server-side web-intake drafts; it does not
persist questionnaire answers, identifiers or attachments in browser storage.
This follows the browser path in the [Field Data Collection
Policy](field-data-collection.md).

The native collection app remains the offline path. It uses the existing
encrypted device store and bearer device sessions (`/api/v1/auth`). A device token is
accepted on every `/api/v1/` route, same route and body as the browser
session cookie; it cannot authenticate anything outside `/api/v1/` (the
browser pages, `/admin/api`, `/intake`). A request carrying a bearer is
authenticated by it alone: a cookie on the same request is ignored, a bad
token is a 401 (never a fallback), it needs no `X-CSRFToken` and it never
sets a cookie. Terms, maintenance and forced-password-change gates apply to
both credentials.

A device session opens, and refreshes, for a worker with an active grant that
opens its gate for interviewer, coder, coding_tester or reviewer in at least
one project (owner, 2026-10-05; [Field Data
Collection](field-data-collection.md), "Who may sign in on a device"). The
session grants nothing by itself: each route keeps its own role and scope
check.

## Browser access

After the existing email, CAPTCHA, password or passkey and factor flow has
completed, the browser calls `GET /api/v1/me/access` (there is no separate
bootstrap route). It uses the same-origin session cookie and returns the
user's whole access summary (`docs/policy/api-v1.md`; shape in
`docs/current-state/api-v1.md`) and, for a cookie request only, the CSRF
token in the `X-CSRFToken` response header, which the client sends back on
every state change. The body is identical for the device bearer credential.

The summary is a set of navigation hints, derived from the authoritative
authorization role resolution. Every workflow API performs its own project,
site and unit scope check. A client must never treat a grant, capability or
link as permission to read or change a record.

An anonymous request receives JSON `401`
`{"error": "Authentication required.", "code": "unauthorized"}`: the cue to
send the browser to `/vaauth/valogin?next=/app/` (sign out:
`/vaauth/valogout`). The response, including errors, is `Cache-Control:
no-store`. No sign-in bypass, device-token fallback, or new authentication
factor is introduced.

## Idle sign-out (web; `digitva-kc89`)

Server rule and the background header: `docs/policy/auth-decorator-rbac.md`
section 5. In the web client:

- The notification poll (60 s), the authoritative refresh (15 min) and the
  reload on tab focus send `X-DigitVA-Background: 1`; every other request is
  user activity.
- A timer counts from the last pointer, key, scroll or touch input (and from
  the tab becoming visible after input). At 28 minutes a dialog says "You
  will be signed out in 2 minutes because of inactivity" with "Stay signed
  in", which sends one ordinary request (refreshing the server stamp) and
  restarts the count. At 30 minutes the client signs out and shows the
  sign-in page.
- Escape, closing the dialog and the default-focused button all mean "Stay
  signed in"; "Sign out" is an explicit, non-default button. Only trusted
  (`isTrusted`) input counts as activity.
- Every web sign-out, manual or idle, first lets registered saves (the open
  interview's draft) finish, up to 5 seconds, then aborts requests, clears the
  recalled interviewer details (`digitva.interviewerRecall.*` in
  `localStorage`, `clearWebRecall()`; `digitva-3rec`) and leaves.
- Any `401` with code `session_idle` goes to the sign-in page with "Signed
  out after 30 minutes of inactivity".
- Any `401` with code `session_expired` (the 12-hour cap from sign-in,
  `digitva-vq05`) goes to the sign-in page with `reason=expired`: "Your
  session ended after 12 hours. Please sign in again."
- The phone app (bearer token) has no idle sign-out and no 12-hour cap.

## Role home and login landing

Owner decision, 2026-10-22 (supersedes 2026-10-11, -12 and -19; design:
`.tasks/2026-10-11-home-jump-page.md`, bead `digitva-dsj2`). The Expo home at
`/app/` is the default home for every signed-in user — admin, `project_pi`,
collaborators, viewers, `site_pi`, field, coding and data manager roles, and
users with no role grants yet — whenever the Expo export is present
(`export_ready()`, an `index.html` in the export directory).

- After login (every sign-in path), after accepting terms on
  `/profile/force-password-change`, and on `/` for a signed-in user, the
  browser goes to `/app/`. The Flask "Return to Dashboard" and logo links
  follow the same rule. `/admin/`, `/data-management/`, `/area/`, `/sitepi/`
  and the other Flask pages stay reachable by URL and from the Expo home.
- The stored `landing_page` column is kept but no longer chooses the
  post-login page while the export is present. Only when the export is
  missing (no `index.html`) does `VaUsers.landing_url()` fall back to the old
  rule: `landing_page` where the user still holds the matching role, then the
  first role dashboard, then `/`.
- `/app/` renders the user's Home / Dashboard directly on login:
  - When the user holds roles or project grants, it shows overall personal
    activity totals (forms filled, drafts in progress, deaths reported, forms
    coded, forms reviewed from `GET /api/v1/me/activity`), role-appropriate
    quick action buttons, and a card per project listing the user's assigned
    roles and scopes in that project, per-project personal activity counts, and
    per-project action buttons.
  - Quick actions reach the Flask pages a role has no Expo screen for: the
    admin console (`/admin/`) for an admin, Data management (`/data-management/`)
    for `project_pi`, collaborator and viewer (`collaborator_pii`) users, and
    the VA dashboard (`/sitepi/`) for `site_pi`.
  - When a user holds no roles in any project yet, `/app/` shows a Welcome
    home state explaining that no project roles have been assigned yet, with
    links to Settings / Profile, Help, and Demo Coding when available.

Effective roles come from the authz helper, so a `site_pi` held at an org
unit (the In-charge) counts as `data_manager` and `interview_supervisor`.
`VaUsers.landing_url()` implements the rule.

## Training menu and the training scope

Owner decision, 2026-10-23 (`digitva-r2pf`; detail in
[training-demo-project.md](training-demo-project.md), "Onboarding and the
public page"). The left menu has a **Training** item, shown only when
`access.training.areas` is not empty (an active participation). Its sub-items
are Interview, Coding and Review, each shown only for the training roles the
user holds; `/app/training` is the overview with the Start button.

The normal Interview, Coding and Review menus, their lists and their counts
(and the Home counts) never show the training project, for any user: the
server leaves it out unless the request asks for `training=1` and the caller
has the matching active participation. The training sub-menus show nothing but
the training project. The Training screens reuse the ordinary screens with a
training scope; the scope comes from the route, not from an editable query.

## Confirmations and submit notices

Owner, 2026-10-23 (`digitva-8ehe`, `digitva-0d3a`). The Expo client never calls
`window.confirm`, `window.alert` or `window.prompt`: browsers that suppress
native dialogs (the in-app browser) cancel them silently. A web confirmation
uses the shared `ConfirmDialog` (`src/ConfirmDialog.tsx`): Cancel takes focus,
Escape cancels, Tab stays inside, and a destructive action gets the destructive
button style. The phone keeps `Alert.alert`. Warning texts live in the string
files, never inline. After a successful web submit the collection screen shows
a dismissible banner ("Interview submitted successfully" with the unique id, or
"Correction submitted"); the phone shows the "Sent N" toast after a send.

## Error messages and the support reference

Field users report problems by screenshot, not by log. So an error the app
cannot name precisely must still identify itself on screen (owner,
2026-10-23, `digitva-l3r8`):

- A generic error (native "Something went wrong", web "server could not
  complete", "Check the highlighted fields", "Server unavailable") carries a
  second line, `Ref: <what> · <HH:MM>Z · v<app version>`, built by
  `errorReference` in `mobile/digitva-collect/src/ui.tsx`. `<what>` is the
  HTTP status, the error code, the method and the route with every id
  segment masked as `:id`, or for a failure on the device, the error class
  and at most 160 characters of its message, whitespace collapsed (so a
  native "→ Caused by:" cause stays visible). Quoted text is masked as `'…'`
  unless it is a bare identifier path such as `'NativeDatabase.prepareAsync'`;
  `file://` and `/data/` paths become `file:…`; digit runs of 4+ become `#`
  (short numbers such as SQLite "code 5" stay).
- The Ref line never carries tokens, query strings, full URLs, names,
  answers or server-provided free text.
- Messages that already say what to do (offline, rate limited, sign in
  again, CSRF refreshed, forbidden) carry no Ref line.
- An interview submit refused with 422 shows the server's own message
  (fixed rule text such as consent, Id10013 or the deceased's identity, no
  answers) with the Ref line, because the page cannot highlight the question
  the rule names. `draft_stale` likewise shows the server's message. All other
  server text stays hidden.
- Support matches a Ref to the server's access log by route, status and UTC
  minute.

## Local error log and "Export errors" (native)

Owner decision, 2026-10-23 (`digitva-j6cx`). So support can see what a phone
reported without a log cable, the Android app keeps a small local error log.

- **What is stored:** one row per error the app showed or reported: UTC time,
  app version, the screen (route pathname, no parameters), the Ref content
  (HTTP status, error code, method and masked route; or the native function
  and scrubbed cause, by the rules above), device brand and model, Android
  release. The same scrubbing as the on-screen Ref line applies, in
  `describeError` (`mobile/digitva-collect/src/errorLog.ts`). Sources: every
  `errorText` call (including messages that carry no Ref line, such as offline
  or rate limited), background refresh failures, and error toasts whose text is
  one of the app's own fixed strings. The same error on the same screen within
  a minute is one row.
- **What is never stored:** answers, names, phone numbers, tokens, URLs or query
  strings, ids, server-provided free text, or any text typed by the worker.
- **Where:** a table (`error_log`) in the interviewer's encrypted store, created by
  the local migration in `src/drafts.ts`. Nothing is written in plaintext;
  while no store is open, up to 50 entries wait in memory only and move in on
  the next unlock. It is not unsent work and is never uploaded.
- **Cap:** the newest 500 rows and at most 30 days, enforced on every write.
- **Wipe:** it lives in the interviewer's database file, so sign-out, a revoked
  session, a wipe after failed PINs and re-enrolment delete it with the store.
- **Export:** Settings > Help & support > Export errors builds one text file
  content, `digitva-errors-<date>.txt` (a header with app version, device and
  export time, then entries newest first, cut to about 60,000 characters), and
  hands it to the Android share sheet (email, WhatsApp). The worker chooses the
  recipient; the app sends nothing itself. No file-sharing or zip package is a
  dependency yet, so the text itself is shared, not an attached file.

## Refused uploads on the phone (native; `digitva-3nui`)

Owner decision, 2026-10-23. The phone shows why the server refused an item,
as the web does, instead of reopening it silently.

- **What is kept per item** (in the encrypted store, with its last send
  error): the HTTP status, the machine code, the server's message, the
  question names it points at (`fields`), the Ref line and the time. The
  message is the server's fixed rule text, never answers. The error log gets
  the Ref line only.
- **422 on an interview** reopens it as in progress, answers kept, and shows
  "Not accepted: <message>" on its Interviews card and, in the questionnaire,
  as rows of the problems list (below), one per question named, each with the
  server's message and Ref and a Go button; there is no banner in the flow any
  more (`digitva-man7`). A `consent_required`
  refusal opens the consent screen first. The refusal clears when the
  interview is marked ready again.
- **409 on an interview** (`conflict`, the case is closed, already submitted
  or changed under the interviewer) is final until the interviewer acts: the
  item is held (not counted as sendable, not retried by Send now) with the
  server's message shown. The interview is **not** deleted: on the phone the
  row is the only copy of the answers, so unlike the web, a refusal that says
  "already submitted" is not treated as done. The interviewer can retry or
  discard it from its card.
- **Before an interview is marked ready**, the phone checks what the server
  checks on a direct start, with the server's own messages: the deceased's
  name (`Id10017` or `Id10018`), sex (`Id10019`) and date of death (`Id10023`,
  or the `_a` / `_b` date when `Id10022` is yes, or the year `Id10024` when
  the exact date is not known; the server stores 1 July of that year), skipped
  when consent (`Id10013`) is no; and the consent question (`Id10013`) when
  the form is complete. A failing interview stays in progress with the reason
  and the "Fix:" line shown.

## Phone form screens (interview and revision)

Owner decisions after the 360 dp field test, 2026-10-24 (`digitva-e49e`,
`digitva-man7`). The interview and revision forms share these rules; the form
engine (`vendor/who-va-2022`) draws the questions and the host screens draw the
top bar.

- **Bottom bar:** one ~56 dp bar fixed under the questions with Back and
  Next/Complete only, single-line labels (`compactFooter`). Save draft and
  Preview answers are in the top bar's ⋮ menu (Save now, Preview answers).
- **Title:** the deceased's name, with "Revision" as a small line above it on
  the revision screen; "DigitVA Collect" when the name is unknown.
- **Revision reason:** the reason sheet opens when a revision opens. Complete
  without a reason opens it again and marks the field invalid (red outline and
  "Choose a reason for the revision.") until one is chosen.
- **Section change** (Next, Back, Sections list, Go) scrolls the questions to
  the top and moves screen-reader focus to the section title.
- **Sheets** (⋮ menu, form language, revision reason, account, Help, Sync, site
  picker) and the engine's Sections list are padded by the bottom system-bar
  inset, scroll when longer than the screen, and the modals are laid out edge
  to edge (`statusBarTranslucent`, `navigationBarTranslucent`).
- **Problems list:** one popup lists every problem: the engine's own
  validation issues plus the stored server refusal (`digitva-3nui`). Each row
  reads Section › Question, the reason and a Go button that opens the section,
  scrolls to the question, focuses and highlights it. A question hidden by skip
  logic opens the earlier answer that controls it and says so. It opens when
  Complete finds errors, from the "N problems" chip in the top bar, and when
  the phone's own pre-send check fails. The web interview uses the same popup
  (a refused 422 lists what the server named). `controller.goToQuestion(name)`
  and `session.goToQuestion(name)` are the engine API; `serverProblems` and
  `onProblemsChange` the host props.
- **Year-only questions** show `[ − ]  2021  [ + ]` with a bordered, ▾ field that
  opens a list of years (newest first, within the constraint); the buttons
  repeat while held and stop at the bounds. Ranged numbers without a picker
  get the same − / + buttons.
- **Interviewer assists** (age group and ages from the dates, narration
  language from the script, voice-typing tip) are described in
  [DigitVA overrides](digitva-who-form-overrides.md), "Interviewer assists".

## Leaving a form

Owner, 2026-10-24. An interviewer never loses typed work by leaving a screen.

- Every exit saves first: the on-screen Back/Leave, the Android hardware back
  and the back-swipe, the Help sheet's "go" buttons, and the tabs. The phone
  flushes the open answer before leaving. If that save fails the app asks
  "Your last answers could not be saved. Leave anyway?" (Stay is the default).
- Exits that end or discard work ask first, with Stay as the default: "Finish
  as incomplete", Cancel of an edit to a saved registration, and (web) leaving
  a registration with unsent typing. The browser's own leave prompt also guards
  reload and close.
- Hiding the browser tab never clears typed fields. Values stay in memory and
  are not drawn on screen while the tab is hidden, and come back when it is shown.
- Sign-out and re-enrol count the registration in progress as unsent work.

## Phone shell: header, tabs and Help

Owner-approved design, 2026-10-23 (`digitva-gmt7`). The Android app has a 48 dp
brand-blue header (emblem, a spinner or Offline marker only while syncing or offline, Help,
the 文A app-language button, account avatar), bottom tabs
(Home, Interviews, Register death, Sync; the badge on Sync is the unsent count)
and an account menu sheet (Settings, Help, language, Lock now, Switch
interviewer, Sign out with the existing unsent-work confirmation, version). The
tabs follow the account's `collection_access`, `registration_access` and
`registered_deaths_access` through the browser's `navEntries` rules and never
show coding or review (web-only). Header and tabs are hidden on the interview
and revision forms; the unlock, sign-in, enrol and PIN screens show a minimal header (emblem, title, 文A) and no tabs; tabs are
also hidden while the keyboard is open, while locked and on the accounts list.
Help is a bottom sheet per screen (what it is for, what to do now) bundled in
the app's English and Hindi dictionaries, so it works offline; only "Open the
full guide" needs the network and opens the server's help page in the phone's
browser.

Home is a dashboard from local data only: the next step (Resume draft, or Start
an interview when none), the unsent count (Send now) and the cases needing a
visit (View, opening Interviews on the To do chip), then Register a death when
the account may register. Interviews searches name, ID, unit and village
(case-insensitive, Unicode-normalised, so Hindi works), filters by All, Drafts,
To do, Sent and Revisions with counts, and shows one card per case: the name as
title, the ID as a muted second line, a status badge and one primary action.
Choosing a site and unit is a searchable full-height sheet of unit names (site
headers only across several real sites; internal placeholder names never
shown), with the last choice under Recent. Lists show skeleton rows while
loading, an empty state with the next action, and a persistent notice while
offline (Refresh disabled with the reason; work stays on the phone).

Unsent (`mobile/digitva-collect/src/unsentWork.ts`, one count for the Sync badge,
the Home card and the Sync sheet; never in the header): what Send now uploads
from this phone across all projects, that is completed interviews, pending
registrations, queued contact attempts and visits, and ready revisions. Drafts
in progress are counted apart ("N in progress", linked to Interviews). Work
Send cannot move (refused, needs an edit) is listed in the Sync sheet as
needing attention and is not in the unsent count. Each listed item shows its
last send error (the Ref line, kept per item in the encrypted store and filed
in the error log). The 文A button switches the app language (English/हिन्दी);
the form menus label the questionnaire language separately.

## Screen capture (temporary allowance)

The native app blocks screenshots and screen recording (`FLAG_SECURE`, applied
at runtime in `mobile/digitva-collect/src/screenCapture.ts`).

- Temporary, owner decision 2026-10-23: builds made with
  `EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL=2026-10-30` allow screenshots for field
  testing until that date (exclusive, device clock). The same installed APK
  blocks again automatically afterwards. A date more than 14 days past app
  start, or an invalid or unset value, keeps the block. Remove the setting from
  builds after expiry.

## Update check

- The app asks its own server `GET /api/v1/app/android/latest` (public, no
  user data) whether a newer APK is hosted, and falls back to the GitHub
  releases page when the server has none or is unreachable. It only tells the
  user and links to the download; it never installs anything by itself
  (`digitva-2vrs`). Phone (`mobile/digitva-collect/src/updateCheck.ts`): the
  check runs on app start at most once a day (the time is stored only after an
  answer, so an offline start is retried at the next start) and on Settings >
  About "Check for updates". The fallback is the newest non-draft `android-v*`
  release of `drguptavivek/DigitVA` (unauthenticated GitHub releases API; its
  arm64 APK is the download). The base `version_code`
  (`major*10000 + minor*100 + patch`) is compared with the installed version
  (the app config `version`). A newer one shows a toast "Update available" with
  a Download button that opens the URL in the browser; when both sources are
  unreachable nothing is said at start and Settings shows "Couldn't check".

## Common questions (Help)

The Help sheet lists 11 interviewer questions bundled in the English and Hindi
dictionaries (`faq_<id>_q` / `_a`; offline), searchable, each answer short with
where to tap and, where it helps, a button that opens that screen. Settings >
Help & support opens the same sheet (`digitva-zgl2`).

## Hosting and languages

The built Expo export is mounted at `/app/`. The default directory is
`mobile/digitva-collect/dist`; deployments may set `EXPO_CLIENT_DIST` to a
dedicated export directory. Only files inside that directory are served.
Known Expo route paths fall back to `index.html` for client-side navigation;
missing assets and unknown paths return `404`. The source tree is never a
fallback document root.

The initial UI locales are English and Hindi. The app UI follows the selected
questionnaire language when starting, resuming or switching an interview.
Questionnaire choices remain controlled by project configuration. A language
without an available UI dictionary uses English app text until that dictionary
is added. Before opening an interview, the login page may select its UI language.
Every browser screen has a compact language icon at the top right. Outside
an interview it switches the English/Hindi app UI. During an interview the
project-configured questionnaire selector occupies that slot and changes
questionnaire and app UI language together.

The shared theme uses platform system fonts with Latin and Devanagari support,
semantic light and dark colors, and touch controls at least 48 pixels high.
UI language and theme preferences may persist locally. Questionnaire language
and translation version are saved with the server draft and restored on resume.

Translations are keyed by question and choice name, so a draft pinned to an
older definition still shows the chosen locale: its own cached translation
version if the phone holds it, else the current one (fetched when online and
not cached). Items missing from the pack stay English; the English-fallback
banner shows only when no pack for the locale is available. The draft's pin
and answers are never touched.

The main menu sits on the left on wider browser screens. Phones retain a slim
left rail with an expanded drawer overlay, preserving vertical form space.
Menu destinations remain role-dependent navigation hints;
leaving an interview through the menu waits for draft saving to succeed.
Each visible section dot navigates directly to that section. A separate
section-list button opens the fly-out, which follows the active form theme.
New draft answers use the authorized server prefill, including the logged-in
interviewer name; existing saved answers take precedence over prefill defaults.

Coding and reviewing destinations stay hidden in the Expo navigation and
workspace until those workflows are implemented inside Expo. Their server
authorization and capability contracts remain unchanged.
