---
title: Expo Client Hosting And Access
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-30
---

# Expo Client Hosting And Access

The [2026-10-25 connectivity profile](expo-connectivity-profile.md) records
measured cold/warm performance, recovery checks and matched-build acceptance.

DigitVA serves the Expo web export under `/app/`. The export is read from
`mobile/digitva-collect/dist` by default; `EXPO_CLIENT_DIST` can point to the
deployment's dedicated export directory. The route serves regular files only
when they resolve inside that directory. It uses `index.html` for the known
Expo client routes and returns `404` for missing assets, unknown routes and
path traversal attempts.

## Local web HMR (opt-in, 2026-10-25)

`make dev-hmr` starts the Expo web client in a local Node 22 container with the
checkout bind-mounted for live edits. Metro listens only inside the Compose
network; `digitva_hmr_ingress` owns `http://localhost:8051` and proxies the
Expo shell, Metro assets and `/hot` websocket to it. Flask API, intake,
authentication, static and support paths remain behind that same origin, so
cookies, CSRF, passkeys and the ICD picker keep their local `localhost:8051`
origin. The existing ICD service remains available on `localhost:8382` and the
ordinary profile ingress on `localhost:8052`.

In Metro development, open the client at `/` or a route such as `/login`.
Expo Router 57 disables its configured `/app` base URL in development, so the
local ingress redirects `/app` and `/app/*` to their root-path equivalents;
production and the static export remain mounted at `/app/`.
The Expo `/admin` route stays on Metro; `/admin/` and its Flask admin console
remain on Flask. The `/api/v1/intake/` APIs and legacy `/intake/` pages also
stay on Flask, while the slashless `/intake` route stays on Metro. Flask's
public-site aliases `/vaindex` and `/index` remain on Flask; `/` is Metro's app
home.

The HMR overlay points Flask at the small
`deploy/expo-hmr/index.html` sentinel only to mark the Expo client as present;
the browser shell itself comes from Metro. `src/strings/*.json` is mounted as
`ui-strings` for the administrative bundle reader; Metro bundles client strings
from source. `GET /api/v1/ui-strings/<locale>` supplies database corrections only
and retains its existing 60-second cache. A named Docker volume holds
`mobile/digitva-collect/node_modules`; the host's dependencies are not
overwritten. `make dev-hmr-stop` stops only the two HMR containers and restores
the ordinary Flask binding on port 8051. This path does not run an Expo export,
APK or Gradle build; release artifacts remain CI-built.

The owner authorized local Docker production web exports for diagnosis on
2026-10-25. Run the same cache builder and profiler against that export before
using it for network measurements; label a dirty working-tree build as local.
Published releases and APK builds still use GitHub Actions.

## Matched WHO and app builds

The web release workflow has two build jobs. `build-who` compiles the WHO package,
checks its types and entrypoint boundaries, and uploads a package archive plus
`who-build.json` and its verified compiled files. `build` downloads that exact
artifact, checks its source commit, package identity and complete file hashes,
installs it before locked `npm ci`, and verifies the installed copy again.

The app asset manifest records the WHO package version, source commit, package
archive SHA-256 and compiled-tree SHA-256 in `components.who`. CI requires this
metadata and the deferred WHO runtime group. Publish attaches both the WHO
package archive and the complete app archive under the same release tag.
The existing complete app archive remains compatible with Docker hosting; the
WHO archive is a verified build input, not an independently deployable browser
application. Its browser chunk is still emitted against the app's matched
React/Metro graph and downloaded separately on demand or in the background.

## Versioned production assets

`public/index.html` paints the saved UI theme (or system theme) before React
starts, with a static startup status. Web readiness and deferred-route loading
retain a themed canvas and visible loading status; deferred screens keep the
navigation shell. Runtime theme changes also update the document background.

The web release workflow runs `scripts/build-expo-web-cache.mjs` after the Expo
export. It generates `asset-manifest.json`, `asset-worker.js` and
`cache-register.js`, recording release, source commit, byte sizes and SHA-256
hashes. The worker verifies downloads and caches only listed `_expo`/`assets`
files whose names contain a content hash. Unversioned files remain inventory
entries but bypass the worker, so an older tab cannot serve stale bytes at a
reused URL. It never caches navigation, API responses or private form definitions.
Old exports without a manifest continue to work without this cache.

HTML and worker files revalidate; content-addressed assets receive immutable
cache headers. An update waits for old tabs to close rather than replacing a
running interview. Idle warming is sequential and requires a reported 4G
connection without a data-saving preference; unknown or slower links use only
on-demand caching. Web interview, registration and case-detail screens
use deferred imports and offer retry when a chunk download fails. Native route
imports are unchanged. CI export size and throttled-browser measurements remain
release acceptance gates; HMR timings are not production measurements.

`whoCoreRuntime.web.ts` and `web/whoRuntimeLoader.ts` resolve one asynchronous
`whoRuntimeModule` for both WHO core and web renderer. Definition compilation,
interview startup and revision reduction await it. Native keeps its existing
static runtime. Browser coding and registration use small app-owned controls;
clinical form definitions and engine behavior stay in the WHO package.

The module imports the additive WHO `/web/preloaded` entry once and aliases its
namespace as core and web. That entry reuses the canonical instrument and shared
browser renderer without the package's nested lazy instrument import. The
ordinary WHO root, `/web` and `/native` exports retain their loading behavior.
This packaging boundary prevents Metro from hoisting the otherwise shared
instrument into an initial common script; the CI marker gate verifies placement.

`web/interviewAssetCache.ts` starts optional warming only after authenticated
access includes an interview action. Registration alone does not warm assets.
The public manifest's `interviewRuntime` group lists the runtime chunk and hashed
JavaScript dependencies. The worker fetches and verifies these sequentially,
without importing or executing them. It cancels when the authenticated context
changes or the page is hidden/offline; completed chunks survive a retry. Anonymous
worker registration itself does not warm assets. Private forms and API responses
remain outside the public cache.

CI runs `scripts/profile-expo-web.mjs` against every initial HTML script (including
Metro common/runtime), reports deterministic gzip sizes and deferred chunks,
validates the manifest, and enforces the initial-byte budget. The JSON report is
included with the web artifact. A deferred filename alone does not prove the WHO
instrument stayed out of Metro's common chunk; inspect the emitted graph and
compare browser transfers before accepting a release.

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
`/training/interview`, `/training/coding`, `/training/reviewing`, and
`/training/reporting` (death registration in the training scope). Interview
details and forms live at `/training/interview/case` and
`/training/interview/form`; coding/review workspaces use
`/training/coding/case` and `/training/reviewing/case`. Legacy
`/training/register`, `/training/review` and ordinary detail links carrying
`training=1` redirect to their canonical training wrapper. Server API scope keys
remain `interview`, `coding`, and `review`. Screens:
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
  an HTTP event trace): at start-up the WHO loaders try to download files that
  already ship in the app, over HTTPS: `icdcdn.who.int` `languageresources/codingtool/languageResources.txt`
  (twice), `icd11files.blob.core.windows.net` `doris/DORIS_v2.1_1.2.0.zip` and the
  index `released-index-files/...pbf.zip`. The engine has no setting that turns
  this off, and without OpenSSL its .NET runtime aborts the process. No telemetry
  or licence call was seen.
- **Packaged-only data (2026-10-28, `digitva-hs7e.5`).** Every init uses
  the dead local proxy before the WHO engine is loaded. First setup and repair
  use the APK assets; no runtime WHO-file download is allowed. Updating the app
  supplies a new data version. The old native update operation returns
  `bundled_only` without restarting the engine; its UI and deep-link action
  are removed. The v4 workspace replaces previous engine data only, never
  clinical stores, attachments, backups or upload queues.
- **OpenSSL.** `io.github.ronickg:openssl:3.3.2-1` (OpenSSL 3.3.2, Apache-2.0),
  a prefab AAR that expo-sqlite already pulls in transitively. `build.gradle`
  copies its arm64 `libssl.so` into the build; `libcrypto.so` is the copy
  expo-sqlite packages from the same artifact. Nothing is vendored; the AAR is
  fetched at build time. Google's NDK OpenSSL AAR was rejected: only 1.1.1q is
  published, and its libcrypto cannot sit beside expo-sqlite's 3.3.2 one.
- **WHO-supplied files.** The APK carries language resources, the compressed
  release and search index, and extracted DORIS rule files. Their staged sizes
  and SHA-256 values are listed in `digitva-icd11/who-files.json`. Engine-built
  indexes, annexes and logs remain in the disposable versioned engine workspace.
- **Setup record.** `filesDir/icd11-<DATA_VERSION>.setup.json` records an
  `attempt` or completed `shipped` setup. Interrupted setup restarts from APK
  copies. Missing or truncated packaged WHO files are repaired from assets.
  Ordinary starts check sizes; same-size corruption is not detected by that
  check. Build-input integrity remains a separate follow-up.
- **Worker priorities.** Interactive calls precede queued setup and
  housekeeping. Calls wait for initialization; every process serializes its
  engine calls. The compatibility update request refuses with `bundled_only`.
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
- **Demand-only startup.** App launch does not schedule engine warm-up.
  Eligible local coding initializes after project access and the editor lease
  are checked. The explicit eligible-account diagnostic can also start it.
  The isolated service remains bound after use; Android may reclaim it and
  the next call reinitializes. No background cache-save hook is present.
- Measured on the phone (one run each, noise about 1 to 2 s): launch to engine
  ready 24.7 s before (init 23.6 s), 19.9 to 21.3 s after (init 19.1 to 20.3 s);
  launcher start with warm-up 20.3 to 22.3 s. Peak `:icd11` PSS 801 to 824 MB
  during init, then 548 MB; main process 130 MB. Per call: search 35 to 120 ms,
  codeinfo under 3 ms, DORIS 40 to 100 ms (7 ms repeat), CoDEdit 5 to 16 ms.
  Hosting the engine in the main process also works now (init 17.4 and 17.7 s in
  two runs; one run returned a native error that was not diagnosed): steady PSS
  666 MB, peak 948 MB in the UI process, so `:icd11` stays the default.
- `src/offlineEngine.ts` exposes availability, init, search, codeinfo, DORIS
  and CoDEdit. Concurrent init calls share one request. Legacy warm-up helpers
  remain unused; the retained update API receives `bundled_only` from native.
- Native Coding, Reviewing and Workspace routes use the shared server-backed
  queue/workspace in both APK variants, subject to current authorization.
- **Engine diagnostic:** an eligible, unlocked Plus account can open Settings
  > Collect Plus > Offline engine check. An explicit deep link must include
  `userId=<eligible-account-id>` as well as `run=1`; the route never bypasses
  account, capability or local unlock checks. The check uses a synthetic
  certificate and displays short results/timings, never patient data.
- **2026-10-28 phone baseline:** SM-E146B, Android 15, 5.3 GiB RAM; local
  release build with packaged-only data. First setup: 20.502 s total,
  134 ms copy, 20.263 s engine initialization. Subsequent cold engine start:
  17.812 s total, 17.702 s engine initialization. Sampled engine PSS peaked
  at 1191.0 MiB on fresh setup and 871.7 MiB on the subsequent start, settling
  around 528 MiB. These are sampled maxima, not allocation peaks. Both checks
  returned expected synthetic DORIS `BA41.Z`; this is not a new server parity
  study. Android Settings reported App 354 MB, Data 501 MB, Total 855 MB.
  Later mode/setup UI additions require their final artifact acceptance;
  raw numeric measurements and synthetic outputs stay in private local files.
- **Build:** GitHub Actions is the default release path. The owner explicitly
  permitted local builds and web-export checks for the 2026-10-28 measurement
  session; that exception does not authorize publication or deployment. `.github/workflows/collect-plus-release.yml`
  (`workflow_dispatch`: `publish`, `tag` such as `collect-plus-v0.3.10-plus.1`)
  runs the same steps the release does: vendor build, `npm ci`, typecheck, tests,
  `APP_VARIANT=plus npx expo prebuild`, `./gradlew assembleRelease` for arm64 only,
  `scripts/verify-android-release.sh` (with the Plus package id), then a sha256. The
  publish job creates a public prerelease with the APK and its `.sha256`, signed with
  the release key from the `android-release` environment (plus signs with the release
  key only in this workflow; a local plus build keeps debug signing).
- **Engine input.** The workflow does not read `private/`. It downloads the engine
  release asset `icd11-engine-<version>.tar.gz` (`scripts/package-icd11-engine.sh`
  packs it from the spike; `scripts/publish-icd11-engine.sh` publishes it, run by the
  owner only), checks `ICD11_ENGINE_SHA256` pinned in the workflow, extracts it and
  stages from that folder (`DIGITVA_ICD11_SPIKE_DIR`, same layout). The workflow stops
  at once while the sha256 pin is the placeholder. The engine tag must equal
  `scripts/icd11-engine.env`; a step checks it.
- Gradle heap for plus: `org.gradle.jvmargs=-Xmx6144m -XX:MaxMetaspaceSize=512m`
  (`plugins/with-android-collect-plus.js`); the plain build keeps the default.
- OpenSSL pairing: the module build fails when its `io.github.ronickg:openssl` version
  differs from the one in `expo-sqlite/android/build.gradle`. With SQLCipher off
  (`expo.sqlite.useSQLCipher`) expo-sqlite ships no `libcrypto.so`, so `loadOpenSsl()`
  fails and every init skips the WHO fetches.
- Local `npm run android:plus:*` scripts remain in `package.json` but are not run
  under the owner rule; the Expo web bundle comes from `expo-web-release.yml`.

### Pure offline mode (digitva-zjqq, 2026-10-26)

Plus-only, on-device only until QR enrolment (`digitva-tb0j` is the enrolled
sync). No masking offline: the same user collects and codes, data never leaves
the device while unenrolled.

- **Device identity** (`src/offlineIdentity.ts`): UUID v4 minted once per
  install, SecureStore (`offline_device_identity`), single-flight, regenerated
  when the stored JSON is corrupted; gated so web and the plain build never
  create one. Enrolment later binds it to the server device row.
- **Offline profile** (`src/offlineProfile.ts`, Settings > Collect Plus >
  "Offline profile"): coder name, age, sex, designation, facility/org, country,
  state, and the SmartVA HIV/malaria mortality levels; name and country are
  required; SecureStore `offline_profile`. A standalone account also needs
  age (18-89 or 99), sex and both mortality levels before any interview starts
  (`standaloneProfileMissing`): setup refuses without them, Home disables
  "New interview" with a "Complete profile" button, and the form route refuses
  a new draft before writing anything. A new standalone draft stores
  `standalonePrefill(profile)` in `drafts.prefill`, which fills and locks
  Id10010/Id10010a/Id10010b/Id10002/Id10003 (none -> `veryl`, other ->
  `undetermined`); drafts started earlier keep no locks. Completion freezes
  SmartVA settings from the interview's own Id10002/Id10003 when none are
  frozen (`source: "interview"`).
- **Standalone home and Settings** (`src/nativeRoutes/standalone.tsx`, `settings.tsx`, `digitva-axim`): the home
  keeps the account name, the clock notice, the backup reminder card (its "Open Settings to back up" button opens
  Settings), New interview, the interview list, Settings and Lock now. The list is split into three tabs with
  counts (digitva-31ci): In progress (drafts), Pending coding (completed, not coded; the default when it has
  records) and Coded. Each row is titled with the deceased's name, age and sex (read from the draft answers by
  `listStandaloneRecords` in one query; the UUID titles a nameless record and sits under the name otherwise). Coded
  rows offer Revise coding only. Enrol this phone sits in Settings > Account;
  an unlocked standalone account's Settings > "Export and backup" holds Export my records, Back up this phone and
  Restore from a backup (`src/standalone/DataActions.tsx`). The home re-reads the last backup time on every focus,
  so a backup made in Settings clears the reminder.
- **Offline coding** (Settings > Collect Plus > "Offline coding";
  `src/nativeRoutes/offlineCoding.native.tsx`): lists completed-unsent
  interviews (metadata only, no PII in the list), opens a case with the
  unmasked `DorisPanel` driven by the offline engine
  (`src/workspace/offlineDoris.ts`), and saves to the per-interviewer store's
  `offline_coding` table (certificate, engine results, local digests,
  `process_token` `local-<uuid>`, `device_uuid` +
  `coder_profile_updated_at` provenance, and `answers_sha256` of the answers
  coded, so later edits make it stale). The row is deleted with its draft when
  an upload is acknowledged; a standalone store pushes it with the interview
  after adoption (device-collection-api.md "Standalone push"). Engine error payloads never surface
  or log (status `unavailable`). Screens are platform-split (`​.native`/`.web`
  twins) so the web export never pulls expo-sqlite.
- **Try DORIS demo (WP6, 2026-10-30).** Collect Plus on Android only
  (`canTryDorisDemo()` in `src/dorisDemoAccess.ts`; plain Collect and the web
  never show it): Help > "Try DORIS (offline demo)" opens route `/doris-demo`
  (`app/doris-demo.tsx`, screen `src/nativeRoutes/dorisDemo.native.tsx`, `.web`
  twin redirects home). It needs no account: the header keeps its Help button on
  the sign-in, lock, enrolment and PIN screens in Plus, and the accounts list has
  it already. Offline only: `src/workspace/dorisDemo.ts` builds a
  `WorkspaceApi` over the same `createOfflineDorisEditor` and
  `createGuidanceRequester` as offline coding, answering only terms, codeinfo,
  selection check and process; saves say the demo saves nothing and every
  case, queue or server call refuses, and the editor's store refuses, so no
  SQLite write, draft, queue entry or request exists. It loads WHO's six
  synthetic certificates (`assets/doris-help-examples.json`, a copy of
  `resource/doris_help_examples.json` kept equal by a test; Metro does not watch
  outside the app root) or a blank one and processes what is on screen; WHO's
  recorded `observed` results are dropped when the file is read. The
  device-wide ICD-11 / DORIS switch is respected (off: a message and a link to
  Settings; turned on from there: wait for Continue). Engine start shows the
  engine's progress. No "Try on web" button yet (comes with WP7).
- **React ICD-11 picker (digitva-9cll.2, 2026-10-29).** In the Collect Plus
  build only (`isPlusVariant()`), `IcdPickerModal` renders
  `src/workspace/doris/picker/IcdPicker.tsx` instead of `IcdPickerFrame`, for
  online and offline coding. No WebView, iframe or Bootstrap; it uses the DORIS
  kit and `theme.ts` tokens (light/dark). It speaks the web page's message
  protocol to `pickerBridge.ts`, so `WorkspaceApi` and the guidance routes are
  the only data path and the verification rule is unchanged. Plain Collect and
  the Expo web build keep the shared web page. Only final codes can be used: a
  category opens its hierarchy and an extension code is marked, with no Use or
  Build (`digitva-9cll.12`). Details:
  [DORIS COD Workflow](doris-cod-workflow.md).
- Offline replies (digitva-9cll.3, 2026-10-30): terms, codeinfo, selection-check
  and process are the server's replies, built by TypeScript ports of the
  server's rules over the on-phone engine, including the final-code refusal of selection-check (`whoEngineApi.ts`,
  `dorisTerminology.ts`, `dorisCertificate.ts`, `dorisProcessing.ts`) and
  replayed against the recorded golden sets in jest; errors are `ApiError`s
  with the server's codes. Limits, accepted: `certificate_digest` is the
  server's but `result_digest` binds the engine release, not a WHO image digest;
  the process token is `local-<uuid>`; the certificate seed from the interview is
  minimum-viable (sex, death/birth dates, estimated age) with provenance
  badges. Details: [Android Engine Interface](icd11-android-engine-interface.md),
  layer 6.

### Profiling

- **Dev build**: a local plus debug build is not made on the developer Mac (owner
  rule, 2026-10-25). Metro over USB (`npx expo start`, `adb reverse tcp:8081
  tcp:8081`) needs an installed build, which comes from CI; use it with Hermes,
  React DevTools and Android Studio once one is installed.
- **Profileable release** (built by `collect-plus-release.yml`): the plus config
  plugin (`addProfileable` in `plugins/with-android-collect-plus.js`) adds
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
  `icd11.init` (whole init), `icd11.copy` (data copy into `filesDir`), and
  `icd11.call` for every engine call (one fixed name; the op is not in it).
  Names never carry user input or certificate text.


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
The lighter package still excludes offline engine assets. Experimental Plus
ships the engines and their reference data together, with no runtime package
download. Public WHO software redistribution still needs written clearance.

## Bundled SmartVA reference (`digitva-hs7e.13`, `.13.1`)

Plus stages the MIT Rust engine through `scripts/build-smartva-android.sh` and
`modules/digitva-smartva`. Its non-exported `:smartva` service calls the existing
C ABI, using embedded data and the `mobile-core` Cargo feature. The default
desktop build still includes reports; the phone excludes chart/font/workbook
dependencies. Algorithm 3.0.1 and Rust wrapper 3.0.2 remain unchanged.

`smartva/ensureLocal.ts` reserves the per-draft upload/editor lease before its
first await and coalesces completion and coding-entry requests. A valid completed
interview starts scoring after its durable save; opening local coding fills a
missing, failed or stale result once. Manual Run/Regenerate remains available.
Default-off device preference, current same-project permissions, both consent
decisions, valid completion and the frozen options snapshot are rechecked.
Missing old settings require explicit repair. Engine failure does not undo the
interview or block leaving the form; interruption is retried on coding entry.

The SQLCipher cache stores projected causes, controlled symptom descriptions and
answer/options/engine provenance. A changed identity invalidates the result;
matched upload acknowledgement deletes the draft and cascades its cache. Phone
results remain advisory; the server generates its own version-linked result.

Private release APK checks on 2026-10-28 passed on Android 15 (SM-E146B) and an
Android 13 emulator with no active network. Phone SmartVA process setup was 93 ms,
and adult/child/neonate scoring 245/34/28 ms. Sampled steady engine PSS was about
60 MiB; co-resident WHO engine about 526 MiB. WHO initialization still takes about
18 seconds on this phone. All 33 native libraries meet 16 KB alignment. Synthetic
checks establish function/parity, not clinical accuracy; full field acceptance
and distribution clearance remain open.
