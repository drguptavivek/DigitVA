---
title: Expo Client Hosting And Access
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-12
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
`src/web/roleHome.ts`) is a router. On the first load after a sign-in it
opens the user's last visited screen (stored per user id in localStorage by
`WebShell`), else the first role screen: coding, reviewing, collection, death
registration, supervision; a data manager with none of those goes to the
server page `/area/`. Later loads show the button list. A user with several
roles switches through the `WebShell` navigation, gated by role, which also
links data managers to `/area/` and `/data-management/`. Coding and
reviewing queues open on `last_project_id` from `/coding/projects` and
`/reviewing/projects`. Every sign-out and a lapsed session clear the
first-load flag.

Interview supervisors (and data managers) have `/supervision`
(`src/web/SupervisionScreen.tsx`): flags and all-cases lists, state and
visit-note filters, confirm or reject a flag, mark duplicate, cancel, reopen,
and a case detail with the visit note (redacted per viewer), possible
duplicates, Choose interview and Reopen for revision (not for ODK cases).
Server refusals are shown by error code through `t()`. Browser session
only: device tokens carry no supervisory powers.

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
