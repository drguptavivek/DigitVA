---
title: Expo Client Hosting And Bootstrap
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-04
---

# Expo Client Hosting And Bootstrap

DigitVA serves the Expo web export under `/app/`. The export is read from
`mobile/digitva-collect/dist` by default; `EXPO_CLIENT_DIST` can point to the
deployment's dedicated export directory. The route serves regular files only
when they resolve inside that directory. It uses `index.html` for the known
Expo client routes and returns `404` for missing assets, unknown routes and
path traversal attempts.

The browser starts by calling `GET /api/v1/client/bootstrap`. An authenticated
session receives the current user's id and display name, a signed CSRF token,
navigation capabilities, and the existing intake, coding and reviewing web
links. An anonymous browser receives a JSON `401` and the
`/vaauth/valogin?next=/app/` login URL instead of an HTML login redirect.
Bootstrap responses are never cached. Browser intake
answers remain server-side drafts, saved and submitted through the existing
`/api/v1/intake/` endpoints: death registration takes and returns
`date_of_birth_partial` (`YYYY-MM` or `YYYY`) beside `date_of_birth`, and the
server re-applies locked prefill answers on every draft save and submit,
whatever the client sends (docs/policy/web-intake.md); native offline collection continues to use
the existing encrypted bearer device API.

The first UI locales are English and Hindi. Interview language drives app UI
language on start, resume and successful switches. The top-right language icon
opens project-configured questionnaire choices; unsupported UI languages fall
back to English. Login retains a language choice before an interview is opened.

Signed-in browser routes use `WebShell`, which supplies the shared left
sidebar or phone rail and the screen header. It forwards optional header actions
and a footer slot to `Screen`; page content does not construct its own main
navigation. Empty footer slots consume no screen space.

On browser reload, routes wait for session bootstrap before rendering. Ordinary
sign-in recovery retains the current `/app/` route and query. Required password
or factor setup continues to use its server-provided recovery destination.

Login, onboarding and device sign-in endpoints: [Authentication, Login and Onboarding](authentication-and-onboarding.md).
