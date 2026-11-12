---
title: Expo Web Client Boundary
doc_type: policy
status: active
owner: engineering
last_updated: 2026-11-12
---

# Expo Web Client Boundary

## Server compatibility and APK identity (2026-10-28)

`GET /api/v1/app/version` is public and returns `api_compatibility: 1` and
`build_revision` (a validated deployed commit SHA or null). The compatibility
level changes only for an incompatible native API contract change, not for
additive fields, bug fixes, web exports or documentation. The commit identifies
the running deployment for diagnostics; matching an APK source SHA is not an
access or compatibility requirement. Responses revalidate without caching.

Native Settings compares the expected contract level to the selected enrolled
or demo server. Compatible, mismatch and unavailable are visible diagnostics;
they do not delete work or disable collection/sync. Offline or an old server
without the endpoint means unavailable. Standalone performs no server check.

Hosted APK metadata at `/api/v1/app/android/latest` keeps the normal Collect
default and accepts only `variant=normal|plus`. Additive `variant` and
`size_bytes` fields describe the actual selected file; separate download links
and filename filtering prevent Plus from replacing normal Collect. The public
download page shows both variants' version and file size. Update checks and
GitHub fallback select only the installed package's variant. Play builds still
use Play updates. Neither check installs an APK automatically.

The first Expo client supports the DigitVA collection workflow in a browser
and on native devices. The browser client is an online client. It uses the
ordinary Flask login session and server-side web-intake drafts; it does not
persist questionnaire answers, identifiers or attachments in browser storage.
This follows the browser path in the [Field Data Collection
Policy](field-data-collection.md).

The COD editor has an explicit per-tab reload-recovery exception for COD lines,
selection, remarks and pending private notes; its boundaries and clearing rules
are in [DORIS COD Workflow](doris-cod-workflow.md#browser-reload-recovery-2026-10-25).
It does not persist questionnaire answers or demographic fields.

Production releases may cache only manifest-listed public web build assets.
Release/source identity and SHA-256 hashes separate caches; HTML, manifest and
worker revalidate. API responses, authentication, clinical records, private form
configuration and attachments never enter this asset cache. Worker activation
waits for existing tabs, preserving active interviews. New document requests use
the server's current HTML. Interview screens load on demand and failed downloads
offer retry; background asset warming requires a reported fast connection
without a data-saving preference.

The login, navigation and coding bundles must not import the WHO interview
runtime as a value. Browser interview compilation and rendering share one
asynchronous runtime boundary. Small presentation controls may be implemented
locally to keep this boundary intact; clinical definitions, validation and
translation rules remain canonical.

After authenticated access confirms interview capability, an idle foreground
browser may download the manifest's WHO runtime group sequentially on a reported
4G connection without data saving. This downloads public bytes without executing
the interview runtime. Anonymous and coder-only sessions do not warm this group.
Logout, account/access changes, hiding the page or losing connectivity cancel
warming; completed verified assets remain reusable. Unknown and slower links
load interview assets on demand. Caching public assets does not make the browser
interview offline: server draft saves and submission still require connectivity.

WHO and DigitVA web have separate build outputs released as one matched pair.
The app build consumes the checksum-verified WHO package built from the same
source commit, and records its package version and artifact digest in the public
asset manifest. The complete web archive remains the hosting contract and
contains the matched deferred WHO chunks; the WHO package artifact is a build
input, not an independently deployable browser application. Independent WHO
deployment or a second React runtime is outside this contract.

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
- **Wipe:** it lives in the interviewer's database file, so a wipe (a revoked
  session with nothing unsent) deletes it with the store.
  Sign-out and re-enrolment keep the store, and the log with it.
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

## Reopening a ready interview (native; `digitva-7amd.13`)

Owner decision, 2026-11-06. A completed interview that has not started sending
shows **Reopen** on its Interviews card.

- Reopen asks first (a confirmation dialog) and says the interview must be
  completed again. It moves the interview back to in progress, answers kept,
  and opens the form. It is a compare-and-set on the stored row: it applies
  only while the interview is still completed and has no upload issue.
- It is **refused** once a send is in flight or done (the send holds the
  interview's upload lease, and sync re-reads the row after taking it, so a
  reopened interview is never sent and a send that began first wins). A sent
  interview is corrected through a revision, not reopened.
- The reopen time is recorded in the interview's local timeline
  (`reopenedAtV1`, newest last, at most 8) beside the answers. It stays on the
  phone and is not sent to the server.
- Complete again is required before it is sent: the completion time is
  restamped and the Interviews card shows Draft until then. A held interview
  (an upload issue) offers no Reopen.

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

## Theme (Petrol; owner decision 2026-11-05, `digitva-3qah`)

The phone app (Android and iOS share one design) and the browser screens built
from the same components follow the Petrol theme in
`docs/design/collect-petrol-theme/README.md`.

- **Colours.** Petrol primary with an amber accent. Tokens are authored in
  OKLCH (`src/themeColors.ts`) and React Native draws their hex; a test checks
  every hex against its OKLCH value. Existing token names stay and map onto
  the Petrol values.
- **Fonts.** Native system fonts (SF Pro on iOS, Roboto on Android).
- **Cards have no borders.** A card stands apart from the canvas by tone and a
  faint shadow (none in dark mode). Rows inside a card are split by an inset
  hairline. Selected and error states are a tint fill, secondary buttons are
  tint-filled, and destructive actions are red text. Fields carry only a faint
  hairline tone at their edge; the field being typed in is the only one with a
  focus ring. A field error is the error tint plus the message directly under
  that field.
- **Accent.** Amber only as a filled badge (or the attention-row tint), always
  with ink text; never as text colour and never with white text.
- **Red and green** mean error and success and nothing else.
- **Hindi** (and any second language) is drawn in the same ink as English;
  weight, not grey, makes it secondary.
- **Rows** are at least 48 pt tall, 56 pt with a second line.
- **Icons** are native: SF Symbols on iOS and Material Symbols on Android
  (through `expo-symbols`, which draws Material Symbols from a font on Android
  and the web), mapped to the same meaning per icon in `src/Icon.tsx`.
- **Dark mode** is derived from the same tokens.
- **Messages** (hints, consent notices, save errors) are notice cards near the
  action they answer, not loose coloured paragraphs. Up to three short
  options are an equal-width segmented control; four options, or any label
  that would wrap (sex, birth-date precision), are choice rows in one card. A
  form's primary action sits full width in a sticky footer.
- **One filled button per screen.** Other actions are tint-filled secondary
  buttons, or text links (Cancel, "I have a sign-in code", "Forgot
  password?"). Lists that open another screen are rows with chevrons, never
  buttons.
- **Passwords and long PINs** have a show/hide eye inside the field (44 pt,
  "Show password" / "Hide password"); showing only unmasks the text, and the
  value stays in the screen's state. The PIN boxes put their eye at the end
  of the row, and the Confirm row takes focus only once the PIN row is full.

## App speed (owner 2026-11-06, `digitva-xxfz`)

The app must feel instant on a field phone. Budgets are measured on the
reference phone (Samsung SM-E146B, 6 GB) with the CI release APK, never a
debug build, and are p90 over ten runs:

| Moment | Budget |
| --- | --- |
| Cold start to the unlock screen | 2.0 s |
| PIN entered to Home drawn | 1.0 s |
| Tab switch or screen push to first frame | 300 ms, no blank frame |
| Open a draft or new interview to first question | 1.5 s |
| Next / Back page in the WHO form | 200 ms |
| Typing and scrolling in forms and lists | no dropped frames (60 fps) |
| Case list of 1,000 rows, first draw | 500 ms |
| Any SQLite read behind a screen | 50 ms, index-backed |
| Send of 50 interviews | the UI stays responsive throughout |

- **Measure before fixing.** Each change cites a before/after number from
  the reference phone. Profiling uses the CI release APK with the React
  Native performance tools and `adb shell am start -W`; no local release
  builds.
- **Startup.** Only what the first screen needs loads at launch: heavy
  screens (form engine, coding, DORIS, ICD-11) load on first use, and
  collectors never load the coding engine. No network call blocks the first
  screen.
- **Lists.** Long lists are virtualised (`FlatList` with stable keys, fixed
  row heights where possible, memoised rows); counts come from one aggregate
  query, never by loading rows.
- **SQLite.** Every list and lookup query is index-backed (a Jest test checks
  `EXPLAIN QUERY PLAN` for the named queries); writes are batched in
  transactions; no query per row; large JSON is parsed once per open.
- **Rendering.** No work in render that can be memoised; context values are
  stable; animations run on the UI thread (Reanimated); answers are saved
  without re-rendering the whole form.
- **Telemetry.** The existing first-party performance telemetry
  (`docs/policy/app-performance-telemetry.md`) adds bucketed timings for cold
  start, unlock to Home and form page change, with the same aggregate-only,
  no-identifier rules, so slow phones in the field show up.

## Text size, high contrast and screen readers (owner 2026-11-06, `digitva-khxv`)

- **Text size** in Settings: Small, Medium (default) and Large, a segmented
  control saved with the other UI preferences on the device (not per account,
  never sent to the server). It scales every text token, the WHO form
  included: Small 0.9, Medium 1.0, Large 1.2. It multiplies the phone's own
  font size setting, which the app keeps honouring; the combined scale is
  capped at 2.0 so screens stay usable. Row heights, PIN boxes and buttons
  grow with the text; nothing is cut off or overlaps at Large with the phone
  set to its largest size.
- **High contrast** in Settings: an on/off switch, saved the same way, that
  works in light and dark mode. It swaps in a high-contrast palette: body and
  secondary text at 7:1 or better against their background, primary
  buttons and links at 7:1, field edges and separators at 3:1, a thicker
  focus ring, and a stronger canvas/card tone step. Cards still have no
  borders. Meaning never rests on colour alone (errors keep their icon and
  message). When the phone itself asks for more contrast (iOS Increase
  Contrast, Android high-contrast text) the switch starts on.
- **Screen readers.** There is no in-app switch: the app works with the
  phone's TalkBack (Android) and VoiceOver (iOS). Every control has a label,
  role and state (selected, checked, disabled, expanded); screen titles are
  headings; a new screen puts focus on its title; errors, toasts and notices
  that appear after an action are announced; decorative icons are hidden;
  reading order follows the layout; and every gesture (pull to refresh,
  swipe) has a button or accessibility action that does the same thing. WHO
  form questions read as question, then the Hindi line, then the choices
  with their state.
- **WCAG.** The phone app and the browser screens meet WCAG 2.2 level AA
  (applied to native apps as W3C's WCAG2ICT guidance describes), with the
  high-contrast palette at AAA contrast (7:1). The criteria that bite most
  here:
  - 1.4.3 and 1.4.11: text 4.5:1 (3:1 at 18 pt or 14 pt bold); focus rings,
    icons that carry meaning and selected states 3:1. Labelled text fields
    meet 1.4.11 through their label; the field edge hairline
    is decorative (the token stays). Disabled
    controls are exempt but stay legible.
  - 1.4.4 and 1.4.10: text to 200% (the phone setting times Large) without
    loss of content; screens scroll vertically and never need sideways
    scrolling at 320 pt width.
  - 1.4.1: colour is never the only signal (errors carry an icon and text;
    selected rows a check mark).
  - 2.5.8: targets at least 24 pt; this app's own minimum is 44 pt.
  - 2.5.1 and 2.5.7: every swipe, drag or pull has a single-tap alternative.
  - 2.4.3, 2.4.6, 2.4.7, 2.4.11: logical focus order, descriptive headings
    and labels, a visible focus indicator that the sticky footer and bars
    never cover (hardware keyboard and the browser).
  - 2.2.1: idle sign-out and any timeout warn first and let the user extend.
    The phone's 5-minute auto-lock shows a non-modal, announced notice 30
    seconds before ("This phone locks in 30 seconds") with Stay unlocked,
    which restarts the timer; any touch does too.
  - 3.1.1 and 3.1.2: the screen language is set, and Hindi text inside an
    English screen (or the reverse) carries its own language, so the screen
    reader pronounces it (`accessibilityLanguage` on iOS, `lang` on the web).
  - 3.3.1, 3.3.2, 3.3.3: required fields and formats are stated before
    entry; an error names the field and says how to fix it.
  - 4.1.2 and 4.1.3: name, role and value on every control; status messages
    announced without moving focus.
- **Checking.** Token contrast is checked by a Jest test for every palette
  (light, dark, both high-contrast). A Jest test walks the rendered screens
  and fails on a pressable without a label or role, or a target under
  44 pt. The browser screens are checked with axe-core in Playwright at
  375, 768 and 1366 px. Each release is checked by hand on a phone with
  TalkBack, with VoiceOver, at Large text with the largest phone font, and in
  high contrast; the results go into the release checklist.

## Phone shell: header, tabs and Help

Owner-approved design, 2026-10-23 (`digitva-gmt7`), revised by the owner
2026-11-05 and 2026-11-06 (`digitva-22i1`: the header and tab bar are light bars on the canvas colour with a
hairline edge, ink title, primary back arrow; a tab tap returns to that tab's screen without rebuilding it, and
Android Back on Interviews or Register goes Home). The phone app (Android and iOS alike) has a 48 dp header:
on a tab root (the accounts list, Home, Interviews, and Register when it is
a tab) the emblem and "DigitVA"; on any other screen a back arrow in its place
(Back for assistive tech, 48 dp target) that goes back, or to the account's Home
when there is nothing to go back to, followed by the screen's title on one line
(cut short with an ellipsis so the right-hand controls stay); that screen drops
its large on-page title but keeps any action from its title row on the page. Tab
roots, the pre-login screens and the forms keep their on-page title, and the
browser is unchanged. No screen puts its own actions in the bar yet (to be added
screen by screen).
On the right only a spinner or Offline marker while syncing or offline, and the
account avatar. Help and the app language are in the account sheet and Settings,
not the signed-in header. Screens drop buttons that only went back. Bottom tabs
(Home, Interviews, Register, Sync; the badge on Sync is the unsent count)
and an account menu sheet (Settings, Help, language, Lock now, Switch
profile (locks first), Sign out (keeps the encrypted data, `digitva-dxgj`), version). The
tabs follow the account's `collection_access`, `registration_access` and
`registered_deaths_access` through the browser's `navEntries` rules and never
show coding or review (web-only). Header and tabs are hidden on the interview
and revision forms; the unlock, sign-in, enrol and PIN screens show a minimal header (emblem, title, 文A, and Help only where "Try DORIS" is offered), no back arrow and no tabs; tabs are
also hidden while the keyboard is open, while locked and on the accounts list.
Phones (shortest side under 600 dp) are locked to portrait; tablets rotate.
Dragging any scrolling screen, the interview form included, closes the keyboard.
Collect Plus on Android offers "Try DORIS" in Help, also before sign-in: the
on-phone ICD-11 engine with WHO's six synthetic certificates or a blank one,
offline, with no account, server call, store write or save. Before sign-in,
Help offers nothing that needs an unlocked account.
On a phone that has not downloaded anything for the account yet (first
sign-in, or after a reinstall), Home shows a modal that cannot be dismissed,
"Downloading questionnaires and data", until the projects, current
questionnaires and cases have downloaded or the download fails (then Home's
usual message shows). It keeps the interviewer online for the one download an
offline interview needs (`digitva-x7kq`, owner request 2026-10-27).
Help is a bottom sheet per screen (what it is for, what to do now) bundled in
the app's English and Hindi dictionaries, so it works offline; only "Open the
full guide" needs the network and opens the server's help page in the phone's
browser.

Home is a dashboard from local data only: the counts card (unsent, cases
needing a visit, opening Interviews on the To do chip, drafts, opening it on
the Drafts chip). While anything is unsent (or the count is not known yet),
Send now is the screen's one filled button and the next step (Resume draft, or
Start an interview when none) is tint-filled; with nothing unsent Send now is
not shown and the next step is the filled button. Then Register a death when
the account may register,
and for coders the coding case lists (Local, Online, My coded cases) as rows
with chevrons in one card. Interviews searches name, ID, unit and village
(case-insensitive, Unicode-normalised, so Hindi works), filters by All, Drafts,
To do, Sent and Revisions with counts, and shows one card per case: the name as
title, the ID as a muted second line, a status badge and one primary action.
Interviews has no Send or Refresh button: pulling the list down refreshes it,
and the Sync sheet's Send now and Refresh buttons are the single-tap
alternative (2.5.1); the coding case lists sit above the search row.
Choosing a site and unit is a searchable full-height sheet of unit names (site
headers only across several real sites; internal placeholder names never
shown), with the last choice under Recent. Register a death shows the site and unit
as one field (the chosen unit's name, or a prompt) that opens the same sheet with
the chosen row ticked; when every unit shares one site, the site name is shown
once under the list instead of on each row. Lists show skeleton rows while
loading, an empty state with the next action, and a persistent notice while
offline (pull-to-refresh off with the reason; work stays on the phone).

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

- Temporary, owner update 2026-11-12 (`digitva-hs7e.14`): standard and Plus
  Android builds made with
  `EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL=2026-12-31T18:30:00Z` allow screenshots
  until the end of 31 December 2026 in India (exclusive, device clock). This
  supersedes the 25 November expiry and the 28-day cap (now 60 days). The same
  installed APK blocks again automatically afterwards. A date more than 60 days
  past app start, or an invalid or unset value, keeps the block. Remove the
  setting from builds after expiry. Builds already installed keep their own
  date; only new CI builds carry the new one.

## Offline gate (native; `digitva-5u65`)

Owner rule, 2026-10-24, from a training phone whose error log filled with
"Unable to resolve host" failures: the Android app makes no server call while
the phone has no network (no Wi-Fi and no mobile data), and says it is offline
instead of raising errors.

- **State:** `expo-network` (`mobile/digitva-collect/src/network.ts`). The phone is
  offline when `isConnected === false` or `isInternetReachable === false`. An
  unknown (`null`/`undefined`) reachability counts as online, so calls
  proceed and a real failure is handled as before.
- **Gate:** every JSON/raw request of `src/api.ts` (so background and periodic
  sync, notification polls, foreground refresh, draft sync, attachment upload
  and Send now), the update check and the clock re-check refuse before
  `fetch` while offline, with an `OfflineError` (a `TypeError`, so existing
  "no network" handling applies). An `OfflineError` is never filed in the
  error log, never raises the background-error banner and sets only the
  header's Offline marker. All work stays in the encrypted store.
- **Send now offline:** a calm info toast, "You're offline. Your work is saved
  and will send when you're back online." No request, no error.
- **Reconnect:** on the change to connected the app runs one pass (debounced
  2 seconds): the foreground poll and, for each unlocked account, one sync so
  queued work goes out.
- **Indicator:** the header's "Offline" marker shows while the phone is
  offline (accessible label "Offline"), not only after a failed request.
- **Real failures:** when the state is unknown or online but a call still
  fails at the network level, it is logged once per offline spell (a spell
  ends at the next successful response or connectivity change), not once per
  attempt.
- Web is unchanged: the gate is inert unless the native shell has started the
  watch.

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
- The Google Play build (`DIGITVA_DISTRIBUTION=play`, `digitva-6o4b`) has no
  update check and no APK download anywhere: Settings > About says app
  updates come from Google Play, and the start-up check does not run. Play's
  Device and Network Abuse policy forbids an app updating itself outside
  Play. The sideloaded build keeps the check above unchanged.

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

**Adding a UI language** (owner 2026-11-06, `digitva-s028`, builds on the
UI-strings editor in `docs/policy/ui-strings.md` and `digitva-dt1e`): a new
app language is added the way a questionnaire language is, by an admin on the
server, and reaches phones and browsers through the API with no app release.

- **Server is the source.** Admin, UI strings (the existing editor, with its
  machine drafts, review, placeholder and markup checks) holds every language,
  including ones with no bundled file. A language is offered to clients once
  an admin publishes it on the Languages panel; machine drafts are never
  served. `GET /api/v1/ui-strings` lists the published UI languages (code,
  native name, BCP 47 tag, direction, version, share reviewed), and
  `GET /api/v1/ui-strings/<locale>` returns the full pack (bundled text with
  accepted corrections over it, or accepted rows alone for a language with no
  bundle), versioned with an ETag as now. No sign-in is needed: the packs are
  reference text with no personal data.
- **Two layers, one pack.** The pack carries the app strings and the WHO
  form's own labels (Next, Back, Don't know, validation messages;
  `vendor/who-va-2022/src/languages/`) as two namespaces, edited on the same
  admin page. Questionnaire question and choice text stays in the existing
  instrument translation packs.
- **Phone.** The app downloads the list and the packs it needs when it can
  reach its server (start, language switch, sync), keeps the last pack per
  language on the device, and lays it over the bundled dictionary. Offline it
  uses the stored pack; with none, the bundled text; missing keys fall back to
  English. A pack that fails the client's checks (unknown key, placeholder set
  differing from English, markup) is dropped key by key, never applied. A
  language the server stops publishing loses its stored pack at the next good
  list; a failed list request (the server answers `503` when its export cannot
  be read) leaves the stored list and packs as they were.
- **Bundled languages** (English, Hindi now) ship in the app so the first
  screen, an unenrolled phone and standalone mode work offline. Before
  enrolment only bundled languages are offered. A published language moves
  into the bundle at a release with `flask ui-strings bake`, as the strings
  policy describes.
- **No language codes in screens.** Pickers, date and number formatting and
  screen-reader language tags read one list: bundled languages plus the
  server's published list. A guard test fails on a hard-coded code (`"hi"`)
  outside the strings and data files. Two or three languages show a segmented
  control; four or more a list sheet, each name in its own script.
- **Questionnaire languages** are added and published by admins (Languages,
  Instrument translations) and reach phones as translation packs. The phone
  offers every questionnaire language the project enables, whether or not a
  UI pack exists for it; without one, the app's own text stays English (the
  earlier filter to UI languages is dropped).
- **Right-to-left** (Urdu): the language's direction is honoured through React
  Native's RTL support with mirrored chevrons and back arrows; an RTL
  language stays unpublished until checked on a phone.
- **Fonts:** system fonts only; a phone that cannot draw a script does not
  offer that language.
- **Review state** travels with the pack, so the app can label a language
  "machine-translated" until a native speaker has reviewed it.

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

Online coding destinations use the shared native queue/workspace in both APK
variants when the caller has coding access (`digitva-6rxf`). Local coding
requires Plus and the same-project self-coding/coder rule below. Reviewing
keeps its existing variant/permission checks. Server authorization remains
authoritative for every case.


## Unified phone coding access (`digitva-6rxf`)

Owner 2026-10-28: onboarded, standalone and demo are contexts of the same
workflow, keeping their existing separate stores and identities. Both APK
variants use the existing native online coding queue/workspace for enrolled
users with coding access. Server authorization remains authoritative. Plus
local ICD-11/MMS/DORIS tools additionally require self-coding and coder access
in the same project (standalone keeps its local self-coding flow). The direct
interview setting is not a coding permission. Capability changes preserve
unsent work; the engine starts only on an eligible offline coding route.
Startup and later local profile editing share one form and storage schema.
The lighter package still excludes offline engine assets; a single-package
on-demand distribution strategy is a separate release/licensing decision.


## Development and release builds (`digitva-a770`)

Owner 2026-10-28: native Android debug builds and Metro HMR are allowed locally
for emulator testing. Native SQLCipher/engine modules require a custom debug
app. Keep existing Metro processes running and use a separate port when needed;
point emulator enrollment at the local backend, not live/staging user data.
Google Play AAB is the primary release path; CI builds and verifies release
artifacts. No Play upload or server deploy is implied by a build.
