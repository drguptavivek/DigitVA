---
title: Expo Client Hosting And Access
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-20
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
Home / Dashboard (`digitva-dsj2`):
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
     `/reviewing`, Supervision `/supervision`, Organization `/organization`,
     People and roles `/people-roles`, Area `/area/`, Data management
     `/data-management/`, VA Dashboard `/sitepi/`, Admin `/admin/`).
  3. One card per project in `access.projects` listing the user's roles and
     unit/site scopes in that project, per-project personal activity counts,
     and direct per-project action buttons.
- Users also switch screens through the `WebShell` navigation, gated by role.
  Coding and reviewing queues open on `last_project_id` from `/coding/projects`
  and `/reviewing/projects` unless a `?project=` query is passed.

Interview supervisors (and data managers) have `/supervision`
(`src/web/SupervisionScreen.tsx`): flags and all-cases lists, state and
visit-note filters, confirm or reject a flag, mark duplicate, cancel, reopen,
and a case detail with the visit note (redacted per viewer), possible
duplicates, Choose interview and Reopen for revision (not for ODK cases).
Server refusals are shown by error code through `t()`. Browser session
only: device tokens carry no supervisory powers.

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

Case cards. Both tabs render one card, `CaseCard` in `src/web/DeathsList.tsx`.
Line 1: the name (the ID when there is no name), age (`51 y`), sex and the
status badges (text, never colour alone). Line 2: `Died:` date and `Area:`.
Line 3: `Phone:` (masked), `Last contact:`, `Next visit:` and, on My
interviews, sections saved, updated time and project. Line 4: the actions,
the map pin when the row has a GPS fix, and the case ID right-aligned in
monospace (shown only when the title is the name). Empty items are omitted;
on a phone items wrap in the same order. Facts are plain text, not chips:
14 px in `foreground` (at least 7:1 on the card in both modes, the
`ui-token-contrast` test), no fixed heights. Each line is a `role="list"` of
`listitem`s; bare values carry an accessible name ("Age 51 years", "Sex
Male", "Date of death 2026-09-22", "Phone ending 3210", "Case ID ..."). Card
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
