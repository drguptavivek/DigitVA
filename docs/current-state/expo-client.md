---
title: Expo Client Hosting And Access
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-11
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
