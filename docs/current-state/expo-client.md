---
title: Expo Client Hosting And Access
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-25
---

# Expo Client Hosting And Access

DigitVA serves the Expo web export under `/app/`. The export is read from
`mobile/digitva-collect/dist` by default; `EXPO_CLIENT_DIST` can point to the
deployment's dedicated export directory. The route serves regular files only
when they resolve inside that directory. It uses `index.html` for the known
Expo client routes and returns `404` for missing assets, unknown routes and
path traversal attempts.

The browser starts by calling `GET /api/v1/me/access`. A signed-in session
receives the user's whole access body (see [API v1](api-v1.md)) and a CSRF
token in the `X-CSRFToken` response header. An anonymous browser receives a
JSON `401` `unauthorized`, the cue to go to `/vaauth/valogin?next=/app/`
(sign out: `/vaauth/valogout`) instead of an HTML login redirect.
Access responses are never cached. Browser intake
answers remain server-side drafts, saved and submitted through the existing
`/api/v1/intake/` endpoints: death registration takes and returns
`date_of_birth_partial` (`YYYY-MM` or `YYYY`) beside `date_of_birth`, and the
server re-applies locked prefill answers on every draft save and submit,
whatever the client sends (docs/policy/web-intake.md); native offline collection continues to use
the encrypted bearer device sessions of `/api/v1/auth`.

The first UI locales are English and Hindi. Interview language drives app UI
language on start, resume and successful switches. The top-right language icon
opens project-configured questionnaire choices; unsupported UI languages fall
back to English. Login retains a language choice before an interview is opened.

The browser home (`/app/`, `src/web/WorkspaceScreen.tsx` with
`src/web/roleHome.ts` and `src/home/api.ts`) is the user's role-appropriate
Home / Dashboard (`digitva-dsj2`). Every signed-in user lands here after login
when the export is present (`VaUsers.landing_url()`, policy
`docs/policy/expo-client.md`); `landing_page` is only the fallback without it:
- For a user with no roles and no project grants yet, it renders a Welcome
  home card explaining that no project roles have been assigned yet, with
  actions for Settings / Profile, Help (`/help`), and Demo Coding when
  `demo_coding.available` is true.
- For a user with roles or project grants, it fetches `GET /api/v1/me/activity`
  and displays:
  1. Overall personal activity counts (forms filled / submitted interviews,
     drafts in progress, deaths reported, forms coded, and forms reviewed).
  2. Role-appropriate quick action buttons for every capability the user holds
     (Fill VA `/collection`, Report a death `/death-registration`, Reported
     deaths `/death-registration?view=mine`, Code VA `/coding`, Review VA
     `/reviewing`, Organization `/organization`,
     People and roles `/people-roles`, Area `/area/`, Data management
     `/data-management/`, VA Dashboard `/sitepi/`, Admin `/admin/`).
  3. One card per project in `access.projects` listing the user's roles and
     unit/site scopes in that project, per-project personal activity counts,
     and direct per-project action buttons.
- Users also switch screens through the `WebShell` navigation, gated by role.
  More lists **Users** `/users` (digitva-75wn) for an admin, project PI or
  data manager (the In-charge included): the people in their scope with
  contacts, roles, account and app-enrolment status, an Activity panel loaded
  on open and an Issue enrolment code dialog (code and QR shown once, or
  emailed), over `GET /api/v1/users` (api-v1.md, "Users").
  An admin also gets two views there (digitva-cgmc, `src/web/UsersAdminTools.tsx`):
  **Grant access**, the grant grid (choose a project; created-date, name or
  email, role and status filters; a table at 768px and wider, cards below;
  per row the unit, six role boxes, status, app enrolment, enrolment code and
  Edit/Save, with the account's grants at other units shown read only), and
  **Upload accounts** (template download, choose a CSV or XLSX, preview every
  row, then create the new ones). The file is sent as base64 in JSON, since the
  shared requester sends JSON only.
  Coding and reviewing queues open on `last_project_id` from `/coding/projects`
  and `/reviewing/projects` unless a `?project=` query is passed.

Interview supervisors (and data managers) work in the Deaths tab
(`/death-registration`, digitva-a5jf): with supervision scope
(`SUPERVISION_ROLES`) the screen shows `SupervisionPanel`
(`src/web/SupervisionPanel.tsx`) under `?view=mine&preset=supervision`, and a
"Needs my attention / All deaths" switch when they also have deaths of their
own (plain Deaths keeps its default; a supervisor with none gets the panel and
no switch). The panel has four tiles that are also filters (Needs my decision,
the default, Overdue revisits, Stuck (30 days), Total in scope; attention
tiles page oldest first), the state and visit-note chips, confirm or reject a
flag, mark duplicate, cancel, reopen, and a case detail with the visit note
(redacted per viewer), possible duplicates, Choose interview and Reopen for
revision (not for ODK cases). `/supervision` (`app/supervision.tsx`) only
redirects to that preset, and there is no Supervision menu entry; Home's
supervisor block opens it ("Needs my decision"). Server refusals are shown by
error code through `t()`. Browser session only: device tokens carry no
supervisory powers.

The VA interview screen `/collection` (`src/web/CollectionScreen.tsx`) has
two actions and an icon-only Refresh: Record death (`/death-registration`,
shown for `death_register` or `both` sites) and Direct VA interview (shown for
`direct` or `both` sites). Direct VA interview opens an inline panel
(`src/web/DirectInterviewPanel.tsx`) with a Project picker and then a Site or
unit picker for that project, built from the intake context (selectable units
only; one entry per unit when a site has several, otherwise the site). A
single project or place is picked automatically; Start interview opens
`/interview` with the project, site and, when known, unit.

An interview linked to a reported death shows a case strip
(`src/web/InterviewCaseStrip.tsx`): name, age, sex and date of death from the draft's
prefill, as plain text; no informant or address, and none for a direct interview.
On `/interview` the blue header bar, the help guide, the title row with the language
switch and Back to collection all scroll away with the form (the screen renders
`AppHeaderBar` non-sticky as the first row of its scroller via `WebShell` `lead`);
only the case strip stays pinned at the top of the viewport, with the form's sticky
section progress below it. Every other route keeps the sticky root header.
The form's Back, Save draft, Preview, Next are one row of four equal-width buttons (package testID `form-footer`), sticky above the phone bottom tabs below 768px and in flow at the card's end from 768px; the package's "More sections appear as you answer" note is blanked via `uiTranslations`.
While the open interview has changes not yet acknowledged by the server, one navigation guard (`src/web/navigationGuard.ts`) holds the left menu, phone bottom bar and More sheet, header logo, Profile, Sign out, Back to collection, router back and tab close/reload behind a "Leave this interview?" alertdialog (Stay, Save and leave, Leave without saving); new-tab links (Help, Website) are not held. Answers autosave about 600 ms after the last change, so the dialog opens only while that save is pending or after it failed, and its body says which; a save of older answers settling late does not clear newer pending ones.

Under the toolbar two tabs, My interviews and Reported deaths, carry their
counts (Reported deaths sums the worklist's per-state `counts`); the chosen tab
is kept in `?tab=interviews|deaths`, and without it the screen opens on My
interviews when the user has drafts in progress, else Reported deaths. My
interviews lists the caller's open drafts (Resume) and submitted interviews
(Revise) on the shared case card below.

Reported deaths is one shared list (`src/web/DeathsList.tsx`,
[Case List Views](../policy/case-list-views.md)), also shown by the Deaths
screen `/death-registration?view=mine` with a Register a death button above
it. It reads `GET /intake/cases` (the interviewer scope plus the deaths a
`death_reporter` registered in its reach; rows reached only as reporter have
`can_interview: false`). One primary action per card (Code now, else Resume,
Start interview, Edit, View); Start, Resume and View need `can_interview`.

Case cards. Both tabs render one card, `CaseCard` in `src/ui/CaseCard.tsx`
(re-exported by `src/web/DeathsList.tsx`; the phone Interviews list uses it with
`idBelowTitle`, the ID as a muted second line).
Line 1: the name (the ID when there is no name), age (`51 y`), sex and the
status badges (text, never colour alone). Line 2: `Died:` date and `Area:`.
Line 3: `Last contact:`, `Next visit:` and, on My
interviews, sections saved, updated time and project. Line 4: the actions,
the map pin when the row has a GPS fix, and the case ID right-aligned in
monospace (shown only when the title is the name). Empty items are omitted;
on a phone items wrap in the same order. Facts are plain text, not chips:
14 px in `foreground` (at least 7:1 on the card in both modes, the
`ui-token-contrast` test), no fixed heights. Each line is a `role="list"` of
`listitem`s; bare values carry an accessible name ("Age 51 years", "Sex
Male", "Date of death 2026-09-22", "Case ID ..."). Card
buttons are at least 44 px high (Code now keeps the shared 40 px desktop
height). The map pin (`MapsPinButton`, `src/web/LocationCapture.tsx`, 44 px,
"Open in Maps") opens Google Maps directions in a new tab on the web
(`rel="noopener noreferrer"`) and `maps://` (iOS) or `geo:` (Android) through
`Linking` on a phone; a row without coordinates shows no pin and nothing is
fetched per card. Edit opens `/death-registration?deathId=`; a
reporter-only row adds `registered=mine`, and the form then reads the
registration from `GET /intake/deaths` (walking at most 20 pages), never the
case detail.

Both tabs use one filter bar (`src/web/caseFilters.tsx`): row 1 search and
Advanced filters; row 2 status chips on the left (deaths: All, To visit, In
progress, Submitted, Ready to code when any; interviews: All, In progress,
Submitted) and, on Reported deaths, two toggles on the right: Mine | All
(`registered_by_me`; Mine is the default for a user whose only death role is
`death_reporter`, and Clear all returns to that default) and Last 30 days |
All (date reported, local dates, today included). On a phone the toggles wrap
under the chips. Advanced filters (bottom sheet under 768 px, side panel
wider) holds Project (more than one project) and Area (the user's units,
Within area) first, then date of death, date reported/started, sex, age band
and min/max; applied ones show as removable chips with Clear all, and the
button shows their count. Project is server-side on Reported deaths
(`GET /intake/cases?project_id=`, scope checked, re-fetches the first page);
every other filter runs on the loaded pages, and the list says "Filtering
loaded cases" while more pages exist. My interviews filters its whole lists
(at most 200 drafts each) on the client, project included.

`WebShell` shows a one-line KPI strip on the home and the five role screens
(coding, reviewing, collection, death registration, supervision):
per project, deaths reported, interviews done and coded with both
percentages of deaths reported, from `GET /api/v1/me/kpis` (cached 60 s per
user on the server). It renders nothing when the list is empty or the call
fails. The user menu links every signed-in user to `/organization`
(`src/web/OrganizationScreen.tsx`): where the user sits in each org-tree
project, the units above with their people, the people at the user's own
unit, and the units below, which open in place. People are shown by name and
cadre only.

Statistics (`/statistics`, `src/web/StatisticsScreen.tsx`, pieces in
`src/web/stats/`, client `src/area/api.ts`) is the area dashboard over
`GET /api/v1/area/{projects,summary,staff}` (policy `docs/policy/area-dashboard.md`).
Menu entry and Home button: any user with an active grant (`statisticsAllowed`,
`src/web/roleHome.ts`); a remembered `/area/` visit maps to `/statistics`. The view
is the URL (`project`, `unit`, `site`, `period`, validated by `parseSelection`),
each choice pushes a history entry, so reload and Back restore it; a unit or site
the server 404s drops to the project top level. Project picker: buttons for up to
four projects, a native select above that. One proportional pipeline bar per child
unit or, in a sites project, per site (a site opens to its card, causes and
staff); deaths reported, interviews received, coded on one scale, with the
reported stage left out when the project has no death register. Then the area's
medians, suppressed top causes (the folded row is the server's `suppressed` flag,
shown as "Other causes"), stations and the by-interviewer list (loads only when
opened, closes on a project change). Card links open the Flask screen and sit on
one wrapped line with the CSV (hidden while loading); a row shows only its
interviews link. The CSV is the summary URL with `format=csv`. Flask `GET /area/`
redirects to `/app/statistics` with the same query when the export is deployed.
The UI has no plural mechanism (`t()` only substitutes), so counts read "1 reported".

Data (`/data`, `src/web/DataScreen.tsx`, pieces in `src/web/data/`, client
`src/data/api.ts`, URL and filter rules in `src/data/query.ts`) is the Overview of
the data manager dashboard over `/api/v1/data-management/*` and
`/api/v1/analytics/{demographics,mv/refresh}`; Pipeline is a later slice (Flask
`/data-management/` and `/data-management/cod-buckets` stay until it lands; Flask links from Statistics map to
`/data` through `dataRouteForLink`). Menu entry under More and Home button:
`dataAccess` in `src/web/roleHome.ts` (data manager, either viewer role, admin; a
remembered `/data-management/` visit maps to `/data`). The URL is the whole view,
with the Flask names (`search`, `project`, `site`, `date_from`, `date_to`,
`odk_status`, `smartva`, `age_group`, `gender`, `odk_sync` default `in_sync`,
`workflow`, `visit_note`, `org_unit`, `page`, `size`, `sort_field`, `sort_dir`,
`selected_sid`), parsed by `parseDataQuery` and changed in place with
`router.setParams` (a push would keep every earlier view and its table rows
mounted); nothing but column visibility is kept in `localStorage`. The sort goes to
the API as `sort[0][field]` / `sort[0][dir]`. Counts, charts and exports take only
the filters those endpoints honour (not search, visit note or unit; exports add
search). A strip of eleven counts (a card with a filter is a button, a second press
lifts it; the Total card has none) with the not-analysable split, a note that the
counts come from a five-minute view and the time they loaded, and a data
manager's Refresh (`POST /analytics/mv/refresh`). The list is a real table with
sortable headers on wide screens and one card per submission below 768px; a plain
collaborator (`redacted`) has no collector or coded-by column, searches the masked
form ID only and cannot sort by coder. Row actions: View (Flask
`/data-management/view/<sid>` for a data manager or admin, `/coding/area/<sid>` for
a viewer; the row is put in `selected_sid` first so Back lands on it), Edit in ODK
(new tab), View changes (a dialog of `upstream-change-details`, then Accept and
recode or Keep current decision, each through `ConfirmDialog`) and Cancel request;
the list and counts reload after each. Data managers and admins also get the
summaries (submissions by site or, for a one-project tree, by unit; age and sex;
workflow distribution; coders' last seven days, each a filter or search), the
five CSV exports as plain links, and a link to the Flask sync page. The screen is
titled and menu-labelled "Data management" (as the Home button). A coder clicked in
the coders panel narrows the list and exports through component state only (a
removable chip; never the URL or history), and the coders panel itself is not narrowed
by it; counts ignore search on the server. When the current query's fetch fails the
previous rows stay but dimmed with "Showing previous results". ODK review comments
are visible text under the status in the table (as on the cards); the last (Actions)
column is sticky and the workflow state wraps, so the table scrolls inside its own
region and the page never scrolls sideways. The server's `gender` filter and
`/filter-options` compare lower-cased.

Causes (`tab=causes`, `src/web/data/CausesTab.tsx`, rules in `src/data/causes.ts`,
data manager and admin only; the tab list is hidden for viewers and `tab=causes` falls
back to Overview) reads `/api/v1/cod-buckets/{schemes,aggregates}` and links
`/api/v1/cod-buckets/export.csv` as an anchor. URL filters: `scheme_code` (default:
the server's), `project`, `site`, `form_id` (typed: there is no form list), `gender`,
`date_from`, `date_to` (sent as `project_id`/`site_id`) and `age` (a view of the
payload's `age_filters` for top causes and main groups, not an API filter). Order:
summary line, top ten bars, main cause groups, age and sex table, causes by
category > subcategory > disease per age scope (collapsed to categories, M/F/U/total
and share), dropped CODs behind a disclosure, export link (one row per death, no
staff names). 400 `invalid_date`, `unknown_scheme` and `no_active_scheme` read as
plain messages. Not drawn yet: heatmap, treemap, age pyramid and sex pie of the Flask
page.

Signed-in browser routes use `WebShell`, which supplies the shared left
sidebar or phone rail and the screen header. It forwards optional header actions
and a footer slot to `Screen`; page content does not construct its own main
navigation. Empty footer slots consume no screen space.

An open coding/review case uses its own HTMX-style browser workspace:
Hints and VA Form Details above category navigation and Query/Response
sections. The shared `CaseWorkspaceScreen` retains allocation-safe loading,
masking and save handling; platform-specific presentation supplies the
browser layout while native screens retain their existing presentation.
Notes are available across categories in coding/review mode and remain
private to the current author and case. See
[Coder Browser Presentation](../policy/coder-browser-presentation.md).

On browser reload, routes wait for `GET /api/v1/me/access` before rendering. Ordinary
sign-in recovery retains the current `/app/` route and query. Pending terms
(403 `terms_required`) go to the terms screen; there is no mandatory factor
setup redirect.

Login, onboarding and device sign-in endpoints: [Authentication, Login and Onboarding](authentication-and-onboarding.md).

## Training menu (digitva-r2pf)

Policy: `docs/policy/training-demo-project.md`, `docs/policy/expo-client.md`.
Served at `/app/training` (the Flask welcome and sign-in `next` point there while
the export is present). Routes (`mobile/digitva-collect/app/training/`): `/training` (overview, Start),
`/training/interview`, `/training/coding`, `/training/review`, and
`/training/register` (death registration in the training scope). Screens:
`src/web/TrainingScreen.tsx` (overview, Interview area), `TrainingChecklist.tsx`
(participation hook, confidentiality notice, area checklists, queue shell);
helpers in `src/training.ts`.

- The menu (`navEntries`) shows Training from `access.training.areas`, with a
  child per area; the phone bottom bar shows the parent only.
- Coding and Review reuse `WorkspaceScreen` with a `training` prop:
  `createWorkspaceApi(request, { training: true })` adds `training=1` to the
  queue, count, allocation and release routes only; intake writes in `TrainingScope` also
  send it, and the server answers 409 `training_scope` for a record on the other side
  (api-v1.md, "Training scope"). The Interview area runs the
  ordinary registration, deaths list and supervision screens inside
  `TrainingScope` (`AppState.web.tsx`), whose bootstrap holds only the training
  project (`trainingBootstrap`, `scope: "training"`); lists ask for
  `training=1`. The menu keeps the user's own bootstrap (`unscopedBootstrap`).
- The Expo home sends a trainee with Start pending to `/training` once per
  browser session (`takeTrainingRedirect`); the Flask hook skips `/app/`.
- New UI strings are in `src/strings/en.json` and `hi.json`.

## Web export and UI string corrections

`npm run export:web` in `mobile/digitva-collect` runs `expo export --platform web`
and then copies `src/strings/*.json` into `dist/ui-strings/`. The server reads
those files for the UI string corrections (digitva-fsjz): the reference is
`dist/ui-strings/en.json`, and each other `<locale>.json` is the bundled text a
correction is checked against. Only the export is in the server image (see
`.dockerignore`), so rebuild the export after changing a bundled string.

The loader reads a file again only when its mtime changes, so a rebuilt export
is seen without a restart. A locale is served through `GET /api/v1/ui-strings/<locale>`;
the policy and the admin page are in `docs/policy/ui-strings.md`.

## Registration numbers (digitva-kzyp, stage 3)

Policy: [Death Registration Identifiers](../policy/death-registration-identifiers.md).

- `src/identifiers.ts`: types, the client pre-checks (`checkIdentifier`: length, character
  type, then pattern as `^(?:pattern)$` on the capitalised value; a pattern that does not compile
  is skipped; advice, the server decides), payload helpers (`identifiersToSend` for a
  registration, `identifierChanges` for a correction: changed codes only, `null` clears),
  `getIdentifierTypes` / `loadIdentifierTypes` (in-memory cache per project) and
  `putCaseIdentifiers`. Re-exported by `src/client/api.ts`.
- `src/IdentifierFields.tsx`: the shared entry component, one row per active type (label above,
  monospaced input, `autoCapitalize="characters"`, autocorrect and spellcheck off, example hint,
  required marker, rule or server message, duplicate warning with Continue and Edit). Typing
  upper-cases and strips leading space only (length preserving), trimming happens on send; the
  selection is controlled so the caret stays put.
- `src/web/CaseIdentifiers.tsx`: `IdentifierFacts` (cards: label first and the number in
  monospace, nothing when missing; detail: "Not yet issued"; badge-only viewers: "recorded" or
  "missing" per type) and `AddIdentifierAction` (shown only when the row or detail carries
  `can_edit_identifiers: true`; opens the fields in a panel and saves through
  `putCaseIdentifiers` with `if_updated_at`; `death_stale` reloads, `case_closed` explains,
  400 fields show under the field, warnings keep the panel open). Used by `CaseCard` lists
  (`DeathsList`), `CaseSummary` / the supervision detail and the case detail.
- Registration form (`DeathRegistrationScreen`): the section appears when the project has active
  types; a new registration sends `identifiers` only when any is set, an edit prefills from the
  case's `identifiers` values and sends only changed codes. A badge-only viewer gets no input
  unless the case says `can_edit_identifiers`. A saved registration that carries a duplicate
  warning pauses on it: Continue goes on as after any save, Edit reopens the new case in the edit
  form.
- Native (`src/nativeRoutes/register.tsx`): the same fields. Types are cached per project in the
  encrypted store under the meta key `identifierTypes` (`getMeta` / `setMeta`, project scoped),
  refreshed by `refreshCases` through `refreshIdentifierTypes` (best effort, a 403 keeps the old
  copy). `RegistrationFields.identifiers` is stored in the queued registration's JSON and
  spread into the `POST /intake/deaths` body, so `client_death_id` idempotency covers it; a 422
  reopens the item (`needs_edit`); a refused `identifiers.<code>` message is stored under the
  meta key `registrationRefusal:<client_death_id>` (`setRegistrationRefusal`, cleared on
  re-save or acknowledgement) and shown under the field when the item reopens. Native shows no duplicate warning (the offline POST is
  answered later); the any-time write and Add action are web only.
- Type configuration lives in the Flask admin Project Setup page (Data collection section,
  `app/templates/admin/panels/identifier_types.html`; also served alone at
  `/admin/panels/identifier-types?project_id=` for admin, project_pi and data_manager of that
  project, and as the page `/admin/registration-numbers` with a project chooser, linked from
  the Manage menu for admin, project_pi and data_manager), not in the Expo client.
- Web behaviours: `loadIdentifierTypes` rejects when the types cannot be loaded (nothing is
  cached); the registration form then shows `idTypesLoadFailed` and `AddIdentifierAction` loads
  the types up front and stays hidden (error text instead of the button) when they fail or the
  project has none. Edits send changes for active types only; a value of a deactivated type
  shows read-only. `isBadgeOnly` is true only when no entry has a `value` key, so one entry the
  server could not decrypt does not hide the others. `cleanIdentifier` applies NFKC first, as
  the server does; `typedCaret` places the caret from the pre-keystroke selection and the
  length change of the typing transform.

## Phone shell, Settings, Help and the error log (digitva-gmt7, digitva-j6cx)

Native only; the browser shell is unchanged. All of it is under
`mobile/digitva-collect/src/nativeShell/` and mounted by `app/_layout.tsx`
through `chrome.tsx` (`chrome.web.tsx` keeps the browser header and bottom bar).

- `shell.tsx` (`ShellProvider`) resolves the interviewer from the route's
  `userId`, holds the sync status (unsent count, last sync, busy, last result,
  offline flag from `AppState.offline`), runs Send now (`syncAccount`) and
  Refresh (reference data, forms, cases) from any screen, and tells mounted
  lists to reload (`AppState.dataChanged`). `Screen` leaves the status-bar and
  navigation-bar insets to the header and tabs while they show.
- `navAdapter.ts` feeds the account's access summary to `src/web/navTabs.ts`
  and keeps Home, Interviews, Register death; Sync opens a sheet. Home and
  Interviews share the `/worklist` route (`view=interviews` marks the second;
  `filter=todo|drafts|sent|revisions` opens it on a chip). Home is the
  dashboard (next step, unsent, cases needing a visit, Register a death);
  Interviews is a search box, filter chips with counts and a `FlatList` of
  cards, one primary action each. Both are built from the same local rows
  (`src/ui/interviewRows.ts`, pure), views in `src/nativeRoutes/worklistParts.tsx`.
  The site/unit picker (`src/ui/ChoiceSheet.tsx`, model `src/ui/sitePicker.ts`)
  lists unit names only, groups by site only across several real sites, hides
  internal placeholder names, and keeps the last choice per project in the
  interviewer's encrypted `meta` (`src/recentTarget.ts`). `src/ui/StateView.tsx`
  holds the Empty, Loading (skeleton rows) and Offline states.
- `sheets.tsx` holds the Account, Help and Sync sheets; Help text is
  `help_<screen>_what|do1..3` in `src/strings/*.json`, chosen by
  `helpContent.ts`, whose guide slugs a test keeps equal to
  `SCREEN_HELP_CONFIG`. The guide URL is the enrolled server plus the slug,
  opened with `Linking.openURL`.
- `src/nativeRoutes/settings.tsx` is the sectioned Settings page.
- Error log: `src/errorLog.ts` (scrubbing, buffer, export text),
  `src/errorLogDb.ts` (table `error_log`, cap, install), `src/errorExport.ts`
  (React Native `Share`). Rules: [policy](../policy/expo-client.md).

## Collect Plus (experimental, adb-only)

A second Android variant of this app, built with `APP_VARIANT=plus`; never
published (policy: [field data collection](../policy/field-data-collection.md)).

- `app.config.js` (`resolveVariant`): name "DigitVA Collect Plus", package
  `com.causeofdeathindia.digitvacollect.plus`, version `<version>-plus` (the
  update check then reports "unknown"), scheme `digitvacollectplus`,
  `extra.appVariant = "plus"` (read by `src/appVariant.ts`). Unset, the config
  is unchanged.
- `plugins/with-android-collect-plus.js`: for plus, native libraries are
  extracted (`extractNativeLibs`, `useLegacyPackaging`, engine `.so` unstripped)
  and the engine is staged from `private/icd11-offline-spike` by
  `modules/digitva-icd11/scripts/stage-engine.js` (fails with a clear message
  if `private/` is missing). `plugins/with-android-abi-splits.js` ships arm64
  only; `with-android-release-signing.js` leaves plus on debug signing. For the
  plain build the plugin only adds `expoAutolinking.exclude` for the module to
  `settings.gradle`, so the plain APK has no module code.
- `modules/digitva-icd11` (Kotlin Expo module + JNI shim over the NativeAOT
  `libdigitva_icd11.so`): data ships as `.bin` assets (AAPT expands `.gz`),
  is copied once to `filesDir/icd11-<version>/`. The engine runs in a bound
  service in its own `:icd11` process (`Icd11Service`, one worker thread that
  serializes calls); init runs once per that process and a failed init is sticky
  until it restarts. Engine error payloads are never logged or returned.
- Engine network calls (found by running the host build with a logging proxy and
  an HTTP event trace): at every start the WHO loaders try to download files that
  already ship in the app, over HTTPS: `icdcdn.who.int` `languageresources/codingtool/languageResources.txt`
  (twice), `icd11files.blob.core.windows.net` `doris/DORIS_v2.1_1.2.0.zip` (and the
  index `released-index-files/...pbf.zip` path). They only refresh or fetch missing
  data; offline they fail and the local files are used. The engine has no setting
  that turns this off (no key in its configuration). With INTERNET granted the call
  would load OpenSSL, unreachable from an app, and the .NET runtime aborts the
  process, so `EngineHost` points `http(s)_proxy` at a dead local port: each
  attempt fails at once, before any TLS. No telemetry or licence call was seen.
- Start-up (SM-E146B, warm data, from `init-timings.txt` written by the bridge):
  the work is CPU bound (about 21 s user, 1.4 s system) and is not an index
  rebuild: the unzipped index and `.annexu` already on disk are not rewritten on a
  warm start (only the `.pbf` and `.annex` are re-extracted from the shipped zip,
  about 0.8 s; the zip must stay, the engine refuses to start without it). A first
  start after install adds about 3 s (extract, build `.annexu`). Shipping a
  prebuilt index therefore saves only that one-off 3 s. Phases, serial:
  config 3.9 s, DORIS 7.4 s, index 10.9 s (22.3 s). DORIS and the index are
  independent, so the bridge loads them on two threads: about 18 to 20 s, same
  output on six certificates (DORIS and CoDEdit). GC settings changed nothing
  measurable.
- Background warm-up: `app/_layout.tsx` calls `scheduleEngineWarmUp()` in the plus
  build (after interactions plus 1 s); it logs `ICD11WARM ready=... ms=...`. The
  module binds the service from the app level and never unbinds, so the engine
  process lives as long as the app process; there is no `onTrimMemory` handler,
  Android decides. The engine has no cache-on-background hook, so nothing is saved
  when the app goes to the background. If Android kills `:icd11`, the next call
  re-inits once and retries.
- Measured on the phone (one run each, noise about 1 to 2 s): launch to engine
  ready 24.7 s before (init 23.6 s), 19.9 to 21.3 s after (init 19.1 to 20.3 s);
  launcher start with warm-up 20.3 to 22.3 s. Peak `:icd11` PSS 801 to 824 MB
  during init, then 548 MB; main process 130 MB. Per call: search 35 to 120 ms,
  codeinfo under 3 ms, DORIS 40 to 100 ms (7 ms repeat), CoDEdit 5 to 16 ms.
  Hosting the engine in the main process also works now (init 17.4 and 17.7 s in
  two runs; one run returned a native error that was not diagnosed): steady PSS
  666 MB, peak 948 MB in the UI process, so `:icd11` stays the default.
- `src/offlineEngine.ts`: `available / init / search / codeinfo / doris / codedit`,
  each with timings; "unavailable" on web and in the plain build. Concurrent
  `init()` calls share one request; `warmUpOfflineEngine` and
  `scheduleEngineWarmUp` start it in the background.
- `src/nativeRoutes/plusWorkspace.tsx`: Coding, Reviewing and Workspace routes
  render `QueueScreen` / `CaseWorkspaceScreen` (plain: `CodingOnWeb`).
- Hidden check: Settings > Collect Plus > "Offline engine check", or
  `digitvacollectplus://engine-check?run=1` (`src/nativeRoutes/engineCheck.tsx`).
- Build: `APP_VARIANT=plus npx expo prebuild --platform android --clean`, then
  `cd android && ./gradlew assembleRelease`; install with `adb install -r`.
  `npm run android:plus:release` does both steps; its `prebuild --clean` deletes and
  regenerates the gitignored `android/` folder, so local edits there are lost.

### Profiling

- **Dev build** (`npm run android:plus:dev` in `mobile/digitva-collect`): a plus
  debug build, prebuilt and staged from `private/` like the release. It is the
  standard debug build (no `expo-dev-client`, which the app does not depend on):
  start Metro with `npx expo start`, then `adb reverse tcp:8081 tcp:8081` so the
  phone reaches it over USB. Use it with Hermes, React DevTools and Android Studio.
- **Profileable release** (`npm run android:plus:release`): the plus config plugin
  (`addProfileable` in `plugins/with-android-collect-plus.js`) adds
  `<profileable android:shell="true"/>` to the merged manifest. The plain build
  gets no such tag. Use this build for representative numbers.
- `scripts/android-profile.sh <package> <out_dir> [interval] [duration]`: samples
  App Summary memory per process and filtered logcat (LMK, trim, kill, ANR).
- `scripts/android-trace.sh <out_dir> [seconds=30]`: records a Perfetto trace
  with `adb shell perfetto -c -` (text config on stdin) for atrace categories
  `am wm view dalvik sched freq gfx` and app tracing in both
  `com.causeofdeathindia.digitvacollect.plus` and its `:icd11` process. Start the
  work during the recording (for example the engine check). Open the pulled
  `.perfetto-trace` at https://ui.perfetto.dev.
- Trace sections (`android.os.Trace`, fixed names, always ended in `finally`):
  `icd11.init` (whole init), `icd11.copy` (data copy into `filesDir`), and per
  call `icd11.search`, `icd11.codeinfo`, `icd11.doris`, `icd11.codedit`. Names
  never carry user input or certificate text.
